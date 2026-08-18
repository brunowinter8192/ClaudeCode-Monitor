# src/core/

## Role

Session discovery, polling loop, and terminal output for the main monitoring pane. This is the heartbeat of the monitor: `monitor.py` discovers JSONL files, drives the streaming loop, and dispatches each tool call through `monitor_session.py` for classification and routing to `monitor_display.py` for output. Touch this package when changing polling behaviour, session scoping, tool call classification, or main-pane display logic. Do NOT touch it to change pane-specific rendering — that lives in `panes/`, `format/`, or the dedicated pane packages.

## Public Interface

```python
from src.core import run_monitor                  # main entry — called by workflow.py
from src.core import process_session_file         # per-session JSONL processing
from src.core import get_file_end_position        # init file position at EOF
from src.core import get_initial_position         # position for new session
from src.core import load_historical_main         # replay main session on startup
from src.core import display_tool_call            # print formatted tool call to stdout
from src.core import display_warning              # print malformed-JSON warning
from src.core import display_user_media           # print media items
from src.core import display_skill_activation     # print skill activation event
from src.core import display_thinking             # print thinking block
from src.core import display_user_prompt_from_jsonl
from src.core import display_system_message
from src.core import print_session_status         # startup session-count line
```

## Flow

```
workflow.py → run_monitor(project_filter, mode)
  → initialize_file_positions()           # scan ~/.claude/projects, set EOF positions
  → [mode dispatch] → pane loop OR run_main_loop()
  → run_main_loop():
      loop: monitor_sessions() → process_all_sessions(sessions)
              → process_session_file(path) → parse_new_tool_calls()
              → classify (task/subagent/tool) → display_*(...)
              → render_main_buffer()      # flush buffer to stdout
```

Buffer: `monitor_display._buffer_append()` appends each event to `main_event_buffer`; when the buffer exceeds `MAIN_EVENT_BUFFER_CAP` (from `constants.py`), the oldest entries are deleted to keep the buffer bounded.

## Modules

### monitor.py (367 LOC)

**Purpose:** Polling orchestrator — discovers sessions, drives the streaming loop, dispatches to pane event loops by mode, and owns all shared state dicts. `run_main_loop()` runs a 24h log janitor (via `log_janitor.cleanup_old_jsonl`) for sweep-eligible logs (`hook_firing.jsonl`, `api_errors.jsonl`, `polling_state.jsonl`).

