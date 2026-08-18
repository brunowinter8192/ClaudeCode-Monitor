"""
p5_worker_proxy_pane_parity_test.py — Regression guard for the worker-proxy pane reaching
search-bar parity with the proxy pane (rollout sub-milestone 3, process-docs/pane_search/).

worker_proxy_pane.py is the proxy pane's closest structural twin — same format_proxy_block/
render_turn pipeline (search kwargs already threaded through, previously defaulted off for this
pane specifically), same forwarded-log data model, same one-sweep reconstruct_all_messages
strategy, same flow_id-fixed _lazy_load_messages_forwarded. The NEW work this milestone covers:

  - 2-ROW HEADER: the search bar takes row 1 (uniform rule); the existing worker-switcher header
    (_format_worker_proxy_header, variable height, click-region table) shifts to row 2+.
    _worker_proxy_header_regions (rows relative to the header's OWN top, computed by the pure
    helper worker_proxy_helpers.py — untouched) get shifted by +_WP_SEARCH_BAR_LINES in
    _build_worker_proxy_output, same rebuild-then-shift pattern already used for
    worker_proxy_line_map/_worker_proxy_copy_rows. content_height/body_hover use
    total_header_lines = _WP_SEARCH_BAR_LINES + worker_header_lines, not the old header_lines
    alone.
  - row-1 press/motion/release drag-select, editor-style deletion (selection-delete Backspace,
    kill-line), n/N jump reusing the EXISTING _wp_just_expanded/worker_item_positions/
    scroll-clamp mechanism (same anchor for collapsed and expanded matches)
  - Enter (_worker_proxy_search_on_commit) always re-runs (no unchanged-query gate — proxy's
    convention, no main-pane-style gate ever existed here to correct); one-sweep
    reconstruct_all_messages merge by flow_id when _worker_proxy_log_path is set
  - WORKER-SWITCH RESET: _refresh_worker_proxy_data's existing worker-change branch (fires for
    BOTH digit-key and header-marker selection, same selection-file + force_reload convergence
    point) now also calls search_bar.handle_search_cancel(_worker_proxy_search) — mirrors
    pane.py's session-change reset and the same fix just landed on the main pane. A stale
    .matches list of entry_idx values would otherwise point into the log just switched away
    from.

Uses REAL src.proxy_display.worker_proxy_pane functions against synthetic entries/workers —
not mocks. importlib.import_module used throughout (dev/ scripts may not use a literal
'from src.' import line).

Run: ./venv/bin/python dev/pane_search/p5_worker_proxy_pane_parity_test.py
"""

# INFRASTRUCTURE
import importlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT))
os.environ.setdefault('MONITOR_CC_ROOT', str(WORKTREE_ROOT))

_ROOT_PKG = 'src'
mod_wp = importlib.import_module(f'{_ROOT_PKG}.proxy_display.worker_proxy_pane')
mod_search_bar = importlib.import_module(f'{_ROOT_PKG}.search_bar')

PANE_WIDTH = 100
_RESULTS = []


def check(label, condition):
    _RESULTS.append((label, bool(condition)))
    status = 'PASS' if condition else 'FAIL'
    print(f"  {status}  {label}")
    return condition


class _FakeMonitor:
    active_project_filter = 'proj'


# FUNCTIONS

# Synthetic worker-proxy entry — same shape as p2/p3's _make_entry (proxy pane fixtures),
# required by build_search_matches/_render_req_expanded regardless of which pane calls them.
def _make_wp_entry(idx: int, marker: str = None, model: str = 'claude-sonnet') -> dict:
    marker_text = marker or f'unique_marker_{idx}'
    messages = [{'role': 'user', 'type': 'text', 'chars': 10, 'blocks': []} for _ in range(idx)]
    messages.append({
        'role': 'user', 'type': 'text', 'chars': len(marker_text),
        'blocks': [{'type': 'text', 'chars': len(marker_text), 'preview': marker_text, 'full_text': marker_text, 'has_cc': False}],
    })
    return {
        'model': model, 'message_count': idx + 1, 'flow_id': f'flow-{idx}', 'cache_breakpoints': [],
        'system_total_chars': 10000, 'tools_total_chars': 5000, 'messages_total_chars': 3000,
        'tools_count': 1, 'tools_hash': f'hash{idx}', 'tools_names': ['tool_a'],
        'tools_defs': [{'name': 'tool_a', 'description': 'd', 'input_schema': {}, 'stripped_original': None}],
        'system_blocks': [{'idx': 0, 'chars': 3, 'preview': 'sys', 'has_cc': False}],
        'messages': messages,
        'schema_warnings': [], 'stripped_msg_indices': [], 'modifications': [],
        'anthropic_beta': [], 'context_management': None, 'diagnostics': None,
        'effort_value': None, 'max_tokens': 0,
        'diff_from_prev': {'messages_added': 1},
        'timestamp': f'2026-04-21T10:{idx:02d}:00Z',
    }


