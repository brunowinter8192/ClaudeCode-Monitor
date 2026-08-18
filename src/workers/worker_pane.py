# INFRASTRUCTURE
from typing import Dict, List, Optional, Set, Tuple
from pathlib import Path
import hashlib
import os
import time

from ..constants import POLL_INTERVAL, INPUT_POLL_INTERVAL, RESET, ZEBRA_BG_A, ZEBRA_BG_B, HOVER_BG, LIGHT_RED_BG
from ..jsonl import read_new_lines, parse_jsonl_lines, extract_cache_turns
from ..input.click_handler import (
    read_keypress, parse_digit_key, setup_keyboard_input, restore_terminal,
    enable_mouse, disable_mouse, read_mouse_event,
    copy_to_clipboard, wait_for_input,
)
from ..utils import truncate_visible
# From worker_format.py: Worker data extraction and block rendering
from .worker_format import extract_worker_tokens, extract_worker_context_pct, format_workers_block
# From worker_tmux.py: tmux session discovery and status detection
from .worker_tmux import list_workers, find_worker_jsonl
from ..ram_audit import register_ram_dump
# From pane_error_log.py: shared exception-safe pane-error sink
from ..pane_error_log import log_pane_error
# From token_search.py: real-render-based search matcher (turn/call force-expanded content) —
# reused unmodified; workers_pane wraps its output with the worker name (see worker_format.py's
# _scope_matches_to_worker for the inverse operation)
from ..panes.token_search import build_token_search_matches
# From token_format.py: format_cache_tracker's nav_out param, called directly (not through
# format_workers_block) for fresh jump-to-match scroll-position computation
from ..format.token_format import format_cache_tracker
# From search_bar.py: shared search-bar mechanics (state, key/mouse handling, drag-select,
# BG-restore sentinel resolution) — rollout sub-milestone 5, retrofitting the workers pane onto
# the proxy pane's reference implementation
from .. import search_bar

worker_expand_states: Dict[str, bool] = {}
worker_scroll_offsets: Dict[str, int] = {}
worker_line_map: Dict[int, str] = {}
worker_hover_row: Optional[int] = None
worker_cache_expand_states: Dict[str, Dict[tuple, bool]] = {}
worker_cache_line_map: Dict[int, tuple] = {}
worker_selected_name: Optional[str] = None
worker_scroll_offset: int = 0
worker_turns: Dict[str, list] = {}
worker_copy_rows: Set[int] = set()  # phys_rows where ⎘ copy button is rendered; populated by _build_workers_output
_worker_copy_feedback_until: Dict = {}  # name OR (name,turn_idx,call_idx) → expiry timestamp for ✓ flash
_worker_pane_width: int = 80  # updated each render cycle; used by click handler for copy-button column check
_worker_header_regions: Dict[Tuple[int, int, int], str] = {}  # (start_col,end_col,phys_row) → 'freeze'; empty when the header line has scrolled out of view

_WORKERS_SEARCH_BAR_LINES = 1  # fixed-height search bar row; the freeze badge (below it) is separate and conditional
_WORKERS_SEARCH_BAR_LABEL = 'search: '

# Search state — permanent row-1 search bar. .matches holds worker-tagged keys: str name
# (worker-level match), (name,'turn',turn_idx), or (name,turn_idx,call_idx) — see
# _workers_search_on_commit. No worker-switch reset analog exists for this pane (unlike the
# proxy/worker-proxy/tokens panes, each tracking exactly one current session/worker) — this pane
# shows ALL workers simultaneously; jump-to-match self-heals by re-parsing fresh at jump time
# (see _jump_to_workers_match), so a stale match referencing a since-vanished worker just
# becomes an inert no-op rather than showing wrong data.
_worker_search: search_bar.SearchState = search_bar.SearchState()

# ORCHESTRATOR

