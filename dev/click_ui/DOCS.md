# dev/click_ui/

## Role

Regression coverage for the click-UI milestone series (making every tmux-pane control reachable
by mouse, not just keyboard). Milestone 1 covers worker selection in the worker-proxy pane header
and the workers pane. `md/` holds every run's report.

## Modules

### p1_worker_selection_click_probe.py (~215 LOC)

**Purpose:** Proves, after one real render pass, that the worker-proxy header's per-worker click
regions (`_worker_proxy_header_regions`) and the workers pane's per-worker row hit area
(`worker_line_map`) each contain one entry per worker at plausible coordinates, and that
dispatching a synthetic mouse click at those coordinates produces the same state change (IPC
selection file content, expand-state) as pressing the corresponding digit key.
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
