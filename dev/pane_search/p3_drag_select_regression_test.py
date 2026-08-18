"""
p3_drag_select_regression_test.py — Regression guard for drag-to-select on the proxy pane's
search bar (row 1), process-docs/pane_search/.

Covers, per the milestone spec:
  - button-0 press on row 1 anchors a selection at the char under the pointer (col->char-index
    mapping, _cell_width-aware for wide chars — em-dash/emoji land in queries per the UTF-8 fix)
  - motion (button 32 = left button held, the 0+32 SGR flag) extends the selection; row is
    ignored while dragging, so vertical drift during a fast drag doesn't break it
  - release finalizes: copies the selected substring to the clipboard via the real
    copy_to_clipboard (monkeypatched to a capturing stub, no real pbcopy call)
  - a plain click (press+release, NO motion in between) does NOT copy anything (must never
    clobber the real clipboard with an empty string) and preserves today's focus-only behavior
  - selection renders as SGR reverse-video (\\033[7m...\\033[27m) bracketing the exact substring
  - click elsewhere, new keyboard input, Esc-cancel, and session-change all clear a live
    selection's highlight
  - a drag that starts on a BODY row (not row 1) never arms search-bar dragging — button-32
    motion after a body-row press falls through to the unchanged generic hover bucket
  - editor-style deletion: Backspace with an active selection deletes it; kill-line (Cmd+Backspace
    hypothesis) empties the whole query; neither clears _proxy_search.matches

(2026-08-18, sub-milestone 1 of the pane-search rollout) pane.py's search state is now ONE
search_bar.SearchState instance (`_proxy_search`) instead of 8 separate flat globals — this
file's state-pokes were mechanically updated to the new attribute path
(`mod_pane._proxy_search_dragging` -> `mod_pane._proxy_search.dragging`, etc.); all function-call
shapes (`_handle_proxy_mouse`, `_search_col_to_query_index`, `_render_proxy_search_bar`,
`_KILL_LINE_CHAR`, ...) are UNCHANGED — pane.py keeps thin compat wrappers over search_bar.py's
generic functions specifically so this suite needed no other changes.

Uses REAL src.proxy_display.pane functions against direct (button, col, row) calls — not a
mock of the mouse-event layer itself (read_mouse_event's own SGR parsing is unchanged and out
of scope here; these tests exercise everything downstream of it, matching the milestone's
own investigation: button 32 for a held-left-button drag is a documented SGR protocol fact,
not something this suite re-derives from raw bytes).

Run: ./venv/bin/python dev/pane_search/p3_drag_select_regression_test.py
"""

# INFRASTRUCTURE
import importlib
import os
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT))
os.environ.setdefault('MONITOR_CC_ROOT', str(WORKTREE_ROOT))

_ROOT_PKG = 'src'
mod_pane = importlib.import_module(f'{_ROOT_PKG}.proxy_display.pane')

PANE_WIDTH = 80
_RESULTS = []


def check(label, condition):
    _RESULTS.append((label, bool(condition)))
    status = 'PASS' if condition else 'FAIL'
    print(f"  {status}  {label}")
    return condition


# FUNCTIONS

def _reset_state(query: str = ''):
    mod_pane.proxy_entries.clear()
    mod_pane.proxy_expand_states.clear()
    mod_pane.proxy_line_map.clear()
    mod_pane._proxy_search.query = query
    mod_pane._proxy_search.focused = False
    mod_pane._proxy_search.dragging = False
    mod_pane._proxy_search.sel_anchor = None
    mod_pane._proxy_search.sel_end = None
    mod_pane._proxy_pane_width = PANE_WIDTH
    mod_pane._proxy_undo_stack.clear()
    mod_pane._proxy_just_expanded = None


def _capture_clipboard():
    captured = []
    orig = mod_pane.copy_to_clipboard
    mod_pane.copy_to_clipboard = lambda text: captured.append(text)
    return captured, orig


# TESTS

