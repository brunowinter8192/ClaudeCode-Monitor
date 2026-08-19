# Menubar Hotkey Latency — Production Build + Restart + Live Measurement (2026-08-19)

Milestone 2 of the hotkey-lag investigation (`process-docs/hotkey_latency/2026-08-19_instrumentation_build.md`
covers the instrumentation itself). This entry covers building the instrumented code into the
production py2app bundle, restarting the live menubar, and the first real `[latency]` evidence
from the actual running app (not from a throwaway test harness).

## Build Procedure Used

Located the established, single canonical build path — `setup_py2app.py` (project root),
documented in `process-docs/menubar_build/menubar_build_consolidation.md` as "the ONE complete
install" (build + install + bootstrap in one command). No new procedure invented.

```bash
./venv/bin/python setup_py2app.py py2app
```

Run from the worktree root (`.claude/worktrees/hotkey-latency/`, which has its own copy of
`setup_py2app.py` and the instrumented `src/menubar/`; `venv/` is a symlink to the main repo's
shared venv, already carrying `py2app`). One command did: py2app compile → `dist/monitor-cc-menubar.app`
→ `_prune_bundle_bloat()` (strips `src/logs/`, proxy/, panes/, etc. — keeps `menubar`,
`session_finder.py`, `constants.py`) → `_install_bundle()` (rmtree+copytree to
`~/Applications/monitor-cc-menubar.app`, ad-hoc codesign, write `~/Library/LaunchAgents/com.brunowinter.monitor-cc-menubar.plist`,
`launchctl bootout` + `bootstrap` with 1s retry).

Build output matched the documented-expected pattern exactly:
`codesign WARN (rc=1): replacing existing signature` (benign, per the consolidation doc) and
`bootstrap retry in 1s (rc=5)... bootstrap com.brunowinter.monitor-cc-menubar: ok` (the
documented "first bootstrap empirically fails rc=5, retry after 1s succeeds" pattern). Build
exit code 0.

## Restart Evidence

- Live process before build: PID 17707 (`pgrep -fl monitor-cc-menubar`), confirmed via
  `launchctl list | grep monitor-cc-menubar` → loaded, no exit status.
- Live process after build: PID 72617 — new PID confirms an actual process replacement, not
  just a plist rewrite.
- `~/Applications/monitor-cc-menubar.app/Contents/MacOS/monitor-cc-menubar` — Mach-O 64-bit
  arm64, mtime updated to the build time (rules out a stale-bundle no-op, the exact incident
  class documented in `src/menubar/DOCS.md`'s "Restart ≠ code update" gotcha).
- `TICK_LATENCY_THRESHOLD_MS` confirmed unchanged at 200 in the built source (not lowered for
  this test) — `git diff` showed a clean worktree post-build (no tracked file changed; `dist/`
  is gitignored).

## First Real Latency Evidence (production app, post-restart)

`menubar.log` resumed fresh `[detection]`/`[latency]` activity within ~7s of the new PID
starting. First cold-cache tick after restart:

```
2026-08-19T18:06:00 [latency] tick total=3611ms sessions_refresh_total=3548ms proc_cache=163ms
  ghostty=776ms tmux_state=13ms bg_task_lsof=110ms per_project_loop=1763ms desktop_detection=722ms
  bg_timer_scan=54ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=8ms
```

3.6s on the very first tick — all caches cold simultaneously (proc_cache, ghostty, tmux_state,
bg_task_lsof, desktop_detection all pay their full first-call cost at once). This alone
reproduces the user-reported "sometimes seconds" symptom class, though this specific tick is a
cold-start artifact, not a steady-state measurement.

50 `[latency]` tick lines accumulated in the following ~2 minutes of live running (unattended,
no user interaction) — EVERY tick exceeded `TICK_LATENCY_THRESHOLD_MS=200`, including
"steady-state" ticks with all caches warm:

```
2026-08-19T18:06:52 [latency] tick total=204ms sessions_refresh_total=171ms proc_cache=0ms
  ghostty=149ms tmux_state=5ms bg_task_lsof=0ms per_project_loop=16ms desktop_detection=0ms
  bg_timer_scan=33ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
```

Plus a periodic (~every 10-11s, matching `desktop_detection.py`'s `_DET_CACHE_TTL=10.0`) spike
back to ~1.1-1.2s driven by `desktop_detection` (~700-720ms) re-running.

## Root-Cause Candidate Found (via this data, not fixed — measurement milestone)

The steady-state `ghostty=145-165ms` appearing on nearly every single tick (not once per 10s,
despite `_GHOSTTY_TTY_REFRESH_INTERVAL=10.0`) traces to a real code path in
`ghostty.py:_refresh_ghostty_tty_to_id`: `_ghostty_tty_last_refresh` is only updated when new
TTYs were found to probe; once every current Ghostty TTY is already mapped (the common steady
state), the function returns early WITHOUT updating the timestamp, so its own TTL guard never
re-arms — `_ghostty_pid()` + `_ghostty_child_ttys()` (2 `ps -A` calls) run on literally every
1.5s tick, forever, not once per 10s as the constant name implies. This is the single largest
recurring contributor keeping steady-state ticks just over the 200ms threshold. Documented as a
`src/menubar/DOCS.md` Gotchas bullet (ghostty.py section) — left unfixed here; this milestone
was build+restart+verify-instrumentation only.

## Unrelated Observation (pre-existing, not caused by this change)

Post-restart, `desktop_detection` consistently returned `all_failed reason=all_no_match` /
`cgw_list_empty ... no_names_returned` for all 5 live main sessions — `desktop_detection.py`'s
own diagnostic logging (untouched by this milestone) fired as designed. Plausible cause: the
ad-hoc re-codesign on every build changes the bundle's signature hash, which can invalidate the
existing Screen Recording TCC grant (`kCGWindowName`/`CGSCopyWindowProperty` visibility) until
the user re-approves in System Settings — consistent with `desktop_detection.py`'s own TCC note
in `DOCS.md`. Not investigated further — outside this milestone's scope (measurement +
restart-verification only); flagged for whoever picks up the actual fix milestone.

## What Was NOT Verified

Hotkey queue-delay (`hotkey=... queue_delay_ms=...` lines) requires a real Cmd+K/L/1..9 press —
the agent cannot generate one. No such lines appear yet in the post-restart log window. Per the
milestone's own instruction, this data comes from the user pressing hotkeys during normal use
after this build; `dev/hotkey_latency/analyze_latency.py` re-run against the accumulated log
later will surface the queue-delay percentiles.
