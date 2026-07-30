# src/workers/

## Role

Workers pane package. Discovers active Claude Code worker sessions via tmux, extracts token and
tool-call data from their JSONL files, renders an interactive TUI pane with expand/collapse and
per-worker cache-tracker, and publishes the selected worker name via an IPC file for cross-pane
coordination with `proxy_display`. Touch this package when changing worker
discovery, worker status detection, or the workers pane display. Do NOT touch for proxy
rendering — that pane only reads the IPC selection file.

## Public Interface

- `run_workers_loop` — Workers pane event loop (entry point from `core.monitor`)
- `write_selection(worker_name)` — write selected worker name to IPC file (used by `proxy_display`)

## Flow

tmux session list → `worker_tmux` (discover workers, detect status, find JSONL path)
→ `worker_format` (extract tokens + tool calls from JSONL, render block)
→ `worker_pane` (event loop, IPC selection file write → stdout)

## Modules

### worker_tmux.py (94 LOC)

**Purpose:** Discover active Claude Code worker sessions via `tmux list-sessions`, detect per-worker status, and locate each worker's most recent session JSONL file.
**Reads:** tmux session list (via subprocess); tmux pane/window state for status detection; worker CWD from tmux env.
**Writes:** Nothing — returns worker dicts and JSONL paths.
**Called by:** `src/workers/worker_pane.py`, `src/proxy_display/worker_proxy_pane.py`
**Calls out:** `session_finder` (encode_project_path)

---

### worker_format.py (199 LOC)

