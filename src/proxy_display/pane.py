# INFRASTRUCTURE
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
import os
import time

from ..constants import (
    RESET, YELLOW, DIM, WHITE, CYAN,
    POLL_INTERVAL, INPUT_POLL_INTERVAL, PROXY_MESSAGES_KEEP_LAST,
    PROXY_REPARSE_INTERVAL_SECONDS,
)
from .parser import (
    parse_proxy_log_forwarded, _lazy_load_messages_forwarded, find_proxy_log_path,
    accumulate_dual_log, _find_dual_log_paths, _infer_model_family, reconstruct_all_messages,
)
from .format import format_proxy_block, _is_standalone_entry
from .search import build_search_matches
from ..panes.token_pane import build_cache_turns
from ..input.click_handler import (
    read_keypress, setup_keyboard_input, restore_terminal,
    enable_mouse, disable_mouse, read_mouse_event,
    resolve_parent_key, copy_to_clipboard, wait_for_input,
)
from ..utils import truncate_visible, _cell_width
from ..ram_audit import register_ram_dump
# From pane_error_log.py: shared exception-safe pane-error sink
from ..pane_error_log import log_pane_error

# Private search-bar colors (not in palette; internal to this module — mirrors
# core/monitor_display.py's identical private-color pattern for its own search bar)
_SRCH_LABEL = '\033[38;2;108;112;134m'   # muted gray — "search:" label
_SRCH_IDLE  = '\033[38;2;166;173;200m'   # medium gray — unfocused query text

_PROXY_HEADER_LINES = 1  # fixed-height search bar row; unlike worker_proxy_pane's header this never wraps

proxy_entries: List[dict] = []
proxy_expand_states: Dict[int, bool] = {}
proxy_line_map: Dict[int, int] = {}
proxy_hover_row: Optional[int] = None
proxy_scroll_offset: int = 0
proxy_log_position: int = 0

_proxy_jsonl_position: int = 0
_proxy_cache_turns: list = []
_proxy_fwd_pos: int = 0          # forwarded-log byte position for incremental reads
_proxy_acc_fwd: dict = {}        # family accumulator for _parse_forwarded_log
_proxy_stripped_pos: int = 0     # dual-log read position for _stripped.jsonl
_proxy_injected_pos: int = 0     # dual-log read position for _injected.jsonl
_proxy_acc_stripped: dict = {}   # family → {'system': {}, 'tools': {}, 'messages': {}, 'fields': {}}
_proxy_acc_injected: dict = {}   # same — both mutated in-place; entries hold references
_proxy_log_path: Optional[Path] = None  # current log file path, updated each poll cycle for lazy-reload
_proxy_pane_width: int = 80  # updated each render cycle; used by click handler for copy-button column check
_proxy_copy_rows: Set[int] = set()  # phys_rows where ⎘ copy button is rendered; populated by format_proxy_block
_copy_feedback_until: Dict[int, float] = {}  # entry_idx → expiry timestamp for ✓ flash
_last_full_parse_ts: float = 0.0  # timestamp of last re-init to position 0 (time-triggered reset)
_proxy_just_expanded = None  # line_map key set by mouse handler on expand; cleared by _build_proxy_output
_proxy_current_main_session: Optional[str] = None  # tracks session change for full state reset
_proxy_session_start_ts: Optional[str] = None  # filters new entries to current session window
_proxy_undo_stack: list = []  # (key, prev_state) tuples for 'u' expand/collapse undo, capped at 200

# Search state — permanent row-1 search bar (always visible, per user design principle)
_proxy_search_query: str = ''
_proxy_search_focused: bool = False
_proxy_search_matches: List[int] = []       # entry_idx list, ordered by position in proxy_entries
_proxy_search_match_set: Set[int] = set()   # set(_proxy_search_matches) for O(1) membership
_proxy_search_current_idx: int = 0          # index into _proxy_search_matches for the jump target

# ORCHESTRATOR

