# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fire_log import log_fire

# Matches any sleep-only background command: bare "sleep N" or "sleep N && echo <anything>".
# [^;&|\n]* stops at shell separators — prevents matching "sleep N && echo x && other_cmd".
_SLEEP_ONLY_BG = re.compile(r'^\s*sleep\s+\d+(?:\.\d+)?\s*(?:&&\s*echo\b[^;&|\n]*)?\s*$')
# Canonical background wake-up command (worker-cli wait, iterative-dev plugin) — replaces the
# old raw sleep-timer + menubar-kill push mechanism with a pull: the command blocks in-process
# until all workers of the project go stably idle (or --timeout), and its own exit IS the
# wake-up. No "already canonical" exemption needed here: _SLEEP_ONLY_BG requires a literal
# "sleep" token, so it can never match _TARGET — every sleep-only match is a stale habit.
_TARGET = "worker-cli wait"

# Orchestrator-only guard (2026-08, live incident): a WORKER arming a background sleep (e.g.
# waiting on its own long test run) must NOT get promoted to "worker-cli wait" — run from a
# worker's worktree cwd, that resolves the worktree path as the project, finds no workers there,
# and blocks up to the full default timeout; that stray wait is then a live child under the
# worker's own claude process, which makes the ORCHESTRATOR's own worker-cli wait see a live
# background task and refuse to finish too (one misfire cascades into two stuck waits). Same
# _WORKTREE_FRAGMENT convention the (now-removed) block_timer_* hooks used.
_WORKTREE_FRAGMENT = '.claude/worktrees/'


# ORCHESTRATOR

# Read Bash tool_input from stdin; rewrite any sleep-only background command → canonical "worker-cli wait".
# Orchestrator-only — skipped entirely from inside a worktree (worker session); worker sleeps stay sleeps.
def rewrite_background_sleep_workflow() -> None:
    if _in_worktree():
        sys.exit(0)
    command, run_in_background, session_id = _parse_input()
    if not run_in_background:
        sys.exit(0)
    if command is None:
        sys.exit(0)
    if not _SLEEP_ONLY_BG.match(command):
        sys.exit(0)
    output = _emit_rewrite()
    log_fire("rewrite_background_sleep", "rewrite", "Bash", command, rewritten=_TARGET, session_id=session_id)
    print(json.dumps(output))
    sys.exit(0)


# FUNCTIONS

# True if this hook is running from inside a worktree cwd (worker session). Fail-open TOWARD
# "skip rewrite" on any os.getcwd() failure (rare — deleted cwd, permission issue): a missed
# rewrite for the orchestrator just means the old sleep-timer form persists this one time
# (harmless); the opposite default would risk rewriting a worker's sleep on the one call where
# cwd detection itself is unreliable — exactly the incident this guard exists to prevent.
def _in_worktree() -> bool:
    try:
        return _WORKTREE_FRAGMENT in os.getcwd()
    except Exception:
        return True

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

# Build allow+updatedInput dict rewriting command to canonical "worker-cli wait"; return it (caller handles print)
def _emit_rewrite() -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {"command": _TARGET, "run_in_background": True},
        },
    }


if __name__ == "__main__":
    rewrite_background_sleep_workflow()
