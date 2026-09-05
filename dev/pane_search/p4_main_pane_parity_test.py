"""
p4_main_pane_parity_test.py — Regression guard for the main pane's search bar reaching full
parity with the proxy pane's reference implementation (rollout sub-milestone 2,
process-docs/pane_search/).

Covers, per the milestone spec:
  - core/monitor_display.py::_main_search is now ONE search_bar.SearchState instance (mirrors
    proxy_display/pane.py's _proxy_search) — the 8 flat globals the main pane used to have
    (_search_query, _search_focused, _search_matches, _search_match_set, _search_current_idx,
    _search_cached_query, plus click-arrow rendering) are gone
  - click-arrows ([<-]/[->]) removed from the rendered bar; n/N key navigation replaces them
    (core/monitor.py::_jump_search_match)
  - drag-to-select on row 1: press anchors, motion extends, release copies the selected
    substring to the clipboard (copy_to_clipboard monkeypatched, no real pbcopy call); a plain
    click (no motion) makes zero clipboard calls
  - editor-style deletion: Backspace with an active selection deletes the SELECTED substring;
    plain Backspace still trims the last char; kill-line (search_bar.KILL_LINE_CHAR) empties the
    whole query regardless of an active selection
  - editing (plain backspace, selection-delete, kill-line) never clears _main_search.matches —
    Enter is the sole recompute trigger
  - Enter ALWAYS re-runs the full match rebuild, NOT gated on query-unchanged — a deliberate
    CORRECTION from the pre-migration main pane (which DID gate on this via _search_cached_query,
    now removed) to proxy's convention: a repeated Enter picks up events appended to
    main_event_buffer since the last search
  - the private core/monitor_display.py::_highlight_query_in_line duplicate is gone; highlighting
    goes through utils.highlight_query_in_line (byte-identical algorithm, confirmed in
    process-docs/pane_search/2026-08-18_search_highlight_scope_fix.md) — wraps only the literal
    matched substring (browser-find style), not the whole row
  - the row-1 HOVER_BG baseline is gone (search_bar.render_search_bar has none — "one visual
    search language across panes", process-docs/pane_search/2026-08-18_m2_search_bar_implementation.md)
  - the dead _search_committed flag (set but never read for branching, pre-migration) is gone
  - '/' focuses the bar (new for this milestone — proxy already had it); this is a one-line
    dispatch inside run_main_loop's while-loop itself, same as every other pane's inline hotkey
    routing ('/' and 'n'/'N' in run_proxy_loop, 'u' for undo) — NOT unit-tested at the loop level
    in this suite, consistent with p2/p3's own scope (they test the extracted handler functions
    _jump_search_match/_handle_proxy_search_input, never the outer while-loop dispatch itself)
  - session change resets _main_search (search_bar.handle_search_cancel) and
    _search_match_line_offsets alongside main_event_buffer.clear() in _refresh_main_data —
    mirrors the proxy pane's _refresh_proxy_data; without this a stale .matches list of
    event_idx values would point past the freshly-cleared buffer

Uses REAL src.core.monitor / src.core.monitor_display functions against synthetic
main_event_buffer entries — not mocks. importlib.import_module used throughout (dev/ scripts
may not use a literal 'from src.' import line).

Run: ./venv/bin/python dev/pane_search/p4_main_pane_parity_test.py
"""

# INFRASTRUCTURE
import importlib
import os
import sys
from datetime import datetime
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT))
os.environ.setdefault('MONITOR_CC_ROOT', str(WORKTREE_ROOT))

_ROOT_PKG = 'src'
mod_monitor = importlib.import_module(f'{_ROOT_PKG}.core.monitor')
mod_md = importlib.import_module(f'{_ROOT_PKG}.core.monitor_display')
mod_search_bar = importlib.import_module(f'{_ROOT_PKG}.search_bar')
mod_constants = importlib.import_module(f'{_ROOT_PKG}.constants')

PANE_WIDTH = 100
_RESULTS = []


def check(label, condition):
    _RESULTS.append((label, bool(condition)))
    status = 'PASS' if condition else 'FAIL'
    print(f"  {status}  {label}")
    return condition


# FUNCTIONS

