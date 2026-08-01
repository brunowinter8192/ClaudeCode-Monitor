# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire

# Fast-path anchor: skip commands with no rag-cli index call at all
_RAG_INDEX_RE = re.compile(r'\brag-cli\s+index\b')
# A segment is the rag-cli index call itself (redirects stay part of the segment)
_RAG_INDEX_SEGMENT_RE = re.compile(r'^rag-cli\s+index\b')
# A segment is a leading cd — the only other thing allowed alongside rag-cli index
_CD_SEGMENT_RE = re.compile(r'^cd\b')
# Shell command separators: && || ; newline | (single, after ||) and space-bounded &.
# Order matters — && before single &, || before |. `2>&1` / `>&` not matched
# (no whitespace before &, no |/;/&& token).
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')

_BLOCK_MESSAGE = (
    "rag-cli index must run alone in the Bash invocation — no other commands before, after, or "
    "piped to it. Only a leading `cd` and output redirection (>, >>, 2>&1) may accompany it. "
    "Run log checks or other commands in a separate Bash call.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a rag-cli index call shares the Bash
# invocation with anything other than a leading cd. Fail-open on any parse error.
def block_rag_cli_index_isolated_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    if not _RAG_INDEX_RE.search(stripped):
        sys.exit(0)
    segments = [s.strip() for s in _SEPARATOR_RE.split(stripped) if s.strip()]
    index_segments = [s for s in segments if _RAG_INDEX_SEGMENT_RE.match(s)]
    if not index_segments:
        sys.exit(0)
    if len(index_segments) > 1:
        _block(command, session_id)
    for seg in segments:
        if _RAG_INDEX_SEGMENT_RE.match(seg) or _CD_SEGMENT_RE.match(seg):
            continue
        _block(command, session_id)
    sys.exit(0)


# FUNCTIONS

# Print block message, log the fire event, exit 2
def _block(command: str, session_id: str) -> None:
    print(_BLOCK_MESSAGE, file=sys.stderr, end="")
    log_fire("block_rag_cli_index_isolated", "block", "Bash", command,
             reason=_BLOCK_MESSAGE, session_id=session_id)
    sys.exit(2)


# Parse stdin JSON; return (command, session_id); (None, None) on any error (fail-open)
def _parse_command():
    try:
        payload = json.loads(sys.stdin.read())
        cmd = payload.get("tool_input", {}).get("command")
        return (cmd if isinstance(cmd, str) else None), payload.get("session_id")
    except Exception:
        return None, None


if __name__ == "__main__":
    block_rag_cli_index_isolated_workflow()