# Runs proxy pane display loop — reads api_requests.jsonl, shows expandable entries
def run_proxy_loop() -> None:
    from ..core import monitor as _monitor
    global _proxy_current_main_session, _proxy_session_start_ts, _copy_feedback_until
    global _proxy_search_focused

    register_ram_dump('proxy', _proxy_ram_state)
    _proxy_current_main_session = _monitor._get_newest_main_session()
    _proxy_session_start_ts = _monitor._get_session_start_ts()
    if _proxy_session_start_ts is None:
        _proxy_session_start_ts = datetime.utcnow().isoformat() + 'Z'
    last_output = None
    last_data_refresh = 0.0
    setup_keyboard_input()
    enable_mouse()
    try:
        while True:
            try:
                input_changed = False
                while True:
                    char = read_keypress()
                    if char is None:
                        break
                    if char == '\033':
                        event = read_mouse_event(char)
                        if event is not None and event[0] != -1:
                            if _handle_proxy_mouse(*event):
                                input_changed = True
                        elif event is not None:
                            pass  # (-1,-1,-1) release sentinel — no-op
                        elif _proxy_search_focused:  # bare ESC while focused → clear query
                            if _handle_proxy_search_cancel():
                                input_changed = True
                    elif _proxy_search_focused:
                        if _handle_proxy_search_input(char):
                            input_changed = True
                    elif char == 'u':
                        if _undo_proxy_expand():
                            input_changed = True
                    elif char == '/':
                        _proxy_search_focused = True
                        input_changed = True
                    elif char in ('n', 'N'):
                        if _jump_search_match(forward=(char == 'n')):
                            input_changed = True

                now = time.time()
                input_changed, last_data_refresh = _refresh_proxy_data(
                    now, input_changed, last_data_refresh, _monitor
                )

                _copy_feedback_until = {k: v for k, v in _copy_feedback_until.items() if v > now}
                if _copy_feedback_until:
                    input_changed = True

                if input_changed:
                    output = _build_proxy_output()
                    if output != last_output:
                        print("\033[2J\033[3J\033[H", end='', flush=True)
                        if output:
                            print(output)
                        last_output = output

                wait_for_input(INPUT_POLL_INTERVAL)
            except Exception:
                log_pane_error('proxy')
                wait_for_input(INPUT_POLL_INTERVAL)
    finally:
        disable_mouse()
        restore_terminal()

# FUNCTIONS

# Extract entry_idx from any proxy line_map key variant
def _entry_idx_from_key(key) -> Optional[int]:
    if isinstance(key, int):
        return key
    if isinstance(key, tuple):
        if isinstance(key[0], str):   # ('req', idx), ('sys', idx), ('tools', idx), ('tool', idx, n), ('sys_block', idx, n)
            return key[1]
        if isinstance(key[0], int):   # (idx, 'neg_delta'), (idx, 'warnings'), (idx, 'schema')
            return key[0]
    return None

# Serialize a proxy entry to full untruncated text (all new-message blocks) for clipboard
def _serialize_proxy(key, entries: list) -> str:
    import json
    entry_idx = _entry_idx_from_key(key)
    if entry_idx is None or entry_idx >= len(entries):
        return ''
    entry = entries[entry_idx]
    model = entry.get('model', '?')
    msg_count = entry.get('message_count', 0)
    parts = [f"entry_idx={entry_idx}  model={model}  msgs={msg_count}"]
    prev_same_idx = _resolve_prev_same(entries, entry_idx)
    start = entries[prev_same_idx].get('message_count', 0) if prev_same_idx is not None else 0
    for msg_idx, msg in enumerate(entry.get('messages', [])[start:], start=start):
        role = msg.get('role', '?')
        msg_type = msg.get('type', '?')
        blocks = msg.get('blocks', [])
        if blocks:
            for blk in blocks:
                ft = blk.get('full_text', blk.get('preview', ''))
                if ft:
                    parts.append(f"\n--- msg[{msg_idx}] {role} {blk.get('type', '?')} ---")
                    parts.append(ft)
        else:
            ct = msg.get('content_tail', '') or msg.get('content_preview', '')
            if ct:
                parts.append(f"\n--- msg[{msg_idx}] {role} {msg_type} ---")
                parts.append(ct)
    return '\n'.join(parts)

