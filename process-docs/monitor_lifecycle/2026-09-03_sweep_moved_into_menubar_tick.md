# Daily monitor sweep moved from its own LaunchAgent into the menubar's tick

Date: 2026-09-03

## Why

The dedicated `com.brunowinter.monitor-cc-sweep` LaunchAgent (`src/setup_monitor_sweep.py` +
`src/com.brunowinter.monitor-cc-sweep.plist`) could not be made to work under launchd: a bare
launchd-spawned `/usr/bin/python3` has no TCC Full Disk Access grant for a checkout under
`~/Documents`, and that specific block cannot be worked around by any plist or code change (fully
diagnosed by real launchd runs, not hand-run shell repros — see `process-docs/monitor_lifecycle/`
for the diagnostic sequence). The user's decision:
the menubar app already runs under launchd AS a codesigned py2app bundle WITH that TCC grant
(Screen Recording + Full Disk Access are tied to the bundle's stable code-signing identity, not
to a bare interpreter), already has a periodic tick (`app.py:_tick`, ~1.5s), and already talks to
tmux — so host the daily sweep there instead of maintaining a second, permanently-blocked
LaunchAgent.

## Design

**Gate state lives in a dedicated file under `paths.py`'s `_APP_SUPPORT`, not `settings.json`.**
`MONITOR_SWEEP_STATE_FILE` (`monitor_sweep_state.json`, `{last_run_ts}`) is separate from
`app_settings.py`'s `SETTINGS_FILE`. Two reasons: (1) `settings.json` is read/written by user-
action-triggered code (`toggleAutoJump_`, `windowDidResize_`) — folding an unrelated maintenance-
cron marker into the same file risks two concurrent writers racing on the same atomic-replace
cycle, and mixes two unrelated concerns (UI preferences vs. a once-a-day scheduling marker);
(2) a dedicated small file matches the existing one-file-per-concern precedent already used for
`PID_FILE`/`HOOKS_FILE`/`GHOSTTY_CWD_UUID_FILE` in the same module.

**The gate is on-disk, not in-memory — deliberately unlike `app.py`'s own
`_last_log_cleanup_ts`.** That existing 24h-cleanup timer is a bare instance float with no
persistence — a menubar restart harmlessly resets it, causing one extra cleanup pass. The sweep
gate cannot behave that way: the task explicitly requires a restart not to re-run the sweep
early, so `monitor_sweep_scheduler.py` reads/writes `MONITOR_SWEEP_STATE_FILE` and only caches
the value in memory after the first read (avoiding a per-tick disk read for the ~57,600 ticks
between two due sweeps).

**The attempt timestamp is written BEFORE the sweep runs, not after it completes.** A crashed or
hung sweep must not cause the very next 1.5s tick to re-fire it — the on-disk timestamp records
"a sweep was attempted at this time", the same semantics a daily cron job typically wants for an
idempotent, safe-to-skip-a-day maintenance task. Verified directly:
`test_monitor_sweep_scheduler.py`'s `_test_attempt_timestamp_persisted_before_sweep_completes`
holds a stubbed sweep open on a `threading.Event` and reads the state file mid-run.

**The actual sweep runs on its own one-shot daemon thread, mirroring `discovery_worker.py`'s
offload shape.** `bg_timer.py` itself spawns no thread — its recurring work
(`_scan_bg_sleep_timers`) is offloaded by being CALLED FROM `discovery_worker.py`'s
already-running background thread, not by owning a thread of its own; its one-off
`_abort_bg_sleep_timers` runs synchronously on the main thread because it's a deliberate,
rare, user-click action. The sweep is a periodic (if rare — once/24h) background chore
unrelated to session discovery, so piggybacking it onto `discovery_worker.py`'s loop would
couple two independent concerns; a fresh `threading.Thread(target=_run_sweep, daemon=True)`
per due cycle (the literal mechanism `discovery_worker.py` itself uses to get off the main
thread) was the closer fit.