# Runs workers display loop (for dedicated workers tmux pane)
def run_workers_loop() -> None:
    from ..core import monitor as _monitor
    global worker_expand_states, worker_scroll_offsets, worker_line_map, worker_hover_row, worker_cache_expand_states, worker_cache_line_map, worker_selected_name, worker_scroll_offset, worker_turns, _worker_copy_feedback_until

    register_ram_dump('workers', _workers_ram_state)
    last_output = None
    workers: list = []
    worker_turns.clear()
    last_data_refresh = 0.0
    frozen = False
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
                            changed, frozen = _handle_workers_mouse(
                                *event, _monitor.active_project_filter, frozen)
                            if changed:
                                input_changed = True
                        elif event is not None:
                            # (-1,-1,-1) release sentinel — no-op unless a row-1 drag was active
                            if _handle_workers_search_release():
                                input_changed = True
                        elif _worker_search.focused:  # bare ESC → cancel search
                            if _handle_workers_search_cancel():
                                input_changed = True
                    elif _worker_search.focused:
                        if _handle_workers_search_input(char, workers, _monitor.active_project_filter):
                            input_changed = True
                    elif char == '/':
                        _worker_search.focused = True
                        input_changed = True
                    elif char in ('n', 'N'):
                        if _jump_workers_search_match(char == 'n', workers, _monitor.active_project_filter):
                            input_changed = True
                    else:
                        changed, frozen = _handle_workers_key(
                            char, workers, frozen, _monitor.active_project_filter)
                        if changed:
                            input_changed = True

                now = time.time()
                workers, input_changed, last_data_refresh = _refresh_workers_data(
                    workers, now, frozen, input_changed, last_data_refresh,
                    _monitor.active_project_filter,
                )

                _worker_copy_feedback_until = {k: v for k, v in _worker_copy_feedback_until.items() if v > now}
                if _worker_copy_feedback_until:
                    input_changed = True

                if input_changed:
                    output = _build_workers_output(workers, frozen)
                    if output != last_output:
                        print("\033[2J\033[3J\033[H", end='', flush=True)
                        if output:
                            print(output)
                        last_output = output

                wait_for_input(INPUT_POLL_INTERVAL)
            except Exception:
                log_pane_error('workers')
                wait_for_input(INPUT_POLL_INTERVAL)
    finally:
        disable_mouse()
        restore_terminal()

# FUNCTIONS

# Build path to the selection IPC file for the given project (shared with proxy pane)
def get_selection_file_path(project_filter: Optional[str]) -> str:
    if project_filter:
        normalized = os.path.normpath(os.path.expanduser(project_filter))
        project_hash = hashlib.md5(normalized.encode()).hexdigest()[:8]
    else:
        project_hash = 'global'
    return f"/tmp/monitor_cc_selected_worker_{project_hash}.txt"

# Write selected worker name to IPC selection file
def _write_selection(project_filter: Optional[str], name: Optional[str]) -> None:
    path = get_selection_file_path(project_filter)
    try:
        if name:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(name)
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

# Serialize a worker entry to full untruncated text for clipboard
def _serialize_workers(key) -> str:
    import json
    if isinstance(key, tuple):
        # Cache call: (worker_name, turn_idx, call_idx)
        w_name, t_idx, c_idx = key
        turns = worker_turns.get(w_name, [])
        if t_idx >= len(turns):
            return ''
        turn = turns[t_idx]
        calls = turn.get('api_calls', [])
        if c_idx >= len(calls):
            return ''
        call = calls[c_idx]
        parts = [f"Worker: {w_name}  Turn {t_idx + 1}, Call {c_idx + 1}  CR:{call.get('cache_read', 0)}  CC:{call.get('cache_creation', 0)}  D:{call.get('direct', 0)}  out:{call.get('output_tokens', 0)}"]
        for blk in call.get('content_blocks', []):
            btype = blk.get('type', '')
            if btype == 'tool_use':
                tool_name = blk.get('tool_name', 'Unknown')
                inp = blk.get('preview', {})
                parts.append(f"\n--- tool_use: {tool_name} ---")
                parts.append(json.dumps(inp, ensure_ascii=False, indent=2))
            elif btype == 'text':
                parts.append(f"\n--- text ---")
                parts.append(blk.get('preview', ''))
        return '\n'.join(parts)
    else:
        # Worker name — serialize status info from current workers list
        # worker_turns holds the turns for this worker; we just emit identity info
        name = str(key)
        turns = worker_turns.get(name, [])
        n_turns = len(turns)
        n_calls = sum(len(t.get('api_calls', [])) for t in turns)
        return f"Worker: {name}\nTurns: {n_turns}  API calls: {n_calls}"

