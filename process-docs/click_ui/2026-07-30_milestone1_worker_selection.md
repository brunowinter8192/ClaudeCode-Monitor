# 2026-07-30 — Milestone 1: worker selection clickable in both worker panes

## Problem

The monitor's tmux panes mix clickable and keyboard-only controls inconsistently. This is the
first of four milestones toward making every control mouse-reachable; scope here is worker
selection only, in two panes:

- `src/proxy_display/worker_proxy_pane.py` — the header already RENDERS workers as
  `[1]name  [2*]name` markers (`_format_worker_proxy_header`, `worker_proxy_helpers.py`), styled
  identically to a real button, but they were inert: `_handle_worker_proxy_mouse` only resolved
  rows via `worker_proxy_line_map`, which starts BELOW the header (`_build_worker_proxy_output`
  shifts it by `header_lines`) — a click on a header marker landed on a row the map has no entry
  for and silently did nothing.
- `src/workers/worker_pane.py` — `_handle_workers_key`'s digit branch expands/collapses a worker
  AND selects it (`worker_selected_name` + `_write_selection`). `_handle_workers_mouse` already
  resolved the same row via the pre-existing `worker_line_map` and toggled expand/collapse, but
  never selected — a worker could be clicked open without ever becoming the one whose proxy log
  the other panes show.

## Pattern choice

Two existing click patterns in the repo: `_button_regions: dict[(start_col,end_col,phys_row) ->
(action,target)]` (`gpu_pane/pane.py`, `news_pane/pane.py`) for discrete rectangular targets on a
known row, and `copy_rows: set[phys_row]` (`proxy_display/pane.py` / `render_turn.py`) for a
single right-edge symbol per row. The worker-proxy header needed several markers packed on one
line at fixed but non-uniform column ranges — the button-region shape, not the single-symbol-per-
row shape — so `_worker_proxy_header_regions: Dict[(start_col,end_col,phys_row), worker_name]`
was added, rebuilt every `_build_worker_proxy_output` call by
`_format_worker_proxy_header(..., pane_width, regions_out=...)`, consulted first in
`_handle_worker_proxy_mouse` before the pre-existing `worker_proxy_line_map` body lookup (no row
overlap: body rows are shifted past `header_lines`).

The workers-pane row needed no new region table at all — `worker_line_map` already mapped the
FULL worker row (header line + purpose line) to the worker name for the pre-existing expand/
collapse click. Whole-row was kept as the hit area (no column check) rather than narrowing it,
since digit-key selection has no notion of "which part of the row was clicked" either — narrowing
would only diverge from key-parity for no benefit. The fix was two lines: mirror the digit-key
branch's `worker_selected_name = name` + `_write_selection(project_filter, name)` into the mouse
branch, and thread `project_filter` through the handler's signature and call site.

## Wrap-straddle gap (found on review)

First pass computed each header marker's region with `divmod(visible_col, pane_width)` for both
the start and end column, but registered the region only `if start_row == end_row` — a marker
whose text crossed a wrap boundary got silently dropped, no region at all, while still being
RENDERED identically to every clickable marker. Measured before the fix, worker set
`['alpha','beta','gamma-long-name','delta']`: pane_width 200 → 4/4 markers had a region, 60 → 3/4
(`delta` dead), 40 → 3/4 (`gamma-long-name` dead), 30 → 2/4.

Fix: `_register_marker_regions(regions_out, name, start, end, pane_width)` splits a marker's
`[start,end]` visible-column span into one region PER physical row it occupies — a straddling
marker now gets 2+ region entries mapping to the same worker name (both row-segments are
legitimate hit areas), instead of being skipped. Re-measured after the fix: all 4 widths above
now have 4/4 markers with >=1 clickable region.

## Verification

`dev/click_ui/p1_worker_selection_click_probe.py` — no live tmux/terminal; seeds real module
globals with synthetic worker lists, drives the real render functions
(`_build_worker_proxy_output`, `_build_workers_output`, and `_format_worker_proxy_header`
directly for the pane-width sweep), reads back real IPC selection files under
`/tmp/monitor_cc_selected_worker_<hash>.txt` for two throwaway project_filter paths, dispatches
synthetic clicks through the real `_handle_worker_proxy_mouse`/`_handle_workers_mouse`.
**35/35 checks passing**: header-region coverage + digit-key-vs-click parity for 3 workers
(worker-proxy) and 2 workers (workers-pane, incl. a scroll-wheel-on-worker-row no-collision
check), plus the wrap-straddle sweep (4 pane widths, both coverage and per-segment click parity).
Full existing regression suite (`dev/pane_error_log/p1_pane_loop_survives_exception_probe.py`,
52/52) re-run to confirm the two mouse-handler signature changes (`monitor` /
`project_filter` params added, call sites updated) didn't disturb either pane's event-loop
exception guard or `finally:` cleanup.

Not verified: a real mouse click through an actual terminal emulator against a live tmux pane —
SGR mouse-report coordinates from a real terminal were not cross-checked against the computed
regions; that needs a human click-test in the running panes.

## Scope note

Deliberately left untouched (later milestones): main/tokens/warnings/gpu/news panes, and the
worker-proxy pane's body content (only the header markers were in scope) and the workers-pane
layout (only the click wiring was added, no visual change).
