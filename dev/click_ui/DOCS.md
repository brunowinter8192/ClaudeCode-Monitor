# dev/click_ui/

## Role

Regression coverage for the click-UI milestone series (making every tmux-pane control reachable
by mouse, not just keyboard). Milestone 1 covers worker selection in the worker-proxy pane header
and the workers pane. Milestone 2 covers copy-by-click in the tokens/warnings/workers panes (the
main pane's own copy-by-click case was removed 2026-09 along with the main pane itself, see
`process-docs/main_pane/`).
Milestone 3 covers two of three remaining single-purpose keyboard controls (workers freeze,
warnings refresh) as pane-chrome buttons — the third (proxy undo) got a button too but it was
reverted 2026-07-30 per user decision after live-testing; `u` stays the only way to undo. Milestone
4 covers gpu (digit keys 1-9 already covered by existing buttons; new `[refresh]`) and news (new
`[refresh]`). (2026-08-18, unrelated proxy-pane search feature milestone: the proxy pane now HAS a
permanent one-line header again — a search bar, not a button, see `p3_button_click_probe.py`'s
entry below.) (2026-08-18, rollout sub-milestone 3: the worker-proxy pane also gained a permanent
row-1 search bar, shifting `_worker_proxy_header_regions` down by one row — `p1_worker_selection_
click_probe.py`'s wrap-straddle test calls `_format_worker_proxy_header` directly, bypassing the
production shift step, so it now replicates that shift itself before dispatching clicks; see that
module's entry below.) `md/` holds every run's report.

## Modules

### p1_worker_selection_click_probe.py (279 LOC)

**Purpose:** Proves, after one real render pass, that the worker-proxy header's per-worker click
regions (`_worker_proxy_header_regions`) and the workers pane's per-worker row hit area
(`worker_line_map`) each contain one entry per worker at plausible coordinates, and that
dispatching a synthetic mouse click at those coordinates produces the same state change (IPC
selection file content, expand-state) as pressing the corresponding digit key. Also sweeps the
worker-proxy header across pane widths (200/60/40/30, with a 16-char worker name) that force a
marker to straddle a wrap boundary, asserting every worker still has >=1 clickable region at
every width and that a synthetic click on EACH row-segment of a straddling marker selects that
worker (`_register_marker_regions` regression guard). **(2026-08-18, rollout sub-milestone 3)**
The wrap-straddle test calls `_format_worker_proxy_header` directly (regions computed RELATIVE
to the header's own top) rather than through `_build_worker_proxy_output` (which shifts them by
`_WP_SEARCH_BAR_LINES` for the new row-1 search bar) — the test now replicates that same shift
itself right after the direct call, before dispatching clicks, so the synthetic coordinates match
what `_handle_worker_proxy_mouse` actually expects (row 1 is reserved for the search bar; a
header marker click at the OLD unshifted row 1 would otherwise be swallowed by the search-bar
press branch instead). The click-parity test (`test_worker_proxy_header_click`) needed no change
— it already goes through the real `_build_worker_proxy_output`, which performs the shift itself.
**Reads:** nothing external — seeds `src.proxy_display.worker_proxy_pane._worker_proxy_workers`
and calls `src.workers.worker_pane._build_workers_output` directly with synthetic worker lists.
**Writes:** `md/p1_worker_selection_click_probe_<timestamp>.md`; IPC selection files under
`/tmp/monitor_cc_selected_worker_<hash>.txt` for two throwaway project_filter paths
(`/tmp/click_ui_probe_worker_proxy`, `/tmp/click_ui_probe_workers_pane`), removed after each
check.
**Called by:** run manually — regression guard for worker-selection click wiring; re-run after
any change to `_format_worker_proxy_header`, `_handle_worker_proxy_mouse`,
`_handle_worker_proxy_key`, `worker_line_map`/`format_workers_block`, `_handle_workers_mouse`, or
`_handle_workers_key`.
**Calls out:** `src.proxy_display.worker_proxy_pane`, `src.workers.worker_pane` — loaded via
`importlib.import_module` (package-qualified; double-dot relative imports).

---

### p2_copy_click_probe.py (281 LOC)

**Purpose:** Proves, per pane (tokens, warnings, workers), that after one real render pass
the copy-row registry contains an entry for every row carrying a copyable unit, and that a
synthetic click on the symbol column copies EXACTLY the same string the `y` key produces for that
row — both paths run through the real serializer (`_serialize_tokens`, `_serialize_warnings`,
`_serialize_workers`), compared against each other, nothing hardcoded.
Also: a pure-function width-guard regression (`utils.append_copy_symbol`) plus one
render-integration width-guard check per pane (narrow `pane_width` → no symbol, no row
registration). **(2026-09) `test_main_pane_copy_click` and its `mod_main_display`/`mod_monitor`
imports removed** — the main pane it covered was deleted entirely (window 0 is now the tokens
pane at full width, see `process-docs/main_pane/`). Regression guards for two bugs found and
fixed in an earlier milestone: (1)
`warnings_render._serialize_warnings` expected a `('error', idx)` tuple but `error_line_map`
stores a bare `int` — `y` silently copied `''` for every warnings row until fixed; (2)
`worker_pane._handle_workers_key`'s `y`-branch resolution order made the
`worker_cache_line_map` fallback dead code — hovering an expanded cache-call row always resolved
to the parent worker's identity instead of the specific call, fixed via
`_resolve_workers_hover_key` (closer-ancestor-wins). Also checks that the workers-pane
copy-region priority does not disturb milestone-1's row-click-select wiring (no state change on a
copy click; a normal non-edge click still selects+expands).
**Reads:** nothing external — seeds `_cache_turns` / `tool_errors` /
`worker_turns` with synthetic data; `copy_to_clipboard` is monkeypatched per module to a
capturing stub (no real pbcopy calls).
**Writes:** `md/p2_copy_click_probe_<timestamp>.md`; one throwaway IPC selection file under
`/tmp/monitor_cc_selected_worker_<hash>.txt` (workers-pane project_filter
`/tmp/click_ui_probe_p2_workers`), removed after the check.
**Called by:** run manually — regression guard for copy-by-click wiring; re-run after any change
to `append_copy_symbol`, `format_cache_tracker`, `_format_warnings_pane`,
`_serialize_warnings`, `format_workers_block`, `_resolve_workers_hover_key`, or any of the three
panes' `_handle_*_mouse` / `_handle_*_key` functions.
**Calls out:** `src.panes.token_pane`,
`src.format.token_format`, `src.panes.warnings_pane`, `src.panes.warnings_render`,
`src.workers.worker_pane`, `src.utils` — loaded via `importlib.import_module`.

