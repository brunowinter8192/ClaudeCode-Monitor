# Proxy pane search — follow-up: highlight scope fix (whole-row → browser-find substring)

**Date:** 2026-08-18 (continues the `pane_search` area — follow-up to M2, based on live user
feedback after the search feature shipped)

## Symptom (user-reported, live)

The search highlight painted the ENTIRE row full-width, not just the matched text. Desired:
content lines highlight only the literal query substring occurrence(s) (browser-find style);
REQ headers highlight only their own text extent (▶/▼ symbol through the last badge), not the
padding out to the pane edge.

## Root cause

M2's mechanism embedded `SEARCH_MATCH_BG`/`SEARCH_CURRENT_BG` as a whole-line PREFIX, then
`_apply_row_backgrounds` detected `SEARCH_...BG in line` and hoisted it to `chosen_bg` — the
exact same code path used for `DIM_YELLOW_BG`/`DIM_GREEN_BG` (strip/inject). That hoist prepends
`chosen_bg` at column 0 and the row ends in `\033[K` (erase-to-EOL) + `RESET`, painting the
entire row. Strip/inject's own inline spans (`render_sections.py`/`render_messages.py`) never
locally reset the background after themselves — they rely on `SOFT_RESET` (`\033[39m`,
foreground-only) and let the BG bleed to end-of-line, which is exactly what makes the
hoist-to-whole-row trick work for THEM (a reasonable design for "annotate this whole line as
stripped/injected"). Search's UX goal is different (browser-find substring highlight) but
happened to share the mechanism in M2.

## The correct mechanism already existed — ported, not reinvented

`core/monitor_display.py`'s `_highlight_query_in_line(line, query, match_bg)` (the main pane's
own search bar) already does browser-find-style highlighting correctly: finds literal
substrings in the ANSI-stripped text, wraps each occurrence in the original ANSI-bearing string
with `{match_bg}{chunk}\033[49m`. Its hardcoded `\033[49m` restore is correct there specifically
because the main pane has NO per-row background at all (confirmed: its row assembly is just
`f"{trunc}\033[49m\033[K{RESET}"`, no zebra/hover prefix) — `\033[49m` (reset to terminal
default) is indistinguishable from "no override" for that pane.

**The proxy pane is different — real per-row backgrounds (zebra/hover/strip/collision) must
survive past a highlighted substring.** A naive port using `\033[49m` would blow a visible hole
back to the terminal's raw default background after every highlighted chunk on zebra-B/hover/
strip-annotated rows — a new defect the naive port would have introduced. The row's correct
restore value (`chosen_bg`) isn't known until `_apply_row_backgrounds` runs, which happens AFTER
`render_turn.py` has already built the line string — the highlighter can't know the right
restore color at embed time.

## Fix — two-phase design

1. Promoted a generalized `highlight_query_in_line(line, query, match_bg, restore_bg='\033[49m')`
   to `src/utils.py` (default arg preserves the main pane's exact existing behavior unchanged).
   `core/monitor_display.py`'s own private copy was deliberately left untouched — out of scope
   for this proxy-pane-focused fix, and the risk of touching an already-working, unrelated pane
   wasn't worth it for a pure DRY win. Noted for a later cleanup: unify when a rollout touches
   that file anyway (per explicit direction — not addressed here).
2. `render_turn.py` embeds highlights using a SENTINEL restore code instead of a real color:
   `_BG_RESTORE_SENTINEL = '\033[999m'` (module constant in `format.py`) — an out-of-range but
   syntactically valid SGR code, so the EXISTING `utils._ANSI_ESCAPE_RE` (`\x1b\[[0-9;]*m`)
   strips it as zero-width everywhere that regex already runs (confirmed: copy-button padding
   math in `_build_req_header_line`, `truncate_visible`'s width computation) — no separate
   sentinel-awareness needed anywhere else.
3. `_apply_row_backgrounds` (format.py), AFTER determining `chosen_bg` for a row, does
   `line.replace(_BG_RESTORE_SENTINEL, chosen_bg)` — text after a highlighted chunk correctly
   resumes the row's real background instead of a raw-default hole.

**Content lines:** `render_turn._mark_search_lines` rewritten from whole-line-prefix to
`highlight_query_in_line(line, query, marker, _BG_RESTORE_SENTINEL)` per line — only the literal
query substring(s) get colored.

**Headers:** `render_turn._build_req_header_line` wraps only the `body` local var (everything
from `req_symbol` through `tag_badge`, i.e. AFTER the leading 2-space indent and BEFORE
`SOFT_RESET`) in `marker + body + sentinel` — the copy-button padding appended afterward is
never touched, satisfying "text extent only, not the padding to the pane edge".

**Priority chain reverted:** search markers removed entirely from `_apply_row_backgrounds`'s
`elif ... in line` hoist chain — search is no longer competing for the row's background, it's an
independent overlay applied on top of whatever `chosen_bg` won (hover/strip/inject/zebra/
collision), visible consistently everywhere including on a hovered or strip/inject-annotated
row. Chain reverts to the pre-M2 order: `hover > DIM_YELLOW_BG > DIM_GREEN_BG > collision >
zebra`. `SEARCH_MATCH_BG`/`SEARCH_CURRENT_BG` imports removed from `format.py` (no longer
referenced there — still imported in `render_turn.py` where the markers are actually embedded).

## Verification

- **Real end-to-end render checks (ad-hoc, real `format_proxy_block` call, not committed as a
  standalone script but confirmed before writing regression assertions):** a synthetic entry with
  a matched message, rendered collapsed and expanded — confirmed the header's leading 2-space
  indent is uncolored, the marker sits immediately after it, and (for content lines) the marker
  wraps exactly the matched substring with the row's indent/DIM styling untouched before it.
  Directly unit-tested `_apply_row_backgrounds` with a synthetic line combining a `DIM_YELLOW_BG`
  span, a `SEARCH_CURRENT_BG` span, and trailing text — confirmed the trailing text correctly
  resumes `DIM_YELLOW_BG` (not a raw-default hole), proving the sentinel-substitution interplay
  with strip/inject spans works as designed. Directly tested `_build_req_header_line` with
  `copy_feedback` provided — confirmed the sentinel sits before the copy-button padding position
  in the string, and the leading indent sits before the marker.
- **40/40** `dev/pane_search/p2_search_feature_regression_test.py` — the two highlight-scope
  tests (`test_collapsed_hit_marks_req_row`, `test_expanded_hit_marks_line`) tightened with new
  checks: marker position is not column-0 (rules out a whole-row prefix), marker sits immediately
  adjacent to the matched substring for content lines, and no unsubstituted
  `_BG_RESTORE_SENTINEL` leaks into final output. All other M2/UTF-8-fix checks unaffected.
- **45/45** `dev/pane_search/p3_drag_select_regression_test.py` and **32/32**
  `dev/click_ui/p3_button_click_probe.py` re-run clean — this fix touches only the search
  highlight mechanism, no interaction with drag-select or chrome click-parity.
- **14/14 byte-identical** via `dev/proxy_dual_log/A_render_refactor_proof.py`, baseline captured
  from the code as it stood immediately before this fix and verified against the code after —
  confirms none of the 14 existing NON-search fixture cases (branch1/2, dual formats, tools,
  system blocks, standalone haiku, copy feedback, hover/scroll, collision, expand fixpoint)
  changed at all, since none of them exercise `search_query`.
- **Not verified as of this entry:** live tmux rendering of the actual highlight colors/scope —
  the mechanism-level checks above prove the ANSI byte sequences are structured correctly, but
  visual confirmation in a real terminal is the user's final gate, same as every prior milestone
  in this area.