# Return module-level state snapshot for RAM audit
def _workers_ram_state() -> list:
    return [
        ('worker_expand_states',       worker_expand_states),
        ('worker_scroll_offsets',      worker_scroll_offsets),
        ('worker_line_map',            worker_line_map),
        ('worker_cache_expand_states', worker_cache_expand_states),
        ('worker_cache_line_map',      worker_cache_line_map),
        ('worker_turns',               worker_turns),
        ('worker_hover_row',           str(worker_hover_row)),
        ('worker_selected_name',       str(worker_selected_name)),
        ('worker_scroll_offset',       worker_scroll_offset),
        ('_worker_search_query',       _worker_search.query),
        ('_worker_search_matches',     _worker_search.matches),
    ]

# Process one mouse event; returns (input_changed, updated_frozen)
def _handle_workers_mouse(button: int, col: int, row: int, project_filter: Optional[str], frozen: bool) -> tuple:
    global worker_hover_row, worker_selected_name, _worker_copy_feedback_until
    if button == 0:
        if row == 1:  # search bar row — focuses; also anchors a potential drag-select
            return search_bar.handle_search_mouse_press(_worker_search, col, _WORKERS_SEARCH_BAR_LABEL), frozen
        # Click elsewhere (freeze badge, cache row, worker row, or unmapped) clears any
        # lingering drag-selection highlight
        had_selection = _worker_search.sel_anchor is not None
        search_bar.clear_selection(_worker_search)
        for (sc, ec, er), action in _worker_header_regions.items():
            if row == er and sc <= col <= ec:
                if action == 'freeze':
                    return True, not frozen
                return had_selection, frozen
        is_copy_click = col >= _worker_pane_width - 2 and row in worker_copy_rows
        cache_key = worker_cache_line_map.get(row)
        if cache_key:
            if is_copy_click:
                copy_to_clipboard(_serialize_workers(cache_key))
                _worker_copy_feedback_until[cache_key] = time.time() + 1.5
                return True, frozen
            w_name, t_idx, c_idx = cache_key
            states = worker_cache_expand_states.setdefault(w_name, {})
            states[(t_idx, c_idx)] = not states.get((t_idx, c_idx), False)
            return True, frozen
        name = worker_line_map.get(row)
        if name:
            if is_copy_click:
                copy_to_clipboard(_serialize_workers(name))
                _worker_copy_feedback_until[name] = time.time() + 1.5
                return True, frozen
            is_now_expanded = not worker_expand_states.get(name, False)
            worker_expand_states[name] = is_now_expanded
            if is_now_expanded:
                worker_scroll_offsets[name] = 0
            worker_selected_name = name
            _write_selection(project_filter, name)
            return True, frozen
        return had_selection, frozen
    if button in (64, 65):
        w_name = None
        cache_hit = worker_cache_line_map.get(row)
        if cache_hit is not None:
            w_name = cache_hit[0]
        else:
            map_hit = worker_line_map.get(row)
            if map_hit is not None:
                w_name = map_hit
            else:
                w_name = worker_selected_name
        if w_name is not None:
            current = worker_scroll_offsets.get(w_name, 0)
            delta = 3 if button == 64 else -3
            worker_scroll_offsets[w_name] = max(0, current + delta)
            return True, frozen
        return False, frozen
    if button == 32 and _worker_search.dragging:  # motion with left button held (0+32), row-1 drag active
        return search_bar.handle_search_mouse_motion(_worker_search, col, _WORKERS_SEARCH_BAR_LABEL), frozen
    if button >= 32:
        worker_hover_row = row
        return True, frozen
    return False, frozen

# Resolve the copyable key at/above hover_row, preferring whichever of worker_cache_line_map /
# worker_line_map has the CLOSER ancestor row — a plain worker_line_map-first fallback would
# always shadow a cache-row hover (its backward search never stops at cache rows, so it always
# finds the owning worker's header first), making the cache-map fallback unreachable
def _resolve_workers_hover_key(hover_row: Optional[int]):
    if hover_row is None:
        return None
    cache_row = worker_row = None
    for r in range(hover_row, 0, -1):
        if cache_row is None and r in worker_cache_line_map:
            cache_row = r
        if worker_row is None and r in worker_line_map:
            worker_row = r
        if cache_row is not None and worker_row is not None:
            break
    if cache_row is not None and (worker_row is None or cache_row > worker_row):
        return worker_cache_line_map[cache_row]
    return worker_line_map.get(worker_row)

