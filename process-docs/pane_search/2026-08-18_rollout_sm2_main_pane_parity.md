# Search-bar rollout — sub-milestone 2: main pane reaches parity with the proxy pane

**Date:** 2026-08-18 (continues the `pane_search` area — sub-milestone 1 extracted the shared
mechanics into `src/search_bar.py` and retrofitted the proxy pane onto it, the rollout's
reference implementation; this entry retrofits the main pane, `core/monitor.py` +
`core/monitor_display.py`)

## Scope

Main pane only. Consumed `src/search_bar.py`'s `SearchState`, `render_search_bar`,
`col_to_query_index`, `handle_search_input` (Backspace/selection-delete/kill-line/Enter with an
injected `on_commit`), the drag press/motion/release handlers (injected `copy_to_clipboard_fn`),
and `KILL_LINE_CHAR`. Deleted `core/monitor_display.py`'s private `_highlight_query_in_line`
duplicate in favor of `utils.highlight_query_in_line` (byte-identical algorithm; confirmed
identical back in the `2026-08-18_search_highlight_scope_fix.md` entry, which had left the main
pane's copy untouched specifically because that fix was proxy-focused). Workers, tokens,
warnings, gpu, news panes explicitly out of scope for this milestone.

## Old bar vs the shared mechanics — what changed

The pre-migration main pane had an older, independently-built search bar (predates the proxy
pane's `/`+`n`/`N`+drag-select design): click-driven `[←]`/`[→]` arrow regions for match
navigation instead of `n`/`N` keys, no drag-to-select, no editor-style deletion, and its own
private `_highlight_query_in_line` copy. Three decisions (confirmed with the user before
implementing):

1. **`/` focus hotkey added** — the main pane previously only supported click-to-focus; the
   proxy pane (reference) supports click OR `/`. Zero collision risk (`/` was unbound on the
   main pane; the only other hotkey there is `y`).
2. **Click-arrows removed, `n`/`N` keys added** — matches the reference exactly (`search_bar`'s
   shared `render_search_bar` doesn't render arrows at all; there is no shared arrow-click
   mechanic to consume). Flagged as a genuine user-habit change (a click-arrow user loses that
   mouse-only navigation path) — no `dev/` test locked in the old arrow behavior (grepped for
   `[←]`/`[→]` across `dev/`, zero hits), so nothing broke mechanically, only the interaction
   habit.
3. **Enter-gate dropped, not preserved.** The pre-migration main pane gated Enter's match rebuild
   on `query != _search_cached_query` (an optimization noted as a deliberate main-pane-only
   divergence back in `2026-08-18_m2_search_bar_implementation.md`: *"the main pane's
   `core/monitor_display.py` search bar DOES gate on this"*). Original plan was to preserve this
   gate as a legitimate pane-specific optimization sitting in the injected `on_commit` callback
   (orthogonal to the shared mechanics). Corrected during the Go decision: DROP the gate, align
   to the proxy pane's always-re-run convention — a repeated Enter with an unchanged query now
   picks up events appended to `main_event_buffer` since the last search; the recompute cost is a
   substring scan over the in-memory buffer, cheap enough that the optimization wasn't worth the
   behavioral inconsistency with the reference pane. `_search_cached_query` deleted entirely.

## Other behavior changes, inherent in adopting the shared functions (not separately decided —
the direct consequence of "consume the shared render/input functions verbatim")

- **Edit-clears-matches → matches persist stale until Enter.** The pre-migration main pane
  cleared `_search_matches`/`_search_match_set` on every keystroke; `search_bar.handle_search_input`'s
  convention (matching the proxy pane, confirmed in `2026-08-18_editor_style_deletion.md`) is
  "Enter is the sole recompute trigger" — edits never touch matches. Migrating onto the shared
  function makes the main pane match this convention.
- **Row-1 `HOVER_BG` baseline removed.** The old bar painted the whole row-1 background in
  `HOVER_BG`; `search_bar.render_search_bar` has no background baseline at all (by design — "one
  visual search language across panes", per the M2 proxy entry). `WHITE`/`HOVER_BG` became dead
  imports in `monitor_display.py`, removed.
- **`_search_committed` dropped as dead state.** Grepped every read-site before removing:
  set on Enter/edit/cancel but never READ for any branch decision (pre-existing vestigial state,
  not introduced by this migration) — confirmed safe to drop, not a behavior change.

## Implementation shape

Mirrors the proxy pane's thin-wrapper pattern, split across the main pane's existing two-file
structure (proxy keeps everything in one file; main pane splits render/state into
`monitor_display.py` and key/mouse routing into `monitor.py` — preserved, not collapsed).
`_main_search: search_bar.SearchState` and `_SEARCH_BAR_LABEL = 'Search: '` live in
`monitor_display.py` (parallel to where the old flat globals lived), referenced as
`_md._main_search` / `_md._SEARCH_BAR_LABEL` from `monitor.py` — single source of truth for the
label instead of duplicating the string in both files. `monitor.py` gained
`_main_search_on_commit` (Enter callback), `_jump_search_match` (n/N), `_handle_main_search_release`
(the SGR `(-1,-1,-1)` release sentinel, previously a bare no-op in this pane, now wired exactly
like proxy's `_handle_proxy_search_release`); `_handle_main_mouse`'s row-1 branch dropped the
`col >= pw-2`/`pw-6` arrow-hit checks entirely in favor of `search_bar.handle_search_mouse_press`,
and gained a `button == 32 and _main_search.dragging` branch for drag-motion (checked before the
generic `button >= 32` hover bucket, same guard order as proxy) plus a `clear_selection` call on
any row≥2 click (a lingering drag-selection highlight now clears the same way proxy's does).

## Not carried over (flagged, left as pre-existing, out of scope)

`_refresh_main_data` (session change handling) never resets `_main_search` — the proxy pane's
equivalent (`_refresh_proxy_data`) explicitly calls `search_bar.handle_search_cancel` on session
change; the main pane's pre-migration code had the identical gap (its own flat
`_search_matches` list was never reset on session change either), so this migration is not a
regression, just an unaddressed latent issue, documented in `core/DOCS.md`'s Gotchas for the next
person touching that function.

## Verification

- **72/72** new regression checks (`dev/pane_search/p4_main_pane_parity_test.py`) against real
  `src.core.monitor`/`src.core.monitor_display` functions (via `importlib.import_module`, real
  calls — not mocked) with synthetic `main_event_buffer` entries: state-shape migration (dead
  flags gone, private highlight duplicate gone), bar renders row 1 with no arrows and no
  `HOVER_BG`, `col_to_query_index` against the pane's own label, the full press→motion→release
  drag flow (exact clipboard substring via a monkeypatched `copy_to_clipboard`), plain-click
  zero-copy, release-no-op-without-drag, body-row click clears selection / never arms a
  body-row drag, new-input clears selection, selection-delete Backspace vs plain Backspace,
  kill-line (with and without an active selection), editing-never-clears-matches across all three
  deletion forms, a REAL Enter-triggered search finding the right event indices, the
  always-re-run-on-Enter correction (asserted by appending a new event between two same-query
  Enters and confirming the second Enter's match count grows), `n`/`N` wrap in both directions,
  Esc clearing state while the bar stays visible, the reverse-video selection render bracket, and
  the highlight wrapping only the literal matched substring (not a whole-row prefix) via a real
  `render_main_buffer` call.
- **48/48** `dev/pane_search/p2_search_feature_regression_test.py`, **62/62**
  `dev/pane_search/p3_drag_select_regression_test.py` — proxy pane suites, re-run clean (this
  milestone touched zero `proxy_display/` files).
- **32/32** `dev/click_ui/p3_button_click_probe.py`, **37/37** `dev/click_ui/p2_copy_click_probe.py`
  — re-run clean; `p2_copy_click_probe.py::test_main_pane_copy_click` is the one pre-existing
  suite that calls the real `_handle_main_mouse`/`render_main_buffer` for the main pane (body-row
  copy clicks only, never row 1) — confirms the row-1 rewrite didn't disturb body-row copy
  behavior.
- **14/14 byte-identical** via `dev/proxy_dual_log/A_render_refactor_proof.py --mode verify`
  against the pre-existing `A_render_refactor_proof_reports/baseline_20260818.json` — confirms
  zero impact on `proxy_display/` rendering (expected, since this milestone touched only
  `core/`).
- Import-level sanity: both `src.core.monitor` and `src.core.monitor_display` import cleanly
  post-migration (`ast.parse` + real `importlib.import_module`, no mocking).
- **Not verified as of this entry:** live tmux/terminal visual rendering of the main pane's bar,
  the `/` focus hotkey's live dispatch (a one-line branch inside `run_main_loop`'s while-loop,
  same as every other pane's inline hotkey routing — not unit-tested at the loop level, consistent
  with how `p2`/`p3` never test `run_proxy_loop`'s own while-loop dispatch either), and drag
  selection via a real trackpad/mouse — remain user visual/live checks, the last verification gate
  for this feature, same as every prior entry in this area.
