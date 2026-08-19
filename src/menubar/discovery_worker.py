# INFRASTRUCTURE
import sys
import threading
import time
from typing import Dict, List, NamedTuple

# From discover.py: Live session discovery + per-cycle sub-phase timings
from .discover import list_alive_sessions, get_last_session_timings, SessionInfo
# From bg_timer.py: orchestrator wake-up process scanning
from .bg_timer import _scan_bg_sleep_timers, BgSleepInfo
# From menubar_log.py: unified log sink for all menubar diagnostic categories
from .menubar_log import log_menubar

REFRESH_INTERVAL = 1.5   # seconds — mirrors app.py POLL_INTERVAL by design; kept as an
                          # independent constant (not imported) to avoid an app<->discovery_worker
                          # circular import (app.py imports start_discovery_worker from here).
BG_REFRESH_LATENCY_THRESHOLD_MS = 200   # mirrors app.py TICK_LATENCY_THRESHOLD_MS by value

# Combined discovery snapshot: sessions + per-project background-sleep-timer info, produced
# together each cycle (bg_by_project depends on cwd_to_project derived from sessions).
class DiscoverySnapshot(NamedTuple):
    sessions:      List[SessionInfo]
    bg_by_project: Dict[str, BgSleepInfo]
    ts:            float   # time.time() when this snapshot was published

_lock = threading.Lock()
_snapshot = DiscoverySnapshot(sessions=[], bg_by_project={}, ts=0.0)
_started = False

# ORCHESTRATOR

# Start the daemon background-discovery thread exactly once; subsequent calls are no-ops.
# The thread is the SOLE caller of list_alive_sessions()/_scan_bg_sleep_timers() from this
# point on — module-level caches in proc_cache.py/ghostty.py/desktop_detection.py are written
# only from this thread (see proc_cache.py:cc_proc_cache_snapshot() for the one cross-thread
# read exception). All AppKit/rumps calls stay on the main thread — this module makes none.
def start_discovery_worker() -> None:
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_worker_loop, name='discovery-worker', daemon=True)
    t.start()

# Thread-safe read of the latest published snapshot; safe to call from the main thread at any
# time, including before the first cycle completes (returns the empty initial snapshot).
def get_latest_snapshot() -> DiscoverySnapshot:
    with _lock:
        return _snapshot

# FUNCTIONS

# Continuous discovery loop: list_alive_sessions() + _scan_bg_sleep_timers() every
# ~REFRESH_INTERVAL seconds (self-paced — subtracts cycle duration so it doesn't drift).
# Exception-safe: a per-cycle failure is logged and the loop continues: never dies.
def _worker_loop() -> None:
    global _snapshot
    while True:
        cycle_t0 = time.monotonic()
        try:
            sessions = list_alive_sessions()
            cwd_to_project = {s.cwd: s.project_name for s in sessions if not s.is_worker and s.cwd}
            bg_by_project = _scan_bg_sleep_timers(cwd_to_project)
            with _lock:
                _snapshot = DiscoverySnapshot(sessions=sessions, bg_by_project=bg_by_project,
                                               ts=time.time())
            _log_if_slow(cycle_t0)
        except Exception as e:
            print(f'[menubar] discovery-worker cycle error: {e}', file=sys.stderr)
        elapsed = time.monotonic() - cycle_t0
        time.sleep(max(0.0, REFRESH_INTERVAL - elapsed))

# Log one [latency] bg_refresh line (same phase-breakdown shape as app.py's tick line) when a
# discovery cycle exceeds BG_REFRESH_LATENCY_THRESHOLD_MS; silent below threshold.
def _log_if_slow(cycle_t0: float) -> None:
    total_ms = (time.monotonic() - cycle_t0) * 1000
    if total_ms > BG_REFRESH_LATENCY_THRESHOLD_MS:
        phases = get_last_session_timings()
        breakdown = ' '.join(f'{k}={v * 1000:.0f}ms' for k, v in phases.items())
        log_menubar('latency', f'bg_refresh total={total_ms:.0f}ms {breakdown}')