**(2026-08-18, rollout sub-milestone 2) Search bar retrofitted onto `search_bar.py`** — full
parity with the proxy pane (the rollout's reference implementation, `src/proxy_display/pane.py`).
`monitor_display._main_search` is one `search_bar.SearchState` instance (was 8 flat globals).
Mouse-event handler (`_handle_main_mouse`): row 1 press → `search_bar.handle_search_mouse_press`
(focuses AND anchors a drag-select — the old click-arrow `[←]`/`[→]` match-nav regions are GONE,
replaced by `n`/`N` keys, see below); row ≥ 2 click clears any lingering drag-selection
(`search_bar.clear_selection`) THEN checks the ⎘ copy-button hit on tool_call REQUEST/RESPONSE
headers via `_main_copy_rows` lookup; `button == 32` (left-button-held motion) while
`_main_search.dragging` extends the selection via `search_bar.handle_search_mouse_motion`,
gated BEFORE the generic `button >= 32` hover bucket so a body-row drag never arms it.
`read_mouse_event`'s `(-1,-1,-1)` SGR-release sentinel now routes to `_handle_main_search_release`
(finalizes a row-1 drag, copies the selection to clipboard via `copy_to_clipboard` — was a bare
no-op before this milestone). Keyboard: `/` focuses the bar (new, matches proxy); `n`/`N`
(unfocused) call `_jump_search_match` (wraps both directions, no-op with zero matches); while
focused, `search_bar.handle_search_input` handles Backspace (selection-delete when a drag-select
is active, else last-char trim), kill-line (`search_bar.KILL_LINE_CHAR`, empties the query
unconditionally), printable chars, and Enter (`_main_search_on_commit` — **always re-runs the
full match rebuild, NOT gated on query-unchanged**; this is a deliberate correction FROM the
pre-migration main pane, which DID gate on an unchanged-query check via a now-removed
`_search_cached_query` — aligned to the proxy pane's convention so a repeated Enter picks up
events appended to `main_event_buffer` since the last search). Editing (any form) never clears
`_main_search.matches` — Enter is the sole recompute trigger, per `search_bar.handle_search_input`'s
shared convention. `run_main_loop()` decomposed (C2): private helpers `_main_ram_state`,
`_handle_main_mouse`, `_handle_main_search_cancel`, `_handle_main_search_input`,
`_main_search_on_commit`, `_jump_search_match`, `_handle_main_search_release`,
`_refresh_main_data`, `_build_main_output`. **(2026-07-31) The `while True:` body is wrapped in
its own `try/except Exception:`** (outside `finally: disable_mouse(); restore_terminal()`, which
still runs on any exit path) — an uncaught exception is caught, logged via
`pane_error_log.log_pane_error('main')`, and the loop continues after
`time.sleep(INPUT_POLL_INTERVAL)` (this loop uses `time.sleep`, not `wait_for_input`, unlike the
other 7 pane loops); `KeyboardInterrupt`/`SystemExit` are `BaseException`, not `Exception`, so
they still propagate and still hit the outer `finally:`.
**Reads:** `~/.claude/projects/**/*.jsonl` via `session_finder`; lazy reads from `panes`, `workers`, `proxy_display`; module-level `monitor_display._main_copy_rows`, `_main_pane_width`, `_main_search`, `_SEARCH_BAR_LABEL`.
**Writes:** stdout (via `monitor_display`); mutates shared state (`file_positions`, `tool_use_caches`, `agent_to_task`, `agent_to_type`, `buffered_subagent_calls`, `call_counter`); mutates `monitor_display._main_search` (query/focused/matches/match_set/current_idx/selection) via Enter/Esc/Backspace/printable/mouse handlers; mutates `monitor_display._search_match_line_offsets` on Enter/cancel; mutates `monitor_display._main_copy_feedback_until` on click.
**Called by:** `workflow.py` (top-level entry).
**Calls out:** `session_finder`, `jsonl`, `pane_error_log` (`log_pane_error`), `search_bar` (shared search-bar mechanics); lazy: `panes`, `workers`, `proxy_display`, `input.click_handler` (copy_to_clipboard, read_mouse_event with sentinel-aware return).

---

### monitor_session.py (141 LOC)

**Purpose:** Per-session JSONL processor — reads new lines, classifies tool calls as task requests/responses, subagent calls, or regular tools, and routes each to the appropriate handler.
**Reads:** Session JSONL files (incremental, via file positions in `monitor.py` state); shared state from `monitor.py`.
**Writes:** Mutates `monitor.call_counter`, `monitor.agent_to_task`, `monitor.agent_to_type`, `monitor.buffered_subagent_calls`; calls `monitor_display` for output.
**Called by:** `monitor.py` via `process_all_sessions()` → `process_session_file()`; also `load_historical_main()` on startup.
**Calls out:** `jsonl`, `monitor_display`.

---

### monitor_display.py (351 LOC)

**Purpose:** Terminal output + event buffer for the main streaming pane. Buffers all events (tool calls, user prompts, system messages, etc.) in `main_event_buffer`. On each render cycle: applies proxy strip highlights (tool_call output replaced with pre-strip content + `highlight_stripped()`; user prompts get `[~]` badge); renders the persistent search bar on row 1; injects ⎘ copy-buttons on REQUEST and RESPONSE header lines of tool_calls with click-region tracking via `_main_copy_rows: dict[phys_row → (event_idx, 'request'|'response')]`; applies per-line substring highlight for search matches via `utils.highlight_query_in_line`; buffer renders from row 2 (row 1 reserved for search bar). `serialize_main_event(event_idx, part='all'|'request'|'response')` converts a buffer entry to clipboard text for the y-hotkey ('all') or ⎘ click ('request' / 'response'). **(2026-07-30) ⎘ copy-button on every OTHER event type's first line:** the pre-existing tool_call branch (request/response split, unconditional `_main_copy_rows` registration even when the symbol doesn't fit — a pre-existing width-guard gap, left as-is, out of scope) is followed by a new `elif eidx >= 0 and eidx != prev_eidx:` branch (first-line-of-event detection via a `prev_eidx` tracker) that appends a `⎘`/`✓` symbol via `utils.append_copy_symbol` and registers `_main_copy_rows[phys_row] = (eidx, 'all')` — but ONLY when the symbol actually fit (`padded != line`), so a too-narrow pane never leaves an invisible hit zone for these rows. `'all'` matches exactly what the pre-existing `y`-key branch in `monitor.py` already produces for every non-tool_call event (`serialize_main_event(key)`, default `part='all'`) — `_handle_main_mouse` needed NO changes, its `_main_copy_rows.get(row)` dispatch was already generic over any `part` string.

