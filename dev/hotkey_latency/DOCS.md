# dev/hotkey_latency/

## Purpose

Measurement tooling for the menubar hotkey-lag investigation (Cmd+K/L/1..9 intermittent slow
response). Verifies the Carbon `GetEventTime` technique and parses the `[latency]` instrumentation
`src/menubar/app.py`, `hotkey_controller.py`, `discover.py`, `system.py`, `discovery_worker.py`
write to `menubar.log` into a distribution report. `analyze_latency.py` is measurement-only
(reads the log, never touches `src/`); the M3 milestone's `src/` fix itself (discovery moved off
the main thread + ghostty TTL re-arm) lives in `src/menubar/`, not here.

Background: `process-docs/hotkey_latency/`.

## Scripts

### probe_get_event_time.py (131 LOC)

Standalone Carbon `GetEventTime`/`GetCurrentEventTime` symbol-and-technique probe. Does not
import `src/` (dev-import-from-src is blocked repo-wide — see `src/hooks/block_dev_imports_src.py`);
duplicates the minimal Carbon ctypes boilerplate instead of importing `hotkey_controller.py`.

**Check 1** (non-interactive): resolves both symbols, asserts `GetCurrentEventTime()` returns a
plausible, monotonically-increasing double (seconds since boot).
**Check 2** (interactive): registers throwaway global hotkey Cmd+Shift+9 (`EventHotKeyID.id=999`,
collision-free with production IDs 1/2..10/20/21/30) and prints `queue_delay_ms` on each press.

**Usage:**
```bash
./venv/bin/python3 dev/hotkey_latency/probe_get_event_time.py
```
Press Cmd+Shift+9 anywhere (global hotkey, no focus required) to see a live delta. Ctrl+C to exit.
No status-bar icon (LSUIElement, no menu). Check 2 requires an interactive GUI session — cannot
be triggered headlessly; Check 1 runs standalone.

### analyze_latency.py (168 LOC)

Parses `menubar.log`'s `[latency]` lines (default path: `menubar.menubar_log.MENUBAR_LOG`,
override via `argv[1]`) into four buckets — main-thread tick phase breakdowns, background
discovery-worker cycle breakdowns (`bg_refresh`, 2026-08 M3), hotkey queue-delays, focus
lookup/osascript splits — and writes a distribution report (mean/median/p90/p95/max per phase,
slowest N entries with full breakdown, per-hotkey percentiles) to `md/latency_report_<UTC-ts>.md`.
`tick` and `bg_refresh` lines share one grammar (`<label> total=Nms phase=Nms ...`), parsed by a
single `_TICK_LIKE_RE` and rendered via one shared `_tick_like_section()` for both. Imports real
menubar code via the `sys.path.insert(0, WORKTREE_ROOT / 'src')` + `from menubar....` pattern (see
`dev/proxy_instrumentation/p1_measure_full_replacement_blast_radius.py` for the established
precedent) — NOT `from src.menubar...` (blocked by the same hook).

**Usage:**
```bash
./venv/bin/python3 dev/hotkey_latency/analyze_latency.py [path/to/menubar.log]
```
