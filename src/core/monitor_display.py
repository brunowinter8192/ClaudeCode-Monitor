# INFRASTRUCTURE
from datetime import datetime
import time
from typing import Optional

from ..constants import (
    RESET, GREEN, YELLOW, CYAN,
    SEARCH_MATCH_BG, SEARCH_CURRENT_BG,
    MODE_ALL, MODE_MAIN, MAIN_EVENT_BUFFER_CAP,
)
from ..format.formatter import format_tool_call
from ..utils import truncate_visible, _ANSI_ESCAPE_RE, append_copy_symbol, highlight_query_in_line
# From search_bar.py: shared search-bar mechanics (SearchState, render_search_bar) — rollout
# sub-milestone 2, retrofitting the main pane onto the proxy pane's reference implementation
from .. import search_bar

INDENT = '  '

main_event_buffer: list = []
main_scroll_offset: int = 0
main_hover_row: Optional[int] = None
main_line_map: dict = {}            # phys_row → event_idx into main_event_buffer
_main_copy_rows: dict = {}          # phys_row → (event_idx, 'all') — one copy region per event, same convention every other pane uses
_main_copy_feedback_until: dict = {}  # (event_idx, part) → expiry float
_main_pane_width: int = 80          # updated each render cycle; read by click handler

_SEARCH_BAR_LABEL = 'Search: '  # single source for both the renderer and monitor.py's mouse/col mapping calls

# Search bar state — one search_bar.SearchState instance replaces what used to be 8 flat
# globals (rollout sub-milestone 2, retrofitting onto the proxy pane's reference
# implementation). .matches holds event_idx values, ordered by position in main_event_buffer.
# Enter always re-runs the full match rebuild (proxy's convention — see
# monitor.py::_main_search_on_commit), not gated on query-unchanged, so a repeated Enter picks
# up events appended to the buffer since the last search.
_main_search: search_bar.SearchState = search_bar.SearchState()
_search_match_line_offsets: dict = {}  # event_idx → line_offset within event where query first appears (main-pane-specific, not part of SearchState)
_search_all_line_offsets: dict = {}  # event_idx → first_line_idx in all_lines (for scroll)
_search_total_lines: int = 0         # len(all_lines) from last render (for scroll)

# FUNCTIONS

# Append structured event to buffer; trim oldest if cap exceeded
def _buffer_append(event_type: str, data: dict, call_number=None) -> None:
    global main_event_buffer
    main_event_buffer.append({'type': event_type, 'data': data, 'call_number': call_number})
    if len(main_event_buffer) > MAIN_EVENT_BUFFER_CAP:
        del main_event_buffer[:len(main_event_buffer) - MAIN_EVENT_BUFFER_CAP]

# Truncate line to max length for display (legacy helper, kept for format_warning)
def truncate_line(line: str, max_length: int) -> str:
    if len(line) <= max_length:
        return line
    return line[:max_length] + '...'

# Format WARNING header with yellow color for malformed lines
def format_warning(file_path: str, line_number: int, error_message: str, raw_line: str) -> str:
    now = datetime.now().strftime('%H:%M:%S')
    header = f"{YELLOW}[{now}] [!] WARNING - Malformed JSON{RESET}"
    truncated_line = truncate_line(raw_line, 200)
    details = [
        f"{INDENT}File: {file_path}",
        f"{INDENT}Line: {line_number}",
        f"{INDENT}Error: {error_message}",
        f"{INDENT}Content: {truncated_line}"
    ]
    return f"{header}\n" + '\n'.join(details)

# Buffer warning event
def display_warning(warning: dict) -> None:
    _buffer_append('warning', warning)

# Buffer tool call event
def display_tool_call(tool_call: dict, call_number: int) -> None:
    _buffer_append('tool_call', tool_call, call_number)

# Format buffered event to list of display strings (split by newline)
def _format_event_to_lines(event: dict) -> list:
    t = event['type']
    d = event['data']
    if t == 'tool_call':
        output_data = d['output'] or ''
        formatted = format_tool_call(
            tool_name=d['tool_name'],
            input_data=d['input'],
            output_data=output_data,
            req_num=d.get('req_num', '?'),
            is_subagent=d.get('is_subagent', False),
            is_error=d.get('is_error', False),
        )
    elif t == 'warning':
        formatted = format_warning(d['file_path'], d['line_number'], d['error_message'], d['raw_line'])
    elif t == 'session_banner':
        formatted = f"{CYAN}--- New session detected ---{RESET}"
    else:
        return []
    return formatted.split('\n')

