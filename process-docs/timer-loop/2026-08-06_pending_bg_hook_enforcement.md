# Enforcement hook for pending-background-task timers — design + implementation, 2026-08-06

Milestone 3: a PreToolUse Bash hook (`src/hooks/block_timer_pending_bg.py`) that reads the state
milestone 2's `src/proxy/pending_bg_state.py` writes and blocks the orchestrator from arming a new
canonical background sleep-timer while an earlier one is still pending. Closes the loop opened by
milestone 1 (what completion notices look like) and milestone 2 (the proxy-side state file) — this
is the actual point of enforcement.

## Structural precedent followed

`block_timer_no_worker_working.py`'s shape, verbatim where applicable: pure `decide()` with an
injectable reader function (that hook's `status_fn(project_path)`, this one's `state_fn()` — no
`project_path` needed since the pending-state file is a single per-project file, not something
`decide()` itself needs to locate), `_WORKTREE_FRAGMENT = '.claude/worktrees/'` cwd exemption
(orchestrator-only), fail-open via a blanket outer `except Exception: sys.exit(0)`, `log_fire(...)`
on block only, `_parse_input()` boilerplate copied unchanged, and the exact same `_SLEEP_ONLY_BG`
regex literal already shared by `rewrite_background_sleep.py` / `block_unauthorized_background.py`
/ `block_timer_no_worker_working.py` — kept identical here too so all four hooks stay
order-independent regardless of `_HOOK_SCRIPTS` ordering. Registered in `hook_setup.py` in the same
slot `block_timer_no_worker_working.py` occupies relative to `rewrite_background_sleep.py` —
inserted directly between them.

## Why this doesn't repeat the 2026-07-20/21 false-block mistake

The removed `block_concurrent_timer.py` computed `expiry = armed_time + 600s` as pure hook-local
arithmetic and blocked purely on that clock. Its failure mode (documented at the time): the
underlying process could finish or die early — a worker going idle before the 600s window elapsed,
or the turn being interrupted/aborted — and the hook had no way to know; it kept blocking a
legitimate new timer until its own stale clock ran out. The 2026-07-20 entry's "accepted edge case"
(interrupted timer leaves a stale future expiry) turned out, per the 2026-07-21 removal entry, to
be common enough via the worker-idle-before-timeout path that the whole hook was removed rather
than patched further.

This hook's block condition is NOT computed from an independent clock at all — it reads
`pending_bg_tasks.json`, which `pending_bg_state.py` writes ONLY from events the proxy directly
observed: `status: pending` exists only because the proxy genuinely saw a launch-ack; the entry
flips to `cleared` only because the proxy genuinely saw a `<task-notification>` completion/kill
block for that exact task id — status/exit-code-agnostic (milestone 1's finding: the dominant real
wording across the corpus is exit 143, i.e. SIGTERM, exactly what a menubar abort or turn-interrupt
produces). An abort therefore generates its OWN clearing signal before the orchestrator's next
timer attempt — the mechanism that was missing entirely in the removed hook. `_PENDING_EXPIRY_SECS
= 3600` (3300s canonical timer + margin) is a narrow safety net for a genuinely different failure —
the completion notice never reaching the proxy at all (proxy process crashed/restarted AND the
session ended before a notice could pass through) — not the primary signal.

## decide() returns the id list, not a bool

Kept from the pre-implementation review: `decide(command, run_in_background, state_fn) -> list[str]`
returns the sorted list of fresh-pending task ids rather than a bare boolean. Empty list is the
falsy/allow case (same idiom as a bool), but a non-empty list gives the workflow what it needs to
name the ids in the block message without a second pass over the state. Message-building
(`_build_block_message`) still re-reads state independently via the same `state_fn` — a deliberate
second read, since message construction is a distinct concern from the block/allow decision and is
internally wrapped so it can never raise; a raise there must never propagate to the workflow's outer
fail-open `except` and silently flip an intended BLOCK into an accidental ALLOW.

## Block-message age + the boundary semantics

Per review: the block message names every fresh-pending id AND the age of the YOUNGEST (most
recently armed) one — `"...pending (ID: abc123, youngest armed 4m ago)..."` — so the orchestrator
reading the block can judge roughly how much wait plausibly remains against the 55-minute ceiling,
without this hook needing to know each task's actual expected duration (it doesn't and can't — the
pending state carries no duration, only `armed_at`).

The expiry check is `age < _PENDING_EXPIRY_SECS`, strictly-less-than, not `<=`: an entry armed
EXACTLY at the 3600s threshold is already treated as stale and does NOT block. The margin exists to
tolerate proxy/TN-delivery lag on the clearing side, not to extend the blocking window by one more
second at the boundary — documented directly in the constant's own comment, and covered by a
dedicated smoke case at both the exact boundary (3600s → allow) and one second under it (3599s →
block).

## A real gotcha in the smoke suite's own design, not the hook

This worktree's filesystem path is itself `.../monitor-cc/.claude/worktrees/timer-loop` — it
contains the exact `.claude/worktrees/` fragment the hook's exemption checks for. A real-entrypoint
subprocess test that doesn't explicitly override `cwd` would inherit the test runner's cwd (inside
this worktree) and hit the exemption on every single case, silently passing regardless of whether
the actual block/allow logic works at all. The smoke suite's Layer 2 (real entry-point) therefore
runs every subprocess with `cwd` forced to a fresh `tempfile.TemporaryDirectory()` outside the
worktree tree entirely; Layer 3 is the mirror-image dedicated case — `cwd` deliberately INSIDE a
constructed `.claude/worktrees/...` path, with a fresh-pending state file present that WOULD block
if the exemption didn't fire — proving the exemption itself works, not merely that Layer 2 never
accidentally triggered it.

## Verification

27/27 checks in `dev/hook_smoke/test_block_timer_pending_bg.py` across the 4 layers described
above. No regressions in the three neighboring hook smoke suites this change sits next to:
`test_block_timer_no_worker_working.py` (10/10), `test_rewrite_background_sleep.py` (11/11),
`test_block_unauthorized_background.py` (9/9), and `test_hook_setup_main_branch_gate.py` (10/10,
confirms the `_HOOK_SCRIPTS` list-length change doesn't disturb the install-gate logic). Live
deployment onto `~/.claude/settings.json` was not attempted from this worktree —
`hook_setup.py`'s own `_guard_not_worktree()` refuses that by design (confirmed firing correctly:
the repo's own post-commit hook ran `hook_setup.py` automatically on this task's commit and hit the
guard, exiting with the expected worktree error) — it happens on the next `hook_setup.py` run from
the main repo root.