def test_col_to_index_ascii():
    print("\n[col mapping] Plain ASCII query — 1-cell-per-char boundary snapping")
    _reset_state('hello world')
    label_w = len(mod_pane._SEARCH_BAR_LABEL)
    check("click before/at label end -> index 0", mod_pane._search_col_to_query_index(label_w, 'hello world') == 0)
    check("click on first char -> boundary 0 (before it)",
          mod_pane._search_col_to_query_index(label_w + 1, 'hello world') == 0)
    check("click on 7th query col -> boundary 6 (before 'w' in 'hello world')",
          mod_pane._search_col_to_query_index(label_w + 7, 'hello world') == 6)
    check("click past the end -> clamped to len(query)",
          mod_pane._search_col_to_query_index(label_w + 999, 'hello world') == len('hello world'))
    check("empty query always maps to 0", mod_pane._search_col_to_query_index(label_w + 5, '') == 0)


def test_col_to_index_wide_char():
    print("\n[col mapping] Wide-char (emoji, 2-cell) query — left/right half snapping")
    q = 'a😀b'  # a(1w) emoji(2w) b(1w)
    label_w = len(mod_pane._SEARCH_BAR_LABEL)
    # cols: label_w+1='a', label_w+2..3=emoji(2 cells), label_w+4='b'
    check("click on 'a' -> boundary 0 (before 'a')",
          mod_pane._search_col_to_query_index(label_w + 1, q) == 0)
    check("click on emoji's LEFT cell -> boundary 1 (before emoji)",
          mod_pane._search_col_to_query_index(label_w + 2, q) == 1)
    check("click on emoji's RIGHT cell -> boundary 2 (after emoji, before 'b')",
          mod_pane._search_col_to_query_index(label_w + 3, q) == 2)
    check("click on 'b' -> boundary 2 (same boundary, before 'b')",
          mod_pane._search_col_to_query_index(label_w + 4, q) == 2)
    check("click past 'b' -> boundary 3 (end of query)",
          mod_pane._search_col_to_query_index(label_w + 5, q) == 3)


def test_drag_select_copies_to_clipboard():
    print("\n[drag flow] press -> motion -> release copies the selected substring")
    _reset_state('hello world')
    captured, orig = _capture_clipboard()
    try:
        label_w = len(mod_pane._SEARCH_BAR_LABEL)
        press_changed = mod_pane._handle_proxy_mouse(0, label_w + 2, 1)  # anchor at index1 ('e')
        check("press returns True (redraw)", press_changed)
        check("press focuses the bar (existing behavior preserved)", mod_pane._proxy_search.focused is True)
        check("press arms dragging", mod_pane._proxy_search.dragging is True)
        check("press sets anchor==end (empty range until motion)",
              mod_pane._proxy_search.sel_anchor == mod_pane._proxy_search.sel_end == 1)
        motion_changed = mod_pane._handle_proxy_mouse(32, label_w + 7, 1)  # extend to index6 ('w')
        check("motion returns True (redraw)", motion_changed)
        check("motion extends sel_end only, anchor unchanged",
              mod_pane._proxy_search.sel_anchor == 1 and mod_pane._proxy_search.sel_end == 6)
        release_changed = mod_pane._handle_proxy_search_release()
        check("release returns True (redraw)", release_changed)
        check("release disarms dragging", mod_pane._proxy_search.dragging is False)
        check("release copies exactly the selected substring",
              captured == ['ello '])
        check("release KEEPS the selection range visible (finished, not cleared)",
              mod_pane._proxy_search.sel_anchor == 1 and mod_pane._proxy_search.sel_end == 6)
    finally:
        mod_pane.copy_to_clipboard = orig


def test_plain_click_no_motion_no_clipboard():
    print("\n[plain click] press+release with NO motion — today's focus-only behavior preserved")
    _reset_state('hello world')
    captured, orig = _capture_clipboard()
    try:
        label_w = len(mod_pane._SEARCH_BAR_LABEL)
        mod_pane._handle_proxy_mouse(0, label_w + 3, 1)
        release_changed = mod_pane._handle_proxy_search_release()
        check("release still returns True (state changed: dragging disarmed)", release_changed)
        check("NO clipboard call on a plain click (never clobber the real clipboard)", captured == [])
        check("selection state fully cleared after a plain click",
              mod_pane._proxy_search.sel_anchor is None and mod_pane._proxy_search.sel_end is None)
        check("focus is still set (existing behavior)", mod_pane._proxy_search.focused is True)
    finally:
        mod_pane.copy_to_clipboard = orig