# Walk backward from k-1 to find first non-standalone entry idx (prev_same reference)
def _resolve_prev_same(entries: list, k: int) -> Optional[int]:
    for i in range(k - 1, -1, -1):
        if not _is_standalone_entry(entries[i]):
            return i
    return None

# Strip messages from all entries outside the keep-last window that are not expanded
def _strip_inactive_messages(entries: list, expand_states: dict) -> None:
    cutoff = max(0, len(entries) - PROXY_MESSAGES_KEEP_LAST)
    for i in range(cutoff):
        e = entries[i]
        if e.get('messages') is None:
            continue
        is_active = (
            expand_states.get(i, False) or
            expand_states.get(('req', i), False) or
            expand_states.get((i, 'neg_delta'), False)
        )
        if not is_active:
            del e['messages']

# Return module-level state snapshot for RAM audit
def _proxy_ram_state() -> list:
    return [
        ('proxy_entries',         proxy_entries),
        ('proxy_expand_states',   proxy_expand_states),
        ('proxy_line_map',        proxy_line_map),
        ('_proxy_cache_turns',    _proxy_cache_turns),
        ('_proxy_fwd_pos',        _proxy_fwd_pos),
        ('_proxy_acc_fwd',        _proxy_acc_fwd),
        ('proxy_hover_row',       str(proxy_hover_row)),
        ('proxy_scroll_offset',   proxy_scroll_offset),
        ('proxy_log_position',    proxy_log_position),
        ('_proxy_jsonl_position', _proxy_jsonl_position),
        ('_proxy_search_query',   _proxy_search_query),
        ('_proxy_search_matches', _proxy_search_matches),
    ]

# Cancel active search on bare ESC while focused; bar stays visible with an empty query.
# Returns True (always triggers redraw).
def _handle_proxy_search_cancel() -> bool:
    global _proxy_search_focused, _proxy_search_query, _proxy_search_matches, _proxy_search_match_set
    _proxy_search_focused = False
    _proxy_search_query = ''
    _proxy_search_matches = []
    _proxy_search_match_set = set()
    return True

# Handle keyboard input while the search bar is focused; returns True if input_changed
def _handle_proxy_search_input(char: str) -> bool:
    global _proxy_search_query, _proxy_search_focused
    if char in ('\x7f', '\x08'):  # backspace (DEL or BS)
        _proxy_search_query = _proxy_search_query[:-1]
        return True
    if char in ('\r', '\n'):  # Enter → (re)run search, unfocus
        _run_proxy_search()
        _proxy_search_focused = False
        if _proxy_search_matches:
            _jump_to_search_match()
        return True
    if char.isprintable():
        if len(_proxy_search_query) < 200:
            _proxy_search_query += char
            return True
    return False

# Run the search: one-sweep reconstruction of ALL entries' messages (merged by flow_id — see
# forwarded_parser.reconstruct_all_messages), then build the match index via search.py's
# real-render-based matcher. Always re-runs (not gated on query-unchanged) — the one-sweep is
# cheap enough (~55ms/190 entries measured, process-docs/pane_search/) that "(re)runs the
# search" picks up requests that streamed in since the last Enter.
def _run_proxy_search() -> None:
    global _proxy_search_matches, _proxy_search_match_set, _proxy_search_current_idx
    if not _proxy_search_query:
        _proxy_search_matches = []
        _proxy_search_match_set = set()
        return
    if _proxy_log_path is not None:
        fwd_path = _proxy_log_path.parent / 'dual_log' / f'{_proxy_log_path.stem}_forwarded.jsonl'
        by_flow = reconstruct_all_messages(fwd_path)
        for e in proxy_entries:
            fid = e.get('flow_id')
            if fid in by_flow:
                e['messages'] = by_flow[fid]
                e['messages_total_chars'] = sum(s.get('chars', 0) for s in by_flow[fid])
    _proxy_search_matches = build_search_matches(_proxy_search_query, proxy_entries, proxy_expand_states, _proxy_pane_width)
    _proxy_search_match_set = set(_proxy_search_matches)
    _proxy_search_current_idx = 0

