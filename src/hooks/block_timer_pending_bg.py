# INFRASTRUCTURE
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fire_log import log_fire

# Matches any sleep-only background command: bare "sleep N" or "sleep N && echo <anything>".
# Mirrors _SLEEP_ONLY_BG in rewrite_background_sleep.py / _CANONICAL in block_unauthorized_background.py
# / block_timer_no_worker_working.py, so this hook is order-independent relative to those.
_SLEEP_ONLY_BG = re.compile(r'^\s*sleep\s+\d+(?:\.\d+)?\s*(?:&&\s*echo\b[^;&|\n]*)?\s*$')

_WORKTREE_FRAGMENT = '.claude/worktrees/'

# 3300s canonical timer duration (rewrite_background_sleep.py normalizes every background
# sleep-timer to exactly "sleep 3300 && echo done") + margin for the proxy's own TN-delivery lag.
# STRICTLY younger-than (age < _PENDING_EXPIRY_SECS), not <=: an entry armed EXACTLY at the
# threshold is already treated as stale and does NOT block — the margin exists to tolerate proxy/
# TN delivery lag, not to extend the blocking window by one more second at the boundary.
_PENDING_EXPIRY_SECS = 3600

# Design rationale — why this hook does NOT repeat the false-block failure the removed
# block_concurrent_timer.py hook had (process-docs/tool_use_safety/
# 2026-07-20_timer_guard_concurrent_redesign.md, 2026-07-21_concurrent_timer_hook_removed.md):
# that hook computed `expiry = armed_time + 600s` blind hook-local arithmetic and blocked purely
# on its own clock — it had no way to know the underlying sleep process died early (worker went
# idle before timeout, or the turn was interrupted/aborted), so it kept blocking a legitimate new
# timer until its own stale clock ran out. This hook instead reads state src/proxy/
# pending_bg_state.py writes from DIRECTLY OBSERVED events: an entry is "pending" only because the
# proxy genuinely saw a launch-ack, and it is cleared only because the proxy genuinely saw a
# completion/kill notice for that id — status/exit-code-agnostic (dev/timer-loop/md/
# bg_completion_wordings_20260806.md: the dominant real wording is exit 143, i.e. exactly the
# SIGTERM a menubar abort/turn-interrupt produces). An abort itself generates the clearing signal
# — the proxy sees the kill notice and clears the entry before the orchestrator's next timer
# attempt. _PENDING_EXPIRY_SECS is a narrow safety net for a DIFFERENT case only — the completion
# notice never reaching the proxy at all (proxy crashed/restarted and the session also ended) —
# not the primary signal, unlike the old hook where the clock WAS the only signal.

_BLOCK_MESSAGE_INTRO = "Go idle immediately — do NOT arm another background timer."
_BLOCK_MESSAGE_TAIL = "Wait for the completion notice instead of retrying the timer.\n"


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if the call is the canonical sleep-timer and a
# fresh (non-expired) pending background task exists. Skipped entirely from inside a worktree
# (this hook is orchestrator-only, same convention as block_timer_no_worker_working.py).
def block_timer_pending_bg_workflow() -> None:
    try:
        if _WORKTREE_FRAGMENT in os.getcwd():
            sys.exit(0)
        command, run_in_background, session_id = _parse_input()
        if command is None:
            sys.exit(0)
        current_project = _current_project_slug()
        pending_ids = decide(command, run_in_background, _read_pending_state, current_project)
        if pending_ids:
            message = _build_block_message(pending_ids, _read_pending_state)
            print(message, file=sys.stderr, end="")
            log_fire("block_timer_pending_bg", "block", "Bash", command,
                     reason=message, session_id=session_id)
            sys.exit(2)
    except Exception:
        sys.exit(0)
    sys.exit(0)


# FUNCTIONS

# Pure decision: gate on run_in_background + sleep-only regex, then check the pending-state file
# via state_fn (injectable — real entrypoint wires _read_pending_state, smoke tests inject a
# stub). current_project ("" when the caller couldn't determine it) scopes which entries count as
# blocking — see _fresh_pending_ids. Returns the sorted list of fresh (non-expired), same-project
# pending task ids — empty means allow, a non-empty list both signals block AND carries what the
# caller needs to name in the message. state_fn exceptions (missing file, corrupt JSON) or a
# non-dict result → allow (fail-open).
def decide(command: str, run_in_background: bool, state_fn, current_project: str = "") -> list:
    if not run_in_background:
        return []
    if command is None or not _SLEEP_ONLY_BG.match(command):
        return []
    try:
        state = state_fn()
    except Exception:
        return []
    if not isinstance(state, dict):
        return []
    return _fresh_pending_ids(state, current_project)


