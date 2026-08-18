# Search-bar rollout — sub-milestone 3: worker-proxy pane reaches parity

**Date:** 2026-08-18 (continues the `pane_search` area — sub-milestone 1 extracted the shared
mechanics into `src/search_bar.py` and retrofitted the proxy pane, sub-milestone 2 retrofitted
the main pane; this entry retrofits the worker-proxy pane, `src/proxy_display/worker_proxy_pane.py`)

## Scope

Worker-proxy pane only — `src/proxy_display/worker_proxy_pane.py` (406→541 LOC). The proxy
pane's closest structural twin: same `format_proxy_block`/`render_turn` render pipeline (search
kwargs already threaded through since M2, but always left at their `None`/`None`/`''` defaults
for this pane specifically until now), same forwarded-log data model, same one-sweep
`reconstruct_all_messages` strategy, same `flow_id`-fixed `_lazy_load_messages_forwarded`. Two
genuinely new pieces this milestone had to build: the 2-row header composition, and a
worker-switch search-state reset.

## 2-row header — approach and why it stayed simple

`_PROXY_HEADER_LINES = 1  # fixed... unlike worker_proxy_pane's header this never wraps` — a
comment already present in `pane.py` before this milestone — anticipated exactly this split.
New `_WP_SEARCH_BAR_LINES = 1`. `_format_worker_proxy_header`/`worker_proxy_helpers.py` (the
pure helper building `_worker_proxy_header_regions`) needed ZERO changes — it still computes
region rows RELATIVE to its own top, exactly as before. `_build_worker_proxy_output` shifts
those relative rows by `+_WP_SEARCH_BAR_LINES` right after the helper call — the exact same
rebuild-then-shift pattern the file already used for `worker_proxy_line_map`/
`_worker_proxy_copy_rows` post-`format_proxy_block`. `total_header_lines =
_WP_SEARCH_BAR_LINES + worker_header_lines` (the latter still `visual_line_count`'d off the
worker header alone, unaffected by the fixed-height search bar) replaces the old `header_lines`
everywhere it fed `content_height`/`body_hover`/either line_map/copy_rows shift site.
`_handle_worker_proxy_mouse`'s row==1 branch now intercepts the search bar before the
header-region loop runs; any other row clears a lingering drag-selection first (mirrors proxy),
then the header-region loop and body lookup run exactly as before, just against
already-shifted-to-physical region rows. The pre-existing overdraw print
(`\033[H{header}\033[K`) and `(output, header)` tuple contract needed no changes at all — both
are generic over whatever string `header` holds, and `header` is now simply
`search_bar_line + '\n' + worker_header` instead of `worker_header` alone.

## Worker-switch reset

`_refresh_worker_proxy_data`'s pre-existing `worker_name != _worker_proxy_last_worker_name`
block — which already fires identically whether the switch came from a digit key
(`_handle_worker_proxy_key`) or a header-marker click (`_handle_worker_proxy_mouse`'s
region-hit branch), since both converge on the same IPC selection file + `_worker_proxy_force_
reload` mechanism before this block ever runs — now also calls
`search_bar.handle_search_cancel(_worker_proxy_search)`. One reset site covers both switch
methods. Mirrors `pane.py`'s session-change reset and the same fix (review-caught, not part of
the original main-pane implementation) that landed on the main pane in sub-milestone 2. Unlike
the main pane, no extra per-line offset dict was needed here — like `pane.py`, this pane jumps
at REQ granularity only via the pre-existing `_wp_just_expanded`/`worker_item_positions`
mechanism, so `handle_search_cancel` alone is sufficient. Not reset on the hourly reparse
trigger — same convention as `worker_proxy_expand_states` (entry_idx-keyed state assumes stable
re-indexing across a same-file reparse), matching `pane.py`'s documented rule.

## Decisions confirmed before implementing