---

### p3_button_click_probe.py (330 LOC)

**Purpose:** Proves, per pane (workers freeze, warnings refresh), that after one real render pass
the header/chrome button region is registered at a plausible coordinate, a synthetic click on it
produces the SAME state change as the corresponding key (`f`/`r`), the freeze badge's rendered
text reflects state BEFORE the click (`[LIVE]`/`[FROZEN]`), a too-narrow pane registers no region
(and renders no button text either), and that each pane's PRE-EXISTING click handling (workers
row-select, warnings expand/copy) still works after the header-check was added ahead of it.
**(2026-07-30) Proxy pane: `[undo]` button reverted** — `u` stays the only way to undo.
**(2026-08-18) Proxy pane: PERMANENT search-bar header added (Milestone 2, unrelated to the
button revert — a deliberate "always visible" design principle, not a hidden-feature button).**
`test_proxy_pane_permanent_search_bar_header` (renamed from `test_proxy_pane_reverted_no_header`,
whose assertions were the OPPOSITE of the new contract) asserts the new header+shift contract:
`_build_proxy_output` returns a plain string with the search bar baked into row 1 (`"search:"`
visible), no leftover `_proxy_header_regions` / `_format_proxy_header` (those were the reverted
button's, never resurrected), row 1 is NOT a body key, row 2 is the first REQ header, clicking
row 1 focuses the search bar, and that expand/collapse clicks, copy-symbol clicks, scroll,
auto-scroll-to-just-expanded, and `_undo_proxy_expand` itself all still work at the SHIFTED rows
— using a real synthetic entry set (`_make_proxy_entry`, matching `dev/display/test_hover_map.py`'s
shape). Functional coverage of the search feature ITSELF (matching, highlighting, n/N, Esc,
scroll-jump, the flow_id lazy-load fix) lives in `dev/pane_search/p2_search_feature_regression_test.py`
— this probe stays scoped to click-parity/chrome, mirroring its role for the other panes.
**Reads:** nothing external — seeds `tool_errors` / synthetic `workers` list / `proxy_entries`
(via `_make_proxy_entry`) directly.
**Writes:** `md/p3_button_click_probe_<timestamp>.md`; one throwaway IPC selection file under
`/tmp/monitor_cc_selected_worker_<hash>.txt` (workers-pane project_filter
`/tmp/click_ui_probe_p3_workers`), removed after the check.
**Called by:** run manually — regression guard for the two remaining pane-chrome buttons (workers
freeze, warnings refresh) and for the proxy pane's permanent search-bar header shape; re-run after
any change to `_format_warnings_header`, `_handle_warnings_mouse`/`_handle_warnings_key`,
`format_workers_block`, `_handle_workers_mouse` (`(button,col,row,project_filter,frozen) ->
(changed, frozen)`) / `_handle_workers_key`, or `_build_proxy_output`/`_handle_proxy_mouse`/
`_undo_proxy_expand`.

**(2026-08-18, rollout sub-milestone 6) `test_warnings_refresh_button`'s row assertion updated.**
`warnings_pane.py` gained its own permanent row-1 search bar — the pre-existing `[refresh]`
header region shifts from row 1 to row `1 + mod_warnings._WARNINGS_SEARCH_BAR_LINES` (row 2).
The ONE hardcoded `next(iter(regions))[2] == 1` assertion was updated to reference the constant
instead of a bare literal — same "update the dependent test when a pane's row contract changes"
pattern as the worker-proxy wrap-straddle fix (sub-milestone 3) and identical to the shift every
other pane in this rollout applied; every OTHER assertion in this test already resolved `(sc, ec,
er)` dynamically and needed no change. `dev/click_ui/p4_gpu_news_button_probe.py` needed ZERO
changes for the gpu/news milestone (sub-milestones 7-8) — see that file's own DOCS entry below.
**Calls out:** `src.panes.warnings_pane`, `src.panes.warnings_render`, `src.workers.worker_pane`,
`src.workers.worker_format`, `src.proxy_display.pane`, `src.proxy_display.format` — loaded via
`importlib.import_module`.

---

### p4_gpu_news_button_probe.py (333 LOC)

**Purpose:** Proves gpu's digit keys 1-9 need NO new button — the pre-existing per-server button
already registered in `_button_regions` computes the IDENTICAL action and fires the IDENTICAL
`rag-cli` subprocess call as `_toggle_server(idx, presets)` (what the digit key calls), asserted
by comparing captured `subprocess.Popen` args + the resulting `_toggle_state` action label
between the two paths, for both a stopped preset (`start`) and a running+healthy preset (`stop`).
Also proves the two NEW `[refresh]` header buttons (gpu, news): region registered after a render,
on row 1, disjoint from every pre-existing button region (different phys_row — asserted, not just
argued); the dispatch loop correctly special-cases `action == 'refresh'` BEFORE the pre-existing
`_fire_button`/`_fire_pipeline` branch (verified by replicating `run_gpu_loop`'s /
`run_news_loop`'s exact inline dispatch snippet in local helpers `_dispatch_gpu_click` /
`_dispatch_news_click`, since neither loop factors mouse dispatch into a standalone function —
the local `force_refresh` variable inside each blocking loop is therefore NOT independently
exercised, only the dispatch-loop's OWN region-matching and branching, mirrored line-for-line);
narrow-pane gets no `[refresh]` text and no region in either pane; news's pre-existing
`[run pipeline]` click still fires the pipeline (regression check) after the new branch was added
ahead of it. **(2026-07-30 review fix)** `test_gpu_refresh_button_width_sweep` /
`test_news_refresh_button_width_sweep`: sweep pane widths on both sides of each pane's
button-visibility crossover (gpu 27, news 38 — both far below the panes' live widths of 215/107)
proving the `'═'` decoration shrinks (fewer chars than its cap, asserted directly) before
`[refresh]` is dropped, that the button is registered at every swept width at/above the
crossover, and that the title text stays fully visible even below it, closing the priority
inversion where the fixed-length decorative rule ate the space `[refresh]` needed first.
**Reads:** nothing external — seeds synthetic gpu preset dicts and news status dicts directly;
`gpu_pane.status.PRESET_NAMES` (resolved once at import time via a REAL `rag-cli server presets`
subprocess call) is monkeypatched to a fixed list so the probe is deterministic regardless of
what's actually running on the machine; `subprocess.Popen` is monkeypatched per module to a
capturing stub (no real rag-cli or news-pipeline process ever launched).
**Writes:** `md/p4_gpu_news_button_probe_<timestamp>.md`.
**Called by:** run manually — regression guard for the gpu/news buttons; re-run after any change
to `_render_pane` (either pane), `_toggle_server`, `_fire_button`, `_fire_pipeline`,
`utils.compute_header_rule_len`, or either loop's inline mouse-dispatch snippet.
**Calls out:** `src.gpu_pane.pane`, `src.news_pane.pane` — loaded via `importlib.import_module`.

**(2026-08-18, rollout sub-milestones 7-8) Needed ZERO changes for the gpu/news search-bar
migration.** Both panes' `_render_pane` kept its OWN row numbering UNSHIFTED (relative to its
own top) by design — the new search bar's row is prepended and `_button_regions` shifted
EXTERNALLY, in each pane's loop, AFTER `_render_pane` returns (mirrors `worker_proxy_pane.py`'s
sub-milestone-3 precedent) — so every assertion in this file (which calls `_render_pane`
directly) kept working unmodified. This is the doc trail for why: confirms the "keep the pure
render function reusable/testable, shift externally" design choice paid off exactly as intended.