def _reset_state(query: str = ''):
    mod_wp.worker_proxy_entries.clear()
    mod_wp.worker_proxy_expand_states.clear()
    mod_wp.worker_proxy_line_map.clear()
    mod_wp.worker_proxy_hover_row = None
    mod_wp.worker_proxy_scroll_offset = 0
    mod_wp._worker_proxy_pane_width = PANE_WIDTH
    mod_wp._worker_proxy_workers = []
    mod_wp._worker_proxy_header_regions.clear()
    mod_wp._worker_proxy_copy_rows.clear()
    mod_wp._worker_proxy_log_path = None
    mod_wp._wp_just_expanded = None
    mod_wp._worker_proxy_force_reload = False
    mod_wp._worker_proxy_last_worker_name = None
    mod_wp._worker_proxy_search.query = query
    mod_wp._worker_proxy_search.focused = False
    mod_wp._worker_proxy_search.matches = []
    mod_wp._worker_proxy_search.match_set = set()
    mod_wp._worker_proxy_search.current_idx = 0
    mod_search_bar.clear_selection(mod_wp._worker_proxy_search)


def _click(button, col, row):
    return mod_wp._handle_worker_proxy_mouse(button, col, row, _FakeMonitor())


def _capture_clipboard():
    captured = []
    orig = mod_wp.copy_to_clipboard
    mod_wp.copy_to_clipboard = lambda text: captured.append(text)
    return captured, orig


# Runs _build_worker_proxy_output with a real (temp-file-backed) selection, monkeypatching only
# get_selection_file_path — every other real function (format_proxy_block, _format_worker_proxy_header, ...) runs unmocked.
def _build_output_with_worker(worker_name):
    tmp_dir = Path(tempfile.mkdtemp(prefix='pane_search_p5_sel_'))
    sel_path = tmp_dir / 'selection.txt'
    if worker_name is not None:
        sel_path.write_text(worker_name, encoding='utf-8')
    orig = mod_wp.get_selection_file_path
    mod_wp.get_selection_file_path = lambda pf: sel_path
    try:
        return mod_wp._build_worker_proxy_output(_FakeMonitor())
    finally:
        mod_wp.get_selection_file_path = orig
        shutil.rmtree(tmp_dir, ignore_errors=True)


# Build a synthetic forwarded_delta JSONL line (mirrors p2_search_feature_regression_test.py's
# _fwd_line — same fixture shape, reconstruct_all_messages is the shared function under test)
def _fwd_line(flow_id: str, model: str, is_first: bool, msg_text: str) -> str:
    entry = {
        'type': 'forwarded_delta', 'request_id': '', 'timestamp': datetime.now(timezone.utc).isoformat(),
        'model': model, 'max_tokens': 100, 'output_config': None, 'context_management': None,
        'diagnostics': None, 'is_first': is_first,
        'counts': {'system': 0, 'tools': 0, 'messages': 1},
        'system_delta': {}, 'tools_delta': {},
        'messages_delta': {'0': {'role': 'user', 'content': msg_text}},
        'flow_id': flow_id,
    }
    return json.dumps(entry)


# TESTS

