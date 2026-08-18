# Proxy pane search — follow-up: editor-style deletion in the search bar

**Date:** 2026-08-18 (continues the `pane_search` area — follow-up to M3's drag-to-select)

## Ask

Two editor-standard deletion behaviors on the search bar: (1) Backspace while a drag-selection
is active deletes the selected text (upgrading selection from copy-only to also an edit target);
(2) Cmd+Backspace kills the whole line.

## Finding that corrected the task's stated assumption

The task's framing assumed M2 already clears `_proxy_search_matches`/`_match_set` on query edits
("probably yes, consistent with how typing already behaves"). Checked `_handle_proxy_search_input`
directly: **it does not** — only `_proxy_search_query` mutates on Backspace/typing; matches stay
stale from the last Enter until the next Enter recomputes them. Reported this correction before
implementing; confirmed by the user — Enter remains the sole recompute trigger, and the new
deletion paths (selection-delete, kill-line) follow the SAME convention (do not clear matches)
rather than introducing a new "clear on edit" behavior that would have also changed the
pre-existing plain-Backspace/typing path.

## Design

- **Selection-delete Backspace:** `_handle_proxy_search_input` already called
  `_clear_proxy_search_selection()` unconditionally at the top (M3's "new input clears
  selection" behavior) — before this fix, that erased the range before Backspace's own branch
  could see it. Now the sorted `(start, end)` range is captured FIRST, then the clear runs, then
  the Backspace branch uses the captured range (if non-empty) to delete `query[:start] +
  query[end:]`, falling back to the pre-existing `query[:-1]` trim when no range was captured.
  Release-copy (M3, unchanged) and Backspace-delete are independent: release always copies on
  mouse-up; a later Backspace additionally deletes the same (still-highlighted) selection.
- **Kill-line:** new named constant `_KILL_LINE_CHAR = '\x15'` (Ctrl-U), documented explicitly
  as an unconfirmed hypothesis — Cmd+Backspace is normally consumed by the terminal app itself;
  on macOS, Ghostty most likely remaps it to Ctrl-U before this process ever sees it. The
  constant's sole purpose is making a rebind trivial once the user's live test captures the real
  sequence. Checked BEFORE the Backspace/Enter/printable branches — `'\x15'.isprintable()` is
  `False` in Python, so before this branch existed the character would have silently fallen
  through every check to a harmless no-op (`return had_selection`); intercepting it earlier was
  the whole point, and is directly regression-guarded (`test_kill_line_not_silently_swallowed_
  by_isprintable_fallthrough`). Kill-line empties the query unconditionally, independent of any
  active selection — not selection-aware, matching standard editor Cmd+Backspace semantics
  (this bar's "cursor" is always conceptually at the end of the query regardless).
- **Matches untouched by any of the three deletion paths** (plain Backspace, selection-delete,
  kill-line) — per the corrected finding above.

## Verification

- **62/62** `dev/pane_search/p3_drag_select_regression_test.py` (up from 45) — new coverage:
  selection-delete removes exactly the selected substring and clears the selection; plain
  Backspace with no selection still trims the last char (regression guard); kill-line empties
  the query with and without an active selection present; the `isprintable()` fallthrough
  regression guard; matches survive all three deletion forms.
- **44/44** `dev/pane_search/p2_search_feature_regression_test.py` (up from 40) — one new case
  running an ACTUAL Enter-triggered search (real `_run_proxy_search` call path, not mocked),
  then kill-line, confirming the query empties while the matches from that real run stay
  untouched.
- **32/32** `dev/click_ui/p3_button_click_probe.py` re-run clean — this fix touches only keyboard
  input handling in the focused search bar, no interaction with mouse click-parity or chrome.
- Direct ad-hoc sanity check (not committed, one-shot) before writing the formal regression
  suite: confirmed `'\x15'.isprintable()` is `False`, confirmed selection-delete produces the
  exact expected substring removal, confirmed matches survive all three edit forms — all matched
  the formal test assertions written afterward.
- **Not verified as of this entry:** the actual Cmd+Backspace → `\x15` mapping hypothesis itself
  — this requires the user's live keyboard test in a real Ghostty/tmux session; if the captured
  sequence differs, `_KILL_LINE_CHAR` is a one-line rebind, by design.
