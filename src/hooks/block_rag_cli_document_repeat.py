# INFRASTRUCTURE
import datetime
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire

# Anchor: rag-cli index/delete invocations. `block_rag_cli_index_isolated.py` already
# forbids >1 `rag-cli index` segment per Bash call (intra-call chaining); this hook targets
# the gap it cannot see — the SAME single-document call repeated across SEPARATE Bash calls
# (each one individually isolated, none of them long-running enough to auto-background).
_RAG_RE = re.compile(r'\brag-cli\s+(index|delete)\b')

# Segment-end operators: terminate the rag-cli logical command (same set as
# block_rag_docs_layer.py's chain-boundary detection).
_SEGMENT_END_RE = re.compile(r'&&|\|\||[;)\n]|(?<!>)&(?![&>])')
# Noise inside the segment: pipes (excluding `||`) and redirects — bounds the argument scan.
_NOISE_RE = re.compile(r'2>&1|2>|&>|>>|<<|>|<|(?<!\|)\|(?!\|)')

# Rolling window and repeat threshold. 600s (not the 30s block_polling_loop.py uses for
# sleep-loop polling) — a full model turn sits between two rag-cli calls here, so a short
# window would expire before a real repeat pattern registers. Threshold 2 (not 3): a
# genuine single-document op is singular by definition (pull one file back in); a SECOND
# --document call to the same collection+subcommand within the window is already the
# opening move of the per-file loop, not a second legitimate one-off.
_WINDOW_SECS = 600
_THRESHOLD = 2

# State file path (env-var overridable for test isolation) — same mechanic as
# block_polling_loop.py.disabled's MONITOR_CC_POLLING_STATE.
_STATE_FILE = os.environ.get(
    "MONITOR_CC_RAG_DOC_REPEAT_STATE",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'logs', 'rag_doc_repeat_state.jsonl',
    ),
)

_BLOCK_MESSAGE_TEMPLATE = (
    "Repeated single-document `rag-cli {subcommand} --collection {collection} --document ...` "
    "calls detected — this is the 2nd such call to this collection within 10 minutes, the "
    "opening move of a per-file loop (an observed incident issued ~40/~48 of these instead "
    "of one call). Use the collection-wide form instead: "
    "`rag-cli {subcommand} --collection {collection}` (no --document). A single one-off "
    "--document call remains fine; it's the repeat that is blocked.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr on the 2nd (or later) single-document
# rag-cli index/delete call to the same collection within the session's 10-min window.
# Fail-open on any parse/state error.
def block_rag_cli_document_repeat_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    matches = list(_RAG_RE.finditer(stripped))
    if not matches:
        sys.exit(0)
    for m in matches:
        subcommand = m.group(1)
        seg_end = _segment_end(stripped, m.end())
        original_segment = command[m.start():seg_end]
        target = _extract_target(subcommand, original_segment)
        if target is None:
            continue
        count = _record_and_count(session_id or "", target)
        if count >= _THRESHOLD:
            _block(command, session_id, target)
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


# Return end index of the logical rag-cli segment starting after the index/delete match,
# bounded by the first chain operator or the first pipe/redirect noise token.
def _segment_end(stripped: str, rag_end: int) -> int:
    end_m = _SEGMENT_END_RE.search(stripped, rag_end)
    seg_end = end_m.start() if end_m else len(stripped)
    noise_m = _NOISE_RE.search(stripped, rag_end, seg_end)
    if noise_m is not None:
        seg_end = min(seg_end, noise_m.start())
    return seg_end


# Return "subcommand:collection" fingerprint when the segment is a single-document op
# (--collection AND --document both present); None otherwise (collection-wide call,
# malformed segment — out of scope, never touches state).
def _extract_target(subcommand: str, original_segment: str):
    try:
        tokens = shlex.split(original_segment)
    except ValueError:
        return None
    collection = _find_flag_value(tokens, '--collection')
    if collection is None:
        return None
    if _find_flag_value(tokens, '--document') is None:
        return None
    return f"{subcommand}:{collection}"


# Return the value of --flag (space-separated or --flag=value form); None if absent
def _find_flag_value(tokens: list, flag: str):
    for i, tok in enumerate(tokens):
        if tok == flag and i + 1 < len(tokens):
            return tokens[i + 1]
        if tok.startswith(flag + '='):
            return tok.split('=', 1)[1]
    return None


# Append new occurrence, prune entries outside the window (self-pruning), return count
# for (session_id, target). Fail-open (0) on any state-file error — can only undercount,
# never overcount (worst case: a real repeat is missed, never a false block).
def _record_and_count(session_id: str, target: str) -> int:
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(seconds=_WINDOW_SECS)
        entries = _read_recent_entries(cutoff)
        entries.append({
            'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'session_id': session_id,
            'target': target,
        })
        _write_entries(entries)
        return sum(
            1 for e in entries
            if e.get('session_id') == session_id and e.get('target') == target
        )
    except Exception:
        return 0


# Read state file entries with ts >= cutoff; returns list of dicts (skips malformed lines)
def _read_recent_entries(cutoff: datetime.datetime) -> list:
    if not os.path.exists(_STATE_FILE):
        return []
    entries = []
    try:
        with open(_STATE_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.datetime.fromisoformat(entry.get('ts', '').replace('Z', '+00:00'))
                    if ts >= cutoff:
                        entries.append(entry)
                except Exception:
                    continue
    except Exception:
        return []
    return entries


# Write entries list to state file (atomic overwrite = self-pruning); fail-silent on any error
def _write_entries(entries: list) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, 'w', encoding='utf-8') as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        return


# Print block message (naming the collection-wide escape), log the fire event, exit 2
def _block(command: str, session_id: str, target: str) -> None:
    subcommand, collection = target.split(':', 1)
    message = _BLOCK_MESSAGE_TEMPLATE.format(subcommand=subcommand, collection=collection)
    print(message, file=sys.stderr, end="")
    log_fire("block_rag_cli_document_repeat", "block", "Bash", command,
              reason=message, session_id=session_id)
    sys.exit(2)


if __name__ == "__main__":
    block_rag_cli_document_repeat_workflow()
