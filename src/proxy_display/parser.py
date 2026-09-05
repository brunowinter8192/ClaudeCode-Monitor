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

# Is ONE message index's delta entry substantial? Extracted from `_msgs_delta_is_substantial`,
# which is now an any-of over it — the split briefly also fed a per-index prepend filter
# (removed 2026-08-30 with the out-of-window prepend itself), so the badge is its only consumer
# again. Kept split because the per-index question is the meaningful one and reads clearer.
# `blks` is one messages_delta value: {blk_idx -> [stripped texts]} or {blk_idx -> [(tag, text)]}.
def _msg_delta_entry_is_substantial(blks, is_injected: bool) -> bool:
    if not isinstance(blks, dict):
        return False
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
        return False
    texts = [
        t for blk in blks.values() if isinstance(blk, list)
        for t in blk if isinstance(t, str)
    ]
    if len(texts) == 1 and _TOTAL_TOKENS_NUKE_RE.match(texts[0].strip()):
        return False
    return bool(texts)


# Is this delta entry the per-request total_tokens nuke — exactly ONE stripped text full-matching
# the marker? The narrow shape the lag correction below keys on; see `accumulate_dual_log`.
def _is_total_tokens_nuke(blks) -> bool:
    if not isinstance(blks, dict):
        return False
    texts = [
        t for blk in blks.values() if isinstance(blk, list)
        for t in blk if isinstance(t, str)
    ]
    return len(texts) == 1 and bool(_TOTAL_TOKENS_NUKE_RE.match(texts[0].strip()))


# Does this line's messages_delta carry anything BADGE-worthy? Badge-only helper — the overlay
# dicts and _msg_idx_by_flow_id are populated from the raw delta regardless, so the expanded view
# keeps rendering IN-WINDOW every span this filters out here. Out-of-window there is nothing left
# to render: the expanded body is the request's payload delta only (2026-08-30), so for a strip
# outside that window this function's verdict decides whether ANY trace reaches the reader.
# Two classes are not substantial (2026-08-29):
#   - stripped side: a message whose blocks' stripped texts amount to exactly ONE text full-matching
#     the total_tokens marker — the per-request CC token-budget nuke, noise on nearly every request.
#   - injected side: a block whose injected spans are only ".", the API-required empty-block filler
#     that `strip_sr.py` / `_apply_role_system_strip` leave behind (same principle the fn_map "."
#     skips already encode write-side).
# Everything else counts, so a real content injection and a real strip badge exactly as before.
# NOTE this is the per-line signal, NOT the final badge. Suppressing every "."-only injection would
# also silence the nag/deferred/date-changed nukes, whose "." IS injected and DOES render green.
# `badge_flags` below re-adds exactly those by coordinating with the flow's stripped side; only the
# total_tokens class ends up with both badge words off.
def _msgs_delta_is_substantial(msgs_delta: dict, entry_type: str) -> bool:
    is_injected = entry_type == 'injected_delta'
    return any(
        _msg_delta_entry_is_substantial(blks, is_injected)
        for blks in (msgs_delta or {}).values()
    )


# Resolve the REQ-header's two badge booleans for one entry -> (show_strip, show_inject).
# Reads the per-flow lookups pane.py / worker_proxy_pane.py attach; falls back to False for any
# lookup a caller did not attach.
#
# The inject side needs the strip side to decide, because an `injected_delta` line CANNOT identify
# the total_tokens class on its own — a total_tokens nuke and a task-tools-nag nuke both inject the
# identical literal "." and the marker text lives only on the stripped side. So the two are
# coordinated by flow_id here, at the consumer, where both lookups are in hand:
#
#   show_inject = real (non-".") injection   OR   ("."-filler present AND the strip side is substantial)
#
# `_inject_fns_lookup` is already the "real injection" bool (`_msgs_delta_is_substantial` treats a
# "."-only block as insubstantial), and a non-empty `_inject_msgs_lookup` entry means the injected
# side touched a message block at all — which, given the writer only records a block when it has an
# injected span, is exactly "a '.'-filler is present" once the real-injection case is excluded.
#
# Resulting behavior, one line per class:
#   - total_tokens nuke  -> strip False, inject False (strip side is the non-substantial one)
#   - task-tools nag / deferred / date-changed / mid-conv nuke -> strip True, inject True
#   - total_tokens + a real strip in the same request -> strip True, inject True
#   - real content injection (bg-exit wake-up, TN wake-up, system rules) -> inject True regardless
#
# Computed per render rather than stored at accumulation time on purpose: the two dual-log files are
# tailed independently, so at accumulation time the peer line for a flow may not have been read yet.
# Deriving it here is order-independent and self-correcting for the running session.
def badge_flags(entry: dict) -> tuple:
    fid = entry.get('flow_id', '')
    show_strip = bool(entry.get('_strip_fns_lookup', {}).get(fid, False))
    show_inject = bool(entry.get('_inject_fns_lookup', {}).get(fid, False))
    if not show_inject and show_strip and entry.get('_inject_msgs_lookup', {}).get(fid):
        show_inject = True
    return show_strip, show_inject


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