# Process one non-escape key event; returns (input_changed, updated_frozen)
def _handle_workers_key(char: str, workers: list, frozen: bool, project_filter: Optional[str]) -> tuple:
    global worker_selected_name
    if char == 'y':
        key = _resolve_workers_hover_key(worker_hover_row)
        if key is not None:
            copy_to_clipboard(_serialize_workers(key))
        return False, frozen
    if char == 'f':
        return True, not frozen
    idx = parse_digit_key(char)
    if idx is not None and 1 <= idx <= len(workers):
        name = workers[idx - 1]['name']
        is_now_expanded = not worker_expand_states.get(name, False)
        worker_expand_states[name] = is_now_expanded
        if is_now_expanded:
            worker_scroll_offsets[name] = 0
        worker_selected_name = name
        _write_selection(project_filter, name)
        return True, frozen
    return False, frozen

# Cancel active search on bare ESC while focused; bar stays visible with an empty query.
# Thin wrapper — search_bar.handle_search_cancel resets query/focused/matches/match_set/
# selection all at once, identical across every pane.
def _handle_workers_search_cancel() -> bool:
    return search_bar.handle_search_cancel(_worker_search)

# Handle keyboard input while the search bar is focused; returns True if input_changed. Thin
# wrapper over search_bar.handle_search_input — on_commit is a closure binding this tick's
# `workers` list and `project_filter` (search_bar's generic on_commit signature only ever
# passes `state`, so the extra context this pane needs is captured here, not threaded through
# search_bar.py itself).
def _handle_workers_search_input(char: str, workers: list, project_filter: Optional[str]) -> bool:
    on_commit = lambda state: _workers_search_on_commit(state, workers, project_filter)
    return search_bar.handle_search_input(_worker_search, char, on_commit=on_commit)

# on_commit callback for search_bar.handle_search_input (fires on Enter): the FIRST pane
# needing a genuine reconstruction step — worker_turns is only populated for currently-EXPANDED
# workers (see _refresh_workers_data), so finding matches across ALL workers requires
# force-parsing every listed worker's own JSONL here (measured ~200ms for 9 real, multi-MB
# session files — comfortably under budget, see process-docs/pane_search/). Three match-key
# shapes: bare `name` (worker-level — text is name+purpose), `(name,'turn',turn_idx)`, and
# `(name,turn_idx,call_idx)` — the latter two wrap token_search.build_token_search_matches'
# own (reused unmodified) ('turn',idx)/(turn_idx,call_idx) shapes with the worker name.
# Freshly-parsed turns are merged into worker_turns for every MATCHED worker (not every worker
# swept) so the render step has data ready the moment a match's worker gets auto-expanded.
def _workers_search_on_commit(state: search_bar.SearchState, workers: list, project_filter: Optional[str]) -> None:
    if not state.query:
        state.matches = []
        state.match_set = set()
        return
    q = state.query.lower()
    matches: list = []
    fresh_turns: dict = {}
    for w in workers:
        name = w.get('name', '')
        if not name:
            continue
        purpose = w.get('purpose', '') or ''
        if q in f"{name} {purpose}".lower():
            matches.append(name)
        jsonl_path = find_worker_jsonl(w.get('session', ''))
        if jsonl_path is None:
            continue
        lines = read_new_lines(jsonl_path, 0)
        messages, _ = parse_jsonl_lines(lines)
        turns = extract_cache_turns(messages)
        fresh_turns[name] = turns
        for key in build_token_search_matches(state.query, turns, _worker_pane_width - 4):
            matches.append((name, 'turn', key[1]) if key[0] == 'turn' else (name, key[0], key[1]))
    state.matches = matches
    state.match_set = set(matches)
    state.current_idx = 0
    matched_names = {m if isinstance(m, str) else m[0] for m in matches}
    for name in matched_names:
        if name in fresh_turns:
            worker_turns[name] = fresh_turns[name]
    if matches:
        _jump_to_workers_match(workers, project_filter)

# Jump to the next (forward=True) or previous search match, wrapping around; returns True if
# a jump happened (False when there are no matches, e.g. before the first Enter)
def _jump_workers_search_match(forward: bool, workers: list, project_filter: Optional[str]) -> bool:
    if not _worker_search.matches:
        return False
    _worker_search.current_idx = (_worker_search.current_idx + (1 if forward else -1)) % len(_worker_search.matches)
    _jump_to_workers_match(workers, project_filter)
    return True

