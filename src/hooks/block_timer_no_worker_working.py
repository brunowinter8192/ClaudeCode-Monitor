# INFRASTRUCTURE
import glob
import json
import os
import re
import shutil
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fire_log import log_fire

# Matches any sleep-only background command: bare "sleep N" or "sleep N && echo <anything>".
# Mirrors _SLEEP_ONLY_BG in rewrite_background_sleep.py / _CANONICAL in block_unauthorized_background.py
# so this hook is order-independent relative to those two.
_SLEEP_ONLY_BG = re.compile(r'^\s*sleep\s+\d+(?:\.\d+)?\s*(?:&&\s*echo\b[^;&|\n]*)?\s*$')

_WORKTREE_FRAGMENT = '.claude/worktrees/'

_BLOCK_MESSAGE = (
    "Go idle immediately. No worker of this project is working — this timer may not be armed.\n"
)

# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if the call is the canonical sleep-timer
# and no worker of the current project is working. Skipped entirely from inside a worktree
# (this hook is orchestrator-only).
def block_timer_no_worker_working_workflow() -> None:
    try:
        if _WORKTREE_FRAGMENT in os.getcwd():
            sys.exit(0)
        command, run_in_background, session_id = _parse_input()
        if command is None:
            sys.exit(0)
        if decide(command, run_in_background, os.getcwd(), _live_worker_statuses):
            print(_BLOCK_MESSAGE, file=sys.stderr, end="")
            log_fire("block_timer_no_worker_working", "block", "Bash", command,
                     reason=_BLOCK_MESSAGE, session_id=session_id)
            sys.exit(2)
    except Exception:
        sys.exit(0)
    sys.exit(0)

# FUNCTIONS

# Pure decision: gate on run_in_background + sleep-only regex, then check the project's worker
# set via status_fn (injectable — real entrypoint wires _live_worker_statuses, smoke tests inject
# a stub). Blocks iff the worker set is empty OR every worker's first status token == 'idle'.
# status_fn exceptions (unresolved binary, subprocess error, timeout, non-zero exit) → allow.
def decide(command: str, run_in_background: bool, project_path: str, status_fn) -> bool:
    if not run_in_background:
        return False
    if command is None or not _SLEEP_ONLY_BG.match(command):
        return False
    try:
        raw = status_fn(project_path)
    except Exception:
        return False
    statuses = _parse_worker_statuses(raw)
    if not statuses:
        return True
    return all(_first_token(status) == 'idle' for status in statuses)

# First whitespace token of a status string, '' when blank (e.g. 'idle 59%' → 'idle')
def _first_token(status: str) -> str:
    return status.split()[0] if status.strip() else ''

# Parse 'worker-cli status --all <project>' stdout into a list of per-worker status strings.
# '(no active workers)' or blank output → [] (empty project worker set).
def _parse_worker_statuses(raw: str) -> list:
    raw = raw.strip()
    if not raw or raw == '(no active workers)':
        return []
    statuses = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        _, _, status = line.partition(':')
        statuses.append(status.strip())
    return statuses

# Resolve absolute path to worker-cli: shutil.which first, then plugin-cache glob fallback.
# Returns None if unresolvable (hook PATH lacks plugin bin).
def _resolve_worker_cli() -> str:
    found = shutil.which('worker-cli')
    if found:
        return found
    candidates = glob.glob(os.path.expanduser(
        '~/.claude/plugins/cache/brunowinter-plugins/iterative-dev/*/bin/worker-cli'
    ))
    return sorted(candidates)[-1] if candidates else None

# Run 'worker-cli status --all <project_path>' with 3s timeout; return raw stdout.
# Raises on unresolved binary / unresolved tmux / subprocess error / timeout / non-zero exit —
# a broken probe must never be mistaken for a zero-worker project; caller (decide) treats any
# raise as allow. tmux check: worker-cli shells out to bare 'tmux' internally — when tmux is
# not on the hook's PATH, worker-cli silently degrades to '(no active workers)' with exit 0
# instead of erroring, which would otherwise be misread as a genuine empty worker set.
def _live_worker_statuses(project_path: str) -> str:
    binary = _resolve_worker_cli()
    if binary is None:
        raise RuntimeError("worker-cli not resolvable")
    if shutil.which('tmux') is None:
        raise RuntimeError("tmux not resolvable on hook PATH — worker-cli status degrades silently")
    result = subprocess.run(
        [binary, 'status', '--all', project_path],
        capture_output=True, text=True, timeout=3,
    )
    if result.returncode != 0:
        raise RuntimeError(f"worker-cli status --all exited {result.returncode}")
    return result.stdout

# Parse stdin JSON; return (command, run_in_background, session_id); (None, False, None) on error (fail-open)
def _parse_input():
    try:
        payload = json.loads(sys.stdin.read())
        tool_input = payload.get("tool_input", {})
        cmd = tool_input.get("command")
        bg = tool_input.get("run_in_background", False)
        cmd = cmd if isinstance(cmd, str) else None
        bg = bg if isinstance(bg, bool) else False
        return cmd, bg, payload.get("session_id")
    except Exception:
        return None, False, None


if __name__ == "__main__":
    block_timer_no_worker_working_workflow()
