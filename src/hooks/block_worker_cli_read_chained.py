# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire
from _known_cli import is_known_cli_segment, is_guard_segment

# `worker-cli capture` / `worker-cli response` — PROTECTED: must run with no redirect (bounded,
# context-destined output). 2026-08: replaces the deleted rewrite_worker_cli_capture_noise.py /
# rewrite_worker_cli_response_noise.py. Also retires the old `worker-cli capture X > /tmp/file`
# / `worker-cli capture X | tail -40` "legitimate fallback" allowances documented on those
# rewrite hooks — both predate the 2026-06-22 capture redesign that made capture's output
# natively clean/context-ready like response's; the workaround's rationale no longer holds.
# `status`, `list`, `send`, `merge`, `spawn`, `kill`, `revive`, `wait` are simply `worker-cli`
# segments — no redirect policing needed (fall through to the generic is_known_cli_segment()
# check below).
_READ_SEGMENT_RE = re.compile(r'^worker-cli\s+(?:capture|response)\b')
# Fast-path anchor: skip commands with no worker-cli capture/response token at all
_READ_RE = re.compile(r'\bworker-cli\s+(?:capture|response)\b')
# Redirect operators only — pipes never need checking here: _SEPARATOR_RE below already splits
# on `|`, so a piped read segment's pipe target becomes its own (foreign, blocking) segment.
_REDIRECT_RE = re.compile(r'2>&1|2>|&>|>>|<<|>|<')
# Shell command separators: && || ; newline | (single, after ||) and space-bounded &.
# Order matters — && before single &, || before |. `2>&1` / `>&` not matched
# (no whitespace before &, no |/;/&& token).
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')

_BLOCK_MESSAGE = (
    "worker-cli capture/response must not be piped/chained with a segment that is neither a "
    "known CLI tool (gh-cli, rag-cli, worker-cli, reddit-cli, linkedin, websearch) nor a "
    "leading cd/guard. Cross-CLI and multi-call chains ARE allowed, e.g. "
    "`worker-cli capture janitor && worker-cli response janitor`.\n"
)
_REDIRECT_MESSAGE = (
    "worker-cli capture/response must run with no redirect (`>`, `>>`, `2>&1`, `&>`, `<`) and "
    "no pipe — output is clean and bounded (2026-06 capture redesign) and must land directly "
    "in context, not a file read back piecemeal. Re-issue the call standalone (or combined "
    "with other known-CLI calls) without the redirect.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a worker-cli capture/response call carries
# a redirect, or if any segment in the command is neither a known-CLI call nor a leading cd/guard.
def block_worker_cli_read_chained_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    if not _READ_RE.search(stripped):
        sys.exit(0)
    for segment in _SEPARATOR_RE.split(stripped):
        seg = segment.strip()
        if not seg:
            continue
        if _READ_SEGMENT_RE.match(seg):
            if _REDIRECT_RE.search(seg):
                _block(_REDIRECT_MESSAGE, command, session_id)
            continue
        if is_known_cli_segment(seg) or is_guard_segment(seg):
            continue
        _block(_BLOCK_MESSAGE, command, session_id)
    sys.exit(0)


# FUNCTIONS

# Parse stdin JSON; return (command, session_id); (None, None) on any error (fail-open)
def _parse_command():
    try:
        payload = json.loads(sys.stdin.read())
        cmd = payload.get("tool_input", {}).get("command")
        return (cmd if isinstance(cmd, str) else None), payload.get("session_id")
    except Exception:
        return None, None

# Print message to stderr, log the fire, exit 2
def _block(message: str, command: str, session_id) -> None:
    print(message, file=sys.stderr, end="")
    log_fire("block_worker_cli_read_chained", "block", "Bash", command,
             reason=message, session_id=session_id)
    sys.exit(2)


if __name__ == "__main__":
    block_worker_cli_read_chained_workflow()
