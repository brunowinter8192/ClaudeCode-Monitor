# INFRASTRUCTURE
import datetime
import json
import time
from typing import Optional

from ..constants import (
    YELLOW, RED, DIM, WHITE, RESET, HOVER_BG, ZEBRA_BG_A, ZEBRA_BG_B, SOFT_RESET,
    DIM_YELLOW_BG, WARNINGS_POLL_INTERVAL,
)
from ..utils import truncate_visible, first_word_of_call, format_worker_prefix, append_copy_symbol
from ..format.strip_marker import highlight_stripped
INDENT = '  '

# FUNCTIONS

# Build header line showing refresh key, last refresh time, and poll interval
def _format_warnings_header(last_refresh_ts: float) -> str:
    if last_refresh_ts:
        last_dt = datetime.datetime.fromtimestamp(last_refresh_ts)
        last_str = last_dt.strftime('%H:%M:%S')
    else:
        last_str = '--:--:--'
    return f"{DIM}[r]efresh · last: {last_str} · polling: {int(WARNINGS_POLL_INTERVAL)}s{RESET}"


# Render all warning sections; returns (rendered_str, new_error_line_map)
def _format_warnings_pane(
    tool_errors: list,
    error_expand_states: dict,
    error_hover_row,
    error_scroll_offset: int,
    pane_height: int,
    pane_width: int,
    last_refresh_ts: float,
    copy_feedback: Optional[dict] = None,
    copy_rows_out: Optional[set] = None,
) -> tuple:
    header = _format_warnings_header(last_refresh_ts)
    content_height = max(1, pane_height - 1)
    all_lines = []
    # each key is None or ('error', idx)
    all_keys = []
    if copy_rows_out is not None:
        copy_rows_out.clear()

    if tool_errors:
        all_lines.append(f"{RED}TOOL ERRORS ({len(tool_errors)}){SOFT_RESET}")
        all_keys.append(None)
        for err_idx, err in enumerate(tool_errors):
            is_expanded = error_expand_states.get(err_idx, False)
            symbol = '\u25bc' if is_expanded else '\u25b6'
            tool_col = f"{WHITE}{err['tool_name']:<16}{SOFT_RESET}"
            w_prefix = format_worker_prefix(err.get('worker_name', ''))
            inline = first_word_of_call(err['tool_name'], err.get('tool_call_input', {}))
            line = f"{DIM}{symbol} {err['timestamp']}  {w_prefix}{tool_col}  {DIM}{inline}{SOFT_RESET}"
            if copy_feedback is not None:
                is_flash = copy_feedback.get(err_idx, 0) > time.time()
                line = append_copy_symbol(line, '\u2713' if is_flash else '\u2398', pane_width)
            all_lines.append(line)
            all_keys.append(('error', err_idx))
            if is_expanded:
                for k, v in err.get('tool_call_input', {}).items():
                    val_str = str(v).replace('\n', ' ')
                    all_lines.append(f"    {DIM}{k}: {val_str}{SOFT_RESET}")
                    all_keys.append(None)
                pre_strip = err.get('_pre_strip_text')
                chunks = err.get('_stripped_chunks', [])
                raw_text = err['full_text']
                display_text = highlight_stripped(pre_strip, chunks) if pre_strip else raw_text
                for raw_line in display_text.split('\n'):
                    raw_line = raw_line.expandtabs(8)
                    all_lines.append(f"    {DIM}{raw_line}{SOFT_RESET}" if raw_line else '')
                    all_keys.append(None)

    if not tool_errors:
        all_lines.append(f"{DIM}No warnings.{SOFT_RESET}")
        all_keys.append(None)

    new_error_line_map = {}
    header_offset = 2  # row 1 = header, body starts at row 2
    visible_lines = all_lines[error_scroll_offset:error_scroll_offset + content_height]
    visible_keys = all_keys[error_scroll_offset:error_scroll_offset + content_height]
    rendered: list = []
    parent_count = sum(1 for k in all_keys[:error_scroll_offset] if k is not None)
    phys_row = header_offset
    for i, (line, key) in enumerate(zip(visible_lines, visible_keys)):
        if key is not None:
            zebra_bg = ZEBRA_BG_B if parent_count % 2 else ZEBRA_BG_A
            parent_count += 1
        else:
            zebra_bg = ZEBRA_BG_A
        is_hovered = (key is not None and error_hover_row is not None
                      and phys_row == error_hover_row)
        if is_hovered:
            chosen_bg = HOVER_BG
        elif DIM_YELLOW_BG in line:
            chosen_bg = DIM_YELLOW_BG
        else:
            chosen_bg = zebra_bg
        if key is not None:
            key_type, key_idx = key
            if key_type == 'error':
                new_error_line_map[phys_row] = key_idx
                if copy_rows_out is not None and ('⎘' in line or '✓' in line):
                    copy_rows_out.add(phys_row)
        rendered.append(f"{chosen_bg}{truncate_visible(line, pane_width)}\033[K{RESET}")
        phys_row += 1
    return header + '\n' + '\n'.join(rendered), new_error_line_map


# Serialize a warnings-pane entry to full untruncated text for clipboard; key is the bare int error_line_map stores
def _serialize_warnings(key, tool_errors: list) -> str:
    if isinstance(key, int) and 0 <= key < len(tool_errors):
        err = tool_errors[key]
        parts = [err.get('tool_name', '?')]
        inp = err.get('tool_call_input', {})
        if inp:
            parts.append(json.dumps(inp, ensure_ascii=False, indent=2))
        parts.append('')
        parts.append(err.get('full_text', ''))
        return '\n'.join(parts)
    return ''