def test_release_noop_without_active_drag():
    print("\n[release no-op] A release with no prior row-1 press changes nothing")
    _reset_state('hello world')
    captured, orig = _capture_clipboard()
    try:
        changed = mod_pane._handle_proxy_search_release()
        check("release with no armed drag returns False", changed is False)
        check("no clipboard call", captured == [])
    finally:
        mod_pane.copy_to_clipboard = orig


def test_body_row_drag_never_arms_search_selection():
    print("\n[scope] A drag starting on a BODY row never arms search-bar dragging")
    _reset_state('hello world')
    mod_pane.proxy_line_map[2] = ('req', 0)
    press_changed = mod_pane._handle_proxy_mouse(0, 5, 2)  # press on a body row, not row 1
    check("body-row press does not arm dragging", mod_pane._proxy_search.dragging is False)
    motion_changed = mod_pane._handle_proxy_mouse(32, 40, 2)  # motion after a body-row press
    check("motion after a body-row press falls through to generic hover (proxy_hover_row set)",
          mod_pane.proxy_hover_row == 2)
    check("search selection untouched by a body-row drag",
          mod_pane._proxy_search.sel_anchor is None and mod_pane._proxy_search.sel_end is None)


def test_click_elsewhere_clears_selection():
    print("\n[clear] Click elsewhere (body row) clears a live drag-selection")
    _reset_state('hello world')
    label_w = len(mod_pane._SEARCH_BAR_LABEL)
    mod_pane._handle_proxy_mouse(0, label_w + 1, 1)
    mod_pane._handle_proxy_mouse(32, label_w + 5, 1)
    mod_pane._handle_proxy_search_release()
    check("selection exists before the elsewhere-click",
          mod_pane._proxy_search.sel_anchor is not None)
    mod_pane.proxy_line_map[2] = ('req', 0)
    changed = mod_pane._handle_proxy_mouse(0, 5, 2)
    check("elsewhere-click reports a change (selection cleared)", changed)
    check("selection cleared after clicking elsewhere",
          mod_pane._proxy_search.sel_anchor is None and mod_pane._proxy_search.sel_end is None)


def test_new_input_clears_selection():
    print("\n[clear] New keyboard input clears a live drag-selection")
    _reset_state('hello world')
    label_w = len(mod_pane._SEARCH_BAR_LABEL)
    mod_pane._handle_proxy_mouse(0, label_w + 1, 1)
    mod_pane._handle_proxy_mouse(32, label_w + 5, 1)
    mod_pane._handle_proxy_search_release()
    check("selection exists before typing", mod_pane._proxy_search.sel_anchor is not None)
    changed = mod_pane._handle_proxy_search_input('x')
    check("typing reports a change", changed)
    check("selection cleared after typing",
          mod_pane._proxy_search.sel_anchor is None and mod_pane._proxy_search.sel_end is None)
    check("query still gets the typed char appended (typing keeps operating at the end)",
          mod_pane._proxy_search.query == 'hello worldx')


def test_backspace_deletes_active_selection():
    print("\n[editor-style delete] Backspace with an active selection deletes the SELECTED "
          "substring (not just the last char) and clears the selection")
    _reset_state('hello world')
    label_w = len(mod_pane._SEARCH_BAR_LABEL)
    mod_pane._handle_proxy_mouse(0, label_w + 2, 1)   # anchor at index1 ('e')
    mod_pane._handle_proxy_mouse(32, label_w + 7, 1)  # extend to index6 ('w') -> selects 'ello '
    mod_pane._handle_proxy_search_release()
    check("selection is 'ello ' before backspace",
          mod_pane._proxy_search.query[mod_pane._proxy_search.sel_anchor:mod_pane._proxy_search.sel_end] == 'ello ')
    changed = mod_pane._handle_proxy_search_input('\x7f')
    check("backspace reports a change", changed)
    check("query has the SELECTED substring removed (not just the last char)",
          mod_pane._proxy_search.query == 'hworld')
    check("selection cleared after selection-delete",
          mod_pane._proxy_search.sel_anchor is None and mod_pane._proxy_search.sel_end is None)


