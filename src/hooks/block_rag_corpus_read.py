# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire

# rag-cli's on-disk document-chunk store (`data/documents/`). Reading files there directly
# bypasses the ranking/formatting rag-cli performs at search time and returns raw chunk files
# instead of search results — see process-docs/tool_use_safety/
# 2026-08-28_rag_cli_path_indirection_bypass.md. `rag-[^/\s]*` (not a literal `rag-cli`) also
# catches a renamed checkout or worktree (e.g. `rag-cli-convert`, `rag-cli-eval`) — a glob dodge
# around a literal `rag-cli` match.
_CORPUS_PATH_RE = re.compile(r'(?:^|/)rag-[^/\s]*/data/documents(?=[/\s\'")]|$)')
# Fast-path anchor: skip commands that don't even mention the corpus subtree.
_CORPUS_ANCHOR = 'data/documents'
# Commands that pull raw file content into context. Deliberately excludes ls/rm/mv/mkdir — file
# management and deletion over the corpus stay sanctioned; only bypassing rag-cli's own
# search/read_document is blocked. The Read tool is out of scope for this hook (Bash only).
_READ_COMMANDS = ("cat", "grep", "head", "tail", "sed", "awk", "rg", "less", "more")
# One `VAR=value` shell assignment token, and zero-or-more as an optional env-var prefix on a
# segment (same pattern _known_cli.py uses for known-CLI segment detection).
_ASSIGN_TOKEN = r'[A-Za-z_][A-Za-z0-9_]*=\S*'
_ASSIGN_PREFIX = rf'(?:{_ASSIGN_TOKEN}\s+)*'
_READ_CMD_RE = re.compile(rf'^{_ASSIGN_PREFIX}(?:{"|".join(_READ_COMMANDS)})\b')
# Shell command separators: && || ; newline | (single, after ||) and space-bounded &. Same set
# the chained-CLI hook family uses.
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')

_BLOCK_MESSAGE = (
    "Reading rag-cli's document corpus directly (cat/grep/head/tail/sed/awk/rg/less/more on a "
    "rag-*/data/documents path) bypasses ranking/formatting and returns raw chunk-store files, "
    "not search results. Use `rag-cli search <query> <collection>` to find relevant chunks, or "
    "`rag-cli read_document <collection> <doc_id>` (add --before N/--after N for context) to "
    "read a specific document. File management (ls, rm, mv, mkdir) on the corpus stays allowed.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if any segment runs a raw-read command
# (cat/grep/head/tail/sed/awk/rg/less/more) whose original (quote-intact) text names a path
# under a rag-cli data/documents tree. Fail-open on any parse error.
def block_rag_corpus_read_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    if _CORPUS_ANCHOR not in command:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    for stripped_seg, original_seg in _split_segments(stripped, command):
        if not _READ_CMD_RE.match(stripped_seg):
            continue
        if _CORPUS_PATH_RE.search(original_seg):
            _block(command, session_id)
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


# Split `stripped` on _SEPARATOR_RE, yielding (stripped_segment, original_segment) pairs —
# same whitespace trimmed off both sides of each pair so the two stay index-aligned (stripped
# and original are the same length; only quote/heredoc interiors differ between them).
def _split_segments(stripped: str, original: str) -> list:
    pairs = []
    pos = 0
    for m in _SEPARATOR_RE.finditer(stripped):
        pairs.append(_trim_pair(stripped[pos:m.start()], original[pos:m.start()]))
        pos = m.end()
    pairs.append(_trim_pair(stripped[pos:], original[pos:]))
    return [p for p in pairs if p[0].strip()]


# Trim leading/trailing whitespace using the ORIGINAL segment's own whitespace boundary (not
# the stripped copy's) — a quoted argument at the very end of a segment leaves blanked-quote
# spaces at the end of `stripped_seg` that are indistinguishable from real trailing whitespace,
# so trimming off of `stripped_seg` would silently cut the real (quoted) path text out of
# `original_seg`. The same index range is then applied to both (same length, so it carries over).
def _trim_pair(stripped_seg: str, original_seg: str) -> tuple:
    left = len(original_seg) - len(original_seg.lstrip())
    right = len(original_seg) - len(original_seg.rstrip())
    end = len(original_seg) - right
    return stripped_seg[left:end], original_seg[left:end]


# Print block message, log the fire event, exit 2
def _block(command: str, session_id) -> None:
    print(_BLOCK_MESSAGE, file=sys.stderr, end="")
    log_fire("block_rag_corpus_read", "block", "Bash", command,
             reason=_BLOCK_MESSAGE, session_id=session_id)
    sys.exit(2)


if __name__ == "__main__":
    block_rag_corpus_read_workflow()