# Synthetic tool_call event (2026-09: system_message no longer renders — the main pane shows
# only tool calls now, see process-docs/main_pane/). serialize_main_event('all') reuses the real
# format_tool_call and returns the marker inside the `command` param line; format_parameters
# renders param lines with NO color codes at all — the same "clean surface" property the old
# system_message body line had — for asserting highlight_query_in_line wraps exactly the matched
# substring, nothing else on the line.
def _make_event(marker: str = None, filler: str = 'plain content'):
    text = f"{filler} {marker}" if marker else filler
    return {
        'type': 'tool_call',
        'data': {'tool_use_id': 'tu', 'tool_name': 'Bash', 'input': {'command': text},
                  'output': '', 'req_num': 1, 'is_subagent': False, 'is_error': False},
        'call_number': None,
    }


def _reset_state(query: str = ''):
    mod_md.main_event_buffer.clear()
    mod_md.main_line_map.clear()
    mod_md._main_copy_rows.clear()
    mod_md._main_copy_feedback_until.clear()
    mod_md._search_match_line_offsets.clear()
    mod_md._search_all_line_offsets.clear()
    mod_md._search_total_lines = 0
    mod_md.main_scroll_offset = 0
    mod_md._main_pane_width = PANE_WIDTH
    mod_md._main_search.query = query
    mod_md._main_search.focused = False
    mod_md._main_search.matches = []
    mod_md._main_search.match_set = set()
    mod_md._main_search.current_idx = 0
    mod_search_bar.clear_selection(mod_md._main_search)


def _capture_clipboard():
    captured = []
    orig = mod_monitor.copy_to_clipboard
    mod_monitor.copy_to_clipboard = lambda text: captured.append(text)
    return captured, orig


# TESTS

def test_state_shape_migrated():
    print("\n[shape] Main pane search state is one search_bar.SearchState; dead flags gone")
    check("_main_search is a search_bar.SearchState instance",
          isinstance(mod_md._main_search, mod_search_bar.SearchState))
    check("_search_committed (dead, never read for branching) removed", not hasattr(mod_md, '_search_committed'))
    check("_search_cached_query (unchanged-query Enter-gate) removed — proxy's always-rerun convention now",
          not hasattr(mod_md, '_search_cached_query'))
    check("private _highlight_query_in_line duplicate removed", not hasattr(mod_md, '_highlight_query_in_line'))
    check("utils.highlight_query_in_line imported instead", 'highlight_query_in_line' in dir(mod_md))


def test_search_bar_renders_row1_no_arrows_no_hover_baseline():
    print("\n[render] Search bar renders at row 1, uses the shared label, no click-arrows, no HOVER_BG baseline")
    _reset_state()
    mod_md.main_event_buffer.append(_make_event('hello'))
    output = mod_md.render_main_buffer(pane_height=20, pane_width=PANE_WIDTH, scroll_offset=0)
    first_line = output.splitlines()[0]
    check("row 1 shows the 'Search: ' label", first_line.startswith('Search:') or 'Search: ' in first_line)
    check("no [<-] click-arrow", '[←]' not in first_line)
    check("no [->] click-arrow", '[→]' not in first_line)
    check("no HOVER_BG baseline on the bar row", mod_constants.HOVER_BG not in first_line)
    check("row 1 is NOT a body key (it's the search bar)", mod_md.main_line_map.get(1) is None)


def test_col_to_index_via_shared_label():
    print("\n[col mapping] search_bar.col_to_query_index against the main pane's own label")
    label = mod_md._SEARCH_BAR_LABEL
    q = 'hello world'
    check("click at label end -> index 0", mod_search_bar.col_to_query_index(len(label), q, label) == 0)
    check("click past the end -> clamped to len(query)",
          mod_search_bar.col_to_query_index(len(label) + 999, q, label) == len(q))


def test_row1_press_focuses_and_arms_drag():
    print("\n[press] A row-1 click focuses the bar and anchors a drag-select")
    _reset_state('hello world')
    label = mod_md._SEARCH_BAR_LABEL
    changed = mod_monitor._handle_main_mouse(0, len(label) + 2, 1)
    check("press returns True (redraw)", changed)
    check("press focuses the bar", mod_md._main_search.focused is True)
    check("press arms dragging", mod_md._main_search.dragging is True)
    check("press anchors at index 1 ('e')", mod_md._main_search.sel_anchor == mod_md._main_search.sel_end == 1)


