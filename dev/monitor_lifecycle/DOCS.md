# dev/monitor_lifecycle/

## Role

Load visibility and regression coverage for the monitor's tmux-session lifecycle: each project's
`monitor_cc_<hash>` session runs nine panes indefinitely until something kills it (see
`src/monitor_janitor.py`). This directory holds the load probe used to establish a CPU/age
baseline before the next overload, the regression test for the sweep that ends stale sessions,
and the gate test for the daily-tick trigger that now runs that sweep (`src/menubar/monitor_sweep_scheduler.py`
— the sweep's own dedicated LaunchAgent was removed 2026-09, blocked by a TCC Full Disk Access
wall under launchd; see `process-docs/monitor_lifecycle/`).

## Modules

### probe_monitor_load.py (136 LOC)

**Purpose:** Snapshot every pane of every live `monitor_cc_*` tmux session — mode, PID, pane age,
CPU time, %CPU (all from `ps`) — plus each session's own age; print a table sorted by CPU time
(descending) and save the same data as a dated markdown report.
**Reads:** Live tmux state (`tmux list-panes -a`) and live process state (`ps`) — no files.
**Writes:** stdout table; `reports/<YYYY-MM-DD>_monitor_load_baseline.md`.
**Called by:** run manually, e.g. before/after a suspected overload, to compare against a prior
dated report in `reports/`.
**Calls out:** none (stdlib `subprocess`/`re`/`pathlib` only).

---

### tests/test_monitor_sweep.py (102 LOC)

**Purpose:** Regression test for `src/monitor_janitor.py`. Creates three real throwaway tmux
sessions (`monitor_cc_testold`, `monitor_cc_testnew`, `worker-testkeep`), ages `testold` by a few
seconds, then sweeps ONLY the fixture pair through `sweep_sessions()` directly (never the real
`monitor_cc_*` sessions on the machine — the live monitors must never see a test threshold).
Asserts: `list_monitor_sessions()` finds both fixtures and excludes the `worker-*` one; after the
sweep `testold` is killed (session gone, its pane's real PID reaped — no orphan) while `testnew`
and `worker-testkeep` are untouched; the sweep log recorded both decisions. Cleans up all three
sessions in a `finally`.
**Reads:** Live tmux state.
**Writes:** Three throwaway tmux sessions (removed at the end); appends to this checkout's real
sweep log via `monitor_janitor._log_path()` (`$MONITOR_CC_ROOT`-or-else-`__file__`-derived — see
`src/DOCS.md`'s `monitor_janitor.py` entry — so running this test from a worktree writes into
that worktree's `src/logs/monitor_sweep.log`, not the main checkout's, unless `MONITOR_CC_ROOT`
is set in the environment).
**Called by:** run manually — regression guard for `monitor_janitor.py`.
**Calls out:** `src.monitor_janitor` (`/tests/` + `test_*.py` naming exempts this file from the
`block_dev_imports_src` hook).

---

### tests/test_monitor_sweep_scheduler.py (177 LOC) — new 2026-09

**Purpose:** Gate-only regression test for `src/menubar/monitor_sweep_scheduler.py`'s
at-most-once-per-24h check (the daily sweep's dedicated LaunchAgent was removed the same
milestone — see `process-docs/monitor_lifecycle/`). Covers the pure `_is_sweep_due(last_ts, now)`
boundary cases (fresh state, 1h ago, 25h ago, exactly-24h) AND the full
`maybe_run_sweep_workflow(now)` integration against an isolated temp state file — never the real
`MONITOR_SWEEP_STATE_FILE` under `APP_SUPPORT`. `_run_sweep` (the real tmux/subprocess work,
already covered by `test_monitor_sweep.py`) is stubbed for every case, so this file touches no
real tmux state. Also covers the re-entry guard (a concurrent tick while a sweep is already
in-progress must not double-trigger) and that the attempt timestamp lands on disk BEFORE a slow
sweep finishes (so a hung/crashed sweep can't cause the very next tick to re-fire it) — both via
a blocking stub + `threading.Event` released at teardown.
**Reads:** nothing outside its own isolated temp state files (`tempfile.mkdtemp`).
**Writes:** isolated temp state files (own tempdir per case, never cleaned up explicitly — OS
temp dir, low volume, matches this directory's other throwaway-fixture tests).
**Called by:** run manually — regression guard for `monitor_sweep_scheduler.py`.
**Calls out:** `src.menubar.monitor_sweep_scheduler` (`/tests/` + `test_*.py` naming exempts this
file from the `block_dev_imports_src` hook).

## reports/

Dated `probe_monitor_load.py` output, one file per run (`<YYYY-MM-DD>_monitor_load_baseline.md`).
Kept as a historical trail — a later overload investigation compares its own probe run against
the closest prior dated report here.