**Purpose:** Extract token sums, context-% and tool call lists from worker JSONL files; render the full workers pane block with per-worker rows, status, context-%, model, token counts, and expanded cache tracker. `extract_worker_context_pct(jsonl_path)` scans assistant messages for the latest `cache_read_input_tokens` value and returns `(100 * (_WORKER_CONTEXT_WINDOW - cr)) // _WORKER_CONTEXT_WINDOW` as remaining context percentage (None if no JSONL data yet). `_WORKER_CONTEXT_WINDOW = 1000000` — flat 1M window, no per-model lookup; the worker fleet runs exclusively on 1M-context models (opus-4-8, sonnet-5, fable-5), haiku-4-5 (200k) is never a worker. **(2026-07-30) Copy symbol on both row kinds:** `format_workers_block` takes `copy_feedback: Optional[dict] = None` — a flat dict mixing `str` name keys (worker header row) and `(name,turn_idx,call_idx)` tuple keys (expanded cache-call rows). Header row: `append_copy_symbol(header_line, ..., pane_width)` when `copy_feedback` given. Cache rows: `_worker_cache_copy_feedback(copy_feedback, name)` filters the flat dict down to a `(turn_idx,call_idx)→expiry` sub-dict scoped to THIS worker (avoids cross-worker key collision — `format_cache_tracker`'s own key format is the 2-tuple, and multiple workers can be expanded simultaneously, each with independent turn/call indices) before passing it to `format_cache_tracker(..., copy_feedback=...)`. **(2026-07-30) `[LIVE]`/`[FROZEN]` badge as the freeze button:** new `regions_out: Optional[dict] = None` param — when given, registers `regions_out['freeze'] = (start_col, end_col)` (COLUMN SPAN ONLY, no row — `format_workers_block` doesn't know the final phys_row, that's resolved by the caller after viewport clipping, see `worker_pane.py`), width-guarded (`pane_width` moved to compute BEFORE the `if not workers:` early return, so both branches can use it): the badge text itself is pre-existing, ALWAYS rendered regardless; only the region registration is gated on whether it fits.
**Reads:** Worker JSONL file (full read for token/tool extraction); worker list + expand/scroll state dicts (for rendering).
**Writes:** Nothing — returns token summary dict, tool call list, or formatted TUI string.
**Called by:** `src/workers/worker_pane.py`
**Calls out:** `jsonl`, `format` (token_format), `utils` (`append_copy_symbol`)

---

### worker_pane.py (364 LOC)

**Purpose:** Workers pane event loop — keyboard/mouse input, periodic data refresh, viewport-clipped screen rendering, and IPC selection file write for cross-pane coordination. Structured as drain-refresh-render: `run_workers_loop` (ORCHESTRATOR, 55 LOC) delegates to four private helpers: `_handle_workers_mouse` (drain mouse events, resolves cache/worker-name line maps, updates scroll offsets ±3 per worker), `_handle_workers_key` (drain keyboard: y-copy, f-freeze, digit-select), `_refresh_workers_data` (tick-boundary `list_workers` + `worker_turns` build; partial-expand branch on input_changed), `_build_workers_output` (format + viewport clip + zebra/hover render loop, updates `worker_line_map`/`worker_cache_line_map`). `_workers_ram_state` is a module-level function (was a closure) registered with `register_ram_dump`. **The `while True:` body has always been wrapped in its own `try/except Exception:`** — the reference pattern the other 7 pane loops were retrofitted to match (2026-07-31). **(2026-07-31 fix)** the except clause previously wrote the traceback with an inline `open('/tmp/monitor_cc_error.log', 'a')` — a failing write (disk full, permissions) would have propagated out of the except block itself and killed the loop, since nothing wrapped it; now delegates to `pane_error_log.log_pane_error('workers')`, which is exception-safe end to end and shared by all 8 pane loops. **(2026-07-30) Row click now selects, not just expands:** `_handle_workers_mouse` takes `project_filter` and, on a `worker_line_map` row hit (the pre-existing whole-row hit area — header line + purpose line, both mapped to the worker name in `format_workers_block`), now also sets `worker_selected_name = name` and calls `_write_selection(project_filter, name)` — matching `_handle_workers_key`'s digit-key branch exactly (toggle expand/collapse AND select, unconditionally, even when collapsing). Call site (`run_workers_loop`) passes `_monitor.active_project_filter`. No column check — the entire row width is the hit area; does not touch the `worker_cache_line_map` branch (cache-call toggle only, no selection) or the scroll/hover branches (different SGR button codes, no collision). Visual affordance unchanged — the row already renders `[idx] name` (CYAN) with a `>>` selected-prefix and `[+]`/`[-]` toggle, the same bracket-button convention used elsewhere; the click wiring makes that existing look-clickable marker actually clickable. **(2026-07-30) Copy-by-click on the ⎘ symbol, both row kinds:** `_handle_workers_mouse` now checks `col >= _worker_pane_width - 2 and row in worker_copy_rows` FIRST on BOTH the `worker_cache_line_map` branch and the `worker_line_map` branch (ahead of the milestone-1 select/expand logic) — a hit calls `copy_to_clipboard(_serialize_workers(key))`, never touches selection state. `worker_copy_rows` is one flat `Set[int]`, populated by `_build_workers_output` via substring-detecting `⎘`/`✓` in the rendered line (same pattern as `proxy_display.format._apply_row_backgrounds`), so it naturally covers both row kinds with no type dispatch needed. **Bug found + fixed in the same pass:** `_handle_workers_key`'s `y`-branch used to try `resolve_parent_key(worker_line_map, hover_row)` first, falling back to `worker_cache_line_map` only on `None` — but `resolve_parent_key` walks backward to row 1, so it ALWAYS finds the owning worker's header/purpose row above any cache-call row, making the cache-map fallback dead code (`y` while hovering an expanded cache row silently copied the parent worker's identity summary, never the specific call). Replaced with `_resolve_workers_hover_key`, which compares which map's nearest ancestor row is CLOSER to `hover_row` and prefers that one — correctly resolves a cache-row hover to the specific `(name,turn_idx,call_idx)` while still resolving a subsequent worker's own header/purpose hover to that worker's name (not a prior worker's trailing cache row). **(2026-07-30) Freeze badge as a clickable button:** `_handle_workers_mouse`'s SIGNATURE CHANGED — now takes `frozen: bool` and returns `(input_changed, updated_frozen)` instead of a bare bool (mirrors `_handle_workers_key`'s existing `(changed, frozen)` contract); `run_workers_loop`'s call site unpacks the tuple the same way it already did for the key path. On `button == 0`, checks `_worker_header_regions` (populated by `_build_workers_output` from `format_workers_block`'s `regions_out['freeze']` column span, resolved to a phys_row) FIRST, ahead of the cache/copy/select checks — a hit returns `(True, not frozen)`, exactly what pressing `f` does. The freeze line is always `all_lines[0]` in `format_workers_block`'s output, but this pane has NO separate fixed header (unlike `proxy_display`/`worker_proxy_pane`) — it's part of the same scrollable content everything else is, so `_build_workers_output` only registers the region when that first line actually survived viewport clipping (`vp_start == 0`); with many workers and default (bottom-anchored) scroll, the badge can scroll out of view like any other early row — a pre-existing characteristic of this pane's layout, not fixed here (deliverable was "don't redesign layout").
**Reads:** `_monitor.active_project_filter` (shared global state); stdin (keyboard/mouse); worker JSONL files via `worker_format`.
**Writes:** ANSI output to stdout; selected worker name to `/tmp/monitor_cc_selected_worker_<hash>.txt`; `/tmp/monitor_cc_error.log` on caught exception (via `pane_error_log`); mutates `worker_copy_rows`, `_worker_copy_feedback_until`, `_worker_pane_width`, `_worker_header_regions`.
**Called by:** `src/core/monitor.py` (via `..workers.run_workers_loop`); `src/proxy_display/worker_proxy_pane.py` (imports `get_selection_file_path`, `write_selection`)
**Calls out:** `jsonl`, `input` (click_handler), `pane_error_log` (`log_pane_error`)