# Derive the _original dual-log path from the resolved main log path
def _find_original_log_path(main_log_path: Optional[Path]) -> Optional[Path]:
    if main_log_path is None:
        return None
    dual_dir = main_log_path.parent / 'dual_log'
    stem = main_log_path.stem
    return dual_dir / f'{stem}_original.jsonl'

# Read new entries from the _original dual-log, keeping the LATEST non-empty tools list per model
# family as a {name: tool_def} map. Unlike _stripped/_injected/_forwarded, _original is NOT
# delta-encoded — every line with tools carries the full list — so no merge logic is needed, just
# overwrite. Tool defs are stable within a session (measured 2026-09-04, process-docs/dual_log_cli/
# 2026-09-04_sys_tool_original_chars_and_whole_strip_lines.md: 0 hash mismatches comparing any
# earlier request's tool-by-name content against the last request's, across 45 sessions), so always
# keeping the newest snapshot is correct without tracking history. acc_by_family: {family ->
# {name -> tool_def}}, mutated IN-PLACE per family dict (same reference-preservation convention as
# accumulate_dual_log) so entries holding a reference see updates automatically. Returns new file
# position; silently ignores missing/unreadable file.
def accumulate_original_tools(path: Optional[Path], last_pos: int, acc_by_family: dict) -> int:
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
                tools = (entry.get('payload') or {}).get('tools')
                if not tools:
                    continue
                family = _infer_model_family(entry.get('model', ''))
                fam_map = acc_by_family.setdefault(family, {})
                fam_map.clear()
                for t in tools:
                    if isinstance(t, dict) and t.get('name'):
                        fam_map[t['name']] = t
            return f.tell()
    except OSError:
        return last_pos

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
# messages_delta touched. Scopes span lookups so a request that did not touch a given index never
# shows a neighbor request's span there. It no longer drives any out-of-window rendering: the
# expanded body is the request's payload delta only (2026-08-30), so an index this flow touched
# outside that window is simply not drawn.
# '_sys_idx_by_flow_id' / '_tool_name_by_flow_id' (2026-09-04): the same per-flow scoping as
# '_msg_idx_by_flow_id', for the system and tools sections — which system indices / tool names
# THIS line's system_delta/tools_delta touched. Added for duallog's `msgs` sys/tool delta-tail
# feature (src/dual_log_cli/overlay.py's `build_sys_tool_overlay`); no lag correction is needed for
# either (unlike messages) — `_diff_system`/`_diff_tools` (src/proxy/diff_engine.py) compute a
# direct same-request diff of that request's own original vs. forwarded halves, never a historical
# ops chain, so there is no shape-ambiguity window for a strip to be recorded one request late.
# '_lag_msg_idx_by_flow_id': {flow_id -> set(msg_idx str)} — the WRITE-SIDE LAG CORRECTION.
# CC hangs the cache-control breakpoint on the last message, so a request's fresh trailing
# role='system' total_tokens msg arrives list-shaped; `_apply_role_system_strip` nukes it correctly
# but `_ops_from_content_change` yields no ops for list content, so the delta writer records no
# stripped span for it. The NEXT request re-sends that msg as a plain string, produces the op, and
# records the strip — one request too late (measured: 0 of 510 recorded against the request that
# performed them, 510 of 510 against the following one). This maps such a delta back onto the flow
# that actually stripped it, so `_lookup_spans` shows the olive original and green "." in-window.
# Three conditions, all required: the index is the PREVIOUS line's trailing msg (prev_count - 1),
# the count did not regress (no restart), and the delta is a total_tokens nuke. That last guard is
# load-bearing — CC overwrites a mid-conversation index in place (the task-tools nag lands on the
# index that was a previous request's trailing msg), and without the marker check the nag's text
# would be attributed to a request that stripped something else there, which is real neighbor bleed.
# Self-neutralising if the writer is ever fixed: the request would record its own strip and the next
# line's repeat would be hash-deduped away, leaving nothing to correct.
# '_last_line_meta': (flow_id, counts.messages) of the previous line of this family — the state the
# correction needs, kept in the acc dict so it survives across incremental calls.
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
                    acc.setdefault('_sys_idx_by_flow_id', {}).clear()
                    acc.setdefault('_tool_name_by_flow_id', {}).clear()
                    acc.setdefault('_lag_msg_idx_by_flow_id', {}).clear()
                    acc['_last_line_meta'] = None
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
                acc.setdefault('_sys_idx_by_flow_id', {})[fid] = set((entry.get('system_delta') or {}).keys())
                acc.setdefault('_tool_name_by_flow_id', {})[fid] = set((entry.get('tools_delta') or {}).keys())
                count = (entry.get('counts') or {}).get('messages', 0)
                prev_meta = acc.get('_last_line_meta')
                if prev_meta is not None:
                    prev_fid, prev_count = prev_meta
                    trailing = str(prev_count - 1)
                    if (count >= prev_count and prev_count > 0
                            and _is_total_tokens_nuke(msgs_delta.get(trailing))):
                        acc.setdefault('_lag_msg_idx_by_flow_id', {}).setdefault(
                            prev_fid, set()).add(trailing)
                acc['_last_line_meta'] = (fid, count)
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
