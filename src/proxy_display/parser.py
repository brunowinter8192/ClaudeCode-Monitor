# INFRASTRUCTURE
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

from .forwarded_parser import (
    _proxy_session_id_for_project,
    _infer_model_family, _summarize_fwd_message, _dict_to_list_fwd,
    _apply_delta_to_list, _extract_forwarded_fields, _parse_forwarded_log,
    _lazy_load_messages_forwarded, parse_proxy_log_forwarded, reconstruct_all_messages,
)

# Newer CC appends a fresh role='system' "<total_tokens>N tokens left</total_tokens>" message to the
# END of the message history on EVERY request; `_apply_role_system_strip` nukes it to "." (correct).
# The nuke lands at a NEW message index each request, so its loc_key is new each request and the
# write-side hash dedup structurally cannot suppress it — a messages_delta entry is written on
# virtually every request. Anchored FULL-match, never substring-anywhere: the same string is
# routinely quoted inside real content. Read-side note: the dual-log line carries no role, so the
# write side's second anchor (role=='system') is not available here — the full-match on a single
# stripped text is doing the whole job, which holds because no strip pass removes a bare, otherwise
# empty total_tokens marker from a non-system message.
_TOTAL_TOKENS_NUKE_RE = re.compile(r"^<total_tokens>\d+ tokens left</total_tokens>$")

# FUNCTIONS

# Does this line's messages_delta carry anything BADGE-worthy? Badge-only helper — the overlay
# dicts and _msg_idx_by_flow_id are populated from the raw delta regardless, so the expanded view
# keeps rendering every span this filters out here.
# Two classes are not substantial (2026-08-29):
#   - stripped side: a message whose blocks' stripped texts amount to exactly ONE text full-matching
#     the total_tokens marker — the per-request CC token-budget nuke, noise on nearly every request.
#   - injected side: a block whose injected spans are only ".", the API-required empty-block filler
#     that `strip_sr.py` / `_apply_role_system_strip` leave behind. Not a real injection (same
#     principle the fn_map "." skips already encode write-side), so a nag/deferred/total_tokens nuke
#     badges `strip` alone instead of `strip inject`.
# Everything else counts, so a real content injection and a real strip badge exactly as before.
def _msgs_delta_is_substantial(msgs_delta: dict, entry_type: str) -> bool:
    is_injected = entry_type == 'injected_delta'
    for blks in (msgs_delta or {}).values():
        if not isinstance(blks, dict):
            continue
        if is_injected:
            for spans in blks.values():
                if not isinstance(spans, list):
                    continue
                texts = [
                    s[1] for s in spans
                    if isinstance(s, (list, tuple)) and len(s) == 2 and s[0] == 'injected' and s[1]
                ]
                if texts and ' '.join(texts) != '.':
                    return True
        else:
            texts = [
                t for blk in blks.values() if isinstance(blk, list)
                for t in blk if isinstance(t, str)
            ]
            if len(texts) == 1 and _TOTAL_TOKENS_NUKE_RE.match(texts[0].strip()):
                continue
            if texts:
                return True
    return False


# Estimate token count from char count (chars/3.5 heuristic, ~±15%)
def _chars_to_tokens(chars: int) -> int:
    return int(chars / 3.5)

# Public wrapper — used by panes to build project-scoped worker log globs
def proxy_session_id_for_project(project_path: str) -> str:
    return _proxy_session_id_for_project(project_path)

# Find the most recent worker proxy log for the given worker name
def find_worker_proxy_log(worker_name: str, project_filter: Optional[str] = None) -> Optional[Path]:
    root = os.environ.get("MONITOR_CC_ROOT", "")
    if not root:
        root = str(Path(__file__).parent.parent.parent)
    logs_dir = Path(root) / "src" / "logs"
    dual_dir = logs_dir / "dual_log"
    if not project_filter:
        return None
    project_session_id = _proxy_session_id_for_project(project_filter)
    fwd_matches = list(dual_dir.glob(f"api_requests_worker_{project_session_id}_{worker_name}_*_forwarded.jsonl"))
    if not fwd_matches:
        return None
    best = max(fwd_matches, key=lambda f: f.stat().st_mtime)
    stem = best.stem[:-len("_forwarded")]
    return logs_dir / f"{stem}.jsonl"  # synthetic path — stem is the log_id

