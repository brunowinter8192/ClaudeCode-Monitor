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
#   - websearch: scrape_url_chromium returns a page in full. search_web/
#     search_engine_drilldown/discover_urls are unprotected. (2026-09-06: the table used
#     to list a stale name, `scrape_url` — the websearch cli.py carried
#     scrape_url_chromium/search_web/search_engine_drilldown/discover_urls the whole
#     time this table had it wrong, so the exact-match `is_protected_segment` check
#     never once fired for the real subcommand. Audited all 8 entries against their
#     actual cli.py/wrapper the same way — see process-docs/tool_use_safety/.)
#   - linkedin: all 5 subcommands (get_company_info, get_company_posts, get_messages,
#     get_thread, get_notifications) are bounded read/query calls (`--count`/`--days`/
#     `--date`-capped) with no write/index-type subcommand — every invocation protected.
#   - penny-cli: single-mode wrapper (`penny-cli --klasse "<Klasse>"`), no subcommands —
#     every invocation protected.
#   - duallog: every subcommand (sessions/msgs/expand/search/reqs — `reqs` added since
#     this table was written) exists to show JSONL content in full — every invocation
#     protected, no unprotected subset, so the added subcommand needed no table change.
PROTECTED_SUBCOMMANDS = {
    "gh-cli": {"get_issue", "list_issues"},
    "rag-cli": {"search"},
    "worker-cli": {"capture", "response"},
    "reddit-cli": {"search_subreddits"},
    "websearch": {"scrape_url_chromium"},
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

# Project-directory-basename -> tool-name map for the wrapper-bypass hole (2026-09-06):
# gh-cli/rag-cli/reddit-cli/websearch/linkedin's ~/.local/bin/<tool> wrapper is a 2-line
# `exec <dir>/venv/bin/python <dir>/cli.py "$@"` shim — invoking that same cli.py through
# the interpreter directly (commonly after a bare `cd <dir>`, so the python line itself
# carries no path at all) never matches `_KNOWN_CLI_RE`, which anchors on the WRAPPER
# name, not the underlying script. `jobscraper` is `linkedin`'s actual on-disk project
# directory (the one entry where key != value — the wrapper name and the directory name
# differ). `worker-cli` is excluded: its wrapper IS a bash script (no interpreter
# indirection exists to bypass). `penny-cli` (`venv/bin/python -m src`, run from its own
# project root) and `duallog` (`./venv/bin/python -m src.dual_log_cli`, run from
# monitor-cc's own root) are ALSO excluded — both use module-form invocation, not a
# `cli.py` script path, and `-m src` (penny-cli) in particular collides with any
# ordinary `python -m src...` call any project on this machine might run. No
# interpreter-path bypass of either has been observed; per the evidence-burden rule this
# stays unfixed absent a real incident (see process-docs/tool_use_safety/).
_CLI_PY_DIR_TOOL = {
    "gh-cli": "gh-cli",
    "rag-cli": "rag-cli",
    "reddit-cli": "reddit-cli",
    "websearch": "websearch",
    "jobscraper": "linkedin",
}
_CLI_DIR_ALT = "|".join(re.escape(d) for d in _CLI_PY_DIR_TOOL)
# One of the 5 project directory basenames as its own path/word segment — a `cd` target,
# or embedded in an absolute interpreter/script path — anchored on both sides so
# `websearch` doesn't also match `my-websearch-notes`.
_CLI_PY_DIR_RE = re.compile(rf'(?:^|[/\s])({_CLI_DIR_ALT})(?=[/\s]|$)')
# A segment invoking `cli.py` through a bare interpreter path — no tool name in sight,
# the whole point of the bypass. `(?:\S+/)?` before `python3?` allows any interpreter
# path prefix (`./venv/bin/`, an absolute venv path, or none — bare `python3 cli.py`);
# `(?:\S+/)?` again before `cli.py` covers an absolute script path given without a
# preceding `cd`.
_INTERPRETER_CLI_RE = re.compile(
    rf'^{_ASSIGN_PREFIX}(?:\S+/)?python3?\s+(?:\S+/)?cli\.py'
    rf'(?:\s+(?P<sub>[A-Za-z0-9_.-]+))?(?:\s|$)'
)


# Match-shaped result for an interpreter-resolved `cli.py` invocation — exposes the same
# .group('tool')/.group('sub') interface as re.Match, so a caller never needs to know
# which resolution path produced its match.
class _InterpreterMatch:
    def __init__(self, tool: str, sub):
        self._groups = {'tool': tool, 'sub': sub}

    def group(self, name: str):
        return self._groups[name]


# FUNCTIONS

# Match `segment` (already whitespace-stripped) against a known-CLI invocation by WRAPPER
# name; return the re.Match (with .group('tool')/.group('sub'), sub may be None) or None.
def match_known_cli_segment(segment: str):
    return _KNOWN_CLI_RE.match(segment)

# Match `segment` against a bare-interpreter `cli.py` invocation, then resolve WHICH tool
# by scanning `command_context` (the whole shell-stripped Bash command this segment came
# from) for one of the 5 known project-directory markers — the directory a preceding
# `cd` landed in, or one baked into an absolute interpreter/script path on this same
# segment. The LAST marker found wins (closest `cd` to the invocation, in a single-call
# script). Returns an `_InterpreterMatch` (same `.group('tool')`/`.group('sub')`
# interface as match_known_cli_segment) or None when the segment isn't a `cli.py`
# interpreter call, or no directory marker resolves it.
def match_interpreter_cli_segment(segment: str, command_context: str):
    match = _INTERPRETER_CLI_RE.match(segment)
    if match is None:
        return None
    dir_matches = list(_CLI_PY_DIR_RE.finditer(command_context))
    if not dir_matches:
        return None
    tool = _CLI_PY_DIR_TOOL[dir_matches[-1].group(1)]
    return _InterpreterMatch(tool, match.group('sub'))

# Resolve `segment` as a known-CLI invocation via EITHER the wrapper name or the bare
# `cli.py` interpreter form (the latter resolved against `command_context`). Tries the
# wrapper form first — cheaper, no context scan needed. Return value carries the same
# `.group('tool')`/`.group('sub')` interface regardless of which form matched, or None.
def resolve_cli_segment(segment: str, command_context: str):
    match = match_known_cli_segment(segment)
    if match is not None:
        return match
    return match_interpreter_cli_segment(segment, command_context)

# True if `segment` invokes one of KNOWN_CLI_TOOLS, optionally env-var-prefixed.
def is_known_cli_segment(segment: str) -> bool:
    return match_known_cli_segment(segment) is not None

# True if `match` (from resolve_cli_segment/match_known_cli_segment) is a PROTECTED
# subcommand of its tool (or the tool itself, when every subcommand is protected). False
# when `match` is None.
def is_protected_segment(match) -> bool:
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
