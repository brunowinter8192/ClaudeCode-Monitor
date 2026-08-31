# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire
from _known_cli import is_allowed_chain_segment

# One `VAR=value` shell assignment token, and zero-or-more as an optional env-var prefix on a
# segment (same pattern _known_cli.py uses for known-CLI segment detection).
_ASSIGN_TOKEN = r'[A-Za-z_][A-Za-z0-9_]*=\S*'
_ASSIGN_PREFIX = rf'(?:{_ASSIGN_TOKEN}\s+)*'
# Trigger: a segment that STARTS WITH an actual rag-cli invocation (optionally env-var-prefixed),
# checked per-segment AFTER splitting — not a bare `\brag-cli\b` search over the whole command.
# 2026-08 fix: the old whole-command search matched `rag-cli` as a PATH SUBSTRING too (observed
# FPs: `ls /Users/.../cli/rag-cli/data/pdf/searxng`, `cd <rag-cli path> && ls` both blocked with
# the piping message although no rag-cli tool was invoked anywhere in the command).
_RAG_CLI_SEGMENT_RE = re.compile(rf'^{_ASSIGN_PREFIX}rag-cli(?:\s|$)')
# `rag-cli search` specifically — PROTECTED: must run with no redirect (bounded output,
# context-destined). 2026-08: absorbed from the deleted rewrite_rag_cli_search_noise.py
# (rewrite-and-strip-noise superseded by block). Other rag-cli subcommands (index, delete,
# list_documents, etc.) keep their existing redirect-allowed behavior — they fall through to
# the generic is_known_cli_segment() check below, which does not police redirects.
_RAG_SEARCH_SEGMENT_RE = re.compile(r'^rag-cli\s+search\b')
# Redirect operators only — pipes never need checking here: _SEPARATOR_RE below already splits
# on `|`, so a piped search segment's pipe target becomes its own (foreign, blocking) segment.
_REDIRECT_RE = re.compile(r'2>&1|2>|&>|>>|<<|>|<')
# Shell command separators: && || ; newline | (single, after ||) and space-bounded &.
# Order matters — && before single &, || before |. `2>&1` / `>&` not matched
# (no whitespace before &, no |/;/&& token).
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')

_BLOCK_MESSAGE = (
    "rag-cli calls must not be piped/chained with a segment that is neither a known CLI tool "
    "(gh-cli, rag-cli, worker-cli, reddit-cli, linkedin, websearch) nor a leading cd/guard. "
    "Cross-CLI chains ARE allowed, e.g. `rag-cli search ... && gh-cli get_issue owner/repo 5`. "
    "Use output redirection (>) to capture non-search rag-cli output instead of piping.\n"
)
_SEARCH_REDIRECT_MESSAGE = (
    "rag-cli search must run with no redirect (`>`, `>>`, `2>&1`, `&>`, `<`) — output is bounded "
    "and must land directly in context, not a file read back piecemeal. Re-issue the call "
    "standalone (or combined with other known-CLI calls) without the redirect.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a rag-cli search call carries a redirect,
# or if any segment in the command is neither a known-CLI call nor a leading cd/guard.
def block_rag_cli_chained_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    segments = [s.strip() for s in _SEPARATOR_RE.split(stripped) if s.strip()]
    if not any(_RAG_CLI_SEGMENT_RE.match(seg) for seg in segments):
        sys.exit(0)
    for seg in segments:
        if _RAG_SEARCH_SEGMENT_RE.match(seg):
            if _REDIRECT_RE.search(seg):
                _block(_SEARCH_REDIRECT_MESSAGE, command, session_id)
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
    log_fire("block_rag_cli_chained", "block", "Bash", command,
             reason=message, session_id=session_id)
    sys.exit(2)


if __name__ == "__main__":
    block_rag_cli_chained_workflow()
