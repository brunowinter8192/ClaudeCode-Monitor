# INFRASTRUCTURE
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

# add project root to path so src.menubar is importable as `from src.` (see Import Convention)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from src.menubar import monitor_sweep_scheduler as sched  # noqa: E402

_NOW = 1_000_000_000.0   # fixed epoch reference — arithmetic only, never compared to real wall time

# ORCHESTRATOR

# Gate-only coverage for monitor_sweep_scheduler.py's at-most-once-per-24h check. _run_sweep
# (the real tmux/subprocess work — already covered by test_monitor_sweep.py) is stubbed out for
# every case here, so this file never touches real tmux state. Each case gets its own isolated
# temp state file (never the real MONITOR_SWEEP_STATE_FILE under APP_SUPPORT) and a fresh module
# state reset. Exits 1 on any failed check.
def test_monitor_sweep_scheduler_workflow() -> None:
    failures = []
    _test_pure_gate_boundaries(failures)
    _test_fresh_state_runs(failures)
    _test_run_1h_ago_does_not_run(failures)
    _test_run_25h_ago_runs(failures)
    _test_reentry_guard_blocks_concurrent_trigger(failures)
    _test_attempt_timestamp_persisted_before_sweep_completes(failures)

    print()
    if failures:
        print(f"FAILED: {len(failures)} case(s):")
        for desc in failures:
            print(f"  - {desc}")
        sys.exit(1)
    print("All checks passed.")

# FUNCTIONS

# Print one check result; append to failures on FAIL
def _check(failures: list, desc: str, ok: bool) -> None:
    print(f"  [{'OK  ' if ok else 'FAIL'}] {desc}")
    if not ok:
        failures.append(desc)

# Pure _is_sweep_due(last_ts, now) — no file, no thread, no module state involved
def _test_pure_gate_boundaries(failures: list) -> None:
    _check(failures, "fresh state (last_ts=0.0) is due",
          sched._is_sweep_due(0.0, _NOW))
    _check(failures, "a run 1h ago is NOT due",
          not sched._is_sweep_due(_NOW - 3600, _NOW))
    _check(failures, "a run 25h ago IS due",
          sched._is_sweep_due(_NOW - 25 * 3600, _NOW))
    _check(failures, "exactly 24h ago IS due (>= boundary, not >)",
          sched._is_sweep_due(_NOW - sched.SWEEP_INTERVAL_SECS, _NOW))

# No state file at all (equivalent to a fresh install / first tick after this feature ships)
def _test_fresh_state_runs(failures: list) -> None:
    fired = _invoke_with_isolated_state(seed_last_run_ts=None, now=_NOW)
    _check(failures, "fresh state (no state file) triggers a sweep attempt", fired)

# A state file recording a run 1h ago — well inside the 24h window
def _test_run_1h_ago_does_not_run(failures: list) -> None:
    fired = _invoke_with_isolated_state(seed_last_run_ts=_NOW - 3600, now=_NOW)
    _check(failures, "a run 1h ago does NOT trigger a sweep attempt", not fired)

# A state file recording a run 25h ago — past the 24h window
def _test_run_25h_ago_runs(failures: list) -> None:
    fired = _invoke_with_isolated_state(seed_last_run_ts=_NOW - 25 * 3600, now=_NOW)
    _check(failures, "a run 25h ago DOES trigger a sweep attempt", fired)

