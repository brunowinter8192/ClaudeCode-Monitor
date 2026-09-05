# src/format/

## Role

ANSI-colored string rendering — tool call pairs, user events, and the token/cache tracker pane. This package has no side effects: every function takes data in and returns a formatted string. Touch this package to change how tool calls look, how events are formatted, or how the cache tracker renders. Do NOT add I/O, state, or pane loop logic here.

## Public Interface

```python
# Strip highlighting (strip_marker.py)
from src.format.strip_marker import highlight_stripped        # inline DIM_YELLOW_BG chunk highlight

# Tool call formatting (formatter.py)
from src.format import format_tool_call
from src.format import format_request, format_response, combine_request_response
from src.format import format_todo_list, format_parameters, format_task_parameters
from src.format import format_output, format_error_output
from src.format import format_value, get_status_icon, get_status_color, shorten_tool_name

# Cache tracker rendering (token_format.py)
from src.format import format_cache_tracker
from src.format import _format_k          # compact "Xk" token count — used by workers/proxy_display
```

**(2026-09) `formatter_events.py` removed entirely** — `format_user_prompt`, `format_hook_annotation`,
`format_system_message`, `format_user_media`, `format_skill_activation`, `format_thinking` all had
zero callers once `core/monitor_session.py` stopped displaying those event types (the main pane
shows only tool calls now, see `core/DOCS.md` and `process-docs/main_pane/`); `format_hook_annotation`
was already unreferenced before this change. `format_system_reminders` (`formatter.py`) was also
removed — the `system_reminders` field it formatted was never populated anywhere in
`jsonl_parser.py`/`jsonl_extractors.py`, so the function was dead on arrival even before this milestone.

## Modules

### strip_marker.py (24 LOC)

**Purpose:** Proxy-strip content highlighting helper — `highlight_stripped` wraps found chunks in `DIM_YELLOW_BG`/`SOFT_RESET` inline. `get_stripped_data`, `build_tool_result_strip_lookup`, and `build_tool_id_strip_lookup` deleted in Stage 3 (main-pane strip overlay removed).
**Reads:** Chunk strings passed as arguments. No I/O, no shared state.
**Writes:** Returns strings. No stdout, no file writes.
**Called by:** `panes.warnings_render`.
**Calls out:** `constants` only.

---

### formatter.py (160 LOC)

**Purpose:** Format one tool call as a single ANSI-colored block for the main pane — `req N:
ToolName` header (GREEN, or BLUE for a subagent call), `key: value` param lines, a blank
separator, then the result (RED when the call errored). **(2026-09, tool-calls-only redesign,
see `process-docs/main_pane/`):** `format_tool_call(tool_name, input_data, output_data, req_num,
is_subagent=False, is_error=False)` — dropped `tool_use_id` (was already unused in the function
body before this change), `timestamp`/`call_number` (replaced by `req_num`, the same ordinal the
tokens pane shows as `REQ #N` for the same request — resolved upstream in
`core/monitor_session.py`, this module stays a pure function with no file-scoped lookups), and
`system_reminders` (the field was never populated anywhere in `jsonl_parser.py`/
`jsonl_extractors.py` — `format_system_reminders` was dead code, removed). `format_request`
returns just the header when `input_data` is empty (no trailing blank param line).
`format_response` no longer takes a header at all — the single `req N:` header above already
identifies the call, so a separate `RESPONSE #N ← Tool [ERROR]` line would be redundant; an error
is still visibly marked, via the same RED `format_error_output` as before. `format_value` gained
an optional `depth: int = 1` param (default unchanged, so every pre-existing single-level caller —
`format_parameters`, `format_task_parameters` — renders a multi-line string byte-identical to
before) to flatten `dict`/`list` values into indented `key: value` / `- item` lines instead of
Python-repr braces and quotes — unobserved in real tool usage (measured 2026-09: 840 real
tool_use blocks across 6 sessions in 2 projects, 0 dict/list-valued params — see
`process-docs/main_pane/`) but kept minimal rather than skipped, since a future tool call could
carry one and the milestone explicitly bans JSON-style punctuation in the rendered output.
Handles todo list rendering (`format_todo_list`, unchanged, kept per the milestone's own
instruction to preserve special-casing that already produces readable output), Task-parameter
`subagent_type` highlighting (`format_task_parameters`, unchanged), and status icons/colors.
**Reads:** Tool call dicts passed as arguments. No shared state, no file I/O.
**Writes:** Returns formatted strings. No stdout, no file writes.
**Called by:** `core/monitor_display.py` (`format_tool_call`, and `serialize_main_event` calling it
directly for clipboard text, ANSI-stripped).
**Calls out:** nothing (only `utils`, `constants`).