# For each matched event: find the first rendered line containing query; returns {event_idx → line_offset}
# Fallback 0 when query is in serialized text but not in rendered lines (e.g. truncated output section)
def _compute_match_line_offsets(query: str, matches: list) -> dict:
    if not query or not matches:
        return {}
    q = query.lower()
    result = {}
    for event_idx in matches:
        if event_idx < 0 or event_idx >= len(main_event_buffer):
            result[event_idx] = 0
            continue
        lines = _format_event_to_lines(main_event_buffer[event_idx])
        found = 0
        for offset, line in enumerate(lines):
            if q in _ANSI_ESCAPE_RE.sub('', line).lower():
                found = offset
                break
        result[event_idx] = found
    return result


# Case-insensitive substring match against serialized event text; returns (matches, match_set)
def _compute_search_matches(query: str) -> tuple:
    if not query:
        return [], set()
    q = query.lower()
    matches = []
    for event_idx in range(len(main_event_buffer)):
        if q in serialize_main_event(event_idx, 'all').lower():
            matches.append(event_idx)
    return matches, set(matches)

# Render the always-visible search bar (row 1). Thin wrapper binding this pane's own label —
# no click-arrows (n/N replace them, see monitor.py::_jump_search_match) and no HOVER_BG row
# baseline (the shared renderer has none — one visual "search" language across panes).
def _render_search_bar(pane_width: int) -> str:
    return search_bar.render_search_bar(_main_search, pane_width, label=_SEARCH_BAR_LABEL)

# Adjust main_scroll_offset so the current match's first line is visible in the buffer area
def ensure_match_visible() -> None:
    import os
    global main_scroll_offset
    state = _main_search
    if not state.matches or state.current_idx >= len(state.matches):
        return
    target_eidx = state.matches[state.current_idx]
    event_start = _search_all_line_offsets.get(target_eidx)
    if event_start is None:
        return
    target_line = event_start + _search_match_line_offsets.get(target_eidx, 0)
    try:
        term = os.get_terminal_size()
        buffer_height = term.lines - 2  # terminal -1 for safety, -1 for search bar row
    except OSError:
        buffer_height = 48
    new_start = max(0, target_line - 2)  # 2 lines context above match
    main_scroll_offset = max(0, _search_total_lines - buffer_height - new_start)

# Count total rendered lines in main_event_buffer at given pane_width (used by sticky-scroll delta)
def _count_buffer_lines(pane_width: int) -> int:
    total = 0
    for event in main_event_buffer:
        total += len(_format_event_to_lines(event)) + 1  # +1 for blank separator between events
    return total