# Auto-expand + auto-select the current match's worker (uniform across all 3 match levels — a
# worker-level match still benefits from seeing that worker's activity, mirrors proxy's own
# jump-auto-expand). Deliberately NEVER touches worker_scroll_offset (the dormant pane-level
# bottom-anchor fail-safe — see worker_pane.py's own Gotcha); if the matched worker is scrolled
# off the top of a long list, that's the same pre-existing limitation that already prevents any
# other means of reaching it (no wheel-scroll-up exists for the outer list either).
# Self-healing: ALWAYS re-parses the target worker's JSONL fresh at jump time rather than
# trusting worker_turns (which _refresh_workers_data clears every poll tick for any worker not
# yet expand-gated) — a match found at Enter-time for a worker not jumped to yet would
# otherwise have its cached turns evicted before a later n/N reaches it.
def _jump_to_workers_match(workers: list, project_filter: Optional[str]) -> None:
    global worker_selected_name
    state = _worker_search
    if not state.matches or state.current_idx >= len(state.matches):
        return
    key = state.matches[state.current_idx]
    name = key if isinstance(key, str) else key[0]
    worker_expand_states[name] = True
    worker_selected_name = name
    _write_selection(project_filter, name)
    w = next((w for w in workers if w.get('name') == name), None)
    if w is None:
        return  # worker vanished between match and jump — self-healing no-op, not a crash
    jsonl_path = find_worker_jsonl(w.get('session', ''))
    if jsonl_path is None:
        return
    lines = read_new_lines(jsonl_path, 0)
    messages, _ = parse_jsonl_lines(lines)
    turns = extract_cache_turns(messages)
    worker_turns[name] = turns
    if isinstance(key, str):
        return  # worker-level match — nothing further to scroll to within the nested view
    target_key = ('turn', key[2]) if key[1] == 'turn' else (key[1], key[2])
    per_worker_expand = worker_cache_expand_states.get(name, {})
    nav: dict = {}
    format_cache_tracker(turns, per_worker_expand, 15, _worker_pane_width - 4, 0, nav_out=nav)
    target_line = nav.get(target_key)
    total_lines = nav.get('total_lines')
    if target_line is None or total_lines is None:
        return
    viewport_lines = max(1, 15 - 1)  # mirrors format_cache_tracker's own internal -1, against the fixed nested-view height (15) format_workers_block always passes
    new_start = max(0, target_line - 2)  # 2 lines context above match
    worker_scroll_offsets[name] = max(0, total_lines - viewport_lines - new_start)

# Finalize a row-1 drag on SGR mouse release; returns True if a redraw is needed. No-op (False)
# unless a row-1 drag was actually in progress. Thin wrapper — release-copies-to-clipboard is
# identical across every pane.
def _handle_workers_search_release() -> bool:
    return search_bar.handle_search_mouse_release(_worker_search, copy_to_clipboard)

# Render the always-visible search bar (row 1). Thin wrapper binding this pane's own label.
def _render_workers_search_bar(pane_width: int) -> str:
    return search_bar.render_search_bar(_worker_search, pane_width, label=_WORKERS_SEARCH_BAR_LABEL)

# Tick-boundary worker data refresh; returns (workers, input_changed, new_last_data_refresh)
def _refresh_workers_data(workers: list, now: float, frozen: bool, input_changed: bool,
                           last_data_refresh: float, project_filter: Optional[str]) -> tuple:
    global worker_turns, worker_selected_name
    if not frozen and now - last_data_refresh >= POLL_INTERVAL:
        workers = list_workers(project_filter) if project_filter else []
        if worker_selected_name is None and workers:
            worker_selected_name = workers[0]['name']
            _write_selection(project_filter, worker_selected_name)
        worker_turns.clear()
        for w in workers:
            name = w.get('name', '')
            jsonl_path = find_worker_jsonl(w.get('session', ''))
            if jsonl_path:
                w['tokens'] = extract_worker_tokens(jsonl_path)
                w['context_pct'] = extract_worker_context_pct(jsonl_path)
                if worker_expand_states.get(name, False):
                    lines = read_new_lines(jsonl_path, 0)
                    messages, _ = parse_jsonl_lines(lines)
                    worker_turns[name] = extract_cache_turns(messages)
        return workers, True, now
    if input_changed:
        for w in workers:
            name = w.get('name', '')
            if worker_expand_states.get(name, False) and name not in worker_turns:
                jsonl_path = find_worker_jsonl(w.get('session', ''))
                if jsonl_path:
                    lines = read_new_lines(jsonl_path, 0)
                    messages, _ = parse_jsonl_lines(lines)
                    worker_turns[name] = extract_cache_turns(messages)
    return workers, input_changed, last_data_refresh

