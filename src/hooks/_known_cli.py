# INFRASTRUCTURE
import re

# The eight CLI tools `block_cli_chained.py` polices. Value is the set of PROTECTED
# subcommands (bounded, context-destined output — piping/redirecting them defeats the
# reason they exist) or None when EVERY invocation of that tool is protected (no
# subcommand is safe to truncate/redirect):
#   - gh-cli: get_issue/list_issues return a single bounded issue/list — the other 7
#     search/research subcommands (search_repos, index_issues, repo_freshness, etc.)
#     are unprotected (redirect for a log is fine, no isolated hook exists for them).
#   - rag-cli: search returns a bounded ranked result set. index/delete/update_docs/
#     list_documents run long or write files — redirect is how progress polling works
#     (see block_rag_cli_index_isolated.py, untouched, a different hook for a different
#     reason: auto-backgrounding, not output-boundedness).
#   - worker-cli: capture/response return one worker's clean, bounded pane/response
#     text (2026-06-22 capture redesign). status/list/send/merge/spawn/kill/revive/wait
#     are unprotected.
#   - reddit-cli: search_subreddits returns a bounded (`--limit`-capped, see
#     block_search_subreddits_limit.py — that hook already forbids capping the result
#     further) subreddit list meant to land in context whole. index_subreddits/deep are
#     long-running fetch+index operations (analogous to rag-cli index) — unprotected.
#   - websearch: scrape_url returns a page in full. search_web/search_engine_drilldown
#     are unprotected.
#   - linkedin: all 5 subcommands (get_company_info, get_company_posts, get_messages,
#     get_thread, get_notifications) are bounded read/query calls (`--count`/`--days`/
#     `--date`-capped) with no write/index-type subcommand — every invocation protected.
#   - penny-cli: single-mode wrapper (`penny-cli --klasse "<Klasse>"`), no subcommands —
#     every invocation protected.
#   - duallog: every subcommand (sessions/msgs/expand/search) exists to show JSONL
#     content in full — every invocation protected, no unprotected subset.
PROTECTED_SUBCOMMANDS = {
    "gh-cli": {"get_issue", "list_issues"},
    "rag-cli": {"search"},
    "worker-cli": {"capture", "response"},
    "reddit-cli": {"search_subreddits"},
    "websearch": {"scrape_url"},
    "linkedin": None,
    "penny-cli": None,
    "duallog": None,
}
KNOWN_CLI_TOOLS = tuple(PROTECTED_SUBCOMMANDS.keys())

_ASSIGN_TOKEN = r'[A-Za-z_][A-Za-z0-9_]*=\S*'
_ASSIGN_PREFIX = rf'(?:{_ASSIGN_TOKEN}\s+)*'
_TOOL_ALT = "|".join(re.escape(t) for t in KNOWN_CLI_TOOLS)
# A segment is a known-CLI invocation: optional env-var-assignment prefix, then one of
# the 8 tool names, then an optional subcommand token (captured), then whitespace or
# end-of-segment. The tool name must be immediately followed by whitespace/end (not by
# `-eval`/other identifier chars) — `(?:\s|$)` after the optional subcommand group
# enforces this, since the subcommand group itself requires `\s+` to even engage.
_KNOWN_CLI_RE = re.compile(
    rf'^{_ASSIGN_PREFIX}(?P<tool>{_TOOL_ALT})(?:\s+(?P<sub>[A-Za-z0-9_.-]+))?(?:\s|$)'
)


# FUNCTIONS

# Match `segment` (already whitespace-stripped) against a known-CLI invocation; return
# the re.Match (with .group('tool')/.group('sub'), sub may be None) or None.
def match_known_cli_segment(segment: str):
    return _KNOWN_CLI_RE.match(segment)

# True if `segment` invokes one of KNOWN_CLI_TOOLS, optionally env-var-prefixed.
def is_known_cli_segment(segment: str) -> bool:
    return match_known_cli_segment(segment) is not None

# True if `segment` invokes a PROTECTED subcommand of a known CLI (or the CLI itself
# when every subcommand is protected). False for a non-CLI segment or an unprotected
# subcommand of a known CLI.
def is_protected_segment(segment: str) -> bool:
    match = match_known_cli_segment(segment)
    if match is None:
        return False
    protected = PROTECTED_SUBCOMMANDS[match.group('tool')]
    if protected is None:
        return True
    return match.group('sub') in protected

# Human-readable "<tool> <subcommand>" naming for block messages — drops the
# subcommand when absent or when it is actually a flag (`--klasse`, `--help`), since
# those are not a real subcommand name.
def tool_sub_name(tool: str, sub) -> str:
    if sub and not sub.startswith('-'):
        return f"{tool} {sub}"
    return tool
