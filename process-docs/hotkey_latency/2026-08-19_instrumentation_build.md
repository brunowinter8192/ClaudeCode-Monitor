# Menubar Hotkey Latency — Instrumentation Build (2026-08-19)

Measurement-only milestone for the intermittent Cmd+K/L/1..9 lag reported by the user
(sometimes seconds). Working hypothesis at start: main-thread contention — Carbon hotkey
handlers run on the app's main runloop; the 1.5s `_tick` (`src/menubar/app.py`) does
synchronous subprocess work (ps/lsof with 2-3s timeouts, tmux calls, AppleScript round-trips
to Ghostty) on that same thread. This entry covers the instrumentation build + its own
end-to-end verification, not a diagnosis — no behavioral fix went in.

## What Was Built

1. **Tick phase timing** (`app.py:_tick`, `discover.py:list_alive_sessions`) — `time.monotonic()`
   around each sub-phase; `discover.py` stores 6 sub-phase durations (`proc_cache`, `ghostty`,
   `tmux_state`, `bg_task_lsof`, `per_project_loop`, `desktop_detection`) in module-level
   `_last_timings`, exposed via `get_last_session_timings()`; `app.py` merges those into its own
   5 top-level phases (`bg_timer_scan`, `focus_tick`, `queue_tick`, `rag_tick`,
   `panel_rebuild_update`) and logs ONE `[latency]` line via `log_menubar` only when total tick
   duration exceeds `TICK_LATENCY_THRESHOLD_MS` (module constant, 200ms default) — silent below
   threshold.
2. **Hotkey queue-delay** (`hotkey_controller.py`) — `_load_carbon()` now binds
   `GetEventTime(event)` / `GetCurrentEventTime()` (both `EventTime` = C double, seconds since
   boot, same clock domain). All 4 handler closures (Cmd+L, Cmd+K, digit dispatch, arrow
   dispatch) capture `GetCurrentEventTime()` as their literal first statement; on a matched press,
   shared helper `_log_queue_delay` logs `hotkey=<name> queue_delay_ms=<entry_t - event_t>`. This
   delta is the direct main-thread-stall measure — gap between OS-level event queuing and the
   handler actually executing.
3. **Focus-path split** (`system.py:_focus_session`) — separately times
   `get_ghostty_terminal_id(cwd)` (`lookup_ms`) and the `osascript` subprocess run
   (`osascript_ms`); both appended to the existing `/tmp/monitor-cc-menubar_focus.log` line and
   emitted as a `log_menubar('latency', ...)` line.
4. `dev/hotkey_latency/probe_get_event_time.py` — standalone symbol-resolution + live-press probe.
5. `dev/hotkey_latency/analyze_latency.py` — parses `menubar.log` `[latency]` lines into a
   distribution report (per-phase mean/median/p90/p95/max, slowest N ticks with breakdown,
   per-hotkey queue-delay percentiles, focus lookup-vs-osascript split).

All 4 new instrumentation categories share `log_menubar('latency', ...)` so the analyzer only
greps one category. No existing behavior changed — pure addition of timing capture + gated
logging (constraint: no async dispatch, no caching changes, no reordering).

## Verification (real integration-level, on this machine, 2026-08-19)

- `list_alive_sessions()` called directly against real `~/.claude/projects/` data (8 live
  sessions on this machine) — `get_last_session_timings()` returned all 6 sub-phases populated
  with real durations.
- A real `CCMenuBarApp` instance was constructed (full `rumps.App` init + `initializeStatusBar()`,
  without entering the blocking `AppHelper.runEventLoop()`) and `_tick(None)` called twice
  (`TICK_LATENCY_THRESHOLD_MS` forced to 0) — produced real `[latency]` lines in the live
  `menubar.log`, e.g.:
  `tick total=4433ms sessions_refresh_total=4390ms proc_cache=393ms ghostty=581ms tmux_state=6ms
  bg_task_lsof=137ms per_project_loop=19ms desktop_detection=3255ms bg_timer_scan=35ms
  focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=7ms`.
- `_focus_session()` called with a real session cwd — real Ghostty AppleScript focus round-trip,
  logged `lookup_ms=0.0 osascript_ms=87.1`.
- `GetCurrentEventTime()` resolved and returned monotonically increasing plausible doubles
  (~873752s uptime) via `_load_carbon()`; `_log_queue_delay` verified at the unit level with a
  fake Carbon object (`event_t=1000.000`, `entry_t=1000.0123` → logged `queue_delay_ms=12.3`,
  matching the spec format exactly).
- `RegisterEventHotKey`/`InstallEventHandler` for a throwaway Cmd+Shift+9 hotkey succeeded
  (non-null `hk_ref`) — confirms the probe's registration path works; a live keypress delta could
  not be captured in this session (no interactive GUI keypress available to the agent) — documented
  as the one gap, left for a human/live-verification pass.
- `analyze_latency.py` run against the real `menubar.log` (containing the above test-generated
  lines): `ticks=4 hotkeys=1 focuses=1`, report written to
  `dev/hotkey_latency/md/latency_report_20260819T155946Z.md` with correct sections (tick
  distribution + per-phase + slowest-4, hotkey per-name percentiles, focus lookup/osascript split).

**Side effects of verification** (disclosed): the test calls ran against the REAL live
`menubar.log` (shared with the actual running menubar app) and the REAL live Ghostty app —
one test press actually shifted terminal focus, and the `[latency]`/`[detection]` test lines are
now persisted in the production log (subject to the existing 7-day `cleanup_old_lines` rotation).
No `src/` behavior was changed and the live menubar process itself was not restarted/touched.

## Preliminary Signal (not a diagnosis)

The one real over-threshold tick captured cold-cache (`desktop_detection=3255ms`,
`sessions_refresh_total=4390ms`, `tick total=4433ms`) is consistent with the main-thread-
contention hypothesis — `desktop_detection` alone (AppleScript + CGS calls) exceeded 3s on a
single call. `proc_cache` (10s TTL), `ghostty` (10s TTL), and `desktop_detection` (10s TTL) are
cache-gated, so most of ~1.5s ticks should skip them cheaply (the second captured tick was 53ms
total) — the slow tick likely coincided with several TTLs expiring simultaneously. This is a
single cold-start sample, not a distribution — the next step (out of this milestone's scope) is
running the menubar live for an extended period and analyzing the accumulated `[latency]` lines
with `analyze_latency.py` to see real-world tick and hotkey queue-delay distributions, then
deciding on a fix (async dispatch off the main thread, TTL tuning, or similar) in a follow-up
milestone.
