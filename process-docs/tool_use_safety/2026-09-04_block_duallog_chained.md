# New hook: block_duallog_chained.py (2026-09-04)

**Topic:** a new `block_duallog_chained.py` PreToolUse hook, joining the `block_gh_cli_chained.py`
family (`block_rag_cli_chained.py`, `block_websearch_scrape_chained.py`,
`block_worker_cli_read_chained.py`), forbids piping/redirecting a `duallog` call and adds `duallog`
to `_known_cli.py`'s `KNOWN_CLI_TOOLS`.

## Motivation

Observed 2026-09-04: the orchestrator ran `duallog expand <session> 1 --before 0 --after 0 | head -60`
and, in a later call, `| tail -25` — reading only one end of a msg's content. `duallog expand`'s
whole purpose is showing a msg's blocks in full; a `head`/`tail`-truncated view can silently omit
the part of the msg that mattered, with no way for the reader to notice what got cut. Same failure
class as the 2026-08-24 CLI-noise conversion in this area (`websearch scrape_url`, `gh-cli
get_issue`, `rag-cli search`, `worker-cli capture`/`response`): a command whose output is bounded
and meant to land in context whole must not be piped or redirected, and the fix is to BLOCK rather
than rewrite — a block forces a standalone re-issue, so there is no risk of a silently-edited
command desyncing from dependent segments the way a rewrite hook's edit could.

## Design decisions

**New hook, not an extension.** No existing chained-CLI hook touched `duallog` at all, so
`block_duallog_chained.py` is new, following the same precedent `block_websearch_scrape_chained.py`/
`block_worker_cli_read_chained.py` set in the 2026-08-24 conversion (new hook when nothing existing
overlaps the surface).

**Every subcommand protected, not a subset — the one real deviation from the family's shape.**
`block_worker_cli_read_chained.py` protects only `capture`/`response`, leaving `status`/`list`/`send`/
etc. as ordinary (redirect-unpoliced) `worker-cli` segments; `block_gh_cli_chained.py` similarly
splits its 9 trigger tools into a 2-command protected subset and a 7-command redirect-allowed
subset. `duallog` has no such split — `sessions`, `msgs`, `expand`, and `search` all produce output
meant to land in context whole (the whole package exists to make ~15 GB of raw JSONL readable; there
is no `duallog` subcommand whose output is naturally safe to truncate). So `block_duallog_chained.py`
uses ONE anchor regex (`^duallog\b`) for both the fast-path trigger and the per-segment protected
check, rather than the two-regex protected/unprotected split every sibling hook needs.

**`duallog` added to `KNOWN_CLI_TOOLS`, not left as a hook-local check.** The 2026-08 cross-CLI relax
already lets `worker-cli`, `gh-cli`, `rag-cli`, `reddit-cli`, `linkedin`, and `websearch` chain with
each other in one Bash call. Adding `duallog` to that same list (rather than only teaching
`block_duallog_chained.py` to recognize the other six) means the relax runs BOTH directions for
free: a `duallog search foo` segment now also passes `block_gh_cli_chained.py`'s/
`block_rag_cli_chained.py`'s/etc. own chain checks, with no per-hook special-casing needed anywhere
else. Confirmed by re-running all four sibling suites unchanged after the addition — 34+24+21+23
cases, all still passing.

**Registered in `hook_setup.py`, `hook_setup.py` itself not run.** Per the worktree isolation rule
this repo enforces on itself: `hook_setup.py`'s own `_guard_not_worktree()` refuses to run from
inside a worktree, so registering the new entry in `_HOOK_SCRIPTS` is the correct and complete
in-worktree action — the repo's `.githooks/post-commit` auto-invocation on a main-branch commit is
what actually activates it later, exactly the mechanism `_shell_strip.py`'s own DOCS.md Gotcha
already documents.

## Verification

- New suite `dev/hook_smoke/test_block_duallog_chained.py` (7 cases: the two verbatim incident forms
  — `| head -60`, `| tail -25` — both BLOCK; a plain `>` redirect BLOCKs; `duallog sessions &&
  duallog msgs x` (same-tool combine), `cd /x && duallog search foo` (leading guard), and a bare
  `duallog expand s 5` all PASS; malformed stdin fails open) — all 7 pass.
- Fed the literal incident command to the hook directly via stdin: exit 2, block message instructing
  a standalone re-issue and reading the whole output.
- Regression: all four sibling chained-CLI suites re-run unchanged after the `KNOWN_CLI_TOOLS`
  addition — `test_block_gh_cli_chained.py` (34/34), `test_block_rag_cli_chained.py` (24/24),
  `test_block_websearch_scrape_chained.py` (21/21), `test_block_worker_cli_read_chained.py` (23/23).
- `hook_setup.py` was intentionally never run in this worktree (its own worktree guard would refuse
  it anyway); a post-commit trigger attempted it automatically after the implementation commit and
  was correctly refused with the expected worktree-guard stderr message.
