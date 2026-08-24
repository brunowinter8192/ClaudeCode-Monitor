# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire
from _known_cli import is_known_cli_segment, is_guard_segment

# `websearch scrape_url` — PROTECTED: must run with no redirect (bounded/full-page output,
# context-destined). 2026-08: replaces the deleted rewrite_websearch_scrape_noise.py.
# Proven incident: `websearch scrape_url URL > /tmp/f.md 2>&1; wc -l /tmp/f.md; head -120
# /tmp/f.md` — the rewrite hook silently stripped the redirect, leaving the dependent wc/head
# segments to hit a nonexistent file; the call exited 1 and surfaced as [ERROR] although the
# scrape succeeded. Blocking instead of rewriting forces a standalone re-issue — no dependent
# segment can ever desync from a silently-edited command. `search_web`/`search_engine_drilldown`
# produce bounded output too and are simply `websearch` segments — no redirect policing needed
# (fall through to the generic is_known_cli_segment() check below).
_SCRAPE_SEGMENT_RE = re.compile(r'^websearch\s+scrape_url\b')
# Fast-path anchor: skip commands with no scrape_url token at all
_SCRAPE_RE = re.compile(r'\bwebsearch\s+scrape_url\b')
# Redirect operators only — pipes never need checking here: _SEPARATOR_RE below already splits
# on `|`, so a piped scrape segment's pipe target becomes its own (foreign, blocking) segment.
_REDIRECT_RE = re.compile(r'2>&1|2>|&>|>>|<<|>|<')
# Shell command separators: && || ; newline | (single, after ||) and space-bounded &.
# Order matters — && before single &, || before |. `2>&1` / `>&` not matched
# (no whitespace before &, no |/;/&& token).
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')

_BLOCK_MESSAGE = (
    "websearch scrape_url must not be piped/chained with a segment that is neither a known CLI "
    "tool (gh-cli, rag-cli, worker-cli, reddit-cli, linkedin, websearch) nor a leading cd/guard. "
    "Cross-CLI chains ARE allowed, e.g. `websearch scrape_url URL && rag-cli search ... coll`.\n"
)
_REDIRECT_MESSAGE = (
    "websearch scrape_url must run with no redirect (`>`, `>>`, `2>&1`, `&>`, `<`) — the page "
    "returns in full and must land directly in context, not a file read back piecemeal via "
    "wc/head/tail (proven incident: a stripped redirect desynced dependent wc/head segments "
    "from the actual output, surfacing a successful scrape as [ERROR]). Re-issue standalone "
    "(or combined with other known-CLI calls) without the redirect.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a scrape_url call carries a redirect, or
# if any segment in the command is neither a known-CLI call nor a leading cd/guard.
def block_websearch_scrape_chained_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    if not _SCRAPE_RE.search(stripped):
        sys.exit(0)
    for segment in _SEPARATOR_RE.split(stripped):
        seg = segment.strip()
        if not seg:
            continue
        if _SCRAPE_SEGMENT_RE.match(seg):
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
    log_fire("block_websearch_scrape_chained", "block", "Bash", command,
             reason=message, session_id=session_id)
    sys.exit(2)


if __name__ == "__main__":
    block_websearch_scrape_chained_workflow()