# Jump to the next (forward=True) or previous search match, wrapping around; returns True if
# a jump happened (False when there are no matches, e.g. before the first Enter)
def _jump_search_match(forward: bool) -> bool:
    global _proxy_search_current_idx
    if not _proxy_search_matches:
        return False
    _proxy_search_current_idx = (_proxy_search_current_idx + (1 if forward else -1)) % len(_proxy_search_matches)
    _jump_to_search_match()
    return True

# Set the scroll-jump target to the current search match's REQ header row — reuses the
# EXISTING _proxy_just_expanded / item_positions / scroll-clamp mechanics in _build_proxy_output
# (same anchor for both collapsed and expanded matches; ('req', idx) is always in item_positions
# regardless of expand state, since render_turn.py appends req_key unconditionally)
def _jump_to_search_match() -> None:
    global _proxy_just_expanded
    target_entry_idx = _proxy_search_matches[_proxy_search_current_idx]
    _proxy_just_expanded = ('req', target_entry_idx)

# Render the always-visible search bar (row 1): "search: <query>_" left, "N/M" match counter
# right. Returns ANSI string truncated to pane_width visible cells.
def _render_proxy_search_bar(pane_width: int) -> str:
    cursor = '_' if _proxy_search_focused else ''
    left_plain = f"search: {_proxy_search_query}{cursor}"
    left_vis = sum(_cell_width(ch) for ch in left_plain)
    m = len(_proxy_search_matches)
    if _proxy_search_query and m > 0:
        counter_plain = f"{_proxy_search_current_idx + 1}/{m}"
        cnt_color = CYAN
    elif _proxy_search_query:
        counter_plain = "0/0"
        cnt_color = _SRCH_LABEL
    else:
        counter_plain = ""
        cnt_color = _SRCH_LABEL
    right_vis = sum(_cell_width(ch) for ch in counter_plain) + (1 if counter_plain else 0)
    gap = max(0, pane_width - left_vis - right_vis)
    query_color = WHITE if _proxy_search_focused else _SRCH_IDLE
    cursor_part = f"{CYAN}_" if _proxy_search_focused else ""
    counter_part = f" {cnt_color}{counter_plain}{RESET}" if counter_plain else ""
    bar = (
        f"{_SRCH_LABEL}search: {RESET}"
        f"{query_color}{_proxy_search_query}{RESET}"
        f"{cursor_part}{RESET}"
        f"{' ' * gap}"
        f"{counter_part}"
    )
    return truncate_visible(bar, pane_width)