def test_drag_select_copies_to_clipboard():
    print("\n[drag flow] press -> motion -> release copies the selected substring")
    _reset_state('hello world')
    captured, orig = _capture_clipboard()
    try:
        label = mod_md._SEARCH_BAR_LABEL
        mod_monitor._handle_main_mouse(0, len(label) + 2, 1)   # anchor at index1 ('e')
        motion_changed = mod_monitor._handle_main_mouse(32, len(label) + 7, 1)  # extend to index6 ('w')
        check("motion returns True and extends sel_end only", motion_changed and mod_md._main_search.sel_end == 6)
        release_changed = mod_monitor._handle_main_search_release()
        check("release returns True (redraw)", release_changed)
        check("release disarms dragging", mod_md._main_search.dragging is False)
        check("release copies exactly the selected substring", captured == ['ello '])
    finally:
        mod_monitor.copy_to_clipboard = orig


def test_plain_click_no_motion_no_clipboard():
    print("\n[plain click] press+release with NO motion makes zero clipboard calls")
    _reset_state('hello world')
    captured, orig = _capture_clipboard()
    try:
        label = mod_md._SEARCH_BAR_LABEL
        mod_monitor._handle_main_mouse(0, len(label) + 3, 1)
        release_changed = mod_monitor._handle_main_search_release()
        check("release still returns True (dragging disarmed)", release_changed)
        check("NO clipboard call on a plain click", captured == [])
        check("selection cleared after a plain click",
              mod_md._main_search.sel_anchor is None and mod_md._main_search.sel_end is None)
    finally:
        mod_monitor.copy_to_clipboard = orig


def test_release_noop_without_active_drag():
    print("\n[release no-op] A release with no prior row-1 press changes nothing")
    _reset_state('hello world')
    changed = mod_monitor._handle_main_search_release()
    check("release with no armed drag returns False", changed is False)


def test_body_row_click_clears_selection():
    print("\n[clear] Click on the buffer area (row >= 2) clears a live drag-selection")
    _reset_state('hello world')
    label = mod_md._SEARCH_BAR_LABEL
    mod_monitor._handle_main_mouse(0, len(label) + 1, 1)
    mod_monitor._handle_main_mouse(32, len(label) + 5, 1)
    mod_monitor._handle_main_search_release()
    check("selection exists before the elsewhere-click", mod_md._main_search.sel_anchor is not None)
    changed = mod_monitor._handle_main_mouse(0, 5, 2)  # unmapped body row
    check("elsewhere-click reports a change (selection cleared)", changed)
    check("selection cleared after clicking elsewhere",
          mod_md._main_search.sel_anchor is None and mod_md._main_search.sel_end is None)


def test_body_row_drag_never_arms_search_selection():
    print("\n[scope] A drag starting on a BODY row never arms search-bar dragging")
    _reset_state('hello world')
    press_changed = mod_monitor._handle_main_mouse(0, 5, 2)
    check("body-row press does not arm dragging", mod_md._main_search.dragging is False)
    motion_changed = mod_monitor._handle_main_mouse(32, 40, 2)
    check("motion after a body-row press falls through to generic hover", mod_md.main_hover_row == 2)


def test_new_input_clears_selection():
    print("\n[clear] New keyboard input clears a live drag-selection")
    _reset_state('hello world')
    label = mod_md._SEARCH_BAR_LABEL
    mod_monitor._handle_main_mouse(0, len(label) + 1, 1)
    mod_monitor._handle_main_mouse(32, len(label) + 5, 1)
    mod_monitor._handle_main_search_release()
    check("selection exists before typing", mod_md._main_search.sel_anchor is not None)
    changed = mod_monitor._handle_main_search_input('x')
    check("typing reports a change", changed)
    check("selection cleared after typing",
          mod_md._main_search.sel_anchor is None and mod_md._main_search.sel_end is None)
    check("typed char appended at the end", mod_md._main_search.query == 'hello worldx')


