# Auto-Abort: Gate on a Worker's Live Background Task

## Observed (2026-07-30)

Sequence causing wasted orchestrator prods: a worker's Bash call gets auto-backgrounded and the
worker correctly goes idle to wait on it; once every worker of the project is idle for ≥5s,
`FocusController.tick`'s `bg_by_project` loop kills the orchestrator's background sleep timer
(existing all-idle-for-5s behavior, unrelated to this project's own `has_bg` state); the
orchestrator wakes, sees `idle`, cannot see the pending background task from a status snapshot
alone, and prods the worker — which then has nothing to do but poll its own background process.

## Root Cause

`all_idle` in `tick()`'s auto-abort loop checked only `w.status == 'idle'` (plus the existing
`_has_recent_send_signal` grace check) — it had no way to know a nominally-idle worker was still
waiting on a live background task. `has_bg` (from `proc_cache._has_active_bg`, fed by the batched
`lsof` scan already run every tick) carries exactly that signal but wasn't consulted here.

## Fix

`src/menubar/focus_controller.py::FocusController.tick` — added `not w.has_bg` to the per-worker
`all_idle` conjunct:

```python
all_idle = all(
    w.status == 'idle' and not w.has_bg and not _has_recent_send_signal(w, signals, now)
    for w in workers
)
```

A worker with `has_bg=True` is never counted idle for abort purposes, regardless of hook status.
The 5s dwell (`_all_workers_idle_since_ts`) only starts accumulating once `has_bg` flips back to
False — no separate branch, reuses the identical dwell/log/abort path as the pre-existing
all-idle case. The `abort_check` log line's per-worker tokens now also carry `has_bg=<bool>` so a
held project's cause is legible directly in `menubar.log` without cross-referencing session state
elsewhere.

## Interaction With the Escape-on-bg-launch Mechanism

`tick()` already has a separate, edge-triggered Escape-on-bg-launch block (fires once per
`has_bg` False→True rising edge, forcing the worker's CC TUI idle so a later prod — after abort —
finds nothing to poll). That mechanism and this gate are complementary, not redundant: the
Escape block handles "make the worker outwardly idle the moment a bg task starts"; this gate
handles "don't kill the orchestrator's own wait-timer while that bg task is still running". Left
unmodified.

## What Was Preserved (and How It Was Checked)

- **Idle worker without a background task still aborts promptly** — the normal wake-up path; a
  guard that erred toward "never abort" would be worse than the original bug. Verified by a
  passing test case, not asserted in prose.
- **Vacuous no-worker case** (`all()` over an empty list is vacuously True) — untouched by this
  change; a project with zero workers has no `w.has_bg` to conjunct against, so it still aborts
  on the same 5s dwell.
- **`_has_recent_send_signal` grace window** — untouched, still conjuncted alongside the new
  `has_bg` check.

## Verification

New dev probe `dev/hook_smoke/test_focus_controller_bg_gate.py`: 6 integration-level cases,
driving the real `FocusController.tick()` across simulated ticks (1s step) with synthetic
`SessionInfo`-shaped session lists and a monkeypatched `_abort_bg_sleep_timers` recording calls
instead of killing real PIDs. All 6 passed:

- idle + `has_bg=True` held >5s → no abort
- idle + `has_bg=False` held >5s → abort (baseline unchanged)
- two workers, one `has_bg=True` → no abort project-wide
- `has_bg` True→False then idle → dwell only starts counting after the flip, no early fire
- zero worker sessions → vacuous abort still fires
- idle within the recent-send grace window → no abort

Also re-ran the two other dev/hook_smoke suites touching the same `tick()`/proc_cache surface:
`test_escape_idle_worker.py` (6/6) and `test_bg_task_detection.py` (6/6) — both clean, no
regression in the Escape-edge-trigger or `has_bg` predicate itself.

Verified at integration level (real function, synthetic inputs, mocked side-effecting collaborator)
— NOT verified at the live AppKit-tick / real-tmux entry-point level; that would require a running
menubar app instance and a real worker session, out of scope for this dev-probe pass.