# Process one mouse event; returns True if display should refresh
def _handle_proxy_mouse(button: int, col: int, row: int) -> bool:
    global proxy_expand_states, proxy_scroll_offset, proxy_hover_row
    global _proxy_just_expanded, _copy_feedback_until, _proxy_undo_stack
    global _proxy_search_focused
    if button == 0:
        if row == 1:  # search bar row — click anywhere on it to focus
            _proxy_search_focused = True
            return True
        key = proxy_line_map.get(row)
        if key is None:
            return False
        is_req = (isinstance(key, tuple) and key[0] == 'req') or isinstance(key, int)
        if is_req and col >= _proxy_pane_width - 2 and row in _proxy_copy_rows:
            entry_idx = _entry_idx_from_key(key)
            if entry_idx is not None and entry_idx < len(proxy_entries) and _proxy_log_path:
                e = proxy_entries[entry_idx]
                if e.get('messages') is None:
                    fwd_path = _proxy_log_path.parent / 'dual_log' / f'{_proxy_log_path.stem}_forwarded.jsonl'
                    _lazy_load_messages_forwarded(e, fwd_path)
            copy_to_clipboard(_serialize_proxy(key, proxy_entries))
            if entry_idx is not None:
                _copy_feedback_until[entry_idx] = time.time() + 1.5
        else:
            _proxy_undo_stack.append((key, proxy_expand_states.get(key, False)))
            if len(_proxy_undo_stack) > 200:
                _proxy_undo_stack.pop(0)
            new_state = not proxy_expand_states.get(key, False)
            proxy_expand_states[key] = new_state
            if new_state:
                entry_idx = _entry_idx_from_key(key)
                if entry_idx is not None and entry_idx < len(proxy_entries) and _proxy_log_path:
                    e = proxy_entries[entry_idx]
                    fwd_path = _proxy_log_path.parent / 'dual_log' / f'{_proxy_log_path.stem}_forwarded.jsonl'
                    if e.get('messages') is None:
                        _lazy_load_messages_forwarded(e, fwd_path)
                    prev_idx = _resolve_prev_same(proxy_entries, entry_idx)
                    if prev_idx is not None:
                        pe = proxy_entries[prev_idx]
                        if pe.get('messages') is None:
                            _lazy_load_messages_forwarded(pe, fwd_path)
                _proxy_just_expanded = key
        return True
    if button == 64:
        proxy_scroll_offset = max(0, proxy_scroll_offset + 3)
        return True
    if button == 65:
        proxy_scroll_offset = max(0, proxy_scroll_offset - 3)
        return True
    if button >= 32:
        proxy_hover_row = row
        return True
    return False

# Undo the last expand/collapse toggle from _proxy_undo_stack; returns True if one was applied
def _undo_proxy_expand() -> bool:
    global proxy_expand_states, _proxy_undo_stack
    if not _proxy_undo_stack:
        return False
    key, prev_state = _proxy_undo_stack.pop()
    proxy_expand_states[key] = prev_state
    return True

