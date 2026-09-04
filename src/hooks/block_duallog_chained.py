# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire
from _known_cli import is_allowed_chain_segment

# `duallog` (sessions/msgs/expand/search — every subcommand, no split like worker-cli's
# capture/response vs status/list) is PROTECTED: no redirect and no pipe. The trigger incident
# (2026-09-04): the orchestrator ran `duallog expand <session> 1 --before 0 --after 0 | head -60`
# and later `| tail -25`, reading only PART of a msg — impossible to notice what a truncated view
# is missing, and the whole point of `expand` is to show a msg's content in full.
_DUALLOG_SEGMENT_RE = re.compile(r'^duallog\b')
# Fast-path anchor: skip commands with no duallog token at all
_DUALLOG_RE = re.compile(r'\bduallog\b')
# Redirect operators only — pipes never need checking here: _SEPARATOR_RE below already splits
# on `|`, so a piped duallog segment's pipe target becomes its own (foreign, blocking) segment.
_REDIRECT_RE = re.compile(r'2>&1|2>|&>|>>|<<|>|<')
# Shell command separators: && || ; newline | (single, after ||) and space-bounded &.
# Order matters — && before single &, || before |. `2>&1` / `>&` not matched
# (no whitespace before &, no |/;/&& token).
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')

_BLOCK_MESSAGE = (
    "duallog (sessions/msgs/expand/search) must not be piped/chained with a segment that is "
    "neither a known CLI tool (gh-cli, rag-cli, worker-cli, reddit-cli, linkedin, websearch, "
    "duallog) nor a leading cd/guard. Re-issue the duallog call standalone and read its whole "
    "output — piping into head/tail/grep/etc. truncates a msg's content, which is exactly what "
    "this command exists to show in full. Cross-CLI and multi-call chains ARE allowed, e.g. "
    "`duallog sessions && duallog msgs <session>`.\n"
)
_REDIRECT_MESSAGE = (
    "duallog (sessions/msgs/expand/search) must run with no redirect (`>`, `>>`, `2>&1`, `&>`, "
    "`<`) and no pipe — its output must land directly in context in full, never a file or a "
    "partial view read back piecemeal. Re-issue the call standalone (or combined with other "
    "known-CLI calls) without the redirect, and read the whole output.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a duallog call carries a redirect, or if
# any segment in the command is neither a known-CLI call nor a leading cd/guard.
def block_duallog_chained_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    if not _DUALLOG_RE.search(stripped):
        sys.exit(0)
    for segment in _SEPARATOR_RE.split(stripped):
        seg = segment.strip()
        if not seg:
            continue
        if _DUALLOG_SEGMENT_RE.match(seg):
            if _REDIRECT_RE.search(seg):
                _block(_REDIRECT_MESSAGE, command, session_id)
            continue
        if is_allowed_chain_segment(seg):
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
    log_fire("block_duallog_chained", "block", "Bash", command,
             reason=message, session_id=session_id)
    sys.exit(2)


if __name__ == "__main__":
    block_duallog_chained_workflow()
