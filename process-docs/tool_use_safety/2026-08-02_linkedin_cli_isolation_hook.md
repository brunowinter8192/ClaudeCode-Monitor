# linkedin CLI Isolation Hook (2026-08-02)

**Topic:** a new PreToolUse hook `block_linkedin_cli_isolated.py` protecting the LinkedIn
project's `linkedin` CLI wrapper from chaining/piping and from more than one invocation
per Bash call.

## Motivation

Not an observed live incident (unlike `block_rag_cli_index_isolated.py`) — requested
proactively as the closing milestone of a LinkedIn-CLI work session, reasoning from the
CLI's own architecture: `linkedin` holds a whole-dispatch process lock
(`src/linkedin/process_lock.py` in that repo) and cold-starts Chrome (~7s) per invocation.
Two `linkedin` calls in one Bash block do not run in parallel — the second blocks on the
first's lock until it releases or its own 120s wait times out. Chaining or piping around
it (as an agent naturally would for other CLIs — `| grep`, `| head`, `&&`) only adds
latency, never saves it.

## Design

**Rule, collapsed to one check:** if any segment of the (quote-stripped) command is a
`linkedin` invocation, more than one segment total (of ANY kind — another command, a pipe
target, or a second `linkedin` call) is a violation. This is simpler than either named
model: `block_gh_cli_chained.py` explicitly allows multiple calls of its protected tools
(the opposite of what's needed here); `block_rag_cli_index_isolated.py`'s two-part check
(`len(index_segments) > 1` plus a per-segment allowlist including `cd`/assignments) is
closer in spirit for the count rule, but a `cd` allowance was deliberately NOT carried
over — unlike `rag-cli index` (path-relative, needs a preceding `cd` to the collection's
root), `~/.local/bin/linkedin` is a global wrapper resolved via `$PATH` from any
directory, so there is no legitimate case requiring a `cd` alongside it.

**One allowance grounded in real usage, not invented for symmetry:** a single
env-var-assignment prefix directly on the `linkedin` segment (`LINKEDIN_HEADED=1 linkedin
get_messages`) — `LINKEDIN_HEADED` is a real env var that repo's `src/linkedin/browser.py`
reads for headed-browser debugging.

**Explicit non-hardening, stated in the hook file itself (not only here):** unlike
`block_rag_cli_index_isolated.py`, this hook does not chase `$(...)`/backtick
command/process substitution. That hook's target has real correctness stakes (a
multi-minute indexing operation holding a collection lock — see the
`2026-08-02_rag_cli_index_isolation_subshell_bypass.md` entry in this same area for what
was actually smuggled through that gap). This hook's target is a pure performance guard;
a bypass only loses the optimization, while chasing every obfuscation route would raise
false-positive risk against the far more common failure mode here — the bare word
"linkedin" legitimately appearing in paths, quoted text, and other commands' arguments,
which the segment-start-anchored match (`^(?:VAR=val\s+)*linkedin(?:\s|$)`) and the
existing `_strip_non_shell_active` quote-blanking already handle without any extra
hardening.

## Verification

25-case smoke test (`dev/hook_smoke/test_block_linkedin_cli_isolated.py`), all passing:
11 block cases (piped to grep/head/tail/sed/awk/wc, two `linkedin` calls chained via
`&&`/`;`, an unrelated command both after AND before the `linkedin` call — no
leading-segment exemption, unlike `block_rag_cli_chained.py`'s trailing-only rule — and an
env-prefixed call still piped) and 13 allow cases: standalone (`--count`/`--days`),
redirect-to-file, env-prefixed standalone, bare `linkedin` with no subcommand (a decision
pinned by an explicit test case, not left to accident), a non-`linkedin` command
untouched, and 5 dedicated false-positive-avoidance cases — "linkedin" as a `cd` path
segment, as part of a `cli/linkedin/cli.py` path, as a `grep` argument, as a different
tool's name prefix (`linkedin-web`), and as text inside single/double quotes — plus 1
malformed-stdin fail-open case.

Verified at hook-script level (real subprocess invocation with real JSON stdin, real exit
code asserted) — NOT verified against a live CC session, and NOT installed into
`~/.claude/settings.json` (registration added to `hook_setup.py`'s script list only,
running the installer is explicitly out of scope for this work — it must run from the
main repo root, not a worktree, and the repo's own post-commit hook confirmed this by
refusing to auto-install from the worktree).