# Tick-boundary proxy data refresh; returns (input_changed, new_last_data_refresh)
def _refresh_proxy_data(now: float, input_changed: bool, last_data_refresh: float, monitor) -> tuple:
    global proxy_entries, proxy_expand_states, proxy_line_map, proxy_scroll_offset, proxy_hover_row
    global proxy_log_position, _proxy_jsonl_position, _proxy_cache_turns
    global _proxy_fwd_pos, _proxy_acc_fwd
    global _proxy_log_path, _last_full_parse_ts
    global _proxy_current_main_session, _proxy_session_start_ts
    global _proxy_stripped_pos, _proxy_injected_pos, _proxy_acc_stripped, _proxy_acc_injected
    global _proxy_undo_stack
    global _proxy_search_query, _proxy_search_focused, _proxy_search_matches, _proxy_search_match_set
    if now - last_data_refresh < POLL_INTERVAL:
        return input_changed, last_data_refresh
    newest = monitor._get_newest_main_session()
    if newest != _proxy_current_main_session and newest is not None:
        _proxy_current_main_session = newest
        _proxy_session_start_ts = monitor._get_session_start_ts()
        if _proxy_session_start_ts is None:
            _proxy_session_start_ts = datetime.utcnow().isoformat() + 'Z'
        proxy_entries.clear()
        proxy_expand_states.clear()
        _proxy_undo_stack.clear()
        proxy_line_map.clear()
        proxy_log_position = 0
        proxy_scroll_offset = 0
        proxy_hover_row = None
        _proxy_jsonl_position = 0
        _proxy_cache_turns = []
        _proxy_fwd_pos = 0
        _proxy_acc_fwd.clear()
        _proxy_log_path = None
        _last_full_parse_ts = now
        _proxy_stripped_pos = 0
        _proxy_injected_pos = 0
        _proxy_acc_stripped.clear()
        _proxy_acc_injected.clear()
        _proxy_search_query = ''
        _proxy_search_focused = False
        _proxy_search_matches = []
        _proxy_search_match_set = set()
        input_changed = True
    if _last_full_parse_ts == 0.0:
        _last_full_parse_ts = now
    elif now - _last_full_parse_ts >= PROXY_REPARSE_INTERVAL_SECONDS:
        proxy_entries.clear()
        proxy_line_map.clear()
        proxy_log_position = 0
        _proxy_jsonl_position = 0
        _proxy_cache_turns = []
        _proxy_fwd_pos = 0
        _proxy_acc_fwd.clear()
        _last_full_parse_ts = now
        _proxy_stripped_pos = 0
        _proxy_injected_pos = 0
        _proxy_acc_stripped.clear()
        _proxy_acc_injected.clear()
        input_changed = True
    new_entries, _proxy_fwd_pos = parse_proxy_log_forwarded(
        monitor.active_project_filter, _proxy_fwd_pos, _proxy_acc_fwd
    )
    filtered = [e for e in new_entries if e.get('timestamp', '') >= _proxy_session_start_ts]
    proxy_entries.extend(filtered)
    _proxy_log_path = find_proxy_log_path(monitor.active_project_filter)
    # Accumulate dual-logs and attach references to all newly-added entries.
    # Entries hold a Python reference to the acc dict; in-place mutations propagate automatically.
    stripped_path, injected_path = _find_dual_log_paths(_proxy_log_path)
    _proxy_stripped_pos = accumulate_dual_log(stripped_path, _proxy_stripped_pos, _proxy_acc_stripped)
    _proxy_injected_pos = accumulate_dual_log(injected_path, _proxy_injected_pos, _proxy_acc_injected)
    for entry in filtered:
        family = _infer_model_family(entry.get('model', ''))
        if family not in _proxy_acc_stripped:
            _proxy_acc_stripped[family] = {'system': {}, 'tools': {}, 'messages': {}, 'fields': {}, '_has_content_by_flow_id': {}, '_msg_idx_by_flow_id': {}}
            _proxy_acc_injected[family] = {'system': {}, 'tools': {}, 'messages': {}, 'fields': {}, '_has_content_by_flow_id': {}, '_msg_idx_by_flow_id': {}}
        entry['_stripped_spans'] = _proxy_acc_stripped[family]
        entry['_injected_spans'] = _proxy_acc_injected[family]
        entry['_strip_fns_lookup'] = _proxy_acc_stripped[family].setdefault('_has_content_by_flow_id', {})
        entry['_inject_fns_lookup'] = _proxy_acc_injected[family].setdefault('_has_content_by_flow_id', {})
        entry['_strip_msgs_lookup'] = _proxy_acc_stripped[family].setdefault('_msg_idx_by_flow_id', {})
        entry['_inject_msgs_lookup'] = _proxy_acc_injected[family].setdefault('_msg_idx_by_flow_id', {})
    _strip_inactive_messages(proxy_entries, proxy_expand_states)
    main_sessions = monitor.get_main_session_files()
    if main_sessions:
        filepath = main_sessions[0]
        _proxy_cache_turns, _proxy_jsonl_position = build_cache_turns(
            filepath, _proxy_jsonl_position, _proxy_cache_turns
        )
    return True, now

