# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire
from _known_cli import is_allowed_chain_segment

# Trigger: any of the 7 search/research tools OR the 2 read commands (get_issue, list_issues) —
# the hook only engages once one of these 9 is present. 2026-08: get_issue/list_issues absorbed
# from the deleted rewrite_gh_cli_read_noise.py (rewrite-and-strip-noise superseded by block).
_GH_TRIGGER_RE = re.compile(
    r'\bgh-cli\s+(?:search_repos|search_code|get_repo_tree|get_file_content'
    r'|index_issues|index_discussions|index_releases|get_issue|list_issues)\b'
)
# The 2 read commands specifically — PROTECTED: must run with no redirect (bounded output,
# context-destined). The other 7 search/research tools keep their existing redirect-allowed
# behavior (unchanged) — they fall through to the generic is_known_cli_segment() check below,
# which does not police redirects.
_GH_READ_SEGMENT_RE = re.compile(r'^gh-cli\s+(?:get_issue|list_issues)\b')
# Redirect operators only — pipes never need checking here: _SEPARATOR_RE below already splits
# on `|`, so a piped read segment's pipe target becomes its own (foreign, blocking) segment.
_REDIRECT_RE = re.compile(r'2>&1|2>|&>|>>|<<|>|<')
# Shell command separators: && || ; newline | (single, after ||) and space-bounded &.
# Order matters — && before single &, || before |. `2>&1` / `>&` not matched
# (no whitespace before &, no |/;/&& token).
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')

_BLOCK_MESSAGE = (
    "gh-cli search/research tools (search_repos, search_code, get_repo_tree, get_file_content, "
    "index_issues, index_discussions, index_releases, repo_freshness) and read commands "
    "(get_issue, list_issues) must not be piped to grep/head/tail/sed/awk/wc, and any other "
    "segment in the same Bash call must be a known CLI tool (gh-cli, rag-cli, worker-cli, "
    "reddit-cli, linkedin, websearch) or a leading cd/guard. Output ALWAYS returns IN FULL to "
    "the context; there is no way to filter or truncate it after the call. Narrow results ONLY "
    "via the tool's own args: --limit, --offset, --path, --metadata-only, --sort-by.\n"
    "Cross-CLI and multi-call chains ARE allowed, e.g.:\n"
    "  gh-cli index_issues \"q1\" owner/repo && gh-cli get_issue owner/repo 5\n"
)
_READ_REDIRECT_MESSAGE = (
    "gh-cli get_issue/list_issues must run with no redirect (`>`, `>>`, `2>&1`, `&>`, `<`) — "
    "output is bounded and must land directly in context, not a file read back piecemeal. "
    "Re-issue the call standalone (or combined with other known-CLI calls) without the redirect.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a protected gh-cli call carries a redirect,
# or if any segment in the command is neither a known-CLI call nor a leading cd/guard.
def block_gh_cli_chained_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    if not _GH_TRIGGER_RE.search(stripped):
        sys.exit(0)
    for segment in _SEPARATOR_RE.split(stripped):
        seg = segment.strip()
        if not seg:
            continue
        if _GH_READ_SEGMENT_RE.match(seg):
            if _REDIRECT_RE.search(seg):
                _block(_READ_REDIRECT_MESSAGE, command, session_id)
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
    log_fire("block_gh_cli_chained", "block", "Bash", command,
             reason=message, session_id=session_id)
    sys.exit(2)


if __name__ == "__main__":
    block_gh_cli_chained_workflow()