- **Bar label `'search: '`** (lowercase, matches `pane.py` — this pane's structural twin) rather
  than the main pane's `'Search: '`.
- **RAM audit parity**: `_worker_proxy_ram_state` gained `_worker_proxy_search.query`/`.matches`
  entries, mirroring `pane.py`'s `_proxy_ram_state` — unlike the main pane's `_main_ram_state`,
  which was deliberately left alone in sub-milestone 2 (pre-existing, no search fields ever
  present there before that milestone; here the pane is greenfield for search, so there was no
  "pre-existing choice" to preserve either way).
- **Always-re-run on Enter** — no correction needed here (unlike the main pane), since this pane
  never had an unchanged-query gate to begin with; `_worker_proxy_search_on_commit` mirrors
  `pane.py`'s `_proxy_search_on_commit` exactly.

## Regression sweep caught one companion fix, outside this pane's own test file

Running the FULL suite set (not just the new `p5` file) surfaced a real, milestone-caused
failure in `dev/click_ui/p1_worker_selection_click_probe.py::test_worker_proxy_header_wrap_
straddle`: that test calls `_format_worker_proxy_header` DIRECTLY, bypassing
`_build_worker_proxy_output`'s new region-shift step — before this milestone that was harmless
(row 1 was the header's own top, nothing else claimed it); after, an unshifted row-1 region
segment collided with `_handle_worker_proxy_mouse`'s new search-bar press branch, and the
click assertion for that one segment failed (32/35). Fixed by replicating the identical
`+_WP_SEARCH_BAR_LINES` shift inside the test itself, immediately after the direct
`_format_worker_proxy_header` call — same shift logic as production, applied by the test since
it deliberately bypasses the function that normally applies it. 35/35 after the fix. This
mirrors the M2 proxy-pane precedent, where the equivalent test in the same file
(`p3_button_click_probe.py`'s proxy-pane case) needed a rewrite for the new header+shift
contract — confirms the "update the dependent test when a pane's row contract changes" pattern
holds across milestones, not just for the pane being migrated.

**Also discovered, confirmed PRE-EXISTING and unrelated:** `dev/display/test_hover_map.py`
fails with `ImportError: cannot import name '_parse_log_file' from
'src.proxy_display.parser'` — `parser.py` was not touched by this milestone (confirmed via
`git diff`, zero lines changed) and `_parse_log_file` does not exist anywhere in
`src/proxy_display/` on this branch at all; this is a stale test referencing a function removed
at some earlier, unrelated point. Left unfixed — out of this milestone's scope, flagged for
whoever next touches that test file.

## Verification

- **77/77** new regression checks (`dev/pane_search/p5_worker_proxy_pane_parity_test.py`)
  against real `src.proxy_display.worker_proxy_pane` functions (via `importlib.import_module`,
  real calls — not mocked): state shape (SearchState instance, lowercase label), 2-row header
  composition (header-region rows >=2, body rows past both header rows), a header-marker click
  at the shifted row still selecting the worker, the full drag-select
  press→motion→release→clipboard flow, plain-click zero-copy, release-no-op-without-drag,
  body-row-click selection-clear, body-row-drag never arming search dragging, selection-delete
  vs plain Backspace, kill-line, editing-never-clears-matches, a REAL Enter-triggered search
  with `_worker_proxy_log_path=None` (skips reconstruction, direct `build_search_matches`),
  always-re-run-on-Enter (new entry appended between two same-query Enters, match count grows),
  the reconstruction-merge path with `_worker_proxy_log_path` SET (self-contained 2-line
  forwarded-delta fixture, confirms `messages` populates from `None` and the reconstructed
  content becomes findable), `n`/`N` wrap in both directions reusing `_wp_just_expanded`, Esc
  clearing state while the bar stays visible, the reverse-video selection render bracket, and
  the worker-switch reset (real `_refresh_worker_proxy_data` call, IPC selection file +
  `list_workers`/`find_worker_proxy_log` monkeypatched to a synthetic worker-B switch).
- **35/35** `dev/click_ui/p1_worker_selection_click_probe.py` — 32/35 before the companion fix
  above, 35/35 after.
- **48/48** `dev/pane_search/p2_search_feature_regression_test.py`, **62/62**
  `dev/pane_search/p3_drag_select_regression_test.py`, **77/77**
  `dev/pane_search/p4_main_pane_parity_test.py` — all proxy/main-pane suites re-run clean (zero
  files this milestone touched outside `worker_proxy_pane.py`, one dev/ test, and DOCS.md).
- **32/32** `dev/click_ui/p3_button_click_probe.py`, **37/37** `dev/click_ui/p2_copy_click_probe.py`
  — re-run clean.
- **14/14 byte-identical** via `dev/proxy_dual_log/A_render_refactor_proof.py --mode verify`
  against the pre-existing `baseline_20260818.json` — confirms zero regression to
  `format.py`/`render_turn.py`'s own rendering (this milestone only added kwargs at
  `worker_proxy_pane.py`'s call sites; `format.py` already had these kwargs default to
  no-op-for-non-passing-callers since M2).
- Import-level sanity: `src.proxy_display.worker_proxy_pane` imports cleanly post-migration
  (`ast.parse` + real `importlib.import_module`).
- **Not verified as of this entry:** live tmux/terminal visual rendering of the worker-proxy
  pane's 2-row header and search bar, the `/` focus hotkey's live dispatch (a one-line branch
  inside `run_worker_proxy_loop`'s while-loop, not unit-tested at the loop level — consistent
  with every prior milestone in this area), and real trackpad drag-select. Standard "user visual
  check" gate, same as every prior entry in this area.
