# INFRASTRUCTURE
import sys
from pathlib import Path
from typing import NamedTuple

# add src/ to path so menubar.focus_controller is importable without 'from src.' prefix
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
from menubar import focus_controller  # noqa: E402
from menubar.bg_timer import BgSleepInfo  # noqa: E402


class _FakeSession(NamedTuple):
    name: str
    is_worker: bool
    tmux_session_name: str
    has_bg: bool
    project_name: str = 'demo-project'
    status: str = 'idle'
    cwd: str = ''


class _FakeApp:
    _auto_focus = False


_BG = {'demo-project': BgSleepInfo(min_remaining=3300, sleep_pids=[99999])}


# ORCHESTRATOR

# Run all cases and print results; exit 1 if any fail
def test_focus_controller_bg_gate_workflow() -> None:
    failures = []
    for desc, fn in CASES:
        ok, detail = fn()
        status = "OK  " if ok else "FAIL"
        print(f"  [{status}] {desc}")
        if not ok:
            print(f"           {detail}")
            failures.append(desc)
    print()
    if failures:
        print(f"FAILED: {len(failures)} case(s):")
        for desc in failures:
            print(f"  - {desc}")
        sys.exit(1)
    print(f"All {len(CASES)} tests passed.")


# FUNCTIONS

# Drive tick() for N seconds of simulated time with a fixed session list; return whether
# _abort_bg_sleep_timers fired at any point.
def _run_ticks(sessions_fn, seconds: float, step: float = 1.0) -> bool:
    aborted = []
    real_abort = focus_controller._abort_bg_sleep_timers
    focus_controller._abort_bg_sleep_timers = lambda pids: aborted.append(pids)
    try:
        fc = focus_controller.FocusController(_FakeApp())
        t = 0.0
        while t <= seconds:
            fc.tick(sessions_fn(t), _BG, t)
            t += step
        return len(aborted) > 0
    finally:
        focus_controller._abort_bg_sleep_timers = real_abort


# One worker idle with has_bg=True held >5s must NOT abort — the worker has a live bg task
# the orchestrator can't see once the timer is killed.
def _case_idle_with_bg_holds() -> tuple:
    sessions = lambda t: [_FakeSession(name='w1', is_worker=True, tmux_session_name='w1',
                                        has_bg=True, status='idle')]
    fired = _run_ticks(sessions, seconds=7.0)
    return not fired, f'want NO abort (has_bg=True), got fired={fired}'


# One worker idle with has_bg=False held >5s must abort — unchanged baseline behavior.
def _case_idle_without_bg_aborts() -> tuple:
    sessions = lambda t: [_FakeSession(name='w1', is_worker=True, tmux_session_name='w1',
                                        has_bg=False, status='idle')]
    fired = _run_ticks(sessions, seconds=7.0)
    return fired, f'want abort (has_bg=False, idle>5s), got fired={fired}'


# Two workers both idle, one with has_bg=True: the project must not abort even though the
# other worker has no background task.
def _case_two_workers_one_with_bg_holds() -> tuple:
    sessions = lambda t: [
        _FakeSession(name='w1', is_worker=True, tmux_session_name='w1', has_bg=False, status='idle'),
        _FakeSession(name='w2', is_worker=True, tmux_session_name='w2', has_bg=True, status='idle'),
    ]
    fired = _run_ticks(sessions, seconds=7.0)
    return not fired, f'want NO abort (w2 has_bg=True), got fired={fired}'


# Worker has_bg=True for the first 3s, then flips False; abort must fire only after the flip,
# once 5s of (idle AND has_bg=False) have elapsed — not counting the time held with has_bg=True.
def _case_bg_flip_then_idle_aborts_after_flip() -> tuple:
    def sessions(t):
        has_bg = t < 3.0
        return [_FakeSession(name='w1', is_worker=True, tmux_session_name='w1',
                              has_bg=has_bg, status='idle')]
    aborted = []
    real_abort = focus_controller._abort_bg_sleep_timers
    focus_controller._abort_bg_sleep_timers = lambda pids: aborted.append(pids)
    try:
        fc = focus_controller.FocusController(_FakeApp())
        fired_before_flip_clears = False
        for t in [0.0, 1.0, 2.0, 3.0, 4.0]:
            fc.tick(sessions(t), _BG, t)
            if aborted:
                fired_before_flip_clears = True
        ok_no_early_fire = not fired_before_flip_clears
        for t in [5.0, 6.0, 7.0, 8.0, 9.0]:
            fc.tick(sessions(t), _BG, t)
        ok_fires_after_grace = len(aborted) > 0
        return (ok_no_early_fire and ok_fires_after_grace,
                f'no-early-fire={ok_no_early_fire} fires-after-grace={ok_fires_after_grace} aborted={aborted}')
    finally:
        focus_controller._abort_bg_sleep_timers = real_abort


# Project with zero worker sessions at all is vacuously all-idle — must still abort (unchanged).
def _case_no_workers_vacuous_abort() -> tuple:
    sessions = lambda t: []
    fired = _run_ticks(sessions, seconds=7.0)
    return fired, f'want abort (vacuous all-idle, no workers), got fired={fired}'


# Worker idle but within the recent-send grace window must NOT abort (unchanged).
def _case_recent_send_grace_holds() -> tuple:
    real_signals = focus_controller._read_orchestrator_signals
    focus_controller._read_orchestrator_signals = lambda now: {'w1': now}
    try:
        sessions = lambda t: [_FakeSession(name='w1', is_worker=True, tmux_session_name='w1',
                                            has_bg=False, status='idle')]
        fired = _run_ticks(sessions, seconds=7.0)
        return not fired, f'want NO abort (recent send signal), got fired={fired}'
    finally:
        focus_controller._read_orchestrator_signals = real_signals


CASES = [
    ('idle worker with has_bg=True holds the abort (>5s)',                    _case_idle_with_bg_holds),
    ('idle worker with has_bg=False still aborts promptly (>5s)',             _case_idle_without_bg_aborts),
    ('two workers, one has_bg=True: NO abort',                                _case_two_workers_one_with_bg_holds),
    ('has_bg=True then False: abort only after flip, not before',             _case_bg_flip_then_idle_aborts_after_flip),
    ('project with zero worker sessions: vacuous all-idle still aborts',      _case_no_workers_vacuous_abort),
    ('idle worker within recent-send grace window: NO abort (unchanged)',     _case_recent_send_grace_holds),
]


if __name__ == "__main__":
    test_focus_controller_bg_gate_workflow()