---

## State

`worker_pane.py` owns:
- `worker_expand_states: Dict[str, bool]` — expand/collapse state keyed by worker name
- `worker_scroll_offsets: Dict[str, int]` — intra-worker scroll position (for expanded cache-tracker, 15-line view); reset to 0 on expand
- `worker_scroll_offset: int` — dormant pane-level scroll int; always 0 after wheel routing moved to `worker_scroll_offsets`; kept as bottom-anchor for viewport fail-safe slice cap
- `worker_copy_rows: Set[int]` — phys_rows where ⎘/✓ is rendered (both worker-header and cache-call rows); cleared+rebuilt each `_build_workers_output` call
- `_worker_copy_feedback_until: Dict` — mixed-key (`str` name OR `(name,turn_idx,call_idx)` tuple) → expiry float for the ✓ flash
- `_worker_header_regions: Dict[Tuple[int,int,int], str]` — `(start_col,end_col,phys_row) → 'freeze'`; empty when the freeze badge (`all_lines[0]`) has scrolled out of the viewport

Mutated by `run_workers_loop`'s private helpers (`_handle_workers_mouse`, `_handle_workers_key`, `_refresh_workers_data`, `_build_workers_output`) — no external mutators. `worker_scroll_offsets` read by `format_workers_block` in the same process.

## Gotchas

**`worker_scroll_offset` (pane-level int) is dormant.** Wheel 64/65 events write to `worker_scroll_offsets[name]` (per-worker dict), which `format_cache_tracker` reads to scroll the expanded REQ view. `worker_scroll_offset` stays permanently 0 — `vp_start = max(0, total_lines - pane_height - worker_scroll_offset)` reduces to a bottom-anchor. The int is not removed because it anchors the `all_lines[vp_start:vp_start + pane_height]` slice-cap that prevents terminal overflow with many workers.

**Safety-net error log:** `worker_pane.py` appends unhandled exceptions in its render loop to `/tmp/monitor_cc_error.log` — silent crash guard so the pane stays alive. Check this file when the workers pane appears frozen or blank without an obvious error on screen.
