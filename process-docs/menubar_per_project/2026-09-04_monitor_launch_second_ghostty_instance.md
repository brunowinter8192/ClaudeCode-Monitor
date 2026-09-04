# Monitor launch spawned a second Ghostty process, breaking click-to-focus for every window

Date: 2026-09-04

## Symptom

Observed 2026-09-04 14:57, right after a rebuild: clicking the mon button launched a SECOND
Ghostty process — `ps` showed `/Applications/Ghostty.app/Contents/MacOS/ghostty
--quit-after-last-window-closed=true --window-save-state=never -e /bin/sh -c cd ...
workflow.py --project ...`. From that point on, `tell application "Ghostty"` AppleScript calls
answered from that second instance, which had exactly one window — `desktop_detection.py` and
`ghostty.py` lost every real main window (menubar log: `all_failed n_mains=4
reason=all_no_match`, then silence as the tty→UUID map went empty).

## Root cause

`system.py:_launch_monitor` gated between two launch mechanisms via `_ghostty_version()` (`ghostty
+version`, parsed for major.minor): `>= (1, 3)` → `_launch_monitor_ghostty_native` (in-process
AppleScript `new window`); otherwise → `_launch_monitor_ghostty_fallback` (`open -na Ghostty.app
--args ...`). The `ghostty` CLI binary lives only under
`/Applications/Ghostty.app/Contents/MacOS/`, which is NOT on the menubar's launchd PATH (the
plist's `EnvironmentVariables/PATH` is Homebrew-first + system dirs, per `src/menubar/DOCS.md`'s
"launchd PATH inheritance" gotcha) — so under the real launchd process, `subprocess.run(['ghostty',
'+version'])` always raised `FileNotFoundError`, `_ghostty_version()` always returned `(0, 0)`, and
the fallback ALWAYS fired in production, even though the installed Ghostty is 1.3.1 (confirmed via
`ghostty +version` from an interactive shell where the binary IS on PATH — this is exactly why the
2026-09-03 build's live verification, run from a worktree venv shell rather than through the real
launchd-run bundle, never caught it). `open -na Ghostty.app` spawns a brand-new, separate Ghostty
process instance rather than opening a window in the already-running one — from then on, every
future `tell application "Ghostty"` AppleScript call from the menubar (click-to-focus for main
sessions, worker viewers, and this same monitor button on its next click) is answered by
whichever instance macOS routes it to, not necessarily the original one with all the real windows.

## Fix

Removed the fallback path entirely rather than fixing the version lookup (e.g. by hardcoding the
`/Applications/Ghostty.app/Contents/MacOS/ghostty` path) — the installed Ghostty (1.3.1) already
satisfies the native-path requirement, and a version check whose only job was to select between
"native" and "spawn a second instance" is a liability now that the second option is known to
actively corrupt the running instance's AppleScript addressability. `_launch_monitor` now calls
`_launch_monitor_ghostty_native(shell_cmd)` unconditionally. `_ghostty_version()` and
`_launch_monitor_ghostty_fallback()` are deleted from `system.py`. A failing `osascript` (e.g. a
future Ghostty removal or crash) stays a logged `[monitor] launch FAILED cwd=... rc=...
stderr=...` line — a tripwire, not a substitute launch mechanism.

## Verification

Unit tests (`dev/menubar_per_project/test_open_or_focus_monitor.py`, stub-based, no real
Ghostty/tmux I/O): added `_test_launch_monitor_uses_native_path_only` — asserts `_ghostty_version`
and `_launch_monitor_ghostty_fallback` are no longer attributes of `src.menubar.system`, and that
`_launch_monitor` calls a stubbed `_launch_monitor_ghostty_native` unconditionally with the built
shell command. All 14 checks (the 3 new ones plus the 11 pre-existing session-name/quoting/
kill-then-relaunch/python3-resolution checks, unaffected by this change) passed. No live
throwaway-cwd run was performed for this fix — the removed branch was the one under test, and
exercising the surviving native path live is unchanged from the 2026-09-03 build's own
verification (already covered there). No production Ghostty process, no production `monitor_cc_*`
tmux session, and no production menubar bundle rebuild were touched.

## Cross-reference

See `process-docs/menubar_per_project/` for the button's original build (2026-09-03) and the
kill-then-relaunch fix for the no-op-on-stale-session bug, also 2026-09-04.
