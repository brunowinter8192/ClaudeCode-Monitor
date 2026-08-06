# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire

# Match any gh-cli search/research call (7 tools) anywhere in the command
_GH_SEARCH_RE = re.compile(
    r'\bgh-cli\s+(?:search_repos|search_code|get_repo_tree|get_file_content'
    r'|index_issues|index_discussions|index_releases)\b'
)
# A segment is allowed if it starts with one of the 7 search/research tools OR repo_freshness —
# repo_freshness alone never triggers this hook (absent from _GH_SEARCH_RE above), but once a
# combined chain is already in scope (>=1 of the 7 present) it may join as a segment.
_GH_SEARCH_SEGMENT_RE = re.compile(
    r'^gh-cli\s+(?:search_repos|search_code|get_repo_tree|get_file_content'
    r'|index_issues|index_discussions|index_releases|repo_freshness)\b'
)
# Shell command separators: && || ; newline | (single, after ||) and space-bounded &.
# Order matters — && before single &, || before |. `2>&1` / `>&` not matched
# (no whitespace before &, no |/;/&& token).
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')

_BLOCK_MESSAGE = (
    "gh-cli search/research tools (search_repos, search_code, get_repo_tree, get_file_content, "
    "index_issues, index_discussions, index_releases) must run STANDALONE — do NOT pipe to grep/"
    "head/tail/sed/awk/wc, do NOT chain with any other command. Output ALWAYS returns IN FULL to "
    "the context; there is no way to filter or truncate it after the call. Narrow results ONLY "
    "via the tool's own args: --limit, --offset, --path, --metadata-only, --sort-by.\n"
    "Multiple gh-cli calls MAY be combined in one Bash command — search/research calls with each "
    "other, and repo_freshness may join the chain too. Separate each call with a shell operator "
    "(&&, ;, or a newline), e.g.:\n"
    "  gh-cli index_issues \"q1\" owner/repo && gh-cli index_issues \"q2\" owner/repo\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a gh-cli search/research call is chained
# with any non-search segment. Multiple gh-cli search/research calls in one Bash = allowed.
def block_gh_cli_chained_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    if not _GH_SEARCH_RE.search(stripped):
        sys.exit(0)
    for segment in _SEPARATOR_RE.split(stripped):
        seg = segment.strip()
        if not seg:
            continue
        if not _GH_SEARCH_SEGMENT_RE.match(seg):
            print(_BLOCK_MESSAGE, file=sys.stderr, end="")
            log_fire("block_gh_cli_chained", "block", "Bash", command,
                     reason=_BLOCK_MESSAGE, session_id=session_id)
            sys.exit(2)
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


if __name__ == "__main__":
    block_gh_cli_chained_workflow()