# Format, clip viewport, and render workers to ANSI string; updates worker_line_map and worker_cache_line_map
def _build_workers_output(workers: list, frozen: bool) -> str:
    global worker_scroll_offset, worker_copy_rows, _worker_pane_width, _worker_header_regions
    _worker_freeze_span: dict = {}
    current_match_key = (
        _worker_search.matches[_worker_search.current_idx]
        if _worker_search.matches and _worker_search.current_idx < len(_worker_search.matches)
        else None
    )
    all_lines, line_keys = format_workers_block(
        workers, worker_expand_states, worker_turns,
        worker_scroll_offsets, worker_cache_expand_states,
        frozen=frozen, selected_name=worker_selected_name,
        copy_feedback=_worker_copy_feedback_until,
        regions_out=_worker_freeze_span,
        search_match_set=_worker_search.match_set, search_current_key=current_match_key,
        search_query=_worker_search.query,
    )
    try:
        term = os.get_terminal_size()
        pane_width = term.columns
        pane_height = term.lines
    except OSError:
        pane_width = 80
        pane_height = 50
    _worker_pane_width = pane_width
    content_height = pane_height - _WORKERS_SEARCH_BAR_LINES  # search bar always wins row 1
    # Viewport clipping: phys_row (1+_WORKERS_SEARCH_BAR_LINES)..N must equal terminal row
    # (1+_WORKERS_SEARCH_BAR_LINES)..N. worker_scroll_offset > 0 shifts viewport toward older
    # content (dormant in practice — see this module's own Gotcha in workers/DOCS.md).
    total_lines = len(all_lines)
    max_offset = max(0, total_lines - content_height)
    worker_scroll_offset = min(worker_scroll_offset, max_offset)
    vp_start = max(0, total_lines - content_height - worker_scroll_offset)
    visible_all = all_lines[vp_start:vp_start + content_height]
    visible_keys = line_keys[vp_start:vp_start + content_height]
    worker_line_map.clear()
    worker_cache_line_map.clear()
    worker_copy_rows.clear()
    # Freeze badge is always all_lines[0] — only clickable when it survived viewport clipping
    # (vp_start == 0 AND at least one line is visible; a scrolled-away header registers nothing,
    # never a stale/wrong-row region). Row shifted by _WORKERS_SEARCH_BAR_LINES since the search
    # bar now owns physical row 1.
    _worker_header_regions.clear()
    if 'freeze' in _worker_freeze_span and vp_start == 0 and visible_all:
        sc, ec = _worker_freeze_span['freeze']
        _worker_header_regions[(sc, ec, 1 + _WORKERS_SEARCH_BAR_LINES)] = 'freeze'
    result_lines = [_render_workers_search_bar(pane_width)]
    phys_row = 1 + _WORKERS_SEARCH_BAR_LINES
    parent_count = sum(1 for k in line_keys[:vp_start] if isinstance(k, str))
    for line, key in zip(visible_all, visible_keys):
        if isinstance(key, str):
            zebra_bg = ZEBRA_BG_B if parent_count % 2 else ZEBRA_BG_A
            parent_count += 1
        else:
            zebra_bg = ZEBRA_BG_A
        is_hovered = (key is not None and worker_hover_row is not None
                      and phys_row == worker_hover_row)
        if is_hovered:
            chosen_bg = HOVER_BG
        elif LIGHT_RED_BG in line:  # substring, not prefix — a search-match wrap may now precede it
            chosen_bg = LIGHT_RED_BG
        else:
            chosen_bg = zebra_bg
        line = search_bar.resolve_bg_restore(line, chosen_bg)
        if key is not None and ('⎘' in line or '✓' in line):
            worker_copy_rows.add(phys_row)
        trunc = truncate_visible(line, pane_width)
        result_lines.append(f"{chosen_bg}{trunc}\033[K{RESET}")
        if isinstance(key, str):
            worker_line_map[phys_row] = key
        elif isinstance(key, tuple):
            worker_cache_line_map[phys_row] = key
        phys_row += 1
    return '\n'.join(result_lines)