**`MONITOR_CC_ROOT` is set from `paths.py`, not passed into `monitor_janitor.py` as a new
concept.** `monitor_janitor.py:_resolve_monitor_cc_root()` already had an env-var-or-`__file__`
resolution (added for the now-removed LaunchAgent's own two invocation paths). Rather than
teach that generic module about menubar-specific naming (`PROJECT_ROOT`, the menubar plist's own
env var), `monitor_sweep_scheduler.py._run_sweep()` sets `os.environ.setdefault('MONITOR_CC_ROOT',
str(paths.MONITOR_CC_ROOT))` immediately before calling `sweep_workflow()` — reusing the
`MONITOR_CC_ROOT` constant `system.py`'s monitor-launch button already established the previous
milestone (env var wins, else `Path(__file__).resolve().parents[2]`), which is exactly correct
here too: a frozen py2app bundle's own `__file__` resolves inside the bundle copy, not the real
checkout, so without this the sweep log would land in the wrong (nonexistent, bundle-internal)
place under a rebuilt bundle.

## py2app bundling — evidence

`src.monitor_janitor` (imported lazily by the new module) and `src.tmux_launcher` (imported by
`system.py` the previous milestone) were NEITHER in `setup_py2app.py`'s `OPTIONS['includes']`
NOR in `_BUNDLE_SRC_KEEP` before this fix — meaning the previous milestone's monitor-launch
button was ALREADY silently broken in a rebuilt production bundle, undetected since no rebuild
happened between that milestone and this one.

Root cause, from the pre-existing code comment on `OPTIONS['packages']`: `'packages':
['src.menubar', 'rumps']` tells py2app to copy `src.menubar`'s entire source tree wholesale as a
package, WITHOUT running modulegraph's per-file import scanner over its contents — that's the
documented reason `session_finder`/`constants` (imported from inside `src.menubar` via `..`)
already needed an explicit `includes` entry. A raw `modulegraph.ModuleGraph` trace from
`menubar_main.py`, run WITHOUT setting `'packages'` (i.e. not reproducing the actual py2app
bundling mode), finds `src.session_finder`, `src.constants`, `src.tmux_launcher`, and
`src.monitor_janitor` all four via plain static analysis — confirming they're all real,
literal, statically-visible import statements, but NOT proving py2app's own `packages`-mode
graph would find them (a full py2app build was explicitly out of scope for this task, so this
could not be tested directly). Given `tmux_launcher.py`/`monitor_janitor.py` are imported from
inside `src.menubar` the exact same way `session_finder.py`/`constants.py` already are (and
those two are the established, working precedent for needing the explicit include), added both
to `OPTIONS['includes']` and to `_BUNDLE_SRC_KEEP` (the whitelist `_prune_bundle_bloat()` prunes
against post-build — required independent of modulegraph's tracing behavior, since pruning
operates on a fixed filename list regardless of how a file got bundled).

## Verification

- `dev/monitor_lifecycle/tests/test_monitor_sweep_scheduler.py` (new, 9 checks, run 3x for
  timing-flake stability): pure `_is_sweep_due` boundaries (fresh/1h/25h/exactly-24h), the full
  `maybe_run_sweep_workflow` integration against an isolated temp state file (fresh state runs, a
  run 1h ago does not, a run 25h ago does), the re-entry guard against a concurrent trigger, and
  the attempt-timestamp-before-completion ordering. `_run_sweep` stubbed throughout — never
  touches real tmux state.
- `dev/monitor_lifecycle/tests/test_monitor_sweep.py` (pre-existing, unmodified): still 11/11,
  confirming the actual sweep logic is untouched by this migration.
- Real end-to-end sanity call: invoked `monitor_sweep_scheduler._run_sweep()` directly (bypassing
  the 24h gate) against the 3 real `monitor_cc_*` sessions running on this machine at the time
  (ages 1.6-2.1h, verified via `tmux list-sessions` before the call) — logged
  `[monitor_sweep] ran sessions=3 killed=0 spared=3` to the shared `menubar.log`, all three
  correctly spared (none old enough to kill), and wrote `src/logs/monitor_sweep.log` inside THIS
  worktree (not the main checkout) — confirming `MONITOR_CC_ROOT` resolution worked exactly as
  designed with no `PROJECT_ROOT` env var set in the shell. `tmux list-sessions` confirmed
  unchanged immediately after. No production session was killed or otherwise touched.

## Deployment (not run by this change)

Same as the prior monitor-button milestone — a `src/menubar/*.py` + `setup_py2app.py` source
edit only, invisible to the running production bundle until rebuilt:
`./venv/bin/python setup_py2app.py py2app` from the actual checkout root.
