# Proxy pane search — Milestone 3: drag-to-select on the search bar

**Date:** 2026-08-18 (continues the `pane_search` area — M1 measured feasibility, M2 built the
search bar + fixed the flow_id bug + the UTF-8 keypress bug, M3 adds drag-to-select on the bar)

## Scope

Press-anchors / motion-extends / release-copies-to-clipboard text selection on the proxy pane's
row-1 search bar only. Copy-only — selection never mutates the query itself. No drag-select in
body rows; no changes to worker proxy pane, main pane, or any other pane.

## Mechanics investigated before planning

- **Button-32 motion routing.** `_handle_proxy_mouse`'s `if button >= 32: proxy_hover_row = row`
  was a catch-all swallowing every motion code identically (32 = left button held and moving,
  the SGR `0+32` flag; 35 = plain hover with no button, `3+32`). Resolved by adding a
  `button == 32` branch gated on a new `_proxy_search_dragging` flag, checked BEFORE the generic
  `>= 32` bucket — a body-row drag never sets the flag, so it falls through unchanged.
- **The SGR release sentinel was a dead end.** `run_proxy_loop`'s `elif event is not None: pass`
  (the `(-1,-1,-1)` release sentinel from `read_mouse_event`) did nothing in every pane sharing
  this pattern — confirmed identical in `core/monitor.py`. Routed to a new
  `_handle_proxy_search_release()`, which stays a no-op (`False`) for every release that isn't a
  row-1 drag, so nothing changes for any other pane interaction.
- **Column-to-character mapping needed `_cell_width` awareness, not raw character count.** The
  bar renders `"search: " + query + cursor`; query characters vary in terminal cell width since
  the UTF-8 keypress fix (M2 follow-up) now lets em-dash/ä/ö/ü (1 cell) and emoji (2 cells,
  confirmed via `utils._cell_width`'s `U+1F000-1FAFF`/`U+2600-27BF` ranges) land in the query.
  `_search_col_to_query_index` walks cumulative cell-width from a shared `_SEARCH_BAR_LABEL`
  constant (single source with the renderer, so mapping and rendering can never disagree on
  where the label ends), snapping single-width chars always to the boundary BEFORE them (the
  only possible relative offset within a 1-cell span) and wide chars to the nearer half.

## Design decisions

- **Selection state as char-boundary indices** (`[0, len(query)]`, "cursor positions" between
  characters), not character indices — needed to represent "before the emoji" vs "after the
  emoji" distinctly for a 2-wide character.
- **Plain click (press+release, no motion) makes zero clipboard calls.** `anchor == end` at
  release is the natural signal that no drag occurred; explicitly skipping the clipboard call in
  that case (rather than calling `copy_to_clipboard('')`) was a deliberate choice — an empty-string
  copy on every ordinary click would silently clobber the user's real clipboard content, a much
  worse failure mode than the feature simply doing nothing when there was nothing to select.
- **Row ignored while dragging** — motion events update `sel_end` from `col` alone; a fast drag
  that drifts vertically off row 1 still extends the (inherently single-line) selection rather
  than aborting it.
- **Reverse video (`\033[7m`/`\033[27m`), not a custom BG constant.** Chosen as the terminal-native
  convention for text selection, deliberately distinct from the app's own `SEARCH_MATCH_BG`/
  `SEARCH_CURRENT_BG`/`DIM_YELLOW_BG` palette (M2's match highlights) — this header string is
  built and returned independently of `format.py`'s body-row `_apply_row_backgrounds`, so the
  two highlight mechanisms never interact. Both codes already matched by the existing
  `utils._ANSI_ESCAPE_RE`, confirmed `truncate_visible`'s width math stays correct.
- **Finished selection stays highlighted after release** (not auto-cleared) — the user can see
  what was just copied. Cleared only on: click elsewhere, new keyboard input (top of
  `_handle_proxy_search_input`, covers backspace/Enter/printable uniformly), Esc-cancel, and
  session change — via one shared `_clear_proxy_search_selection()` helper reused at all four
  sites so the clearing behavior can't drift between call sites.
- **Test file: new `p3_drag_select_regression_test.py`, not folded into `p2`.** Unlike the M2
  follow-up UTF-8 fix (a bug fix within the same already-shipped feature, folded into `p2`), this
  is a genuinely new milestone — mirrors `dev/click_ui`'s own established per-milestone
  `p1`/`p2`/`p3`/`p4` file split rather than growing one file indefinitely.

## Verification

- **45/45** new regression checks (`dev/pane_search/p3_drag_select_regression_test.py`) against
  real `pane.py` functions via direct `(button, col, row)` calls (not simulated raw SGR bytes —
  `read_mouse_event`'s own parsing is unchanged and out of scope; button 32 for a held-left-button
  drag is a documented SGR protocol fact taken as given): column-mapping correctness for both
  plain ASCII and a wide-char/emoji query, the full press→motion→release flow (exact clipboard
  substring via a monkeypatched `copy_to_clipboard`, no real `pbcopy` call), plain-click zero-copy
  behavior, release-with-no-drag no-op, body-row drags never arming search-bar selection, all four
  clearing triggers, and the reverse-video render bracket (present only around the exact selected
  substring, absent entirely with no active selection).
- **35/35** `dev/pane_search/p2_search_feature_regression_test.py` (M2 + UTF-8 fix suite)
  re-run clean — the drag-select additions didn't touch any of that surface.
- **32/32** `dev/click_ui/p3_button_click_probe.py` re-run clean — the press/motion/release
  changes to `_handle_proxy_mouse` didn't disturb expand/collapse, copy-symbol, scroll, or
  auto-scroll-to-just-expanded, all still exercised at the header-shifted rows from M2.
- Manual ad-hoc verification (not committed, one-shot) of the column-mapping edge cases before
  writing the formal test — confirmed the emoji left-half/right-half boundary snap behaves as
  designed (col on the emoji's left cell → boundary before it, right cell → boundary after it)
  before committing to the formula in the regression suite.
- **Not verified as of this entry:** live tmux mouse drag via a real trackpad/mouse — the
  synthetic `(button, col, row)` tests exercise every downstream code path exactly as the real
  SGR parser would drive them, but an actual physical drag is the final confirmation, left to the
  user.
