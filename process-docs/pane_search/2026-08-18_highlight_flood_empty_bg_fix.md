# Proxy pane search — follow-up: highlight still flooded on empty-background rows

**Date:** 2026-08-18 (continues the `pane_search` area — follow-up to the earlier highlight-scope
fix in this same area, same date)

## Symptom (live-confirmed by the user, self-reproduced byte-for-byte)

Despite the earlier highlight-scope fix (substring-only, sentinel-based restore), the highlight
STILL flooded to end-of-line on every row whose `chosen_bg` resolved to the empty string —
`ZEBRA_BG_A = ''`, hit on every second zebra row (and any row with no background override at
all). `ZEBRA_BG_B` rows (non-empty) restored correctly, which is exactly why the earlier fix's
own verification (a synthetic `DIM_YELLOW_BG`-flavored line) missed this — it happened to only
exercise the non-empty case.

## Root cause — confirmed against the code before applying the handed-down fix

`_apply_row_backgrounds`'s sentinel substitution was `line.replace(_BG_RESTORE_SENTINEL,
chosen_bg)`. When `chosen_bg == ''`, this DELETES the sentinel outright — there is nothing left
in the string to close the search-highlight background before the row's trailing `\033[K`
(erase-to-EOL), so the terminal keeps painting the highlight color across the erased region to
the end of the row. Reproduced exactly with the handed-down repro:
`_apply_row_backgrounds([line], [('msg',5,0)], set(), None, None, 120, 0)` on a line containing
`SEARCH_CURRENT_BG + text + _BG_RESTORE_SENTINEL` — output was
`'    <SEARCH_CURRENT_BG>...Diff\x1b[K\x1b[0m'`, no reset code between the matched text and the
erase-to-EOL.

## Fix

`_BG_RESTORE_SENTINEL` substitution value changed to `chosen_bg if chosen_bg else '\033[49m'` —
an explicit default-background reset when the row has no BG override of its own, instead of
deleting the sentinel with nothing to replace it. The LEADING `f'{chosen_bg}{trunc}'` prefix
does NOT need the analogous fix: `''` there is harmless because the PRIOR row's own trailing
`RESET` (`\033[0m`, full reset) already cleared the terminal's active background by the time
this row starts printing — at that position, omission genuinely means "no override, use
whatever's already clean." Mid-line, after a real color (the search marker) was already set,
omission does not restore anything — it must be an explicit reset instead. Checked and confirmed
this distinction before concluding no change was needed at the leading-prefix site.

## Verification

- **Confirmed the exact handed-down repro against the code BEFORE fixing** — verified the
  diagnosis was accurate, not assumed.
- **Confirmed the fix resolves it**, via the same repro: `\033[49m` now appears between the
  matched text and `\033[K`; sanity-checked the non-empty-`chosen_bg` (`ZEBRA_BG_B`) case is
  unaffected by the fix (still substitutes to the real color as before).
- Added the exact repro as a permanent regression case,
  `dev/pane_search/p2_search_feature_regression_test.py::
  test_sentinel_resolves_to_default_bg_not_empty_string_on_zebra_a_rows` — **verified this test
  FAILS against the pre-fix code** (`git stash` on just `format.py`, re-ran: 2 of the 4 checks
  failed, matching the exact symptom) **and passes post-fix** — a genuine regression guard, not
  a test that would have passed either way.
- **48/48** `p2_search_feature_regression_test.py` (44→48, +4 new checks).
- **62/62** `p3_drag_select_regression_test.py`, **32/32** `p3_button_click_probe.py` — unaffected,
  re-run clean (this fix is scoped entirely to `_apply_row_backgrounds`'s sentinel substitution).
- **14/14 byte-identical** via `A_render_refactor_proof.py`, baseline captured immediately before
  this fix — confirms zero regression to any non-search rendering path.
- **Not verified as of this entry:** live tmux visual confirmation that the flood is actually
  gone in a real terminal — the ANSI byte-sequence structure is proven correct via the exact
  repro, but visual confirmation is the user's own next step, same as every prior entry in this
  area.