def test_backspace_deletes_active_selection():
    print("\n[editor-style delete] Backspace with an active selection deletes the SELECTED substring")
    _reset_state('hello world')
    label = mod_md._SEARCH_BAR_LABEL
    mod_monitor._handle_main_mouse(0, len(label) + 2, 1)   # anchor at index1 ('e')
    mod_monitor._handle_main_mouse(32, len(label) + 7, 1)  # extend to index6 ('w') -> 'ello '
    mod_monitor._handle_main_search_release()
    changed = mod_monitor._handle_main_search_input('\x7f')
    check("backspace reports a change", changed)
    check("query has the SELECTED substring removed", mod_md._main_search.query == 'hworld')
    check("selection cleared after selection-delete",
          mod_md._main_search.sel_anchor is None and mod_md._main_search.sel_end is None)


def test_backspace_without_selection_still_trims_last_char():
    print("\n[editor-style delete] Backspace with no selection still trims the last char")
    _reset_state('hello')
    changed = mod_monitor._handle_main_search_input('\x7f')
    check("backspace reports a change", changed)
    check("last char trimmed", mod_md._main_search.query == 'hell')


def test_kill_line_empties_query():
    print("\n[editor-style delete] Kill-line (search_bar.KILL_LINE_CHAR) empties the whole query")
    _reset_state('some fairly long search query text')
    changed = mod_monitor._handle_main_search_input(mod_search_bar.KILL_LINE_CHAR)
    check("kill-line reports a change", changed)
    check("query fully emptied", mod_md._main_search.query == '')


def test_kill_line_ignores_active_selection():
    print("\n[editor-style delete] Kill-line empties the query regardless of an active selection")
    _reset_state('hello world')
    label = mod_md._SEARCH_BAR_LABEL
    mod_monitor._handle_main_mouse(0, len(label) + 2, 1)
    mod_monitor._handle_main_mouse(32, len(label) + 7, 1)
    mod_monitor._handle_main_search_release()
    mod_monitor._handle_main_search_input(mod_search_bar.KILL_LINE_CHAR)
    check("query fully emptied (not just the selected substring)", mod_md._main_search.query == '')
    check("selection also cleared", mod_md._main_search.sel_anchor is None)


def test_editing_never_clears_matches():
    print("\n[matches] Editing (plain backspace, selection-delete, kill-line) never clears "
          "_main_search.matches — Enter remains the sole recompute trigger")
    _reset_state('foo')
    mod_md._main_search.matches = [1, 2, 3]
    mod_md._main_search.match_set = {1, 2, 3}
    mod_monitor._handle_main_search_input('\x7f')
    check("matches survive plain backspace", mod_md._main_search.matches == [1, 2, 3])
    mod_md._main_search.query = 'bar'
    label = mod_md._SEARCH_BAR_LABEL
    mod_monitor._handle_main_mouse(0, len(label) + 1, 1)
    mod_monitor._handle_main_mouse(32, len(label) + 3, 1)
    mod_monitor._handle_main_search_release()
    mod_monitor._handle_main_search_input('\x7f')
    check("matches survive selection-delete backspace", mod_md._main_search.matches == [1, 2, 3])
    mod_monitor._handle_main_search_input(mod_search_bar.KILL_LINE_CHAR)
    check("matches survive kill-line", mod_md._main_search.matches == [1, 2, 3])


def test_enter_runs_real_search_and_finds_matches():
    print("\n[real search] Enter runs the real _main_search_on_commit -> _compute_search_matches path")
    _reset_state('marker_a')
    mod_md.main_event_buffer.extend([
        _make_event('marker_a'),
        _make_event(),
        _make_event('marker_a'),
    ])
    changed = mod_monitor._handle_main_search_input('\r')
    check("Enter reports a change", changed)
    check("matches found the two events containing the query", mod_md._main_search.matches == [0, 2])
    check("match_set mirrors matches", mod_md._main_search.match_set == {0, 2})
    check("current_idx reset to 0", mod_md._main_search.current_idx == 0)
    check("Enter unfocuses the bar", mod_md._main_search.focused is False)