def test_state_shape():
    print("\n[shape] Worker-proxy search state is one search_bar.SearchState, lowercase label")
    check("_worker_proxy_search is a search_bar.SearchState instance",
          isinstance(mod_wp._worker_proxy_search, mod_search_bar.SearchState))
    check("label matches the proxy pane's ('search: ', this pane's structural twin)",
          mod_wp._WP_SEARCH_BAR_LABEL == 'search: ')
    check("search bar is fixed 1-line", mod_wp._WP_SEARCH_BAR_LINES == 1)


def test_two_row_header_composition_and_shifts():
    print("\n[2-row header] Search bar row 1, worker-switcher header shifted to row 2+; "
          "header_regions and line_map both account for the search bar row")
    _reset_state()
    mod_wp._worker_proxy_workers = [{'name': 'alpha', 'session': ''}, {'name': 'beta', 'session': ''}]
    mod_wp.worker_proxy_entries.extend(_make_wp_entry(i) for i in range(3))
    output, header = _build_output_with_worker('alpha')
    lines = header.splitlines()
    check("row 1 (search bar) contains the label", 'search:' in lines[0])
    check("row 1 has no click-arrows", '[<-]' not in lines[0] and '[->]' not in lines[0]
          and '[←]' not in lines[0] and '[→]' not in lines[0])
    check("worker-switcher header text appears on a LATER line, not row 1",
          any('WORKER-PROXY' in l for l in lines[1:]))
    check("row 1 is not a body line_map key", mod_wp.worker_proxy_line_map.get(1) is None)
    check("row 2 (worker header) is not a body line_map key either",
          mod_wp.worker_proxy_line_map.get(2) is None)
    check("all header-region rows are >= 2 (shifted past the search bar row)",
          bool(mod_wp._worker_proxy_header_regions) and
          all(er >= 2 for (_sc, _ec, er) in mod_wp._worker_proxy_header_regions))
    check("all body line_map rows are past BOTH header rows (search bar + 1-line worker header)",
          all(r >= 3 for r in mod_wp.worker_proxy_line_map))


def test_header_marker_click_still_selects_worker_at_shifted_row():
    print("\n[header click] A click on the (now row-2+) worker marker still selects that worker")
    _reset_state()
    mod_wp._worker_proxy_workers = [{'name': 'alpha', 'session': ''}]
    mod_wp.worker_proxy_entries.extend(_make_wp_entry(i) for i in range(2))
    _build_output_with_worker('alpha')
    check("region exists and is at a shifted (>=2) row", bool(mod_wp._worker_proxy_header_regions))
    (sc, ec, er), name = next(iter(mod_wp._worker_proxy_header_regions.items()))
    check("marker region row is 2 (single-line worker header, right after the search bar)", er == 2)
    captured = []
    orig_write_selection = mod_wp.write_selection
    mod_wp.write_selection = lambda pf, n: captured.append(n)
    try:
        changed = _click(0, sc, er)
    finally:
        mod_wp.write_selection = orig_write_selection
    check("header-marker click at the shifted row selects the worker", changed and captured == [name])
    check("force_reload set", mod_wp._worker_proxy_force_reload is True)


def test_row1_press_focuses_and_arms_drag():
    print("\n[press] A row-1 click focuses the bar and anchors a drag-select")
    _reset_state('hello world')
    label = mod_wp._WP_SEARCH_BAR_LABEL
    changed = _click(0, len(label) + 2, 1)
    check("press returns True (redraw)", changed)
    check("press focuses the bar", mod_wp._worker_proxy_search.focused is True)
    check("press arms dragging", mod_wp._worker_proxy_search.dragging is True)
    check("press anchors at index 1 ('e')",
          mod_wp._worker_proxy_search.sel_anchor == mod_wp._worker_proxy_search.sel_end == 1)


def test_drag_select_copies_to_clipboard():
    print("\n[drag flow] press -> motion -> release copies the selected substring")
    _reset_state('hello world')
    captured, orig = _capture_clipboard()
    try:
        label = mod_wp._WP_SEARCH_BAR_LABEL
        _click(0, len(label) + 2, 1)
        motion_changed = _click(32, len(label) + 7, 1)
        check("motion extends sel_end only", motion_changed and mod_wp._worker_proxy_search.sel_end == 6)
        release_changed = mod_wp._handle_worker_proxy_search_release()
        check("release returns True (redraw)", release_changed)
        check("release disarms dragging", mod_wp._worker_proxy_search.dragging is False)
        check("release copies exactly the selected substring", captured == ['ello '])
    finally:
        mod_wp.copy_to_clipboard = orig


