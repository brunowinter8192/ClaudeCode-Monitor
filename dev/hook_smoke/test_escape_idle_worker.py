# INFRASTRUCTURE
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# add src/ to path so menubar.focus_controller is importable without 'from src.' prefix
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
from menubar import focus_controller  # noqa: E402


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


# ORCHESTRATOR

# Run all cases and print results; exit 1 if any fail
def test_escape_idle_worker_workflow() -> None:
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

# Edge-trigger: has_bg sequence False,True,True,False,True on ONE worker must fire exactly
# twice (the two False->True rising edges), never on the two held-True/held-False ticks.
def _case_edge_trigger_sequence() -> tuple:
    calls = []
    real_send = focus_controller._send_escape_key
    focus_controller._send_escape_key = lambda name: (calls.append(name) or True)
    try:
        fc = focus_controller.FocusController(_FakeApp())
        sequence = [False, True, True, False, True]
        for has_bg in sequence:
            s = _FakeSession(name='w1', is_worker=True, tmux_session_name='worker-demo-w1', has_bg=has_bg)
            fc.tick([s], {}, 0.0)
        ok = calls == ['worker-demo-w1', 'worker-demo-w1']
        return ok, f'want 2 calls (rising edges), got {len(calls)}: {calls}'
    finally:
        focus_controller._send_escape_key = real_send


# Same as above but the worker never drops back to has_bg=False before rising twice —
# a THIRD tick with the same True state must NOT re-fire (protects against the Escape-into-
# quit-menu failure mode of a per-tick send).
def _case_no_refire_while_held_true() -> tuple:
    calls = []
    real_send = focus_controller._send_escape_key
    focus_controller._send_escape_key = lambda name: (calls.append(name) or True)
    try:
        fc = focus_controller.FocusController(_FakeApp())
        for _ in range(5):
            s = _FakeSession(name='w1', is_worker=True, tmux_session_name='worker-demo-w1', has_bg=True)
            fc.tick([s], {}, 0.0)
        ok = calls == ['worker-demo-w1']
        return ok, f'want exactly 1 call across 5 held-True ticks, got {len(calls)}: {calls}'
    finally:
        focus_controller._send_escape_key = real_send


# Main sessions (is_worker=False) must never be targeted, even with has_bg=True.
def _case_main_never_targeted() -> tuple:
    calls = []
    real_send = focus_controller._send_escape_key
    focus_controller._send_escape_key = lambda name: (calls.append(name) or True)
    try:
        fc = focus_controller.FocusController(_FakeApp())
        s = _FakeSession(name='main-proj', is_worker=False, tmux_session_name='', has_bg=True)
        fc.tick([s], {}, 0.0)
        ok = calls == []
        return ok, f'want 0 calls for a main session, got {len(calls)}: {calls}'
    finally:
        focus_controller._send_escape_key = real_send


# Worker with no resolvable tmux_session_name (cwd-unavailable fallback in discover.py) must
# also never be targeted — there is nowhere to send the key.
def _case_worker_without_tmux_name_skipped() -> tuple:
    calls = []
    real_send = focus_controller._send_escape_key
    focus_controller._send_escape_key = lambda name: (calls.append(name) or True)
    try:
        fc = focus_controller.FocusController(_FakeApp())
        s = _FakeSession(name='w2', is_worker=True, tmux_session_name='', has_bg=True)
        fc.tick([s], {}, 0.0)
        ok = calls == []
        return ok, f'want 0 calls for empty tmux_session_name, got {len(calls)}: {calls}'
    finally:
        focus_controller._send_escape_key = real_send


# Fail-safe: real _send_escape_key (no monkeypatch) against a tmux session name that does not
# exist must return False and must not raise into tick().
def _case_dead_session_fails_safe() -> tuple:
    fc = focus_controller.FocusController(_FakeApp())
    dead_name = 'monitor-cc-escape-probe-does-not-exist-zzz'
    s = _FakeSession(name='w3', is_worker=True, tmux_session_name=dead_name, has_bg=True)
    try:
        fc.tick([s], {}, 0.0)
        got = focus_controller._send_escape_key(dead_name)
        return got is False, f'want False for a dead tmux session, got {got}'
    except Exception as e:
        return False, f'tick() raised: {e!r}'


# tmux binary missing entirely (FileNotFoundError from subprocess.run) must also fail safe.
def _case_missing_tmux_binary_fails_safe() -> tuple:
    real_run = subprocess.run

    def _raising_run(*a, **kw):
        raise FileNotFoundError('tmux: command not found (synthetic)')

    focus_controller.subprocess.run = _raising_run
    try:
        got = focus_controller._send_escape_key('any-session')
        return got is False, f'want False when tmux binary is missing, got {got}'
    finally:
        focus_controller.subprocess.run = real_run


CASES = [
    ('False->True->True->False->True fires exactly on the 2 rising edges', _case_edge_trigger_sequence),
    ('has_bg held True across ticks does not re-fire',                    _case_no_refire_while_held_true),
    ('main session with has_bg=True is never targeted',                   _case_main_never_targeted),
    ('worker with empty tmux_session_name is never targeted',             _case_worker_without_tmux_name_skipped),
    ('dead tmux session name fails safe (no raise)',                      _case_dead_session_fails_safe),
    ('missing tmux binary fails safe (no raise)',                         _case_missing_tmux_binary_fails_safe),
]


if __name__ == "__main__":
    test_escape_idle_worker_workflow()