def test_enter_always_reruns_not_gated_on_unchanged_query():
    print("\n[correction] A repeated Enter with the SAME query re-runs the search (NOT gated on "
          "query-unchanged, unlike the pre-migration main pane) — picks up a new event streamed "
          "in since the first Enter")
    _reset_state('marker_b')
    mod_md.main_event_buffer.append(_make_event('marker_b'))
    mod_monitor._handle_main_search_input('\r')
    mod_md._main_search.focused = True  # simulate re-focusing without editing the query
    check("first Enter found 1 match", mod_md._main_search.matches == [0])
    mod_md.main_event_buffer.append(_make_event('marker_b'))  # new event streamed in
    check("query unchanged before the second Enter", mod_md._main_search.query == 'marker_b')
    mod_monitor._handle_main_search_input('\r')
    check("second Enter (same query) picked up the new event -> 2 matches now",
          mod_md._main_search.matches == [0, 1])


def test_n_N_jump_wraps_both_directions():
    print("\n[nav] n/N jump forward/backward through matches, wrapping around; no-op with zero matches")
    _reset_state()
    check("no-op with zero matches", mod_monitor._jump_search_match(forward=True) is False)
    mod_md._main_search.matches = [5, 12, 30]
    mod_md._main_search.current_idx = 0
    check("n advances to idx 1", mod_monitor._jump_search_match(forward=True) and mod_md._main_search.current_idx == 1)
    check("n advances to idx 2", mod_monitor._jump_search_match(forward=True) and mod_md._main_search.current_idx == 2)
    check("n wraps back to idx 0", mod_monitor._jump_search_match(forward=True) and mod_md._main_search.current_idx == 0)
    check("N (backward) wraps to idx 2", mod_monitor._jump_search_match(forward=False) and mod_md._main_search.current_idx == 2)


def test_esc_cancel_clears_state_bar_stays():
    print("\n[Esc] Cancel clears query/matches/selection; the bar itself is never hidden "
          "(it's a permanent row, not a toggle)")
    _reset_state('hello world')
    label = mod_md._SEARCH_BAR_LABEL
    mod_md._main_search.focused = True
    mod_md._main_search.matches = [1, 2]
    mod_md._main_search.match_set = {1, 2}
    mod_monitor._handle_main_mouse(0, len(label) + 1, 1)
    mod_monitor._handle_main_mouse(32, len(label) + 5, 1)
    mod_monitor._handle_main_search_release()
    mod_md._search_match_line_offsets = {1: 0, 2: 0}
    changed = mod_monitor._handle_main_search_cancel()
    check("cancel reports a change", changed)
    check("query cleared", mod_md._main_search.query == '')
    check("matches cleared", mod_md._main_search.matches == [] and mod_md._main_search.match_set == set())
    check("focused cleared", mod_md._main_search.focused is False)
    check("selection cleared", mod_md._main_search.sel_anchor is None)
    check("main-pane-specific line offsets cleared too", mod_md._search_match_line_offsets == {})
    bar = mod_md._render_search_bar(PANE_WIDTH)
    check("bar still renders (never hidden)", 'Search:' in bar)


def test_session_change_resets_search_state():
    print("\n[clear] Session change resets _main_search and the main-pane-specific offset dict "
          "(mirrors the proxy pane's _refresh_proxy_data; without this a stale .matches list "
          "would point past the freshly-cleared buffer)")
    _reset_state('hello world')
    mod_md.main_event_buffer.extend([_make_event('hello world')])
    mod_md._main_search.matches = [0]
    mod_md._main_search.match_set = {0}
    mod_md._main_search.focused = True
    mod_md._search_match_line_offsets = {0: 0}
    check("search state populated before session change",
          mod_md._main_search.matches == [0] and mod_md._main_search.query == 'hello world')

    fake_session = Path('/tmp/pane_search_p4_fake_session.jsonl')
    orig_get_newest = mod_monitor._get_newest_main_session
    orig_monitor_sessions = mod_monitor.monitor_sessions
    mod_monitor._get_newest_main_session = lambda: fake_session
    mod_monitor.monitor_sessions = lambda: None  # isolate the session-change reset block itself
    try:
        now = 10_000_000.0
        mod_monitor._refresh_main_data(now, 0.0, now, None)  # current_main_session=None -> forces the change branch
    finally:
        mod_monitor._get_newest_main_session = orig_get_newest
        mod_monitor.monitor_sessions = orig_monitor_sessions
        mod_monitor.file_positions.pop(fake_session, None)
        mod_monitor.tool_use_caches.pop(fake_session, None)

    check("query cleared by session change", mod_md._main_search.query == '')
    check("matches cleared by session change",
          mod_md._main_search.matches == [] and mod_md._main_search.match_set == set())
    check("focused cleared by session change", mod_md._main_search.focused is False)
    check("main-pane-specific line offsets cleared by session change", mod_md._search_match_line_offsets == {})