def test_backspace_without_selection_still_trims_last_char():
    print("\n[editor-style delete] Backspace with NO active selection still trims the last "
          "char — the pre-existing single-char behavior is unaffected")
    _reset_state('hello')
    check("no selection active", mod_pane._proxy_search.sel_anchor is None)
    changed = mod_pane._handle_proxy_search_input('\x7f')
    check("backspace reports a change", changed)
    check("last char trimmed (regression: unchanged pre-existing behavior)",
          mod_pane._proxy_search.query == 'hell')


def test_kill_line_empties_query():
    print("\n[editor-style delete] Kill-line (_KILL_LINE_CHAR, Cmd+Backspace hypothesis) "
          "empties the WHOLE query")
    _reset_state('some fairly long search query text')
    changed = mod_pane._handle_proxy_search_input(mod_pane._KILL_LINE_CHAR)
    check("kill-line reports a change", changed)
    check("query fully emptied", mod_pane._proxy_search.query == '')


def test_kill_line_ignores_active_selection():
    print("\n[editor-style delete] Kill-line empties the query REGARDLESS of an active "
          "selection (not selection-aware, matches standard editor Cmd+Backspace semantics)")
    _reset_state('hello world')
    label_w = len(mod_pane._SEARCH_BAR_LABEL)
    mod_pane._handle_proxy_mouse(0, label_w + 2, 1)
    mod_pane._handle_proxy_mouse(32, label_w + 7, 1)
    mod_pane._handle_proxy_search_release()
    check("selection is active before kill-line", mod_pane._proxy_search.sel_anchor is not None)
    mod_pane._handle_proxy_search_input(mod_pane._KILL_LINE_CHAR)
    check("query fully emptied (not just the selected substring)", mod_pane._proxy_search.query == '')
    check("selection also cleared", mod_pane._proxy_search.sel_anchor is None)


def test_kill_line_not_silently_swallowed_by_isprintable_fallthrough():
    print("\n[editor-style delete] \\x15 is intercepted by the kill-line branch BEFORE the "
          "isprintable() fallthrough — regression guard for the exact bug being fixed")
    check("'\\x15'.isprintable() is False (confirms the fallthrough risk this branch prevents)",
          mod_pane._KILL_LINE_CHAR.isprintable() is False)
    _reset_state('should be wiped')
    mod_pane._handle_proxy_search_input(mod_pane._KILL_LINE_CHAR)
    check("query was actually cleared, not silently ignored", mod_pane._proxy_search.query == '')


def test_editing_never_clears_matches():
    print("\n[matches] Editing (any form: plain backspace, selection-delete, kill-line) never "
          "clears _proxy_search.matches — Enter remains the sole recompute trigger (confirmed: "
          "neither did the pre-existing plain-backspace/typing path)")
    _reset_state('foo')
    mod_pane._proxy_search.matches = [1, 2, 3]
    mod_pane._proxy_search.match_set = {1, 2, 3}
    mod_pane._handle_proxy_search_input('\x7f')
    check("matches survive plain backspace", mod_pane._proxy_search.matches == [1, 2, 3])
    mod_pane._proxy_search.query = 'bar'
    label_w = len(mod_pane._SEARCH_BAR_LABEL)
    mod_pane._handle_proxy_mouse(0, label_w + 1, 1)
    mod_pane._handle_proxy_mouse(32, label_w + 3, 1)
    mod_pane._handle_proxy_search_release()
    mod_pane._handle_proxy_search_input('\x7f')
    check("matches survive selection-delete backspace", mod_pane._proxy_search.matches == [1, 2, 3])
    mod_pane._handle_proxy_search_input(mod_pane._KILL_LINE_CHAR)
    check("matches survive kill-line", mod_pane._proxy_search.matches == [1, 2, 3])


def test_esc_cancel_clears_selection():
    print("\n[clear] Esc-cancel clears a live drag-selection (alongside the query)")
    _reset_state('hello world')
    mod_pane._proxy_search.focused = True
    label_w = len(mod_pane._SEARCH_BAR_LABEL)
    mod_pane._handle_proxy_mouse(0, label_w + 1, 1)
    mod_pane._handle_proxy_mouse(32, label_w + 5, 1)
    mod_pane._handle_proxy_search_release()
    check("selection exists before Esc", mod_pane._proxy_search.sel_anchor is not None)
    mod_pane._handle_proxy_search_cancel()
    check("selection cleared after Esc",
          mod_pane._proxy_search.sel_anchor is None and mod_pane._proxy_search.sel_end is None)
    check("query also cleared (existing Esc behavior)", mod_pane._proxy_search.query == '')


