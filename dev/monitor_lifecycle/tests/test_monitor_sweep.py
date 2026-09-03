# INFRASTRUCTURE
import subprocess
import sys
import time
from pathlib import Path

# add project root to path so src.monitor_janitor is importable as `from src.` (see Import Convention)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
from src.monitor_janitor import list_monitor_sessions, sweep_sessions, _LOG_PATH  # noqa: E402

_OLD_NAME    = "monitor_cc_testold"
_NEW_NAME    = "monitor_cc_testnew"
_WORKER_NAME = "worker-testkeep"
_OLD_AGE_WAIT   = 2.0  # seconds to let testold "age" before the sweep
_TEST_THRESHOLD = 1.0  # sweep threshold used only by this test — production stays 24h, unconditional

# ORCHESTRATOR

# Create fixture sessions, sweep ONLY the fixture pair (never the live monitor_cc_* sessions
# already running on this machine), assert kill/spare/untouched + no orphaned pane process +
# log lines written, then clean up. Exits 1 on any failed check.
def test_monitor_sweep_workflow() -> None:
    failures = []
    old_pid = new_pid = worker_pid = None
    try:
        old_pid = _create_fixture_session(_OLD_NAME)
        time.sleep(_OLD_AGE_WAIT)
        new_pid = _create_fixture_session(_NEW_NAME)
        worker_pid = _create_fixture_session(_WORKER_NAME)

        all_sessions = list_monitor_sessions()
        names = {name for name, _ in all_sessions}
        _check(failures, "enumeration includes testold", _OLD_NAME in names)
        _check(failures, "enumeration includes testnew", _NEW_NAME in names)
        _check(failures, "enumeration excludes worker-* session", _WORKER_NAME not in names)

        # Sweep only the fixture pair — real monitor_cc_* sessions from other projects on this
        # machine must never see the test's 1s threshold (production always uses the 24h default).
        fixture_pair = [(n, c) for n, c in all_sessions if n in (_OLD_NAME, _NEW_NAME)]
        sweep_sessions(fixture_pair, _TEST_THRESHOLD)

        _check(failures, "testold session killed", not _session_exists(_OLD_NAME))
        _check(failures, "testnew session spared", _session_exists(_NEW_NAME))
        _check(failures, "worker-* session untouched", _session_exists(_WORKER_NAME))
        _check(failures, "testold pane process reaped (no orphan)", not _pid_alive(old_pid))
        _check(failures, "testnew pane process still alive", _pid_alive(new_pid))
        _check(failures, "worker-* pane process untouched", _pid_alive(worker_pid))
        _check(failures, "log recorded testold as KILLED", _log_has(_OLD_NAME, "KILLED"))
        _check(failures, "log recorded testnew as SPARED", _log_has(_NEW_NAME, "SPARED"))
    finally:
        _cleanup_fixtures()

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

# Create a throwaway tmux session running a real child process; return its pane pid
def _create_fixture_session(name: str) -> int:
    subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)  # clear stale leftovers
    subprocess.run(["tmux", "new-session", "-d", "-s", name, "sleep 120"], check=True)
    pid_raw = subprocess.run(
        ["tmux", "list-panes", "-t", name, "-F", "#{pane_pid}"],
        capture_output=True, text=True
    ).stdout.strip()
    return int(pid_raw)

# True if the named tmux session still exists
def _session_exists(name: str) -> bool:
    return subprocess.run(["tmux", "has-session", "-t", name], capture_output=True).returncode == 0

# True if a process with this pid is still running
def _pid_alive(pid: int) -> bool:
    return subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode == 0

# True if the sweep log's tail has a line naming this session with this status
def _log_has(name: str, status: str) -> bool:
    if not _LOG_PATH.exists():
        return False
    tail = _LOG_PATH.read_text(encoding='utf-8').splitlines()[-20:]
    return any(f"{name} " in line and status in line for line in tail)

# Kill all three fixture sessions, ignoring any that are already gone
def _cleanup_fixtures() -> None:
    for name in (_OLD_NAME, _NEW_NAME, _WORKER_NAME):
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)


if __name__ == "__main__":
    test_monitor_sweep_workflow()