def test_render_reverse_video_bracket():
    print("\n[render] Active selection renders SGR reverse-video around the exact substring")
    _reset_state('hello world')
    label = mod_md._SEARCH_BAR_LABEL
    mod_monitor._handle_main_mouse(0, len(label) + 2, 1)   # index1
    mod_monitor._handle_main_mouse(32, len(label) + 7, 1)  # index6
    mod_monitor._handle_main_search_release()
    bar = mod_md._render_search_bar(PANE_WIDTH)
    check("reverse-video ON code present", '\033[7m' in bar)
    check("reverse-video OFF code present", '\033[27m' in bar)
    check("the reversed span wraps exactly the selected substring", '\033[7mello \033[27m' in bar)

    _reset_state('hello world')  # no selection
    bar2 = mod_md._render_search_bar(PANE_WIDTH)
    check("no reverse-video codes when there is no selection", '\033[7m' not in bar2)


def test_highlight_wraps_substring_only_via_real_render():
    print("\n[highlight] render_main_buffer highlights only the literal matched substring "
          "(browser-find style) via utils.highlight_query_in_line — not the whole row")
    _reset_state('unique_marker_2')
    mod_md.main_event_buffer.extend([_make_event('unique_marker_2')])
    mod_monitor._handle_main_search_input('\r')  # real search run
    output = mod_md.render_main_buffer(pane_height=20, pane_width=PANE_WIDTH, scroll_offset=0)
    check("current-match BG present", mod_constants.SEARCH_CURRENT_BG in output)
    check("highlight wraps exactly the matched substring, restore right after",
          f"{mod_constants.SEARCH_CURRENT_BG}unique_marker_2\033[49m" in output)
    check("highlight is NOT a whole-row prefix (row 1 char after the newline is not the BG code)",
          not output.splitlines()[-1].split('unique_marker_2')[0].endswith(mod_constants.SEARCH_CURRENT_BG.rstrip()))


# ORCHESTRATOR

def run_probe_workflow():
    print("=" * 70)
    print("P4 — main pane search bar parity regression suite")
    print("=" * 70)
    test_state_shape_migrated()
    test_search_bar_renders_row1_no_arrows_no_hover_baseline()
    test_col_to_index_via_shared_label()
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
    test_kill_line_ignores_active_selection()
    test_editing_never_clears_matches()
    test_enter_runs_real_search_and_finds_matches()
    test_enter_always_reruns_not_gated_on_unchanged_query()
    test_n_N_jump_wraps_both_directions()
    test_esc_cancel_clears_state_bar_stays()
    test_session_change_resets_search_state()
    test_render_reverse_video_bracket()
    test_highlight_wraps_substring_only_via_real_render()

    total = len(_RESULTS)
    passed = sum(1 for _, ok in _RESULTS if ok)
    print("\n" + "=" * 70)
    print(f"{passed}/{total} checks passed")
    print("=" * 70)

    report_dir = Path(__file__).resolve().parent / 'md'
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = report_dir / f'p4_main_pane_parity_test_{ts}.md'
    lines = [f"# P4 main pane parity regression — {ts}", "", f"{passed}/{total} checks passed", ""]
    for label, ok in _RESULTS:
        lines.append(f"- [{'x' if ok else ' '}] {label}")
    report_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"\nReport written to: {report_path}")

    if passed != total:
        sys.exit(1)


if __name__ == '__main__':
    run_probe_workflow()