def test_plain_click_no_motion_no_clipboard():
    print("\n[plain click] press+release with NO motion makes zero clipboard calls")
    _reset_state('hello world')
    captured, orig = _capture_clipboard()
    try:
        label = mod_wp._WP_SEARCH_BAR_LABEL
        _click(0, len(label) + 3, 1)
        release_changed = mod_wp._handle_worker_proxy_search_release()
        check("release still returns True (dragging disarmed)", release_changed)
        check("NO clipboard call on a plain click", captured == [])
        check("selection cleared after a plain click",
              mod_wp._worker_proxy_search.sel_anchor is None and mod_wp._worker_proxy_search.sel_end is None)
    finally:
        mod_wp.copy_to_clipboard = orig


def test_release_noop_without_active_drag():
    print("\n[release no-op] A release with no prior row-1 press changes nothing")
    _reset_state('hello world')
    changed = mod_wp._handle_worker_proxy_search_release()
    check("release with no armed drag returns False", changed is False)


def test_body_row_click_clears_selection():
    print("\n[clear] Click on the buffer area (row >= 2, unmapped) clears a live drag-selection")
    _reset_state('hello world')
    label = mod_wp._WP_SEARCH_BAR_LABEL
    _click(0, len(label) + 1, 1)
    _click(32, len(label) + 5, 1)
    mod_wp._handle_worker_proxy_search_release()
    check("selection exists before the elsewhere-click", mod_wp._worker_proxy_search.sel_anchor is not None)
    changed = _click(0, 5, 10)  # unmapped body row, no header regions registered
    check("elsewhere-click reports a change (selection cleared)", changed)
    check("selection cleared after clicking elsewhere",
          mod_wp._worker_proxy_search.sel_anchor is None and mod_wp._worker_proxy_search.sel_end is None)


def test_body_row_drag_never_arms_search_selection():
    print("\n[scope] A drag starting on a BODY row never arms search-bar dragging")
    _reset_state('hello world')
    _click(0, 5, 10)
    check("body-row press does not arm dragging", mod_wp._worker_proxy_search.dragging is False)
    _click(32, 40, 10)
    check("motion after a body-row press falls through to generic hover", mod_wp.worker_proxy_hover_row == 10)


def test_new_input_clears_selection():
    print("\n[clear] New keyboard input clears a live drag-selection")
    _reset_state('hello world')
    label = mod_wp._WP_SEARCH_BAR_LABEL
    _click(0, len(label) + 1, 1)
    _click(32, len(label) + 5, 1)
    mod_wp._handle_worker_proxy_search_release()
    check("selection exists before typing", mod_wp._worker_proxy_search.sel_anchor is not None)
    changed = mod_wp._handle_worker_proxy_search_input('x')
    check("typing reports a change", changed)
    check("selection cleared after typing",
          mod_wp._worker_proxy_search.sel_anchor is None and mod_wp._worker_proxy_search.sel_end is None)
    check("typed char appended at the end", mod_wp._worker_proxy_search.query == 'hello worldx')


def test_backspace_deletes_active_selection():
    print("\n[editor-style delete] Backspace with an active selection deletes the SELECTED substring")
    _reset_state('hello world')
    label = mod_wp._WP_SEARCH_BAR_LABEL
    _click(0, len(label) + 2, 1)
    _click(32, len(label) + 7, 1)
    mod_wp._handle_worker_proxy_search_release()
    changed = mod_wp._handle_worker_proxy_search_input('\x7f')
    check("backspace reports a change", changed)
    check("query has the SELECTED substring removed", mod_wp._worker_proxy_search.query == 'hworld')
    check("selection cleared after selection-delete",
          mod_wp._worker_proxy_search.sel_anchor is None and mod_wp._worker_proxy_search.sel_end is None)


