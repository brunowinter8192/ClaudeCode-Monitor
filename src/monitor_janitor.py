# INFRASTRUCTURE
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

# From tmux_launcher.py: kill a tmux session by name
from .tmux_launcher import kill_session

_SESSION_PREFIX  = "monitor_cc_"
_MAX_AGE_SECONDS = 24 * 3600
_LOG_PATH        = Path(__file__).resolve().parent / "logs" / "monitor_sweep.log"

# ORCHESTRATOR

# Kill every monitor_cc_* tmux session older than max_age_seconds; log one line per session.
# Production callers never pass max_age_seconds — the 24h threshold is unconditional.
def sweep_workflow(max_age_seconds: int = _MAX_AGE_SECONDS) -> list:
    sessions = list_monitor_sessions()
    results = sweep_sessions(sessions, max_age_seconds)
    return results

# FUNCTIONS

# List (session_name, session_created_epoch) for every tmux session named monitor_cc_*.
# Registry-free: reads tmux directly, same lesson as the worker-cli janitor (a registry can
# lose a live session; tmux itself cannot).
def list_monitor_sessions() -> list:
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}|#{session_created}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    sessions = []
    for line in result.stdout.strip().split('\n'):
        if '|' not in line:
            continue
        name, created = line.split('|', 1)
        name, created = name.strip(), created.strip()
        if name.startswith(_SESSION_PREFIX) and created.isdigit():
            sessions.append((name, int(created)))
    return sessions

# Evaluate + act on every session; return one result dict per session
def sweep_sessions(sessions: list, max_age_seconds: int) -> list:
    now = time.time()
    return [sweep_one_session(name, created, now, max_age_seconds) for name, created in sessions]

# Kill the session if its age exceeds max_age_seconds, log the decision, return the outcome.
# tmux kill-session tears down every pane in the session (verified in dev/monitor_lifecycle),
# so no separate per-pane process cleanup is needed here.
def sweep_one_session(name: str, created: int, now: float, max_age_seconds: int) -> dict:
    age_seconds = now - created
    killed = age_seconds >= max_age_seconds
    if killed:
        kill_session(name)
    log_sweep_line(name, age_seconds, killed)
    return {"name": name, "age_seconds": age_seconds, "killed": killed}

# Append one line to the sweep log: UTC timestamp, session name, age in hours, KILLED/SPARED
def log_sweep_line(name: str, age_seconds: float, killed: bool) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    status = "KILLED" if killed else "SPARED"
    with _LOG_PATH.open('a', encoding='utf-8') as f:
        f.write(f"{ts} {name} age={age_seconds / 3600:.1f}h {status}\n")

if __name__ == "__main__":
    sweep_workflow()
