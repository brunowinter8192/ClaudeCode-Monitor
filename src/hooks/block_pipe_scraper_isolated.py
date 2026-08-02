# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire

# Fast-path anchor: skip commands with no pipe_scraper module invocation at all
_SCRAPER_RE = re.compile(r'-m\s+src\.crawler\.pipe_scraper\b')
# One `VAR=value` shell assignment token (value = any non-whitespace run)
_ASSIGN_TOKEN = r'[A-Za-z_][A-Za-z0-9_]*=\S*'
# Zero or more assignment tokens, space-separated, as an env-var prefix on a command
_ASSIGN_PREFIX = rf'(?:{_ASSIGN_TOKEN}\s+)*'
# A segment is the pipe_scraper call itself, optionally env-var-prefixed and optionally
# path-prefixed on the interpreter (e.g. `./venv/bin/python`, `/usr/bin/python3`)
# (redirects stay part of the segment)
_SCRAPER_SEGMENT_RE = re.compile(
    rf'^{_ASSIGN_PREFIX}(?:\S+/)?python3?\s+-m\s+src\.crawler\.pipe_scraper\b'
)
# A segment is a leading cd — allowed alongside pipe_scraper (module path is CWD-relative)
_CD_SEGMENT_RE = re.compile(r'^cd\b')
# A segment is one or more bare shell variable assignments and nothing else — allowed
# alongside pipe_scraper (e.g. `OUTPUT_DIR=/tmp/x` on its own line before `cd "$WEBSEARCH"`)
_ASSIGNMENT_ONLY_SEGMENT_RE = re.compile(rf'^(?:{_ASSIGN_TOKEN}\s*)+$')
# Shell command separators: && || ; newline | (single, after ||) and bare & (background).
# Order matters — && before single &, || before |. Single & excludes `&&`/`&>`/`N>&M`
# (2>&1) via lookaround on both sides — no whitespace requirement, since bash treats
# `x&tail` (no spaces at all) identically to `x & tail` as two commands.
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||(?<![&>])&(?![&>])')
# Backslash+newline is a shell line continuation, not a separator — collapsed before split
_LINE_CONTINUATION_RE = re.compile(r'\\\n')
# Any command/process substitution anywhere blocks outright when pipe_scraper is present —
# checked against the RAW (unstripped) command: _strip_non_shell_active keeps $()/backticks
# shell-active outside quotes, but its double-quote scanner blanks them INSIDE "..." even
# though real bash still evaluates $(...) there (`cd "$(pwd)"` really runs pwd) — a bare
# raw-text search closes that gap too. Plain `$VAR`/`${VAR}` expansion does not match (no
# literal `(` follows `$`).
_SUBSHELL_RE = re.compile(r'\$\(|`|<\(|>\(')

_BLOCK_MESSAGE = (
    "python -m src.crawler.pipe_scraper must run alone in the Bash invocation — no other "
    "commands before, after, or piped to it, and no command/process substitution ($(...), "
    "`...`, <(...), >(...)) anywhere in it. Only shell variable assignments, a `cd`, and the "
    "pipe_scraper call itself (optionally env-var-prefixed, with output redirection) may "
    "accompany it. This lets the long-running scraper auto-background instead of blocking the "
    "worker on a poll chained into the same call. Run log checks or other commands in a "
    "separate Bash call.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a pipe_scraper call shares the Bash
# invocation with anything other than assignments, a cd, and itself. Fail-open on any parse error.
def block_pipe_scraper_isolated_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    joined = _LINE_CONTINUATION_RE.sub(' ', stripped)
    if not _SCRAPER_RE.search(joined):
        sys.exit(0)
    if _SUBSHELL_RE.search(command):
        _block(command, session_id)
    segments = [s.strip() for s in _SEPARATOR_RE.split(joined) if s.strip()]
    scraper_segments = [s for s in segments if _SCRAPER_SEGMENT_RE.match(s)]
    if not scraper_segments:
        sys.exit(0)
    if len(scraper_segments) > 1:
        _block(command, session_id)
    for seg in segments:
        if (_SCRAPER_SEGMENT_RE.match(seg) or _CD_SEGMENT_RE.match(seg)
                or _ASSIGNMENT_ONLY_SEGMENT_RE.match(seg)):
            continue
        _block(command, session_id)
    sys.exit(0)


# FUNCTIONS

# Print block message, log the fire event, exit 2
def _block(command: str, session_id: str) -> None:
    print(_BLOCK_MESSAGE, file=sys.stderr, end="")
    log_fire("block_pipe_scraper_isolated", "block", "Bash", command,
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
    block_pipe_scraper_isolated_workflow()
