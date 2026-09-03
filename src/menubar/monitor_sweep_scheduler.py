# INFRASTRUCTURE
import json
import os
import threading

# From paths.py: sweep-gate state file (survives a menubar restart) + Monitor_CC checkout root
from .paths import MONITOR_SWEEP_STATE_FILE, MONITOR_CC_ROOT
# From menubar_log.py: unified log sink for all menubar diagnostic categories
from .menubar_log import log_menubar

SWEEP_INTERVAL_SECS = 24 * 3600   # run at most once per day, independent of any tmux/Ghostty window being open

_last_sweep_ts = None       # lazy-loaded from MONITOR_SWEEP_STATE_FILE on first check; None = not yet loaded
_sweep_in_progress = False  # in-process re-entry guard against two ticks racing while a sweep thread is running

# ORCHESTRATOR

# Called every menubar tick (app.py:_tick). The gate is on-disk (MONITOR_SWEEP_STATE_FILE), not
# an in-memory-only timestamp like app.py's own _last_log_cleanup_ts — it MUST survive a menubar
# restart, so a restart never re-runs the sweep early. The attempt timestamp is recorded
# immediately, before the sweep itself runs, so a slow or failing sweep can't cause the very next
# tick to re-fire it. The actual sweep runs on a daemon thread — tmux/subprocess I/O never blocks
# the tick, the same offload shape discovery_worker.py uses for session discovery (a dedicated
# background thread, not inline synchronous work on the main/tick thread).
def maybe_run_sweep_workflow(now: float) -> None:
    global _last_sweep_ts, _sweep_in_progress
    if _sweep_in_progress:
        return
    if _last_sweep_ts is None:
        _last_sweep_ts = _read_last_sweep_ts()
    if not _is_sweep_due(_last_sweep_ts, now):
        return
    _last_sweep_ts = now
    _write_last_sweep_ts(now)
    _sweep_in_progress = True
    threading.Thread(target=_run_sweep, name='monitor-sweep', daemon=True).start()

# FUNCTIONS

# Pure gate decision — split out from maybe_run_sweep_workflow so a test can check it directly
# without touching the state file or spawning a thread.
def _is_sweep_due(last_ts: float, now: float) -> bool:
    return now - last_ts >= SWEEP_INTERVAL_SECS

# Read the last recorded sweep-attempt timestamp; 0.0 (always due) if the file is missing or
# corrupt — a fresh install or the first tick after this feature ships should not wait a full 24h.
def _read_last_sweep_ts() -> float:
    try:
        return float(json.loads(MONITOR_SWEEP_STATE_FILE.read_text(encoding='utf-8'))['last_run_ts'])
    except Exception:
        return 0.0

# Atomic write: tempfile + os.replace, same pattern as app_settings.py's _save_settings. A write
# failure only delays the NEXT gate decision (the in-memory _last_sweep_ts is already updated by
# the caller) — logged rather than silently swallowed, never re-raised (the tick must not crash
# over a non-critical state-file write).
def _write_last_sweep_ts(ts: float) -> None:
    try:
        tmp = MONITOR_SWEEP_STATE_FILE.with_name(MONITOR_SWEEP_STATE_FILE.name + '.tmp')
        tmp.write_text(json.dumps({'last_run_ts': ts}), encoding='utf-8')
        os.replace(tmp, MONITOR_SWEEP_STATE_FILE)
    except Exception as e:
        log_menubar('monitor_sweep', f'state-write FAILED {e}')

# Runs on a daemon thread, off the tick. Sets MONITOR_CC_ROOT (monitor_janitor.py's own
# resolution env var — see its DOCS.md entry) from paths.MONITOR_CC_ROOT if not already present:
# under the frozen py2app bundle, monitor_janitor.py's own __file__-based fallback would resolve
# inside the bundle copy, not the real checkout (the same reason system.py's monitor-launch
# button needed MONITOR_CC_ROOT — see paths.py's docstring there). Never lets an exception
# escape the thread silently — logs it instead.
def _run_sweep() -> None:
    global _sweep_in_progress
    try:
        os.environ.setdefault('MONITOR_CC_ROOT', str(MONITOR_CC_ROOT))
        from ..monitor_janitor import sweep_workflow
        results = sweep_workflow()
        killed = sum(1 for r in results if r['killed'])
        log_menubar('monitor_sweep',
                     f'ran sessions={len(results)} killed={killed} spared={len(results) - killed}')
    except Exception as e:
        log_menubar('monitor_sweep', f'FAILED {e}')
    finally:
        _sweep_in_progress = False
