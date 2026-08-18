# Search-bar rollout -- FINAL milestone, sub-milestones 6-8 bundled: warnings + gpu + news panes

**Date:** 2026-08-18 (continues and CONCLUDES the `pane_search` area -- sub-milestone 1 extracted
the shared mechanics and retrofitted the proxy pane; 2 the main pane; 3 the worker-proxy pane; 4
the tokens pane; 5 the workers pane; this entry retrofits the final three panes -- warnings, gpu,
news -- in one bundled plan/Go/commit stream, per the approved decision that all three are
structurally simple enough to not need separate milestones)

## Scope

- **Warnings** (`src/panes/warnings_pane.py` + `warnings_render.py`): 1-level expand
  (`error_expand_states[idx]`), full data always loaded.
- **GPU** (`src/gpu_pane/pane.py`): flat, small live-fetched lists, NO scroll infra at all.
  Approved decision: full bar mechanics, HIGHLIGHT-ONLY, no jump-to-match, keep the N/M counter.
- **News** (`src/news_pane/pane.py` ONLY -- `log_pane.py` EXCLUDED per decision): same reduced
  scope as gpu, same structural shape.

## Warnings -- the explicitly-required verification, and what it found

Before assuming the same collateral fix every prior pane needed, `warnings_render.py`'s row-bg
loop was read at line level, per the milestone's own explicit instruction. Finding: it ALREADY
used `DIM_YELLOW_BG in line` (substring form) -- **not** `.startswith()`. This is the ONLY pane
in the entire rollout whose pre-existing detection needed zero collateral fix. Made into a
permanent regression guard (`test_warnings_dim_yellow_bg_already_used_in_not_startswith`, via
`inspect.getsource`) rather than left as a one-time finding, so a future refactor that
accidentally reintroduces `.startswith()` gets caught.

`ZEBRA_BG_A == ''` (the actual sentinel-bug trigger, same shared constant every pane hits) DID
still apply -- `search_bar.resolve_bg_restore` threaded into that same, already-correct loop.
Two independent findings, not one: "no `.startswith()` fix needed" and "sentinel fix still
needed" are separate facts about this pane, both verified directly (not assumed from either one).