# Return epoch float of proxy session start (marker file mtime); falls back silently to time.time()
def get_proxy_session_start_ts(project_filter: str) -> float:
    root = os.environ.get("MONITOR_CC_ROOT", "")
    if not root:
        root = str(Path(__file__).parent.parent.parent)
    session_id = _proxy_session_id_for_project(project_filter)
    marker_file = Path(root) / "src" / "logs" / f".proxy_session_{session_id}"
    if marker_file.exists():
        try:
            mtime = marker_file.stat().st_mtime
            if time.time() - mtime < 86400:  # stale guard: >24h → fallback
                return mtime
        except OSError:
            pass
    return time.time()

# Locate current proxy JSONL via marker file; returns Path or None
def find_proxy_log_path(project_filter: Optional[str]) -> Optional[Path]:
    if not project_filter:
        return None
    root = os.environ.get("MONITOR_CC_ROOT", "")
    if not root:
        root = str(Path(__file__).parent.parent.parent)
    session_id = _proxy_session_id_for_project(project_filter)
    marker_file = Path(root) / "src" / "logs" / f".proxy_session_{session_id}"
    log_id = session_id
    if marker_file.exists():
        try:
            lines = marker_file.read_text(encoding="utf-8").splitlines()
            if len(lines) >= 2 and lines[1].strip():
                log_id = lines[1].strip()
        except OSError:
            pass
    return Path(root) / "src" / "logs" / f"api_requests_{log_id}.jsonl"

# Derive stripped/injected dual-log paths from the resolved main log path
def _find_dual_log_paths(main_log_path: Optional[Path]) -> tuple:
    if main_log_path is None:
        return None, None
    dual_dir = main_log_path.parent / 'dual_log'
    stem = main_log_path.stem  # e.g. api_requests_<log_id>
    return (
        dual_dir / f'{stem}_stripped.jsonl',
        dual_dir / f'{stem}_injected.jsonl',
    )

# Read new entries from one dual-log file (stripped or injected), accumulate per model_family.
# acc_by_family: {family -> {'system': {}, 'tools': {}, 'messages': {}, 'fields': {}}}
# Mutates acc_by_family IN-PLACE so all proxy_entries holding a reference see updates
# automatically. is_first -> .clear() + .update() on existing section dicts (preserves refs).
# '_has_content_by_flow_id': per-flow_id bool — did THIS line's delta carry any SUBSTANTIAL
# content, for the header badge. Derived from system/tools/messages_delta (fields_delta excluded —
# a field-only change must not badge; fields stay in the fields drill-down). Not fn_map. The
# messages part goes through `_msgs_delta_is_substantial`, which drops the per-request total_tokens
# nuke and "."-only filler injections — badge-only, the overlay dicts below are unaffected, so the
# expanded view still renders every span this filter hides from the header.
# '_msg_idx_by_flow_id': {flow_id -> set(msg_idx str)} — which message indices THIS line's
# messages_delta touched. Lets the expanded view render this flow's own spans even when they
# sit outside the rendered delta window, and scope span lookups so a request that did not
# touch a given index never shows a neighbor request's span there.
# Returns new file position; silently ignores missing/unreadable file.
def accumulate_dual_log(path: Optional[Path], last_pos: int, acc_by_family: dict) -> int:
    if path is None or not path.exists():
        return last_pos
    try:
        with open(path, 'r', encoding='utf-8') as f:
            f.seek(last_pos)
            while True:
                raw_line = f.readline()
                if not raw_line:
                    break
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                family = _infer_model_family(entry.get('model', ''))
                acc = acc_by_family.setdefault(
                    family,
                    {
                        'system': {}, 'tools': {}, 'messages': {}, 'fields': {},
                        '_has_content_by_flow_id': {}, '_msg_idx_by_flow_id': {},
                    }
                )
                if entry.get('is_first', False):
                    for section in ('system', 'tools', 'messages', 'fields'):
                        acc[section].clear()
                    acc.setdefault('_has_content_by_flow_id', {}).clear()
                    acc.setdefault('_msg_idx_by_flow_id', {}).clear()
                acc['system'].update(entry.get('system_delta') or {})
                for name, val in (entry.get('tools_delta') or {}).items():
                    acc['tools'][name] = val
                msgs_delta = entry.get('messages_delta') or {}
                for midx, blks in msgs_delta.items():
                    if midx not in acc['messages']:
                        acc['messages'][midx] = {}
                    acc['messages'][midx].update(blks)
                acc['fields'].update(entry.get('fields_delta') or {})
                fid = entry.get('flow_id', '')
                has_content = bool(
                    entry.get('system_delta') or entry.get('tools_delta')
                    or _msgs_delta_is_substantial(msgs_delta, entry.get('type', ''))
                )
                acc.setdefault('_has_content_by_flow_id', {})[fid] = has_content
                acc.setdefault('_msg_idx_by_flow_id', {})[fid] = set(msgs_delta.keys())
            return f.tell()
    except OSError:
        return last_pos