def test_backspace_without_selection_still_trims_last_char():
    print("\n[editor-style delete] Backspace with no selection still trims the last char")
    _reset_state('hello')
    changed = mod_wp._handle_worker_proxy_search_input('\x7f')
    check("backspace reports a change", changed)
    check("last char trimmed", mod_wp._worker_proxy_search.query == 'hell')


def test_kill_line_empties_query():
    print("\n[editor-style delete] Kill-line (search_bar.KILL_LINE_CHAR) empties the whole query")
    _reset_state('some fairly long search query text')
    changed = mod_wp._handle_worker_proxy_search_input(mod_search_bar.KILL_LINE_CHAR)
    check("kill-line reports a change", changed)
    check("query fully emptied", mod_wp._worker_proxy_search.query == '')


def test_editing_never_clears_matches():
    print("\n[matches] Editing (plain backspace, selection-delete, kill-line) never clears "
          "_worker_proxy_search.matches — Enter remains the sole recompute trigger")
    _reset_state('foo')
    mod_wp._worker_proxy_search.matches = [1, 2, 3]
    mod_wp._worker_proxy_search.match_set = {1, 2, 3}
    mod_wp._handle_worker_proxy_search_input('\x7f')
    check("matches survive plain backspace", mod_wp._worker_proxy_search.matches == [1, 2, 3])
    mod_wp._handle_worker_proxy_search_input(mod_search_bar.KILL_LINE_CHAR)
    check("matches survive kill-line", mod_wp._worker_proxy_search.matches == [1, 2, 3])


def test_enter_runs_real_search_no_log_path():
    print("\n[real search] Enter with _worker_proxy_log_path=None skips reconstruction and runs "
          "build_search_matches directly against the pre-populated synthetic entries")
    _reset_state('unique_marker_1')
    mod_wp.worker_proxy_entries.extend(_make_wp_entry(i) for i in range(3))
    check("_worker_proxy_log_path is None (no reconstruction)", mod_wp._worker_proxy_log_path is None)
    changed = mod_wp._handle_worker_proxy_search_input('\r')
    check("Enter reports a change", changed)
    check("real search found exactly entry 1", mod_wp._worker_proxy_search.matches == [1])
    check("match_set mirrors matches", mod_wp._worker_proxy_search.match_set == {1})
    check("current_idx reset to 0", mod_wp._worker_proxy_search.current_idx == 0)
    check("Enter unfocuses the bar", mod_wp._worker_proxy_search.focused is False)
    check("_wp_just_expanded set to the match's req key (reuses the expand-click auto-scroll anchor)",
          mod_wp._wp_just_expanded == ('req', 1))


def test_enter_always_reruns_not_gated_on_unchanged_query():
    print("\n[always-rerun] A repeated Enter with the SAME query re-runs the search — no "
          "unchanged-query gate exists on this pane (proxy's convention, nothing to correct here)")
    _reset_state('marker_b')
    mod_wp.worker_proxy_entries.append(_make_wp_entry(0, 'marker_b'))
    mod_wp._handle_worker_proxy_search_input('\r')
    check("first Enter found 1 match", mod_wp._worker_proxy_search.matches == [0])
    mod_wp._worker_proxy_search.focused = True
    mod_wp.worker_proxy_entries.append(_make_wp_entry(1, 'marker_b'))
    mod_wp._handle_worker_proxy_search_input('\r')
    check("second Enter (same query) picked up the new entry -> 2 matches now",
          mod_wp._worker_proxy_search.matches == [0, 1])