---

### token_format.py (293 LOC)

**Purpose:** Build logical lines for the token/cache tracker — groups API calls into turns with CR/CC/D counts, handles expand/collapse and viewport clipping. Returns a 5-tuple `(visible_lines, visible_keys, sticky_header, viewport_start, initial_parent_count)` — return arity UNCHANGED since 2026-08-18 (see below). The fifth element `initial_parent_count` is the number of collapsed parent rows before the current viewport — used by `token_pane.py` to keep expand/collapse key assignments stable across scrolls. Does NOT render (no zebra, no hover, no truncation) — that is `token_pane.py`'s job. Also provides `_format_k` for compact token counts. `format_cache_tracker` accepts an optional `response_rid_map: dict` (keyed by `request_id`); when a call's `request_id` matches, renders (1) usage-extras lines above the content-blocks loop (5m/1h TTL split, web_search/web_fetch if non-zero, tier/speed/geo, iteration count) and (2) rate-limit header lines (`rl: 5h:X%→HH:MM  7d:X%→…`; status/overage in YELLOW when non-nominal). Graceful when map absent or request_id not matched. **(2026-07-30) Optional `copy_feedback: Optional[dict] = None`** (keyed by `(turn_idx,call_idx)`, same as `line_keys`) — when given, appends a `⎘`/`✓` symbol to the call-summary line via `utils.append_copy_symbol`; `None` (the default, used by every pre-existing caller) skips the branch entirely, byte-identical to before.

**(2026-08-18, rollout sub-milestone 4) Search-highlight embedding — 4 new optional params, ZERO return-arity change.** `search_match_set: Optional[set]`, `search_current_key`, `search_query: str = ''`, `nav_out: Optional[dict] = None`. A match key is either `(turn_idx, call_idx)` [found in that call's own header or force-expanded detail content] or `('turn', turn_idx)` [found in the turn's own prompt/timestamp line]. BOTH get an UNCONDITIONAL whole-line "container mark" (`f"{marker}{line}{search_bar._BG_RESTORE_SENTINEL}"`, `marker` = `SEARCH_CURRENT_BG` or `SEARCH_MATCH_BG`) — not a literal-substring-only wrap, since the actual matching text may be buried in unrendered (collapsed) detail; mirrors `proxy_display`'s REQ-header "text extent" marking. An EXPANDED matching call additionally gets its specific matching detail line(s) browser-find substring-highlighted via `utils.highlight_query_in_line(line, search_query, marker, _BG_RESTORE_SENTINEL)` — header stays marked too (uniform, keeps orientation when scrolling). `('turn', idx)` keys are deliberately NEVER added to `line_keys` — turn headers stay non-interactive for clicks exactly as before this milestone; `nav_out`, when given, is populated (`.clear()`-then-rewritten in place, same contract as `proxy_display.format`'s `copy_rows_out`) with `{key: absolute_line_idx, ..., 'total_lines': N}` for the caller's OWN jump-to-match scroll math — deliberately a SEPARATE out-param from `line_keys`/return value, so `workers/worker_format.py`'s reuse of this function (which assumes every non-None key is a plain 2-int-tuple, `(name, ck[0], ck[1])`) is completely unaffected. All 4 new params default to no-op values — verified byte-identical against all 4 real callers (`token_pane.py`, `workers/worker_format.py`, `dev/click_ui/p2_copy_click_probe.py`, `dev/display/A_format_cache_tracker_proof.py`) via a frozen-turns old-vs-new comparison held constant in one process (the live `A_format_cache_tracker_proof.py` harness reads directly from `~/.claude/projects/.../*.jsonl` — the top-10-most-recently-modified REAL session files — which were actively growing during this milestone's own session, producing a false-positive mismatch on a naive capture-then-verify-later run; see `process-docs/pane_search/` for the full writeup). Two helpers extracted for this: `_format_turn_header_line(turn_idx, turn, pane_width)` (prompt-truncation/timestamp/think_str construction, now shared by the real render loop AND `panes/token_search.py`'s matcher so they can never disagree) and `_call_thinking_meta(call)` (has_thinking/sig_chars extraction, same rationale).

