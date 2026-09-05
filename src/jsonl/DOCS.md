# src/jsonl/

## Role

Session JSONL parsing pipeline. Reads `~/.claude/projects/**/*.jsonl` files incrementally by byte
offset, correlates tool_use/tool_result pairs, extracts typed metadata (prompts, media, thinking,
skills, usage), and provides cache-turn data for the token and worker panes. This is the
single source of truth for all session content — every pane that displays session data reads
through this package. Touch it when adding new message types, changing extraction logic, or
modifying cache-turn grouping. Do NOT touch for display logic — that lives in the pane packages.

## Public Interface

- `parse_new_tool_calls(filepath, last_position, tool_use_cache, request_numbers=None)` — incremental parse, returns 9-tuple of lists + new position
- `read_new_lines(filepath, last_position)` — read raw new lines from file
- `parse_jsonl_lines(lines)` — parse raw lines into message dicts
- `get_current_position(filepath)` — return current byte offset
- `get_message_content(message)` — extract content from a message dict
- `is_tool_use(message)` — check if message is a tool_use block
- `extract_cache_turns(messages)` — extract per-turn cache tracking data grouped by user prompts

## Flow

`~/.claude/projects/**/*.jsonl` → `jsonl_parser` (incremental read by byte offset, line parse,
tool_use/tool_result correlation, requestId → ordinal assignment) → `jsonl_extractors` (typed
extractions from message list) → callers: `core.monitor_session` (the main pane), `panes.token_pane`,
`workers` (the latter two read lower-level functions — `read_new_lines`/`parse_jsonl_lines`/
`extract_cache_turns`/`get_message_content`/`is_tool_use` — directly, NOT `parse_new_tool_calls`/
`parse_new_tool_calls_isolated`, which only `core/monitor_session.py` calls; corrected 2026-09,
previously stale here).

## Modules

### jsonl_parser.py (302 LOC)

**Purpose:** Core session JSONL parser — reads new lines incrementally by byte offset, correlates tool_use/tool_result pairs, delegates typed extraction to `jsonl_extractors`, and (2026-09, additive) assigns each distinct API request a stable ordinal number. **`update_request_numbers(messages, request_numbers)`** mutates `request_numbers` (`{requestId: ordinal}`, a persistent dict the caller owns — mirrors the `tool_use_cache` convention) in place: for each `type == 'assistant'` message with non-zero `cache_read`/`cache_creation`/`input_tokens` usage (the SAME qualifying condition `jsonl_cache_turns.extract_cache_turns` uses to build an `api_call`), its `requestId` gets the next ordinal the first time it's seen — insertion order makes `len(request_numbers) + 1` the next value, no separate counter needed. This is the SAME number `format_cache_tracker`'s own `request_num` loop shows as `REQ #N` in the tokens pane, verified 2026-09 against 840 real tool_use blocks across 6 sessions in 2 projects: 0 disagreements (`dev/main_pane/probe_req_numbering.py`, `process-docs/main_pane/`). `create_tool_use_entry` additionally stamps `request_id` (the owning message's own `requestId`, `''` when absent) onto every tool_use entry — this is what `core/monitor_session.py` looks up in `request_numbers` to resolve the main pane's `req N` header. `parse_new_tool_calls`/`parse_new_tool_calls_isolated` both gained an optional trailing `request_numbers: dict = None` param (calls `update_request_numbers` only when given) — every pre-existing caller passes none, so the 9-tuple return and all existing behavior stay byte-identical. The subprocess path (`parse_new_tool_calls_isolated` with `last_position == 0`) always builds its OWN `request_numbers` dict in the child process and returns it via the Queue (4th element, alongside the existing cache-state transfer) — the parent only applies it into the caller's dict when one was actually requested.
**Reads:** Session JSONL file (by `filepath` + `last_position` byte offset); `tool_use_cache` dict for cross-chunk correlation; `request_numbers` dict (optional) for requestId ordinal assignment.
**Writes:** Nothing — returns 9-tuple `(tool_calls, new_position, malformed_warnings, user_media, thinking_blocks, user_prompts, skill_activations, usage_data, system_messages)`. Mutates the caller-supplied `tool_use_cache` and (when given) `request_numbers` dicts in place.
**Called by:** `src/core/monitor_session.py` (the only real caller of `parse_new_tool_calls_isolated`/`parse_new_tool_calls` — `monitor.py` re-exports the module but does not call it directly; `workers`/`token_pane` use lower-level functions from this package instead, see Flow above)
**Calls out:** —

---

### jsonl_extractors.py (180 LOC)

**Purpose:** Extract typed data from parsed JSONL message lists: user media (images/documents), user prompts, thinking blocks, skill activations, usage data, system messages.
**Reads:** List of message dicts (from `parse_jsonl_lines`).
**Writes:** Nothing — one typed list returned per extractor function.
**Called by:** `src/jsonl/jsonl_parser.py`
**Calls out:** —

---

### jsonl_cache_turns.py (150 LOC)

**Purpose:** Extract per-turn cache tracking data grouped by user prompts; each turn contains a list of requests with CR/CC/D/Out token metrics. Implements streaming-snapshot dedup: CC sometimes writes multiple assistant messages for the same request as incremental snapshots (partial thinking + final output). The dedup logic uses a `seen_types` set of `(type, identifier)` tuples (`('tool_use', tool_name)`, `('thinking',)`, `('text', preview)`) to skip blocks already counted in an earlier snapshot of the same response — preventing double-counting of thinking_chars across snapshots. Each `api_call` dict carries 6 usage extras from the `usage` object: `cache_creation_ttl` (dict `{ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}`), `server_tool_use` (dict `{web_search_requests, web_fetch_requests}`), `service_tier` (str), `speed` (str), `inference_geo` (str, often `""`), `iterations` (list of per-iteration breakdown dicts).
**Reads:** List of message dicts.
**Writes:** Nothing — returns list of cache turn dicts.
**Called by:** `src/panes/token_pane.py`, `src/workers/worker_pane.py`
**Calls out:** —
Private helpers (same module): `_parse_user_message_text`, `_extract_content_blocks`, `_build_api_call`, `_merge_duplicate_call`.

## Gotchas

- **CC's current JSONL format splits one logical API response into multiple top-level `assistant` lines — one per content block** (thinking/text/tool_use each get their own line), all sharing the identical `requestId` and `usage` object (measured 2026-09, `process-docs/main_pane/`). `extract_cache_turns`'s pre-existing per-`requestId` dedup (`_input_key`, `_merge_duplicate_call`) and `jsonl_parser.update_request_numbers`'s first-seen-per-`requestId` ordinal assignment both already handle this correctly without any special-casing for the split — do not assume one JSONL line == one API response when reading this package's code.
