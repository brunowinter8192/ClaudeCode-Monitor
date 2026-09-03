# INFRASTRUCTURE
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

# From tmux_launcher.py: kill a tmux session by name
from .tmux_launcher import kill_session

_SESSION_PREFIX  = "monitor_cc_"
_MAX_AGE_SECONDS = 24 * 3600

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

# The checkout this process's logs belong to: $MONITOR_CC_ROOT if set, else derived from
# wherever monitor_janitor.py itself is physically executing from (a worktree, if run from one)
# — no main-checkout fallback like dual_log_cli's, since this path is a WRITE target that must
# follow whichever checkout's code produced the entry, not a read source to prefer aggregating
# in one place. Two callers, two ways this resolves correctly: `claude_proxy_start.sh`'s bash
# trigger `cd`'s into $MONITOR_CC_ROOT before invoking `-m`, so __file__ already matches by
# construction (no env var needed there). The menubar's daily tick-triggered sweep (2026-09,
# `src/menubar/monitor_sweep_scheduler.py` — replaced this module's own LaunchAgent, blocked by
# a TCC Full Disk Access wall under launchd, see `process-docs/monitor_lifecycle/`) sets
# $MONITOR_CC_ROOT explicitly before calling `sweep_workflow()`, since a frozen py2app bundle's
# own __file__ resolves inside the bundle copy, not the real checkout.
def _resolve_monitor_cc_root() -> Path:
    env_root = os.environ.get("MONITOR_CC_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parent.parent

# Sweep log path under the resolved checkout's src/logs/ — resolved fresh on every call so a
# test can point MONITOR_CC_ROOT elsewhere without reimporting this module
def _log_path() -> Path:
    return _resolve_monitor_cc_root() / "src" / "logs" / "monitor_sweep.log"

# Append one line to the sweep log: UTC timestamp, session name, age in hours, KILLED/SPARED
def log_sweep_line(name: str, age_seconds: float, killed: bool) -> None:
    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    status = "KILLED" if killed else "SPARED"
    with log_path.open('a', encoding='utf-8') as f:
        f.write(f"{ts} {name} age={age_seconds / 3600:.1f}h {status}\n")

if __name__ == "__main__":
    sweep_workflow()
