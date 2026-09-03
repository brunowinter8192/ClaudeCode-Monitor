# dev/monitor_lifecycle/

## Role

Load visibility and regression coverage for the monitor's tmux-session lifecycle: each project's
`monitor_cc_<hash>` session runs nine panes indefinitely until something kills it (see
`src/monitor_janitor.py`). This directory holds the load probe used to establish a CPU/age
baseline before the next overload, and the regression test for the sweep that ends stale
sessions.

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

### tests/test_monitor_sweep.py (101 LOC)

**Purpose:** Regression test for `src/monitor_janitor.py`. Creates three real throwaway tmux
sessions (`monitor_cc_testold`, `monitor_cc_testnew`, `worker-testkeep`), ages `testold` by a few
seconds, then sweeps ONLY the fixture pair through `sweep_sessions()` directly (never the real
`monitor_cc_*` sessions on the machine — the live monitors must never see a test threshold).
Asserts: `list_monitor_sessions()` finds both fixtures and excludes the `worker-*` one; after the
sweep `testold` is killed (session gone, its pane's real PID reaped — no orphan) while `testnew`
and `worker-testkeep` are untouched; the sweep log recorded both decisions. Cleans up all three
sessions in a `finally`.
**Reads:** Live tmux state.
**Writes:** Three throwaway tmux sessions (removed at the end); appends to `src/logs/monitor_sweep.log`
(the real sweep log — same file production uses).
**Called by:** run manually — regression guard for `monitor_janitor.py`.
**Calls out:** `src.monitor_janitor` (`/tests/` + `test_*.py` naming exempts this file from the
`block_dev_imports_src` hook).

## reports/

Dated `probe_monitor_load.py` output, one file per run (`<YYYY-MM-DD>_monitor_load_baseline.md`).
Kept as a historical trail — a later overload investigation compares its own probe run against
the closest prior dated report here.