def test_enter_triggers_reconstruction_merge_when_log_path_set():
    print("\n[reconstruction] Enter merges reconstruct_all_messages(fwd_path) by flow_id into "
          "worker_proxy_entries when _worker_proxy_log_path is set — the NEW wiring for this pane")
    tmp = Path(tempfile.mkdtemp(prefix='pane_search_p5_fwd_'))
    dual_log_dir = tmp / 'dual_log'
    dual_log_dir.mkdir()
    log_path = tmp / 'api_requests_worker_abc12345_alpha_1.jsonl'
    fwd_path = dual_log_dir / 'api_requests_worker_abc12345_alpha_1_forwarded.jsonl'
    lines = [
        _fwd_line('flow-0', 'claude-opus-5', True, 'plain filler'),
        _fwd_line('flow-1', 'claude-opus-5', False, 'reconstructed_marker_text'),
    ]
    fwd_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    try:
        _reset_state('reconstructed_marker_text')
        mod_wp.worker_proxy_entries.extend([
            {**_make_wp_entry(0), 'flow_id': 'flow-0', 'messages': None},
            {**_make_wp_entry(1), 'flow_id': 'flow-1', 'messages': None},
        ])
        mod_wp._worker_proxy_log_path = log_path
        changed = mod_wp._handle_worker_proxy_search_input('\r')
        check("Enter reports a change", changed)
        check("entry 1's messages were populated from the reconstruction merge (were None before)",
              mod_wp.worker_proxy_entries[1]['messages'] is not None)
        check("the reconstructed content is findable — real search found entry 1",
              mod_wp._worker_proxy_search.matches == [1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_n_N_jump_wraps_both_directions():
    print("\n[nav] n/N jump forward/backward through matches, wrapping around; no-op with zero matches")
    _reset_state()
    check("no-op with zero matches", mod_wp._jump_worker_search_match(forward=True) is False)
    mod_wp._worker_proxy_search.matches = [5, 12, 30]
    mod_wp._worker_proxy_search.current_idx = 0
    check("n advances to idx 1", mod_wp._jump_worker_search_match(forward=True) and mod_wp._worker_proxy_search.current_idx == 1)
    check("n advances to idx 2", mod_wp._jump_worker_search_match(forward=True) and mod_wp._worker_proxy_search.current_idx == 2)
    check("n wraps back to idx 0", mod_wp._jump_worker_search_match(forward=True) and mod_wp._worker_proxy_search.current_idx == 0)
    check("N (backward) wraps to idx 2", mod_wp._jump_worker_search_match(forward=False) and mod_wp._worker_proxy_search.current_idx == 2)
    check("_wp_just_expanded tracks the current match's req key", mod_wp._wp_just_expanded == ('req', 30))


def test_esc_cancel_clears_state_bar_stays():
    print("\n[Esc] Cancel clears query/matches/selection; the bar itself is never hidden")
    _reset_state('hello world')
    label = mod_wp._WP_SEARCH_BAR_LABEL
    mod_wp._worker_proxy_search.focused = True
    mod_wp._worker_proxy_search.matches = [1, 2]
    mod_wp._worker_proxy_search.match_set = {1, 2}
    _click(0, len(label) + 1, 1)
    _click(32, len(label) + 5, 1)
    mod_wp._handle_worker_proxy_search_release()
    changed = mod_wp._handle_worker_proxy_search_cancel()
    check("cancel reports a change", changed)
    check("query cleared", mod_wp._worker_proxy_search.query == '')
    check("matches cleared", mod_wp._worker_proxy_search.matches == [] and mod_wp._worker_proxy_search.match_set == set())
    check("focused cleared", mod_wp._worker_proxy_search.focused is False)
    check("selection cleared", mod_wp._worker_proxy_search.sel_anchor is None)
    bar = mod_wp._render_worker_proxy_search_bar(PANE_WIDTH)
    check("bar still renders (never hidden)", 'search:' in bar)


def test_render_reverse_video_bracket():
    print("\n[render] Active selection renders SGR reverse-video around the exact substring")
    _reset_state('hello world')
    label = mod_wp._WP_SEARCH_BAR_LABEL
    _click(0, len(label) + 2, 1)
    _click(32, len(label) + 7, 1)
    mod_wp._handle_worker_proxy_search_release()
    bar = mod_wp._render_worker_proxy_search_bar(PANE_WIDTH)
    check("reverse-video ON code present", '\033[7m' in bar)
    check("reverse-video OFF code present", '\033[27m' in bar)
    check("the reversed span wraps exactly the selected substring", '\033[7mello \033[27m' in bar)

    _reset_state('hello world')
    bar2 = mod_wp._render_worker_proxy_search_bar(PANE_WIDTH)
    check("no reverse-video codes when there is no selection", '\033[7m' not in bar2)


def test_worker_switch_resets_search_state():
    print("\n[worker switch] Switching the selected worker resets _worker_proxy_search — mirrors "
          "pane.py's session-change reset and the fix just landed on the main pane; fires for "
          "BOTH digit-key and header-marker selection (both converge on this same code path)")
    _reset_state('hello world')
    mod_wp.worker_proxy_entries.append(_make_wp_entry(0, 'hello world'))
    mod_wp._worker_proxy_search.matches = [0]
    mod_wp._worker_proxy_search.match_set = {0}
    mod_wp._worker_proxy_search.focused = True
    mod_wp._worker_proxy_last_worker_name = 'workerA'  # pretend we're currently on workerA
    check("search state populated before the switch",
          mod_wp._worker_proxy_search.matches == [0] and mod_wp._worker_proxy_search.query == 'hello world')

    tmp_dir = Path(tempfile.mkdtemp(prefix='pane_search_p5_switch_'))
    sel_path = tmp_dir / 'selection.txt'
    sel_path.write_text('workerB', encoding='utf-8')
    orig_get_sel = mod_wp.get_selection_file_path
    orig_list_workers = mod_wp.list_workers
    orig_find_log = mod_wp.find_worker_proxy_log
    mod_wp.get_selection_file_path = lambda pf: sel_path
    mod_wp.list_workers = lambda pf: [{'name': 'workerB', 'session': ''}]
    mod_wp.find_worker_proxy_log = lambda name, pf=None: None
    try:
        mod_wp._refresh_worker_proxy_data(10_000_000.0, False, 0.0, _FakeMonitor())
    finally:
        mod_wp.get_selection_file_path = orig_get_sel
        mod_wp.list_workers = orig_list_workers
        mod_wp.find_worker_proxy_log = orig_find_log
        shutil.rmtree(tmp_dir, ignore_errors=True)

    check("selected worker actually changed", mod_wp._worker_proxy_last_worker_name == 'workerB')
    check("query cleared by the worker switch", mod_wp._worker_proxy_search.query == '')
    check("matches cleared by the worker switch",
          mod_wp._worker_proxy_search.matches == [] and mod_wp._worker_proxy_search.match_set == set())
    check("focused cleared by the worker switch", mod_wp._worker_proxy_search.focused is False)


# ORCHESTRATOR

def run_probe_workflow():
    print("=" * 70)
    print("P5 — worker-proxy pane search bar parity regression suite")
    print("=" * 70)
    test_state_shape()
    test_two_row_header_composition_and_shifts()
    test_header_marker_click_still_selects_worker_at_shifted_row()
    test_row1_press_focuses_and_arms_drag()
    test_drag_select_copies_to_clipboard()
    test_plain_click_no_motion_no_clipboard()
    test_release_noop_without_active_drag()
    test_body_row_click_clears_selection()
    test_body_row_drag_never_arms_search_selection()
    test_new_input_clears_selection()
    test_backspace_deletes_active_selection()
    test_backspace_without_selection_still_trims_last_char()
    test_kill_line_empties_query()
    test_editing_never_clears_matches()
    test_enter_runs_real_search_no_log_path()
    test_enter_always_reruns_not_gated_on_unchanged_query()
    test_enter_triggers_reconstruction_merge_when_log_path_set()
    test_n_N_jump_wraps_both_directions()
    test_esc_cancel_clears_state_bar_stays()
    test_render_reverse_video_bracket()
    test_worker_switch_resets_search_state()

    total = len(_RESULTS)
    passed = sum(1 for _, ok in _RESULTS if ok)
    print("\n" + "=" * 70)
    print(f"{passed}/{total} checks passed")
    print("=" * 70)

    report_dir = Path(__file__).resolve().parent / 'md'
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = report_dir / f'p5_worker_proxy_pane_parity_test_{ts}.md'
    lines = [f"# P5 worker-proxy pane parity regression — {ts}", "", f"{passed}/{total} checks passed", ""]
    for label, ok in _RESULTS:
        lines.append(f"- [{'x' if ok else ' '}] {label}")
    report_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"\nReport written to: {report_path}")

    if passed != total:
        sys.exit(1)


if __name__ == '__main__':
    run_probe_workflow()
