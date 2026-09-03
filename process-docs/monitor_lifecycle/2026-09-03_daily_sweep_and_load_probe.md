# Daily monitor_cc_* sweep + load probe, 2026-09-03

## Problem

`workflow.py --project <path>` runs one tmux session per project, `monitor_cc_<md5(project)[:8]>`,
with nine pane processes (`workflow.py --mode <mode>`). Closing the Ghostty window only detaches
tmux — the nine panes keep running. Nothing else ever ends a monitor. At build time, three
projects had monitors open (27 Python processes total, confirmed by
`dev/monitor_lifecycle/probe_monitor_load.py`'s baseline run) and a prior day's session — one of
those monitors plus a CPU-hungry `workers` pane — produced a system overload (Activity Monitor
showed roughly a dozen single-thread Python processes with 30 min to over an hour of CPU time
each). There was no mechanism that ever ended a monitor unprompted.

## Decision: registry-free sweep, unconditional 24h, no working-skip guard

Modeled on the worker-cli janitor (`process-docs/worker_janitor/`) but deliberately simpler:

- **Enumeration is registry-free** — `tmux list-sessions -F '#{session_name}|#{session_created}'`
  directly, filtered to the `monitor_cc_` prefix. Same lesson as the worker janitor: a
  registry can lose a live session; tmux itself cannot.
- **No working-skip guard.** The worker janitor spares a worker mid-turn because killing it costs
  real in-flight state. A monitor pane has no mid-turn state worth sparing — it is a passive
  display over JSONL/proxy logs, always safely restartable via `workflow.py --project <path>`
  (or `Ctrl+R` self-heal, `tmux_launcher.restart_panes`). So age alone gates the kill, no
  status check needed.
- **Kill is by exact tmux session name** (`tmux kill-session -t <name>`), never `pkill -f`. See
  `process-docs/pipeline/` for the incident record: `pkill -f <pattern>` matched worker cmdlines
  that happened to contain the pattern in their prompt text, killing 3 unrelated workers in one
  session alone. A monitor pane's cmdline is `python3 workflow.py --mode <mode> --project <path>`
  — a `pkill -f` on any project-path fragment would risk the same collateral match against a
  worker whose prompt mentions that path. Exact-name `tmux kill-session` has no such risk.
- **Threshold is unconditional 24h, no flag.** `sweep_workflow(max_age_seconds=...)` accepts an
  override only so the regression test can inject a short threshold against real throwaway
  sessions (tmux's `session_created` cannot be backdated) — production call sites never pass one.

## Kill-session pane teardown, verified

`tmux kill-session` was verified (not assumed) to reap every pane's process, not just detach it:
created a session with a real `sleep 120` child as the pane command, captured `#{pane_pid}`,
killed the session, and confirmed `ps -p <pid>` returned rc=1 (no such process) immediately after.
Folded into `dev/monitor_lifecycle/tests/test_monitor_sweep.py` as a standing regression check
(`testold pane process reaped (no orphan)`), run against `monitor_cc_testold`/`_testnew` fixtures
plus an untouched `worker-testkeep` control — not against real monitor sessions, since a full
nine-pane real monitor needs an actual project checkout to launch meaningfully and the process-
teardown behavior is a tmux property, not something specific to `workflow.py`'s nine commands.

## Invocation: `python3 -m src.monitor_janitor`, not a new workflow.py mode

Considered adding a `sweep` mode to `workflow.py`/`startup.py` (the existing dispatch pattern for
one-off pane processes like `gpu`/`news`). Rejected — it would touch two extra files
(`startup.py`'s argparse choices, `workflow.py`'s `main()`) for no gain: `src/__init__.py`
already makes `src` a real package, so `python3 -m src.monitor_janitor` (run with CWD = repo
root) resolves `monitor_janitor.py`'s own relative import of `tmux_launcher.kill_session`
without any `sys.path` gymnastics, and needs zero other files touched. `claude_proxy_start.sh`'s
trigger wraps the call in `( cd "$MONITOR_CC_ROOT" && ... )` since the caller's CWD is
whatever `--project` pointed at, not necessarily the repo root.

## Two triggers, one log

1. `src/claude_proxy_start.sh` — a `nohup ... & ` detached block right after the existing
   `worker-cli janitor` trigger, same fully-detached idiom, but with no `command -v` guard (this
   is a same-repo module, always present, unlike the external `worker-cli` binary).
2. `com.brunowinter.monitor-cc-sweep` LaunchAgent (`src/com.brunowinter.monitor-cc-sweep.plist`),
   `StartCalendarInterval` at 04:00 daily — covers the case where no main session starts for
   days (a monitor from three days ago outlives every session-start trigger otherwise). Modeled
   on `src/menubar/com.brunowinter.monitor-cc-menubar.plist`'s `PATH` block (launchd's default
   PATH has no Homebrew; `tmux`, invoked by `monitor_janitor.py` via `subprocess`, lives in
   `/opt/homebrew/bin`). Unlike the menubar plist, no `RunAtLoad`/`KeepAlive` — this is a
   one-shot daily job, not a long-running app to keep alive. `src/setup_monitor_sweep.py` mirrors
   `src/menubar/setup_menubar.py`'s `write_plist()` (token-substitute `<PROJECT_ROOT>`, write to
   `~/Library/LaunchAgents/`) but stops short of bootstrapping — `bootstrap_command()` only
   returns the `launchctl bootstrap` string for the user to run themselves; installing a
   LaunchAgent that fires unconditionally every day is not something to do without the user's
   explicit go-ahead.

Both triggers write to the same `src/logs/monitor_sweep.log` (registered in `src/log_janitor.py`'s
`_LOG_REGISTRY` as `monitor_sweep`, `sweep_eligible=False` — plain text, not JSONL, so
`cleanup_old_jsonl`'s per-line `ts`-field parse does not apply; volume is a handful of lines per
day, no rotation built for it yet).

## Verification (2026-09-03)

- Live run against the three real monitors on the build machine (all under 2h old): all three
  logged `SPARED`, none killed, all nine-pane sets confirmed still present afterward via
  `tmux list-sessions`.
- `dev/monitor_lifecycle/tests/test_monitor_sweep.py`: 11/11 checks pass — enumeration finds both
  `monitor_cc_test*` fixtures and excludes `worker-testkeep`; sweeping only the fixture pair (not
  the real sessions) kills `testold` (session gone, real child PID reaped) and spares `testnew`;
  `worker-testkeep` session and process both untouched throughout; both decisions logged.
- `dev/monitor_lifecycle/probe_monitor_load.py`: baseline run found 27 panes across the three
  live sessions (matches the reported "27 Python processes" count), sorted by CPU time — top
  offender was a `workers` pane at 2:33 CPU time / 6.3% CPU, 46 min old. Report saved to
  `dev/monitor_lifecycle/reports/2026-09-03_monitor_load_baseline.md` as the reference point for
  the next suspected overload.
- NOT verified: the LaunchAgent actually firing under launchd (not installed, per scope — the
  user runs `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.brunowinter.monitor-cc-sweep.plist`
  themselves; `write_plist()`'s token substitution was checked against a temp directory only).