# Resolve the _errors dual-log path for the current proxy session of project_filter.
# Returns None if project_filter is empty; path may not exist (callers check .exists()).
def find_errors_log_path(project_filter: Optional[str]) -> Optional[Path]:
    if not project_filter:
        return None
    root = os.environ.get('MONITOR_CC_ROOT', '') or str(Path(__file__).parent.parent.parent)
    session_id = _proxy_session_id_for_project(project_filter)
    marker_file = Path(root) / 'src' / 'logs' / f'.proxy_session_{session_id}'
    log_id = session_id
    if marker_file.exists():
        lines = marker_file.read_text(encoding='utf-8').splitlines()
        if len(lines) >= 2 and lines[1].strip():
            log_id = lines[1].strip()
    return Path(root) / 'src' / 'logs' / 'dual_log' / f'api_requests_{log_id}_errors.jsonl'

# Resolve the _response dual-log path for the current proxy session of project_filter.
# Returns None if project_filter is empty; path may not exist (callers check .exists()).
def find_response_log_path(project_filter: Optional[str]) -> Optional[Path]:
    if not project_filter:
        return None
    root = os.environ.get('MONITOR_CC_ROOT', '') or str(Path(__file__).parent.parent.parent)
    session_id = _proxy_session_id_for_project(project_filter)
    marker_file = Path(root) / 'src' / 'logs' / f'.proxy_session_{session_id}'
    log_id = session_id
    if marker_file.exists():
        lines = marker_file.read_text(encoding='utf-8').splitlines()
        if len(lines) >= 2 and lines[1].strip():
            log_id = lines[1].strip()
    return Path(root) / 'src' / 'logs' / 'dual_log' / f'api_requests_{log_id}_response.jsonl'

# Read new _response entries from last_pos; returns ({request_id: headers_dict}, new_pos).
# Silently ignores missing/unreadable file and malformed lines.
def read_response_log(path: Optional[Path], last_pos: int) -> tuple:
    if path is None or not path.exists():
        return {}, last_pos
    rid_map: dict = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            f.seek(last_pos)
            while True:
                raw = f.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = entry.get('request_id', '')
                if rid:
                    rid_map[rid] = entry.get('headers', {})
            return rid_map, f.tell()
    except OSError:
        return {}, last_pos

# Glob dual_log/api_requests_worker_{project_session_id}_*_errors.jsonl, read new records per
# file by byte-pos. worker_name extracted from filename (mirrors scan_worker_logs naming logic).
# Unprefixed fallback when project_session_id is empty. Returns (records, new_positions).
def scan_worker_errors_logs(last_positions: dict, project_session_id: str = '',
                            min_mtime: float = 0) -> tuple:
    root = os.environ.get('MONITOR_CC_ROOT', '') or str(Path(__file__).parent.parent.parent)
    dual_dir = Path(root) / 'src' / 'logs' / 'dual_log'
    if not dual_dir.exists():
        return [], dict(last_positions)
    new_positions = dict(last_positions)
    records: list = []
    pattern = (
        f'api_requests_worker_{project_session_id}_*_errors.jsonl'
        if project_session_id else
        'api_requests_worker_*_errors.jsonl'
    )
    for fpath in sorted(dual_dir.glob(pattern)):
        try:
            if min_mtime and fpath.stat().st_mtime < min_mtime:
                continue
        except OSError:
            continue
        last_pos = last_positions.get(str(fpath), 0)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                f.seek(last_pos)
                while True:
                    raw_line = f.readline()
                    if not raw_line:
                        break
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # Extract worker_name: stem = api_requests_worker_[{hash}_]{name}_{ts}_errors
                    stem = fpath.stem
                    remaining = stem.replace('api_requests_worker_', '')
                    if remaining.endswith('_errors'):
                        remaining = remaining[:-len('_errors')]
                    if project_session_id and remaining.startswith(project_session_id + '_'):
                        remaining = remaining[len(project_session_id) + 1:]
                    rec['_worker_name_from_file'] = remaining.rsplit('_', 1)[0]
                    records.append(rec)
                new_positions[str(fpath)] = f.tell()
        except OSError:
            continue
    return records, new_positions