**Known limitation (documented, not fixed this milestone):** `_compute_cache_viewport`'s sticky-header TRUNCATION path (`len(raw) > pane_width+20`) rebuilds `sticky_header` from ONLY `re.search(r'Turn \d+ \[[^\]]+\]', raw).group(0)`, discarding everything before/after — including a prepended search marker/sentinel if the matching turn line was long enough to truncate. Net effect: a matching turn's highlight can silently disappear specifically when that turn is BOTH a search match AND long enough to truncate AND currently the sticky header. Match data and jump-to-match still work correctly in this case; only that one visual cue is lost. Narrow, cosmetic-only, left unfixed — would need restructuring the truncation logic.
**Reads:** Cache turn lists, expand state dicts, pane dimensions, scroll offset, optional response_rid_map/copy_feedback/search_match_set/search_current_key/search_query/nav_out — all passed as arguments.
**Writes:** Returns 5-tuple (unchanged shape); mutates `nav_out` in place when given (`.clear()`-then-rewrite). No stdout, no file writes.
**Called by:** `panes/token_pane.py` (`format_cache_tracker`); `panes/token_search.py` (`_format_turn_header_line`, `_call_thinking_meta`, `_format_cache_call`, `_render_expanded_call_lines`); `workers/worker_format.py` (`format_cache_tracker`, `_format_k`); `proxy_display/format.py` (`_format_k`); `dev/click_ui/p2_copy_click_probe.py`, `dev/display/A_format_cache_tracker_proof.py` (test/proof callers).
**Calls out:** `format.formatter` (`shorten_tool_name`, module-level import), `utils` (`append_copy_symbol`, `highlight_query_in_line`), `search_bar` (`_BG_RESTORE_SENTINEL`).
Private helpers (same module): `_fmt_rl_reset_time`, `_render_expanded_call_lines`, `_compute_cache_viewport`, `_call_thinking_meta`, `_format_turn_header_line`.

## Gotchas

- `highlight_stripped` wraps each **line** of a chunk individually (`DIM_YELLOW_BG{line}SOFT_RESET` per `\n`-separated segment) rather than wrapping the whole chunk as a single unit. Downstream renderers (`warnings_pane`) split the result on `\n` and apply a per-line zebra BG; a single wrap around the whole chunk would leave lines 2..N without `DIM_YELLOW_BG`, causing the zebra selector to miss them. `outer_bg` is appended once after the final highlighted line to restore the caller's row background.
- `token_format.py` imports `formatter.shorten_tool_name` at module level — same package, `from .formatter import shorten_tool_name`. Do NOT change to `..formatter`.
- `_format_k` and `_format_cache_call` use leading underscores but are exported and used by 4 external callers — they are effectively public despite the naming convention.
- `format_cache_tracker` returns a **5-tuple** `(visible_lines, visible_keys, sticky_header, viewport_start, initial_parent_count)` — NOT a string, and this shape is preserved even after the 2026-08-18 search-highlight additions (4 new params, all optional out-params/kwargs, zero new return values — `nav_out` is populated in place, not returned). The render loop (zebra/hover/truncation, plus `search_bar.resolve_bg_restore` per row) lives in `token_pane.py`. `initial_parent_count` counts collapsed parent rows before the viewport start; callers that don't need it unpack with `_, _, _, _, _`.
- Line content uses `SOFT_RESET` (`\033[39m`) instead of `RESET` (`\033[0m`) for inline FG-color endings. This lets the render loop inject a row-level BG without it being killed mid-line. Exception: `_format_cache_call` keeps `RESET` for `cc_broken` rows (error-BG ends at the line terminator, not mid-content).
