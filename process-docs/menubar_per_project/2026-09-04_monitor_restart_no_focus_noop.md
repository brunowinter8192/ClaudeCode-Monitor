# Monitor button no-op on a stale tmux session — kill-then-relaunch fix

Date: 2026-09-04

## Symptom

Every click on a project's "mon" button in the menubar panel did nothing once the project's
`monitor_cc_<hash>` tmux session still existed but its Ghostty window had been closed by hand.
Observed in the menubar log: every click logged
`focus_worker session=monitor_cc_79b52c8d ... NO-OP reason=no_attach_client`.

## Root cause

`src/menubar/system.py:_open_or_focus_monitor` branched on `check_session_exists`: when the
session already existed, it called `_focus_worker(session_name)` — the same mechanism
`app.py:focusWorker_` uses for worker-viewer rows. `_focus_worker` finds its target by scanning
`ps -A` for a live `tmux attach`/`attach-session -t <session>` client and, per its own docstring,
deliberately does nothing when no such client is running (closed viewer window) — a user decision
that is correct for a worker-viewer row (see `process-docs/menubar_per_project/` for the
2026-09-03 button build) but wrong for the monitor button: a `monitor_cc_<hash>` tmux session
commonly outlives its Ghostty window (the user just closes the window), and every click on this
specific button is expected to always produce a visible result.

## Fix

`_open_or_focus_monitor(cwd)` no longer has a focus branch at all:
1. Derive `session_name` via `tmux_launcher.py:generate_session_name(cwd)` — unchanged, still
   never re-derived locally.
2. If `tmux_launcher.py:check_session_exists(session_name)` is true, kill it via the existing
   `tmux_launcher.py:kill_session(session_name)` helper (already used by
   `launch_split_screen`'s own stale-session cleanup — no new tmux-kill code was written).
3. Unconditionally call the existing `_launch_monitor(cwd)` — unchanged, still opens a NEW
   Ghostty window running `cd <MONITOR_CC_ROOT> && python3 workflow.py --project <cwd>`.

`_focus_worker` itself, `_find_worker_viewer_tty`, and `app.py:focusWorker_` were left untouched —
they remain the correct mechanism for worker-viewer rows, where a closed-window no-op is still the
intended behavior.

## Verification

Unit tests (`dev/menubar_per_project/test_open_or_focus_monitor.py`, stub-based, no real
tmux/osascript I/O): adapted the existing focus-vs-launch branch tests into a kill-then-relaunch
shape — asserts that an existing session triggers `kill_session(session_name)` followed by
`_launch_monitor(cwd)` (both, always), and that a non-existing session triggers only
`_launch_monitor(cwd)` with `kill_session` never called. All 11 checks (including the
pre-existing session-name-derivation, quoting-safety, and python3-plist-resolution checks,
unaffected by this change) passed. No production `monitor_cc_*` tmux session and no production
menubar bundle were touched — no live throwaway-cwd run was performed for this fix (the branch
logic is fully covered by the stub tests above).

## Deployment (not run by this change)

Same as every other `src/menubar/*.py` edit — the running production menubar is a frozen py2app
bundle and needs `./venv/bin/python setup_py2app.py py2app` to pick this up. See
`src/menubar/DOCS.md`'s "Restart ≠ code update" gotcha.