# Build ANSI output for proxy pane; auto-scrolls to just_expanded entry (also the search-jump
# target — see _jump_to_search_match); clears _proxy_just_expanded.
# Row 1 is the permanent search bar (_PROXY_HEADER_LINES=1); body rows start at row 2 — mirrors
# worker_proxy_pane.py's header/body split + line_map/copy_rows row-shift pattern.
def _build_proxy_output() -> str:
    global proxy_scroll_offset, _proxy_pane_width, _proxy_copy_rows, _proxy_just_expanded
    try:
        term = os.get_terminal_size()
        pane_height = term.lines - 1
        pane_width = term.columns
    except OSError:
        pane_height = 50
        pane_width = 80
    _proxy_pane_width = pane_width
    header = _render_proxy_search_bar(pane_width)
    content_height = max(1, pane_height - _PROXY_HEADER_LINES)
    body_hover = (
        (proxy_hover_row - _PROXY_HEADER_LINES)
        if proxy_hover_row and proxy_hover_row > _PROXY_HEADER_LINES
        else None
    )
    _proxy_copy_rows.clear()
    if not proxy_entries:
        # Mirrors worker_proxy_pane.py's placeholder-body guard: no entries yet → no line_map/
        # copy_rows to shift, no scroll-jump target possible. proxy_line_map cleared explicitly
        # (format_proxy_block's own early-return for empty entries never touches it).
        proxy_line_map.clear()
        _proxy_just_expanded = None
        body, _total_lines = format_proxy_block(proxy_entries, proxy_expand_states, proxy_line_map, body_hover, content_height, pane_width, proxy_scroll_offset)
        return header + '\n' + body
    item_positions: dict = {}
    current_match_entry_idx = (
        _proxy_search_matches[_proxy_search_current_idx]
        if _proxy_search_matches and _proxy_search_current_idx < len(_proxy_search_matches)
        else None
    )
    # format_proxy_block is called with content_height as its own pane_height argument and
    # internally derives its real viewport as max(1, pane_height - 1) — mirror that exact value
    # here (once) so both clamp sites below match what the renderer actually shows.
    viewport_lines_n = max(1, content_height - 1)
    body, total_lines = format_proxy_block(
        proxy_entries, proxy_expand_states, proxy_line_map, body_hover,
        content_height, pane_width, proxy_scroll_offset,
        turns=_proxy_cache_turns, item_positions_out=item_positions,
        copy_feedback=_copy_feedback_until, copy_rows_out=_proxy_copy_rows,
        search_match_set=_proxy_search_match_set, search_current_entry_idx=current_match_entry_idx,
        search_query=_proxy_search_query,
    )
    max_scroll = max(0, total_lines - viewport_lines_n)
    proxy_scroll_offset = min(proxy_scroll_offset, max_scroll)
    shifted = {r + _PROXY_HEADER_LINES: k for r, k in proxy_line_map.items()}
    proxy_line_map.clear()
    proxy_line_map.update(shifted)
    shifted_copy = {r + _PROXY_HEADER_LINES for r in _proxy_copy_rows}
    _proxy_copy_rows.clear()
    _proxy_copy_rows.update(shifted_copy)
    if _proxy_just_expanded is not None and _proxy_just_expanded in item_positions:
        item_line = item_positions[_proxy_just_expanded]
        max_scroll = max(0, total_lines - viewport_lines_n)
        clamped = min(proxy_scroll_offset, max_scroll)
        start = max(0, total_lines - viewport_lines_n - clamped)
        if item_line < start or item_line >= start + viewport_lines_n:
            proxy_scroll_offset = max(0, total_lines - viewport_lines_n - item_line)
            _proxy_copy_rows.clear()
            body, total_lines = format_proxy_block(
                proxy_entries, proxy_expand_states, proxy_line_map, body_hover,
                content_height, pane_width, proxy_scroll_offset,
                turns=_proxy_cache_turns,
                copy_feedback=_copy_feedback_until, copy_rows_out=_proxy_copy_rows,
                search_match_set=_proxy_search_match_set, search_current_entry_idx=current_match_entry_idx,
                search_query=_proxy_search_query,
            )
            shifted = {r + _PROXY_HEADER_LINES: k for r, k in proxy_line_map.items()}
            proxy_line_map.clear()
            proxy_line_map.update(shifted)
            shifted_copy = {r + _PROXY_HEADER_LINES for r in _proxy_copy_rows}
            _proxy_copy_rows.clear()
            _proxy_copy_rows.update(shifted_copy)
    _proxy_just_expanded = None
    return header + '\n' + body
