# Menubar Hotkey Latency — Discovery Moved Off Main Thread + Ghostty TTL Fix (2026-08-19)

Milestone 3 of the hotkey-lag investigation (`process-docs/hotkey_latency/2026-08-19_instrumentation_build.md`
= M1 instrumentation, `2026-08-19_production_bringup.md` = M2 first live measurement). This entry
covers the structural fix: moving the whole discovery pipeline (`list_alive_sessions()` +
`_scan_bg_sleep_timers()`) off the main thread onto a background daemon thread, plus the
`ghostty.py` TTL re-arm fix M2 identified as the largest recurring steady-state cost.

## Design

New module `src/menubar/discovery_worker.py`: `start_discovery_worker()` spawns one daemon
thread (idempotent) running a self-paced ~1.5s loop — `list_alive_sessions()` →
`_scan_bg_sleep_timers()` → publish a `DiscoverySnapshot(sessions, bg_by_project, ts)` under a
`threading.Lock()` → log `[latency] bg_refresh ...` when the cycle exceeds
`BG_REFRESH_LATENCY_THRESHOLD_MS=200` (own constant, mirrors `app.py`'s `TICK_LATENCY_THRESHOLD_MS`
by value, not import, to avoid a circular import). Whole-cycle `try/except` keeps the thread
alive across any single bad cycle.

`sessions_controller.py:SessionsController.refresh()` no longer calls `list_alive_sessions()` —
it reads `discovery_worker.get_latest_snapshot()` (cheap in-memory read, no I/O). Signature/return
type unchanged, so the 6 pre-existing `.refresh()`-only call sites (`queue_controller.py` x4,
`panel_lifecycle.py:_open_queue_panel`, `windowDidEndLiveResize_` queue branch) needed zero
changes. New `.bg_by_project` property added for the 4 call sites that previously called
`_scan_bg_sleep_timers()` directly: `app.py:_tick`, `abortBgTimer_`, `windowDidEndLiveResize_`
(panel branch), `panel_lifecycle.py:_open_main_panel`. After this change, no main-thread code
anywhere in `src/menubar/` calls `list_alive_sessions()` or `_scan_bg_sleep_timers()` directly —
confirmed via grep across the whole package post-change.

## Concurrency Consequence: One New Cross-Thread Hazard, Fixed

