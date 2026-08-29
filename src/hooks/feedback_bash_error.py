# INFRASTRUCTURE
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _fire_log import log_fire

_FEEDBACK_MESSAGE = (
    "This tool call FAILED. "
    "1. Diagnose why before any retry. "
    "2. Retry corrected ONCE. "
    "3. After 2 failures on this goal, STOP and report to the user."
)
_EVENT_NAME = "PostToolUseFailure"


# ORCHESTRATOR

# Read a PostToolUseFailure payload from stdin; emit the retry-discipline message back to the
# model as additionalContext. Exits 0 in every path — this hook never blocks anything (the tool
# call already ran and already failed).
def feedback_bash_error_workflow() -> None:
    payload = _parse_payload()
    if payload is None:
        sys.exit(0)
    if not _is_bash_tool_error(payload):
        sys.exit(0)
    command = (payload.get("tool_input") or {}).get("command", "")
    log_fire(
        "feedback_bash_error", "feedback", payload.get("tool_name") or "Bash", command,
        reason=_FEEDBACK_MESSAGE, session_id=payload.get("session_id"),
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": payload.get("hook_event_name") or _EVENT_NAME,
            "additionalContext": _FEEDBACK_MESSAGE,
        }
    }))
    sys.exit(0)


# FUNCTIONS

# Parse stdin JSON; None on any error (fail-open — a hook must never disturb a tool call by failing)
def _parse_payload():
    try:
        payload = json.loads(sys.stdin.read())
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


# True only for a genuine failed Bash tool call. Three measured gates, all fail-closed:
#   1. tool_name == "Bash" — the matcher already scopes this, the check makes a mis-registration
#      under another matcher harmless instead of noisy.
#   2. a non-empty "error" string — the shape signal that a failure actually happened. A success
#      payload (PostToolUse) carries "tool_response" and no "error" at all, so a hook accidentally
#      registered on the success event stays silent. Keyed on shape, not on the event name, which
#      is the part a future CC version is most likely to rename.
#   3. is_interrupt falsy — a user ESC also produces a failure payload, and telling the model to
#      diagnose and retry something the USER stopped would be exactly wrong.
def _is_bash_tool_error(payload: dict) -> bool:
    if payload.get("tool_name") != "Bash":
        return False
    error = payload.get("error")
    if not isinstance(error, str) or not error.strip():
        return False
    if payload.get("is_interrupt"):
        return False
    return True


if __name__ == "__main__":
    feedback_bash_error_workflow()