# Filter state entries to fresh-pending, SAME-PROJECT task ids: status=='pending', armed_at
# parses, age STRICTLY younger than _PENDING_EXPIRY_SECS (see constant comment for the boundary
# rationale), and project match. Project scoping (2026-08, cross-project false-block incident —
# see block_timer_pending_bg.py's project-scoping design note above _current_project_slug): an
# entry with NO "project" field (pre-migration state, or project_path was unresolvable at arm
# time) still blocks unconditionally — backward-compat default, and such entries age out via the
# normal expiry anyway. An entry WITH a "project" field only blocks when it matches
# current_project. An entry with an unparseable armed_at is skipped, not counted — fail-open
# per-entry, same spirit as the file-level fail-open.
def _fresh_pending_ids(state: dict, current_project: str) -> list:
    now = datetime.now(timezone.utc)
    fresh = []
    for task_id, entry in state.items():
        if not isinstance(entry, dict) or entry.get("status") != "pending":
            continue
        age = _entry_age_secs(entry, now)
        if age is None or age >= _PENDING_EXPIRY_SECS:
            continue
        entry_project = entry.get("project")
        if entry_project is not None and entry_project != current_project:
            continue
        fresh.append(task_id)
    return sorted(fresh)


# Age in seconds of one entry's armed_at vs now; None if armed_at is missing/unparseable.
def _entry_age_secs(entry: dict, now: datetime):
    armed_at = entry.get("armed_at", "")
    try:
        ts = datetime.fromisoformat(armed_at.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    return (now - ts).total_seconds()


# Build the block message naming every pending id and the age of the YOUNGEST (most recently
# armed) one, so the orchestrator can judge how much wait plausibly remains against the 55min
# ceiling. Re-reads state_fn() independently from decide()'s own read (message-building is a
# separate concern from the block/allow decision) — any failure here degrades to a message with
# no age info, never raises (a raise here must never flip an intended BLOCK into an accidental
# ALLOW via the workflow's outer fail-open except).
def _build_block_message(pending_ids: list, state_fn) -> str:
    youngest_age = None
    try:
        state = state_fn()
        now = datetime.now(timezone.utc)
        ages = [a for a in (_entry_age_secs(state.get(tid, {}), now) for tid in pending_ids) if a is not None]
        if ages:
            youngest_age = min(ages)
    except Exception:
        youngest_age = None
    plural = "s" if len(pending_ids) > 1 else ""
    ids_str = ", ".join(pending_ids)
    age_clause = f", youngest armed {_format_age(youngest_age)} ago" if youngest_age is not None else ""
    return (
        f"{_BLOCK_MESSAGE_INTRO} Background task{plural} still pending "
        f"(ID{plural}: {ids_str}{age_clause}). {_BLOCK_MESSAGE_TAIL}"
    )


# Humanize a seconds count as "Ns" / "Nm" / "Nh Nm" (no seconds once minutes are shown).
def _format_age(secs) -> str:
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hrs, rem_mins = divmod(mins, 60)
    return f"{hrs}h {rem_mins}m" if rem_mins else f"{hrs}h"


# Normalize a project name/basename to the same canonical slug claude_proxy_start.sh derives for
# dual-log stems and src/proxy/pending_bg_state.py stamps on armed entries (PROJECT_BASENAME):
# lower-case, any run of non-[a-z0-9] chars (including existing underscores/hyphens) collapsed to
# a single "_", leading/trailing "_" stripped. Duplicated in pending_bg_state.py rather than
# shared — this hook and the proxy writer stay structurally independent (src/hooks/ has no import
# path into src/proxy/, same convention as the file-path helpers already duplicated between them).
def _normalize_project_slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


# This hook's own project, derived from cwd's basename. Main-session cwd IS the project root (the
# same assumption the _WORKTREE_FRAGMENT check above makes), so basename(cwd) is the raw project
# name to normalize — e.g. cwd "/Users/x/Monitor_CC" -> "monitor_cc", matching the "monitor_cc"
# slug pending_bg_state.py would have stamped from PROXY_PROJECT_PATH="/Users/x/Monitor_CC".
def _current_project_slug() -> str:
    return _normalize_project_slug(os.path.basename(os.getcwd().rstrip('/')))


# Real state reader — same MONITOR_CC_ROOT/tmp-fallback convention as src/proxy/pending_bg_state.py.
# Raises naturally on a missing/corrupt file; decide()'s try/except treats any raise as allow.
def _read_pending_state() -> dict:
    path = _resolve_pending_bg_state_file()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_pending_bg_state_file() -> Path:
    root = os.environ.get("MONITOR_CC_ROOT")
    if root:
        return Path(root) / "src" / "logs" / "pending_bg_tasks.json"
    return Path("/tmp") / "pending_bg_tasks.json"


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
    block_timer_pending_bg_workflow()
