# Auto-Abort: Fire When a Project Has No Workers At All

## Observed (2026-07-29)

A canonical `sleep 600 && echo done` background timer ran its full 10 minutes for a project
with zero worker sessions allocated. Auto-abort never triggered.

## Root Cause

`FocusController.tick` (`src/menubar/focus_controller.py`) computed:

```python
workers = workers_by_project.get(proj, [])
all_idle = bool(workers) and all(w.status == 'idle' and ... for w in workers)
```

`bool(workers)` forced `all_idle = False` whenever a project had no worker sessions, so
`_all_workers_idle_since_ts` was never seeded and the 5s dwell never started — a bg timer with
no workers to wait on held for its full duration regardless of elapsed idle time.

## Fix

Dropped the `bool(workers) and` guard. `all()` over an empty Python list evaluates to `True`
(vacuous truth), so a zero-worker project now naturally satisfies `all_idle = True` and flows
through the exact same 5s dwell bookkeeping, logging, and `_abort_bg_sleep_timers` call already
used for the all-workers-idle case — no new branch, no new constant, no dwell-duration change.

## `'unknown'` Bucket — Deliberately Unaffected

The `if proj == 'unknown': continue` skip in `tick()` runs before the workers/`all_idle`
computation, unconditional on worker count. Unattributed bg timers (ancestry-walk couldn't
resolve a CC process to a project cwd — see `initial_design.md` for the attribution chain in
`bg_timer.py:_scan_bg_sleep_timers`) still never reach the abort check either way; there is no
project to evaluate workers against. This fix only changes behavior for named, attributed
projects.

## Verification

Pure-function check of the isolated `all()` expression (no app/session dependency): empty
worker list → `True`; all-idle non-empty list → `True`; one working among idle → `False`.
`python3 -m py_compile` clean on `focus_controller.py`. NOT verified at live-tick level — no
real zero-worker project + live sleep-timer run was observed against the fixed code this
session; the changed logic reuses the pre-existing (already-exercised) dwell/log/abort path
verbatim, only the guard changed.
