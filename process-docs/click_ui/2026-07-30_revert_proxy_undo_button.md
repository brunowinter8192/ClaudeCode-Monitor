# 2026-07-30 — Revert: proxy pane `[undo]` button and its header

## Problem

User decision after live-testing milestone 3: the proxy pane's `[undo]` button is not wanted.
`u` is the preferred interaction and stays. The one-line header (`PROXY  [undo]`,
`_format_proxy_header` in `format.py`) existed SOLELY to host that button — this pane had no
header before milestone 3. With the button gone, a title-only header costs a display line for
nothing, so it goes too, along with everything the header/body split had forced onto
`_build_proxy_output`: `content_height`, `header_lines` (via `visual_line_count`), the
`proxy_line_map`/`_proxy_copy_rows` `+ header_lines` shift, the `(output, header)` tuple return,
and the caller's overdraw print.

## Approach: targeted unwind, not a commit revert

Milestone 3's commit (`e7f95ed`) and milestone 4's width-guard fix (`e97550a`) both touched OTHER
files in the same commits (workers freeze button, warnings refresh button, gpu/news buttons,
`utils.compute_header_rule_len`). A `git revert` of those commits would have taken all of that
down too — explicitly out of scope ("do NOT touch the workers or warnings buttons"). Instead,
`src/proxy_display/pane.py` and `src/proxy_display/format.py` were edited by hand back to their
exact pre-milestone-3 shape, using `git log`/`git diff` against `e7f95ed^` as the reference for
what milestone 3 had added to THESE TWO FILES specifically (imports, module state, the header
function, the three call sites it touched in `pane.py`).

**Verified exact, not approximate:** after the edit, `git diff e7f95ed^ -- src/proxy_display/pane.py`
and the same for `format.py` both produced EMPTY output — both files are now byte-identical to
their state immediately before milestone 3 touched them. This is stronger evidence than "looks
right" — it proves no vestigial plumbing, no leftover comment, no stray whitespace survived.

## What was removed

- `format.py`: `_format_proxy_header` function entirely, plus its now-unused imports (`WHITE`,
  `_ANSI_ESCAPE_RE` from `utils`) — both were added in milestone 3 solely for that function;
  `DIM` reverts to being imported-but-unused again (confirmed via `git show e7f95ed^` that `DIM`
  was ALREADY a dead import before milestone 3 — pre-existing, not something to additionally
  clean up here, matching the "don't fix unrelated pre-existing issues" precedent from earlier
  milestones).
- `pane.py`: the `_format_proxy_header` import, the `_proxy_header_regions` module dict, the
  `Tuple` typing import (only used for that dict's annotation), the header-region check at the
  top of `_handle_proxy_mouse`'s `button == 0` branch, `_build_proxy_output`'s entire
  header-construction block (`header = _format_proxy_header(...)`, `header_lines =
  visual_line_count(...)`, `content_height = max(1, pane_height - header_lines)`,
  `viewport_lines_n = max(1, content_height - 1)` computed OUTSIDE the loop, the two
  `proxy_line_map`/`_proxy_copy_rows` `+ header_lines` shift blocks after each
  `format_proxy_block` call), its `(output, header)` return, and `run_proxy_loop`'s overdraw
  print (`\033[H{header}\033[K`) — back to a plain `print(output)`.
- `_undo_proxy_expand()` itself: UNTOUCHED. `u` still calls it, unchanged, exactly as before
  milestone 3 ever existed.

## Verification

`dev/click_ui/p3_button_click_probe.py`'s proxy test was rewritten from
`test_proxy_undo_button` (button region, click/key parity, empty-stack styling) to
`test_proxy_pane_reverted_no_header`, proving the REVERT is complete and that everything the
header/body split had touched still works correctly at unshifted rows: `_build_proxy_output`
returns a plain string again; no `[undo]` text anywhere in the output; no leftover
`_proxy_header_regions` attribute or `_format_proxy_header` function; row 1 resolves to a real
body `REQ` key, not a header; a click on row 1 toggles expand/collapse directly (no header
offset); the copy-symbol click still fires at its own row; `u`/`_undo_proxy_expand` still undoes
the last toggle; the scroll wheel still works; and the just-expanded entry still stays visible in
the very next render (auto-scroll-to-just-expanded intact, exercised via a real synthetic
3-entry set built with the same `_make_proxy_entry` fixture shape `dev/display/test_hover_map.py`
uses). **28/28 checks passing** on the first full run (down from 24, since the workers-freeze and
warnings-refresh tests were untouched and kept passing; the proxy section grew from 12 checks to
14 with the added row-1/no-collision/auto-scroll assertions).

Full regression suite re-run clean: milestone-1 probe 35/35, milestone-2 probe 37/37,
milestone-4 probe 53/53, `pane_error_log` exception-guard suite 52/52 — specifically checked
BOTH `[proxy]` (the reverted loop, still guards correctly) and `[worker_proxy]` (the OTHER pane
that legitimately keeps its header/body split — read `worker_proxy_pane.py` first to confirm it
shares no machinery with what was being removed here; it imports only `format_proxy_block` from
`.format`, never `_format_proxy_header`, and owns its own separate
`_worker_proxy_header_regions`/`_format_worker_proxy_header` pair in `worker_proxy_helpers.py` —
confirmed untouched and still fully passing, 5/5 checks each). `dev/display/test_hover_map.py`:
40/40 passing checks unchanged (its one pre-existing unrelated crash reproduces identically).

Not verified: a real mouse click / `u` keypress through an actual terminal emulator against a
live tmux pane — same boundary as every prior milestone in this effort, needs a human check.

## Scope note

Left untouched, as instructed: the workers-pane freeze button and the warnings-pane refresh
button (milestone 3); every gpu/news change (milestone 4); `worker_proxy_pane.py`'s own
legitimate header/body split; all keyboard handling everywhere.
