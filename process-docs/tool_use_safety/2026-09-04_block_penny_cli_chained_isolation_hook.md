# penny-cli Isolation Hook (2026-09-04)

**Topic:** a new PreToolUse hook `block_penny_cli_chained.py` forcing `penny-cli` (a
wrapper on PATH, `penny-cli --klasse "<Klasse>"`, from the repo
`~/Documents/ai/haendler/penny`) to run strictly standalone.

## Motivation

Observed live incident: the orchestrator kept chaining `penny-cli` with other commands
instead of issuing it alone, e.g. `gcommit "..." && penny-cli --klasse "X" 2>&1 | sed -n
'/^Klasse/,$p'`. `penny-cli`'s output is bounded and must land directly in context — same
class of failure `block_rag_cli_chained.py`'s `search` protection and
`block_linkedin_cli_isolated.py`'s whole-invocation isolation already exist to prevent, but
neither existing hook's rule was tight enough by itself: `block_rag_cli_chained.py`'s
per-tool relaxation (`_known_cli.is_allowed_chain_segment`) would let `penny-cli` join a
cross-CLI chain; `block_linkedin_cli_isolated.py`'s isolation rule does not police a
redirect on the lone segment or a substitution-wrapped invocation.

## Design

**Baseline copied from `block_linkedin_cli_isolated.py`:** split on the same
`_SEPARATOR_RE` as the rest of the chained-CLI family; if any segment starts with
`penny-cli` (optionally env-var-assignment-prefixed, `_PENNY_CLI_SEGMENT_RE`), then more
than one segment total is a violation — no exception for `cd`, no exception for another
known CLI, no exception for `echo`/`printf`, no exception for loop scaffolding. This is
the one deliberate divergence from every OTHER hook in the chained-CLI family
(`block_gh_cli_chained.py`, `block_rag_cli_chained.py`, `block_websearch_scrape_chained.py`,
`block_worker_cli_read_chained.py`, `block_duallog_chained.py`): none of those import
`_known_cli` conditionally — they all import it and use `is_allowed_chain_segment` to grant
the cross-CLI/guard/echo/loop relaxations. This hook does not import `_known_cli` at all,
by design — every one of those relaxations is exactly the "anything else" the requesting
prompt named as forbidden.

**Two tightenings beyond `block_linkedin_cli_isolated.py`'s isolation rule**, each
borrowed from a different existing hook rather than invented fresh:

1. A redirect (`>`, `>>`, `2>&1`, `&>`, `<`) on the lone `penny-cli` segment blocks too —
   the same `_REDIRECT_RE` `block_rag_cli_chained.py` applies to its one PROTECTED
   subcommand (`rag-cli search`), applied here unconditionally since `penny-cli` has no
   unprotected subcommand the way `rag-cli`/`worker-cli` do.
2. Command/process substitution anywhere in the raw command blocks too — the same
   `_SUBSHELL_RE` and raw-command rationale `block_rag_cli_index_isolated.py` uses
   (`_strip_non_shell_active` blanks `$(...)`/backticks sitting inside a double-quoted
   region even though real bash still evaluates them there).

**New mechanism not present in any prior hook in this family:** a dedicated
`_WRAPPED_PENNY_RE` catching `$(penny-cli ...)` / `` `penny-cli ...` `` as a TRIGGER, not
just as a subshell violation once triggered. Without it, `OUT=$(penny-cli --klasse "X")`
would never be recognized as a `penny-cli` invocation at all: the outer segment
`OUT=$(penny-cli --klasse "X")` is consumed in full by `_ASSIGN_TOKEN`'s greedy `\S*` value
match up to the first whitespace (`OUT=$(penny-cli`), so `_PENNY_CLI_SEGMENT_RE` never sees
a literal `penny-cli` token at segment-start and the whole command would silently pass.
`_WRAPPED_PENNY_RE` is anchored directly after the opening `$(`/backtick (optional
whitespace, optional env-assignment prefix) so it fires on `$(penny-cli ...)` without
false-triggering on `$(ls .../penny-cli)` — penny-cli as a path substring inside an
unrelated substitution.

**Path-substring trigger avoidance carried over unchanged from `block_rag_cli_chained.py`'s
2026-08 fix:** the trigger is a per-segment `^`-anchored match, never a bare `\bpenny-cli\b`
search over the whole command — so `ls ~/Documents/ai/haendler/penny/bin/penny-cli` and
`ln -sf ~/Documents/ai/haendler/penny/bin/penny-cli ~/.local/bin/penny-cli` (both real
commands a setup/install step would plausibly run) never trigger the hook, since neither
starts a segment with the `penny-cli` token.

## Registration constraint (discovered during this session, not anticipated)

`hook_setup.py`'s Layer 3 install gate (`_script_on_main`) only registers a script
verifiably committed on the `main` branch of the MAIN repo checkout; `_guard_not_worktree`
additionally refuses to run the installer at all from inside a `.claude/worktrees/` path.
Both were exercised directly: running `python3 src/hooks/hook_setup.py` from this worktree
exits 2 with the worktree-guard message, and the repo's own `.githooks/post-commit` hook
fired automatically on commit and hit the identical guard. Neither `~/.claude/settings.json`
nor the running hook set gained an entry as a result — confirmed by grepping the script name
out of `~/.claude/settings.json` after the commit. This matches the established pattern
already documented for `block_linkedin_cli_isolated.py`'s own registration: going live
happens on merge into `main`, when `.githooks/post-merge` runs the installer from the real
main-repo context, not from a worker's worktree.

## Verification

13-case smoke test (`dev/hook_smoke/test_block_penny_cli_chained.py`), all passing: 7 block
cases (the verbatim chained incident, piped to `head`, redirected to a file, a leading `cd`
guard, a cross-CLI chain with `rag-cli search`, a command substitution wrapping the call,
and a command substitution used as an argument to the call) and 5 allow cases (standalone,
env-var-prefixed standalone, and the two path-substring cases plus a command with no
`penny-cli` at all), plus 1 malformed-stdin fail-open case.

Verified at hook-script level (real subprocess invocation with real JSON stdin, real exit
code asserted) — NOT verified against a live CC session, and NOT installed into
`~/.claude/settings.json` for the reason stated above.
