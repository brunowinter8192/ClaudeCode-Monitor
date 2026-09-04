# New hook: block_worker_send_while_working.py (2026-09-04)

**Topic:** a new `block_worker_send_while_working.py` PreToolUse hook blocks `worker-cli send
<name> ...` to a worker whose live status is `working`, modeled 1:1 on the pre-existing
`block_worker_kill_while_working.py`; the kill guard's own block message was shortened in the same
pass since its old wording pointed at exactly the workaround (`worker-cli send '{name}' 'stop'`)
the new hook now forbids.

## Motivation

`worker-cli send` to a worker that is still `working` races the worker's own turn — the message
can arrive mid-tool-call, get buried under the worker's own next output, or simply confuse a
session that has not asked for input yet. `worker-cli kill` already had exactly this guard
(`block_worker_kill_while_working.py`, an earlier entry in this area); `send` had none. Structural
gap, not a new failure mode — the same live-status check just needed to run in front of a second
subcommand.

## Design decisions

**Copy, not share.** `decide(command, status_fn)`, `_resolve_worker_cli()`,
`_live_worker_status(name)`, and `_parse_command()` are byte-for-byte identical between the two
hooks, only the regex (`kill` vs `send`) and the block message differ. Copied rather than factored
into a shared module, matching this hook family's existing convention (`block_gh_cli_chained.py`/
`block_rag_cli_chained.py`/`block_websearch_scrape_chained.py`/`block_worker_cli_read_chained.py`
already share `_known_cli.py` for their CHAIN logic, but each of those, and this pair, keeps its own
independent `decide`/parse/regex — a hook script here is small enough that sharing would trade a
handful of duplicated lines for an inter-file dependency graph in a security-critical, individually
auditable surface).

**Double-gate kept identical, not just copied by name.** Regex-only would block a `send` dispatched
right after a worker finishes its turn (a race the same way a post-finish `kill` would false-positive)
— the live `worker-cli status` check is what makes the block conditional on the worker being
VERIFIABLY working at hook-fire time, zero false positives for idle/dead/nonexistent workers. Same
rationale, same code shape, same three canonical statuses (`working`/`idle`/`dead` — confirmed as
the complete vocabulary before writing any case).

**Message text: named no alternative at all, deliberately.** The kill guard's ORIGINAL message
suggested `worker-cli send '{name}' 'stop'` as the escape hatch — but that suggestion is now itself
a blocked action while the worker is working. Rather than teach a workaround that immediately loops
back into the new hook, both messages were reduced to a flat, terminal statement: `"worker '{name}'
is working — do not {kill|send messages to} a working worker. Not possible.\n"`. Neither message
proposes what to do instead (wait, or use ESC) — that instruction lives in the interactive UX
(ESC), not in a hook's stderr, which this pass treats as out of scope.

## Verification

- New suite `dev/hook_smoke/test_block_worker_send_while_working.py` (12 cases): `working` (with
  and without a `%` suffix) blocks; `idle`, `dead`, an unknown/empty status, a `status_fn`
  exception, a quoted self-referential `worker-cli send` inside another send's message, and a
  heredoc-body self-reference all allow; a multi-send command blocks on whichever named worker is
  `working`; a non-send command passes through untouched. Two additional subprocess-level checks
  against the real entrypoint (not just the pure `decide()` function, since stdin parsing is
  untested by the pure-function cases alone): malformed JSON on stdin fails open, and a command
  naming a worker this sandbox cannot actually resolve (`worker-cli status` unreachable) also fails
  open — all 12 pass.
- `dev/hook_smoke/test_block_worker_kill_while_working.py` re-run unchanged after the message edit:
  13/13 pass — confirmed the suite asserts only on `decide()`'s `(block, name)` tuple, never the
  message text, so the wording change needed no test update.
- `hook_setup.py`'s `_HOOK_SCRIPTS` entry added directly after the kill guard's; `hook_setup.py`
  itself intentionally never run in this worktree (its own worktree guard would refuse it anyway) —
  a post-commit trigger attempted it automatically and was correctly refused with the expected
  worktree-guard stderr message, same as every prior hook addition in this worktree.

## Relevant Symbols / Paths

- `decide`, `_SEND_RE`, `_BLOCK_MESSAGE` (`src/hooks/block_worker_send_while_working.py`)
- `_BLOCK_MESSAGE` (`src/hooks/block_worker_kill_while_working.py`) — the corrected wording
- Area: `process-docs/tool_use_safety/` — see `2026-09-04_block_duallog_chained.md` in this same
  area for the sibling new-hook precedent this entry follows
