# dev/click_ui/

## Role

Regression coverage for the click-UI milestone series (making every tmux-pane control reachable
by mouse, not just keyboard). Milestone 1 covers worker selection in the worker-proxy pane header
and the workers pane. Milestone 2 covers copy-by-click in the main/tokens/warnings/workers panes.
`md/` holds every run's report.

## Modules

### p1_worker_selection_click_probe.py (268 LOC)

**Purpose:** Proves, after one real render pass, that the worker-proxy header's per-worker click
regions (`_worker_proxy_header_regions`) and the workers pane's per-worker row hit area
(`worker_line_map`) each contain one entry per worker at plausible coordinates, and that
dispatching a synthetic mouse click at those coordinates produces the same state change (IPC
selection file content, expand-state) as pressing the corresponding digit key. Also sweeps the
worker-proxy header across pane widths (200/60/40/30, with a 16-char worker name) that force a
marker to straddle a wrap boundary, asserting every worker still has >=1 clickable region at
every width and that a synthetic click on EACH row-segment of a straddling marker selects that
worker (`_register_marker_regions` regression guard).
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

### p2_copy_click_probe.py (343 LOC)

**Purpose:** Proves, per pane (main, tokens, warnings, workers), that after one real render pass
the copy-row registry contains an entry for every row carrying a copyable unit, and that a
synthetic click on the symbol column copies EXACTLY the same string the `y` key produces for that
row — both paths run through the real serializer (`serialize_main_event`, `_serialize_tokens`,
`_serialize_warnings`, `_serialize_workers`), compared against each other, nothing hardcoded.
Also: a pure-function width-guard regression (`utils.append_copy_symbol`) plus one
render-integration width-guard check per pane (narrow `pane_width` → no symbol, no row
registration). Regression guards for two bugs found and fixed in this milestone: (1)
`warnings_render._serialize_warnings` expected a `('error', idx)` tuple but `error_line_map`
stores a bare `int` — `y` silently copied `''` for every warnings row until fixed; (2)
`worker_pane._handle_workers_key`'s `y`-branch resolution order made the
`worker_cache_line_map` fallback dead code — hovering an expanded cache-call row always resolved
to the parent worker's identity instead of the specific call, fixed via
`_resolve_workers_hover_key` (closer-ancestor-wins). Also checks that the workers-pane
copy-region priority does not disturb milestone-1's row-click-select wiring (no state change on a
copy click; a normal non-edge click still selects+expands).
**Reads:** nothing external — seeds `main_event_buffer` / `_cache_turns` / `tool_errors` /
`worker_turns` with synthetic data; `copy_to_clipboard` is monkeypatched per module to a
capturing stub (no real pbcopy calls).
**Writes:** `md/p2_copy_click_probe_<timestamp>.md`; one throwaway IPC selection file under
`/tmp/monitor_cc_selected_worker_<hash>.txt` (workers-pane project_filter
`/tmp/click_ui_probe_p2_workers`), removed after the check.
**Called by:** run manually — regression guard for copy-by-click wiring; re-run after any change
to `append_copy_symbol`, `render_main_buffer`, `format_cache_tracker`, `_format_warnings_pane`,
`_serialize_warnings`, `format_workers_block`, `_resolve_workers_hover_key`, or any of the four
panes' `_handle_*_mouse` / `_handle_*_key` functions.
**Calls out:** `src.core.monitor_display`, `src.core.monitor`, `src.panes.token_pane`,
`src.format.token_format`, `src.panes.warnings_pane`, `src.panes.warnings_render`,
`src.workers.worker_pane`, `src.utils` — loaded via `importlib.import_module`.