# Two calls in the same due window: the second must not double-trigger while the first's
# (stubbed) sweep thread is still marked in-progress
def _test_reentry_guard_blocks_concurrent_trigger(failures: list) -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="monitor_sweep_gate_"))
    state_file = tmp_dir / "monitor_sweep_state.json"
    orig_state_file, orig_last_ts, orig_in_progress = (
        sched.MONITOR_SWEEP_STATE_FILE, sched._last_sweep_ts, sched._sweep_in_progress)
    sched.MONITOR_SWEEP_STATE_FILE = state_file
    sched._last_sweep_ts = None
    release = threading.Event()
    calls = []
    sched._sweep_in_progress = False

    def _blocking_stub():
        calls.append(1)
        release.wait(timeout=3)
        sched._sweep_in_progress = False

    orig_run_sweep = sched._run_sweep
    sched._run_sweep = _blocking_stub
    try:
        sched.maybe_run_sweep_workflow(_NOW)          # due → spawns the blocking stub
        time.sleep(0.1)                                # let the thread actually start and set the flag
        sched.maybe_run_sweep_workflow(_NOW + 1)       # still "due" by time, but a sweep is already running
        _check(failures, "a concurrent tick while a sweep is in-progress does not re-trigger",
              len(calls) == 1)
    finally:
        release.set()
        _wait_until(lambda: not sched._sweep_in_progress, timeout=3)
        sched._run_sweep = orig_run_sweep
        sched.MONITOR_SWEEP_STATE_FILE, sched._last_sweep_ts, sched._sweep_in_progress = (
            orig_state_file, orig_last_ts, orig_in_progress)

# The on-disk attempt timestamp must be written BEFORE the (stubbed, slow) sweep finishes — a
# crashed/hung sweep must not cause the very next tick to re-fire it
def _test_attempt_timestamp_persisted_before_sweep_completes(failures: list) -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="monitor_sweep_gate_"))
    state_file = tmp_dir / "monitor_sweep_state.json"
    orig_state_file, orig_last_ts, orig_in_progress = (
        sched.MONITOR_SWEEP_STATE_FILE, sched._last_sweep_ts, sched._sweep_in_progress)
    sched.MONITOR_SWEEP_STATE_FILE = state_file
    sched._last_sweep_ts = None
    sched._sweep_in_progress = False
    release = threading.Event()

    def _slow_stub():
        release.wait(timeout=3)
        sched._sweep_in_progress = False

    orig_run_sweep = sched._run_sweep
    sched._run_sweep = _slow_stub
    try:
        sched.maybe_run_sweep_workflow(_NOW)
        time.sleep(0.1)   # the stub is still blocked on release — sweep has NOT "completed"
        recorded = json.loads(state_file.read_text(encoding='utf-8'))['last_run_ts']
        _check(failures, "attempt timestamp is on disk before the sweep itself finishes",
              recorded == _NOW)
    finally:
        release.set()
        _wait_until(lambda: not sched._sweep_in_progress, timeout=3)
        sched._run_sweep = orig_run_sweep
        sched.MONITOR_SWEEP_STATE_FILE, sched._last_sweep_ts, sched._sweep_in_progress = (
            orig_state_file, orig_last_ts, orig_in_progress)

# Point the module at an isolated temp state file (optionally pre-seeded), stub out _run_sweep
# (never touch real tmux), call maybe_run_sweep_workflow(now) once, wait for the (fast, no-op)
# stub to run if it was going to, then restore everything. Returns whether the stub fired.
def _invoke_with_isolated_state(seed_last_run_ts, now: float) -> bool:
    tmp_dir = Path(tempfile.mkdtemp(prefix="monitor_sweep_gate_"))
    state_file = tmp_dir / "monitor_sweep_state.json"
    if seed_last_run_ts is not None:
        state_file.write_text(json.dumps({"last_run_ts": seed_last_run_ts}), encoding="utf-8")

    orig_state_file, orig_last_ts, orig_in_progress, orig_run_sweep = (
        sched.MONITOR_SWEEP_STATE_FILE, sched._last_sweep_ts, sched._sweep_in_progress,
        sched._run_sweep)
    sched.MONITOR_SWEEP_STATE_FILE = state_file
    sched._last_sweep_ts = None
    sched._sweep_in_progress = False
    fired = threading.Event()

    def _fast_stub():
        fired.set()
        sched._sweep_in_progress = False

    sched._run_sweep = _fast_stub
    try:
        sched.maybe_run_sweep_workflow(now)
        return fired.wait(timeout=2)
    finally:
        sched._run_sweep = orig_run_sweep
        sched.MONITOR_SWEEP_STATE_FILE, sched._last_sweep_ts, sched._sweep_in_progress = (
            orig_state_file, orig_last_ts, orig_in_progress)

# Poll predicate() until True or timeout — used to wait for a background thread's cleanup
def _wait_until(predicate, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)


if __name__ == "__main__":
    test_monitor_sweep_scheduler_workflow()