Consequence stated explicitly per the milestone's own framing: module-level caches in
`proc_cache.py`, `ghostty.py`, `desktop_detection.py` are now written ONLY by the discovery-worker
thread. Auditing every reader of those caches found exactly ONE surviving cross-thread READ:
`system.py:_focus_session` (main thread, click/hotkey-triggered) → `ghostty.py:get_ghostty_terminal_id`
→ `_tty_for_cwd`, which iterated `proc_cache.py:_cc_proc_cache.items()` directly. With a second
thread now mutating that dict (`_refresh_cc_proc_cache`'s `del`/insert), this iteration could
raise `RuntimeError: dictionary changed size during iteration` — a hazard that did not exist
before (single-threaded). Confirmed with a real concurrent stress test BEFORE fixing: an
unprotected baseline (`del`+insert churn on one thread, `.items()` iteration on 4 reader threads,
2s) produced 213 `RuntimeError`s. Fix: `proc_cache.py` gained `_cc_proc_cache_lock`
(`threading.Lock()`); `_refresh_cc_proc_cache` now builds new lsof-derived entries in a local dict
OUTSIDE the lock (never hold a lock across subprocess I/O) and applies both the stale-PID
deletions and new entries to `_cc_proc_cache` in one locked block; new
`cc_proc_cache_snapshot()` returns a lock-protected copy — `ghostty.py:_tty_for_cwd` now reads
through that instead of the raw dict. Re-ran the identical stress pattern (4 readers, 3s) against
the fixed code: 0 errors. `get_ghostty_terminal_id`'s own `_ghostty_tty_to_id.get(tty)` read
needed no fix — a single-key `.get()` is safe under the GIL without a lock (only iteration over a
mutating dict is unsafe).

`discover.py`'s and `ghostty.py:_write_cwd_uuid_map`'s own direct `_cc_proc_cache.items()` reads
were left unchanged — both run only inside `list_alive_sessions()`, i.e. only on the
discovery-worker thread (same thread as the writer post-M3), no race.

Two trade-offs identified and accepted (not fixed, low severity):
1. `menubar_log.cleanup_old_lines()` (main thread, once/24h) does a non-atomic full-file
   read+rewrite; a concurrent bg-thread `log_menubar()` append during that window could in theory
   be lost. Diagnostic-log-only, self-heals next line.
2. On launch, the panel shows 0 sessions for the first ~1.5-4s until the bg thread's first
   (possibly cold-cache) cycle completes — the main thread no longer blocks waiting for it.

## ghostty.py TTL Re-Arm Fix

`_refresh_ghostty_tty_to_id`'s `if not new_ttys:` branch (the STEADY-STATE case — fires every
cycle once all live TTYs are mapped) used to return WITHOUT updating `_ghostty_tty_last_refresh`,
so `_GHOSTTY_TTY_REFRESH_INTERVAL=10.0`'s guard never re-armed — `_ghostty_pid()` +
`_ghostty_child_ttys()` (2 `ps -A` calls) ran on every single discovery cycle, not once per 10s
(M2 measured ~145-165ms of `ghostty`-phase cost on nearly every cycle). One-line fix: set
`_ghostty_tty_last_refresh = now` in that branch before returning. Accepted trade-off: a
newly-opened terminal's tty→uuid mapping may lag up to 10s. The sibling `if not ghostty_pid:
return` branch has the identical latent bug (fires only when Ghostty itself isn't running) — left
unfixed, not the measured steady-state case, out of this milestone's stated scope.

## Verification

**Regression guards (existing dev smoke suites, unchanged code paths):**
`dev/timer-loop/test_abort_stamp_scope.py` (6/6 passed) and `dev/hook_smoke/test_bg_task_detection.py`
(6/6 passed) — both exercise `bg_timer.py`/`proc_cache.py` code the `_cc_proc_cache_lock`
restructuring touched; confirms the lock addition didn't change `_has_active_bg`/
`_abort_bg_sleep_timers` behavior.

**Integration-level (real calls, real threads, this session):**
- Started `discovery_worker` for real, waited for the first cycle: `sessions=8`,
  `bg_by_project={'monitor-cc': BgSleepInfo(min_remaining=3122, sleep_pids=[12657])}` after 4.56s
  (cold cache) — `SessionsController.refresh()`/`.bg_by_project` correctly read the published
  snapshot.
- Concurrency stress test (above): 213 errors unprotected → 0 errors with the fix, same load
  pattern, real threads, real dict mutation.
- Constructed a real `CCMenuBarApp`, started the worker, called `_tick(None)` repeatedly:
  tick 1 (worker just started) = 34ms wall (mostly one-time init, not discovery); ticks 2-7 =
  0.000-0.007s wall. `[latency] snapshot_consume=0ms` confirmed in the log for every one of these
  ticks — zero `[latency] tick` lines logged (nothing exceeded the unchanged 200ms threshold).
- `discovery_worker.py` cycle timing directly observed (threshold forced to 0 in a throwaway test
  process only, never in the production build): cold first cycle 3935ms
  (`desktop_detection=2792ms`), then 61ms/47ms/53ms/56ms/... with `ghostty=0ms` on the large
  majority of cycles — direct confirmation the TTL fix works, not just in theory.

**Production build + restart (same procedure as M2 — `./venv/bin/python setup_py2app.py py2app`):**
build succeeded (`bootstrap: ok` on first try this time, no retry needed), PID changed
34075→62728 confirming a real restart, no stderr/stdout errors from the new process. Live
`menubar.log` post-restart transition observed directly: last old-shape `[latency] tick` line
(with `sessions_refresh_total=...`, the pre-M3 12-phase shape) at `18:46:26` — the moment the old
process actually exited; from `18:46:30` onward, **zero** `[latency] tick` lines appeared over the
following ~1.5 minutes of live running (multiple real Cmd+K/Cmd+L/Cmd+3 presses from the user
during that window, confirmed via `[latency] hotkey=...` lines interleaved), replaced entirely by
periodic `[latency] bg_refresh` lines (~every 10-11s, `total≈1100-1200ms`, driven by
`desktop_detection≈700ms` — matches the `_DET_CACHE_TTL=10.0` cadence, an unrelated,
already-documented cost). `dev/hotkey_latency/analyze_latency.py` re-run against the live log
(861 tick lines total across the whole 7-day-retention window — the pre-fix majority — vs. 33
bg_refresh lines from the post-fix window so far) produced
`dev/hotkey_latency/md/latency_report_20260819T164925Z.md`; hotkey queue-delay across 89 real
captured presses (`cmd+k`×67, `cmd+l`×12, `cmd+1..3`×3-4 each — genuine user presses during this
session, not synthetic): median 0.2ms, p95 0.5ms — Carbon event delivery itself was never the
bottleneck; the delay the user perceived pre-fix must have come from the main thread being
blocked processing a slow tick when a press landed (or from the visible delay in the panel
populating), not from queued-but-undelivered Carbon events. `_focus_session` split (11 samples):
`lookup_ms` ~0, `osascript_ms` median 87.1ms — unrelated to this milestone's fix, unchanged from
M2 (out of scope, `_focus_session` sync behavior explicitly not touched).

## What Remains Open

`osascript_ms` (~85-120ms per focus call) and `desktop_detection`'s periodic ~700ms-1ms retry
(both now isolated to the background thread, no longer blocking the main thread or hotkey
handlers) were explicitly out of this milestone's scope. Hotkey queue-delay data is now
substantially populated with real user presses (89 samples) showing no bottleneck at the Carbon
level — any further investigation into perceived hotkey lag should look at panel-populate timing
or the window between a press and the visible UI update, not Carbon event queuing.