# Render event buffer to screen-sized string with zebra shading + truncation; fills main_line_map
# Row 1 is the persistent search bar; buffer events render from row 2 onward.
def render_main_buffer(pane_height: int, pane_width: int, scroll_offset: int) -> str:
    global main_line_map, _main_copy_rows, _main_pane_width
    global _search_all_line_offsets, _search_total_lines
    global main_scroll_offset

    state = _main_search
    _main_pane_width = pane_width
    buffer_height = pane_height - 1  # row 1 reserved for search bar

    all_lines = []
    all_event_indices = []  # parallel list: event_idx per line, or -1 for blanks
    _search_all_line_offsets = {}
    for event_idx, event in enumerate(main_event_buffer):
        _search_all_line_offsets[event_idx] = len(all_lines)
        event_lines = _format_event_to_lines(event)
        for el in event_lines:
            all_lines.append(el)
            all_event_indices.append(event_idx)
        all_lines.append('')
        all_event_indices.append(-1)  # blank separator

    _search_total_lines = len(all_lines)

    # Clamp scroll_offset to the real max the renderer can display, and write back to the
    # global — otherwise an over-scroll tick keeps inflating state past what's ever shown,
    # and scroll-down needs to unwind the phantom offset before the display reacts.
    max_scroll = max(0, _search_total_lines - buffer_height)
    if scroll_offset > max_scroll:
        scroll_offset = max_scroll
        main_scroll_offset = max_scroll

    # Clamp current_idx on buffer shrink (matches only populated on Enter commit)
    if state.matches:
        state.current_idx = min(state.current_idx, len(state.matches) - 1)

    current_match_eidx = (
        state.matches[state.current_idx]
        if state.matches and state.current_idx < len(state.matches)
        else None
    )

    total = _search_total_lines
    # scroll_offset=0 → show newest (bottom); increasing offset scrolls up
    start = max(0, total - buffer_height - scroll_offset)
    visible = all_lines[start:start + buffer_height]
    visible_event_indices = all_event_indices[start:start + buffer_height]

    main_line_map.clear()
    _main_copy_rows.clear()
    result_lines = []
    prev_eidx = -2  # sentinel distinct from any real eidx or the -1 blank-separator marker

    for phys_idx, (line, eidx) in enumerate(zip(visible, visible_event_indices)):
        phys_row = phys_idx + 2  # row 1 is search bar; buffer starts at row 2

        # Search highlight: inject BG only around matched substring (per line, ANSI-safe).
        # No per-row background on this pane (row assembly below is a plain trunc+\033[49m) —
        # utils.highlight_query_in_line's default '\033[49m' restore is correct, no sentinel needed.
        if eidx >= 0 and state.match_set and state.query:
            if eidx == current_match_eidx:
                line = highlight_query_in_line(line, state.query, SEARCH_CURRENT_BG)
            elif eidx in state.match_set:
                line = highlight_query_in_line(line, state.query, SEARCH_MATCH_BG)

        # ⎘ copy-button on the first line of an event — part='all', matching what the 'y' key
        # already copies for these rows (serialize_main_event default). tool_call is now ONE
        # block (req N: Tool + params + result), same as every other event type — the old
        # separate REQUEST/RESPONSE two-region special case is gone along with that split.
        # Registered ONLY when the symbol actually fits, so a too-narrow pane never leaves an
        # invisible hit zone.
        if eidx >= 0 and eidx != prev_eidx:
            stripped = _ANSI_ESCAPE_RE.sub('', line)
            is_flash = _main_copy_feedback_until.get((eidx, 'all'), 0) > time.time()
            copy_sym = '✓' if is_flash else '⎘'
            padded = append_copy_symbol(line, copy_sym, pane_width)
            if padded != line:
                line = padded
                _main_copy_rows[phys_row] = (eidx, 'all')

        trunc = truncate_visible(line, pane_width)
        result_lines.append(f"{trunc}\033[49m\033[K{RESET}")
        if eidx >= 0:
            main_line_map[phys_row] = eidx
        prev_eidx = eidx

    bar_line = _render_search_bar(pane_width)
    return f"{bar_line}\033[K{RESET}\n" + '\n'.join(result_lines)

# Serialize a main-pane event to full untruncated text for clipboard. `part` is always 'all' now
# that tool_call is one block (req N: Tool + params + result) — the old 'request'/'response'
# two-region split is gone along with the header pair it copied. Reuses format_tool_call directly
# (ANSI stripped) rather than reconstructing the text a second time, so clipboard content can
# never drift from what the pane actually shows.
def serialize_main_event(event_idx: int, part: str = 'all') -> str:
    if event_idx < 0 or event_idx >= len(main_event_buffer):
        return ''
    event = main_event_buffer[event_idx]
    t = event['type']
    d = event['data']
    if t == 'tool_call':
        formatted = format_tool_call(
            tool_name=d.get('tool_name', '?'),
            input_data=d.get('input', {}),
            output_data=d.get('output', '') or '',
            req_num=d.get('req_num', '?'),
            is_subagent=d.get('is_subagent', False),
            is_error=d.get('is_error', False),
        )
        return _ANSI_ESCAPE_RE.sub('', formatted)
    else:
        return f"[{t}]"

# Print session status after initialization
def print_session_status(session_count: int, project_filter: Optional[str] = None, mode: str = MODE_ALL) -> None:
    if session_count == 0:
        print(f"{YELLOW}No sessions found.{RESET}")
        if project_filter:
            print(f"{YELLOW}Project {project_filter} has no active Claude Code sessions.{RESET}\n")
        else:
            print(f"{YELLOW}No sessions in ~/.claude/projects{RESET}\n")
    else:
        mode_label = ''
        if mode == MODE_MAIN:
            mode_label = ' (main agent only)'
        print(f"{GREEN}Monitoring {session_count} sessions{mode_label}{RESET}")
        if project_filter:
            print(f"{CYAN}Project: {project_filter}{RESET}")
        print(f"{CYAN}Waiting for new tool calls...{RESET}\n")
