# rag-cli index Isolation Hook — Command-Substitution and Bare-& Bypass Fix (2026-08-03)

**Topic:** two further bypass holes in `block_rag_cli_index_isolated.py`, found by
adversarial replay after the 2026-08-02 env-prefix fix, plus additional vectors found
by self-directed hunting for the same class of gap.

## Reported Holes

`X=$(tail /tmp/a.log) rag-cli index --collection x` and
`` X=`tail /tmp/a.log` rag-cli index --collection x `` both passed (exit 0) — must block.

**Root cause:** `_shell_strip._strip_non_shell_active` deliberately keeps command
substitutions (`$(...)`) and backtick expressions shell-active (not blanked, unlike
quotes/heredocs) — by design, since other hooks need to see real shell-active content.
`_ASSIGN_TOKEN`'s value part (`\S*`) matches any non-whitespace run, so it happily
swallows `$(tail /tmp/a.log)` as an assignment value, riding an arbitrary command into
the invocation through a segment that still classifies as a bare assignment.

## Fix

New standalone gate `_SUBSHELL_RE` (`\$\(|` backtick `|<\(|>\(`) checked once, right
after the anchor confirms `rag-cli index` is present, independent of segment
classification — "no legitimate reason for a subshell in an isolated index call".
Checked against the RAW (unstripped) command, not the quote-blanked stripped text: a
first implementation checked the stripped text and missed `cd "$(pwd)" && rag-cli
index ...` — `_strip_non_shell_active`'s double-quote scanner blanks `$(...)` inside
`"..."` even though real bash still evaluates it there (`cd "$(pwd)"` really runs
`pwd`). Switching the gate to the raw command closed that gap too; no existing test
command contains `$(`/backtick/`<(`/`>(` in the raw text, so this is a safe restriction
(false positives no more than a stray shell-metacharacter that has no reason to appear
near an isolated index call anyway).

## Self-Directed Hunt

Probed beyond the four reported cases before closing the round, since the standalone
gate is a class-fix, not a case-fix:

| Probe | Outcome |
|---|---|
| `rag-cli index --collection $(cat /tmp/name.txt)` (substitution in an argument) | closed by `_SUBSHELL_RE` |
| `rag-cli index --collection x > >(tail -5)` / `< <(cat /tmp/y)` (process substitution) | closed by `_SUBSHELL_RE` (`<(`/`>(` included) |
| `X=$((1+1)) rag-cli index --collection x` (arithmetic expansion) | closed — `$((` starts with `$(`, same gate |
| `` rag-cli index --collection x > `pwd`/out.log `` (backtick in redirect target) | closed by `_SUBSHELL_RE` |
| `cd "$(pwd)" && rag-cli index --collection x` (substitution inside double quotes) | initially NOT closed (stripped-text gate blanked it) — root-caused, gate moved to raw text, now closed |
| `rag-cli index --collection x &tail /tmp/y` (bare `&`, no trailing space) | NOT closed by the subshell gate — separate root cause, see below |
| `rag-cli index --collection x&tail /tmp/y` (bare `&`, no spaces at all) | same separate root cause |
| `X="a;b" rag-cli index --collection x` (quoted metacharacter, not substitution) | correctly still ALLOWED — control case |
| `rag-cli index --collection x &> /tmp/out.log` (`&>` redirect) | correctly still ALLOWED — control case |

**Second, independent finding:** the original single-`&` separator pattern
(`\s&(?=\s|$)`) required whitespace on BOTH sides of `&` to recognize it as a
background-operator separator. Real bash tokenizes `&` as a control operator
regardless of surrounding whitespace — `cmd &tail` and `cmd&tail` are both exactly
`cmd &` followed by `tail` as a second command. Neither form was being split into two
segments, so the whole glued string still matched `_RAG_INDEX_SEGMENT_RE` at its start
and passed as if it were a single index call. Fixed by dropping the whitespace
requirement and using lookaround instead: `(?<![&>])&(?![&>])` — excludes `&&` (lookahead
`&`), `&>` (lookahead `>`), and `N>&M`/`2>&1` (lookbehind `>`), while now matching `&`
regardless of adjacent whitespace. Verified `&&`/`&>`/`2>&1` handling is unaffected
(regex alternation order still resolves `&&` as its own two-character match before the
single-`&` alternative can partially consume it).

This `_SEPARATOR_RE` change is local to `block_rag_cli_index_isolated.py` only — the
identical pattern is duplicated (not shared) in `block_rag_cli_chained.py` and
`block_gh_cli_chained.py`, both left untouched per scope.

## Verification

Reproduced both reported holes BEFORE the fix via direct subprocess calls (exit 0 for
both). After the fix, extended smoke suite
`dev/hook_smoke/test_block_rag_cli_index_isolated.py` to 37 cases (was 24) — all
passing: 20 block (10 prior + 10 new: 6 substitution-vector variants, 2 bare-&
variants — note the double-quoted-`cd`-target case surfaced the raw-vs-stripped-text
distinction above) and 17 allow (14 prior + 3 new control cases proving the fix does
not over-block quoted metacharacters or the `&>` redirect operator). Cross-checked no
regression on `block_rag_cli_chained.py`'s own 11-case smoke (file untouched). Re-ran
the verbatim live command from the 2026-08-02 report (assignment line + `cd
"$RAG_ROOT"` + env-prefixed index + backslash-continued redirect) — still exit 0.

Verified at hook-script level (real subprocess invocation, real JSON stdin, real exit
code asserted) — NOT verified against a live CC session (requires main-repo-root
`hook_setup.py` registration, out of scope for a worktree session).