def test_render_reverse_video_bracket():
    print("\n[render] Active selection renders SGR reverse-video around the exact substring; "
          "no selection renders without it")
    _reset_state('hello world')
    label_w = len(mod_pane._SEARCH_BAR_LABEL)
    mod_pane._handle_proxy_mouse(0, label_w + 2, 1)   # index1
    mod_pane._handle_proxy_mouse(32, label_w + 7, 1)  # index6
    mod_pane._handle_proxy_search_release()
    bar = mod_pane._render_proxy_search_bar(PANE_WIDTH)
    check("reverse-video ON code present", '\033[7m' in bar)
    check("reverse-video OFF code present", '\033[27m' in bar)
    check("the reversed span wraps exactly the selected substring",
          '\033[7mello \033[27m' in bar)

    _reset_state('hello world')  # no selection
    bar2 = mod_pane._render_proxy_search_bar(PANE_WIDTH)
    check("no reverse-video codes when there is no selection", '\033[7m' not in bar2)


def test_session_change_clears_selection():
    print("\n[clear] Session change clears a live drag-selection")
    _reset_state('hello world')
    label_w = len(mod_pane._SEARCH_BAR_LABEL)
    mod_pane._handle_proxy_mouse(0, label_w + 1, 1)
    mod_pane._handle_proxy_mouse(32, label_w + 5, 1)
    mod_pane._handle_proxy_search_release()
    check("selection exists before session change", mod_pane._proxy_search.sel_anchor is not None)

    class _FakeMonitor:
        active_project_filter = None  # keeps parse_proxy_log_forwarded/find_proxy_log_path as safe no-ops
        def _get_newest_main_session(self):
            return '/tmp/pane_search_p3_fake_session'
        def _get_session_start_ts(self):
            return '2026-04-21T10:00:00Z'
        def get_main_session_files(self):
            return []

    mod_pane._proxy_current_main_session = None  # force the session-change branch to fire
    mod_pane._refresh_proxy_data(0.0, False, -9999.0, _FakeMonitor())
    check("selection cleared on session change",
          mod_pane._proxy_search.sel_anchor is None and mod_pane._proxy_search.sel_end is None)


# ORCHESTRATOR

def run_probe_workflow():
    print("=" * 70)
    print("P3 — proxy-pane search bar drag-to-select regression suite")
    print("=" * 70)
    test_col_to_index_ascii()
    test_col_to_index_wide_char()
    test_drag_select_copies_to_clipboard()
    test_plain_click_no_motion_no_clipboard()
    test_release_noop_without_active_drag()
    test_body_row_drag_never_arms_search_selection()
    test_click_elsewhere_clears_selection()
    test_new_input_clears_selection()
    test_backspace_deletes_active_selection()
    test_backspace_without_selection_still_trims_last_char()
    test_kill_line_empties_query()
    test_kill_line_ignores_active_selection()
    test_kill_line_not_silently_swallowed_by_isprintable_fallthrough()
    test_editing_never_clears_matches()
    test_esc_cancel_clears_selection()
    test_render_reverse_video_bracket()
    test_session_change_clears_selection()

    total = len(_RESULTS)
    passed = sum(1 for _, ok in _RESULTS if ok)
    print("\n" + "=" * 70)
    print(f"{passed}/{total} checks passed")
    print("=" * 70)

    from datetime import datetime
    report_dir = Path(__file__).resolve().parent / 'md'
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = report_dir / f'p3_drag_select_regression_test_{ts}.md'
    lines = [f"# P3 drag-select regression — {ts}", "", f"{passed}/{total} checks passed", ""]
    for label, ok in _RESULTS:
        lines.append(f"- [{'x' if ok else ' '}] {label}")
    report_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"\nReport written to: {report_path}")

    if passed != total:
        sys.exit(1)


if __name__ == '__main__':
    run_probe_workflow()