**(2026-08-18, rollout sub-milestone 2) Search bar migrated to `search_bar.py`** — full parity
with the proxy pane (the reference implementation). `_main_search: search_bar.SearchState` (one
instance) replaces what used to be 8 flat globals (`_search_query`, `_search_focused`,
`_search_committed` — dead, set but never read for any branch, dropped entirely —,
`_search_matches`, `_search_match_set`, `_search_current_idx`, `_search_cached_query` — the
unchanged-query Enter-gate, also dropped, see below). `_render_search_bar(pane_width)` is now a
thin wrapper over `search_bar.render_search_bar(_main_search, pane_width, label=_SEARCH_BAR_LABEL)`
— renders `Search: <query>_  N/M`, NO click-arrows (removed — `n`/`N` keys in `monitor.py`
navigate instead) and NO `HOVER_BG` row baseline (the shared renderer has none, by design — "one
visual search language across panes", `process-docs/pane_search/`). The private
`_highlight_query_in_line` duplicate is GONE — highlighting goes through
`utils.highlight_query_in_line(line, query, match_bg)`, same algorithm, same default
`restore_bg='\033[49m'` (this pane has NO per-row background at all, confirmed: row assembly is
a plain `f"{trunc}\033[49m\033[K{RESET}"` — no `_BG_RESTORE_SENTINEL` machinery needed here,
unlike the proxy pane's zebra/hover/strip-annotated rows).

**Search infrastructure:**
- `_main_search.query`/`.focused`/`.matches`/`.match_set`/`.current_idx`/drag-select fields — see `search_bar.py`'s `SearchState`.
- `_compute_search_matches(query)` case-insensitive substring match on serialized event text (untruncated, including bash output beyond render-truncation) — called from `monitor.py::_main_search_on_commit` on EVERY Enter (not gated on query-unchanged — corrected to the proxy pane's convention: a repeated Enter picks up events appended to `main_event_buffer` since the last search).
- `_compute_match_line_offsets(query, matches)` returns event_idx → first rendered-line-offset where query appears (for scroll-to-match-line, not just scroll-to-event-start) — main-pane-specific, not part of `SearchState`.
- `ensure_match_visible()` scrolls so current match's line is visible (2 lines context above); reads `_main_search.matches`/`.current_idx`.

**ANSI-safe BG handling:** render loop ends each line with `\033[49m\033[K{RESET}` — the explicit `\033[49m` (BG-reset only) before `\033[K` (erase-to-EOL) ensures the search-match BG can't bleed across the rest of the row even if `truncate_visible` cut the line mid-highlight before reaching the per-chunk `\033[49m` injected by `utils.highlight_query_in_line`.

**Reads:** Tool call dicts, event dicts passed as arguments; module-level `_strip_by_tool_id`, `_strip_prompt_ts_set`, `main_hover_row`, `_main_search`, `_main_copy_rows`, `_main_copy_feedback_until`, `_main_pane_width`, `_search_all_line_offsets`, `_search_match_line_offsets`, `_search_total_lines`.
**Writes:** stdout via `print()` (via `render_main_buffer`); mutates `main_event_buffer`, `main_scroll_offset`, `main_hover_row`, `main_line_map`, `_strip_by_tool_id`, `_strip_prompt_ts_set`, `_main_copy_rows`, `_main_copy_feedback_until` (expiry cleanup), `_main_pane_width`, `_search_all_line_offsets`, `_search_total_lines`, `_main_search.current_idx` (clamp on buffer shrink).
**Called by:** `monitor.py` (`print_session_status`, `ingest_proxy_strip_data`, `render_main_buffer`, `serialize_main_event`, `ensure_match_visible`, `_compute_search_matches`, `_compute_match_line_offsets`, `_count_buffer_lines`); `monitor_session.py` (all display functions).
**Calls out:** `format.formatter`, `format.formatter_events`, `format.strip_marker`, `utils` (`truncate_visible`, `_ANSI_ESCAPE_RE`, `_cell_width`, `highlight_query_in_line`), `search_bar` (shared search-bar mechanics).

---

## State

`monitor.py` owns all module-level state. Key variables:

| Variable | Type | Mutated by |
|---|---|---|
| `file_positions` | `Dict[Path, int]` | `monitor_session` via `update_session_tracking` |
| `call_counter` | `int` | `monitor_session.process_session_file` |
| `agent_to_task` / `agent_to_type` | `Dict[str, str]` | `monitor_session.handle_task_request` |
| `buffered_subagent_calls` | `Dict[str, List]` | `monitor_session.handle_subagent_call` |
| `active_project_filter` | `str \| None` | `run_monitor()` on startup |
| `_strip_proxy_position` | `int` | `_refresh_strip_cache()` each poll cycle |

`monitor_display.py` owns main-pane render state:

| Variable | Type | Mutated by |
|---|---|---|
| `main_event_buffer` | `list` | `_buffer_append` (via all `display_*` fns) |
| `main_scroll_offset` | `int` | `run_main_loop` (wheel events), `ensure_match_visible`, `render_main_buffer` (upper-bound write-back clamp) |
| `main_hover_row` | `int \| None` | `run_main_loop` (mouse motion events) |
| `main_line_map` | `Dict[int, int]` | `render_main_buffer` each render cycle |
| `_main_copy_rows` | `Dict[int, Tuple[int,str]]` | `render_main_buffer` (phys_row → (event_idx, 'request'\|'response'\|'all')) |
| `_main_copy_feedback_until` | `Dict[Tuple[int,str], float]` | `run_main_loop` click handler (set ✓-flash expiry), cleanup loop (prune expired) |
| `_main_pane_width` | `int` | `render_main_buffer` (start of cycle, snapshot for click handler) |
| `_main_search` | `search_bar.SearchState` | `monitor.py`'s search/mouse handlers (query/focused/matches/match_set/current_idx/drag-select fields, one instance replacing the pre-2026-08-18 flat globals — see `search_bar.py`) |
| `_search_match_line_offsets` | `Dict[int, int]` | `monitor.py::_main_search_on_commit` (Enter, via `_compute_match_line_offsets`) / `_handle_main_search_cancel` (clear) — event_idx → first line within event containing query; main-pane-specific, not part of `SearchState` |
| `_search_all_line_offsets` | `Dict[int, int]` | `render_main_buffer` (event_idx → first line offset in `all_lines`, used by `ensure_match_visible`) |
| `_search_total_lines` | `int` | `render_main_buffer` (len of all_lines, used by `ensure_match_visible`) |

All pane modules read monitor.py state via `from ..core import monitor as _monitor`.

## Gotchas

- `monitor_session.py` lazy-imports `monitor` (`from . import monitor as _monitor`) to avoid circular import at module level — both live in the same package so `.` is correct.
- Session scoping: `_get_session_start_ts()` reads the newest main session JSONL and subtracts 60s as the cutoff. Changing this affects what history gets replayed on startup.
- `is_agent_file()` in `monitor.py` filters out subagent JSONLs by path pattern — logic must stay in sync with `session_finder.py` which indexes them.
- `_handle_main_mouse` wheel-up (`monitor.py`) only lower-bounds `main_scroll_offset` at 0 — the upper bound lives solely in `render_main_buffer`'s write-back clamp (`max_scroll = max(0, total - buffer_height)`), not in the handler. Any new code path that mutates `main_scroll_offset` without going through a subsequent `render_main_buffer` call can overshoot for one frame; it self-corrects on the next render, same pattern as `proxy_display/pane.py`.
- `_refresh_main_data` resets `_main_search` (`search_bar.handle_search_cancel`) and `_search_match_line_offsets` on a session change, right alongside `main_event_buffer.clear()` — mirrors the proxy pane's `_refresh_proxy_data`. Without this, a stale `.matches` list of event_idx values would point past the freshly-cleared buffer until the next Enter recomputed it (the pre-2026-08-18 flat-globals version had this exact gap; fixed as part of the search-bar migration, not left as a follow-up).