**Match key:** bare `int` err_idx -- simplest of any pane in the rollout (no nesting, one expand
level, matches `error_line_map`'s own existing key shape exactly). **Matcher:**
`build_warnings_search_matches` checks the underlying dict fields directly (`tool_name`,
`worker_name`, `tool_call_input`, `full_text`) rather than re-rendering -- this pane's render is
trivial (no branching to risk diverging from), and checking raw fields covers the FULL
untruncated `full_text` regardless of collapsed/expanded display state, arguably broader
coverage than a render-based matcher would give. **Two-stage marking**, confirmed against a
non-trivial fixture: a multi-word Bash command (`'echo unique_marker_x'`) was needed specifically
because `warnings_render.py`'s PRE-EXISTING `first_word_of_call` already shows a one-word inline
preview even when collapsed -- a single-word marker would have made the "hidden while collapsed"
assertion pass for the wrong reason (the marker just happens to be the first word, unrelated to
whether search's own container-marking design actually works). Caught by the test's first run
failing, not assumed correct in advance.

**`header_lines` generalization:** `_format_warnings_pane` gained `header_lines: int = 1`
(default preserves both other real callers -- `dev/click_ui/p2_copy_click_probe.py` and
`p3_button_click_probe.py`, both call positionally, verified compatible before editing) --
replaces what used to be a hardcoded `header_offset = 2`. `warnings_pane.py` passes
`header_lines=2` (search bar + `[refresh]`). The pre-existing overdraw print stays byte-for-byte
unchanged, fed the new 2-line `header` string.

**One test fix, one line, same pattern as sub-milestone 3's wrap-straddle fix:**
`p3_button_click_probe.py::test_warnings_refresh_button` hardcoded `next(iter(regions))[2] == 1`
for the `[refresh]` region's row -- now 2 (shifted past the new search bar). Every OTHER
assertion in that test already resolved rows dynamically and needed no change.

## GPU + News -- highlight-only, verified structurally simple before implementing

Confirmed via grep before writing any code: `pane_height` is accepted by both panes'
`_render_pane` but never read anywhere in the function body -- no viewport clipping exists, the
"no scroll infra" premise was verified, not assumed. Neither pane has any per-row
background/zebra/hover loop either (lines are plain ANSI-colored text, always the terminal's own
default background) -- so embedding highlights needs **no sentinel at all**:
`utils.highlight_query_in_line`'s default `restore_bg='\033[49m'` is directly correct, the same
simple case as the main pane (`core/monitor_display.py`) established back in sub-milestone 2.

**Design:** `_render_pane` gains `search_query`/`search_match_line_set`/`search_current_line`,
applied as a SINGLE post-loop pass right before the final `'\n'.join(lines)` -- touches none of
the existing per-section construction code. Match keys are plain 0-based indices into
`_render_pane`'s own `lines` list -- no click-interactivity concept needed for matches (only
buttons are clickable in these panes), so no coupling to physical row numbers at all. The
matcher (`_gpu_search_on_commit`/`_news_search_on_commit`) calls `_render_pane` ONCE without
search kwargs to get exactly what the real render would show, splits/ANSI-strips/scans -- no
separate matcher function or module needed (no collapse/expand state to force-open, everything
is always fully shown already).

**n/N interpretation (confirmed with the user before implementing, since the task phrasing was
ambiguous):** cycles `current_idx` only (which on-screen match gets `SEARCH_CURRENT_BG` vs
`SEARCH_MATCH_BG`, and the N/M counter text) -- ZERO scroll/jump call, since there is nothing to
scroll to (everything is either on screen, highlighted, or it isn't). This gives real value
(cycling visual attention across multiple simultaneously-visible matches) without needing to
fabricate a scroll mechanism these panes were never designed to have.

**Row-shift for `_button_regions`, and why it stays external:** confirmed BEFORE implementing
that `dev/click_ui/p4_gpu_news_button_probe.py` calls `_render_pane` DIRECTLY and asserts on
`_button_regions` with no shift expectation (`output.split('\n')[0]` assumed to be the rule/title
line). Mirroring worker-proxy's sub-milestone-3 precedent exactly: `_render_pane`'s own row
numbering stays UNSHIFTED, relative to its own top; the shift (`+_GPU_SEARCH_BAR_LINES` /
`+_NEWS_SEARCH_BAR_LINES`) happens EXTERNALLY, in `run_gpu_loop`/`run_news_loop`, applied to
`_button_regions` after `_render_pane` returns. Verified: **zero changes needed to
`p4_gpu_news_button_probe.py`** -- the 53 pre-existing checks in that file passed unmodified
before and after this milestone's implementation, confirmed by running it both times.

**Inline dispatch, an existing characteristic, not something this milestone changed:** both
panes' mouse/key dispatch has always been inline in `run_gpu_loop`/`run_news_loop` (no standalone
`_handle_gpu_mouse` function exists, unlike every other pane in the rollout) -- `p4_gpu_news_
button_probe.py` already documented this boundary before this milestone. `search_bar.py`'s
functions (`handle_search_mouse_press`/`_motion`/`_release`, `handle_search_input`,
`handle_search_cancel`) are called DIRECTLY at the inline dispatch sites, no pane-specific
wrapper functions needed (unlike every prior pane, which had thin wrappers) -- since there's no
existing handler-function convention to preserve call shapes for here.

## Verification

- **82/82** new regression checks (`dev/pane_search/p8_warnings_gpu_news_parity_test.py`)
  covering all three panes against REAL functions (via `importlib.import_module`, no mocking):
  full mechanics suite per pane, the `DIM_YELLOW_BG`-already-correct verification made permanent,
  the two-stage marking with the corrected multi-word-command fixture, the `ZEBRA_BG_A==''`
  sentinel repro, `_render_pane`'s unshifted-row-numbering + external-shift replication (mirrors
  the real loop's own shift snippet) for both gpu and news, highlight-only matching for both
  (news's query target -- `TARGET_COLLECTION`, a stable constant -- deliberately sidesteps
  `_is_running()`'s real filesystem/subprocess dependency for assertion purposes), and n/N
  cycling with an explicit "scroll state stays untouched" check for warnings (which HAS real
  scroll infra, unlike gpu/news, making this the one pane where "n/N doesn't scroll" is a
  meaningful behavioral claim to verify rather than a vacuous one).
- **48/48** `p2`, **62/62** `p3`, **77/77** `p4`, **77/77** `p5`, **78/78** `p6`, **76/76** `p7`
  -- all prior-milestone suites re-run clean.
- **35/35** `p1_worker_selection_click_probe`, **37/37** `p2_copy_click_probe`, **32/32**
  `p3_button_click_probe` (1 line fixed, documented above), **53/53**
  `p4_gpu_news_button_probe` (UNMODIFIED, confirmed both before and after implementation).
- **14/14 byte-identical** via `dev/proxy_dual_log/A_render_refactor_proof.py --mode verify` --
  confirms zero impact on `proxy_display/` (untouched this milestone).
- `dev/display/test_hover_map.py`: 40/40 of the tests that don't hit the pre-existing, unrelated
  `ImportError: _parse_log_file` (confirmed again -- untouched by this milestone, first flagged
  in sub-milestone 3, still unaddressed, out of scope for every milestone in this rollout).
- Import-level sanity: `src.panes.warnings_pane`, `src.panes.warnings_render`,
  `src.gpu_pane.pane`, `src.news_pane.pane` all import cleanly post-migration (`ast.parse` +
  real `importlib.import_module`, no mocking).
- **Not verified as of this entry:** live tmux/terminal visual rendering of any of the three
  panes' bars, the `/` focus hotkey's live dispatch in each pane's own inline loop (not
  unit-tested at the loop level -- consistent with every prior milestone in this area), and real
  trackpad drag-select. Standard "user visual check" gate, same as every prior entry in this area.

## Rollout status

This concludes the search-bar rollout. All 8 tmux panes (main, proxy, worker-proxy, tokens,
workers, warnings, gpu, news) now share `src/search_bar.py`'s mechanics -- `news_pane/log_pane.py`
is the one deliberate exclusion (right-side log-tail pane, top-anchored scroll-free rendering,
judged out of scope for the entire rollout from the original decomposition).
