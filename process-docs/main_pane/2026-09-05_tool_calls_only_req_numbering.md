# Main Pane Redesign: Tool-Calls-Only, Numbered Like the Tokens Pane (2026-09-05)

## Problem

The main pane rendered each tool call as a `REQUEST #N`/`RESPONSE #N` header pair, where `N` was
`call_number` — a running per-tool-call counter local to the main pane. The tokens pane numbers
`REQ #N` by distinct API request (`requestId`), in order of first appearance. The two numbers never
matched for the same call, so the main pane was useless for cross-referencing "which request was
that" against the tokens pane.

## Investigation — measuring before designing

Before touching any code, `dev/main_pane/probe_req_numbering.py` computed both numbering schemes
independently against real session JSONL and compared them:

- **Tokens-pane number:** the REAL `jsonl_cache_turns.extract_cache_turns` plus the exact
  `request_num += 1`-per-`api_call` loop `format_cache_tracker` uses (reused, not reimplemented,
  so there was no risk of the probe silently disagreeing with what the tokens pane itself shows).
- **Main-pane-intended number:** a single global counter over qualifying `assistant` messages in
  file order (the same non-zero `cache_read`/`cache_creation`/`input_tokens` condition
  `extract_cache_turns` uses), assigning the next ordinal to a `requestId` the first time it's
  seen — no per-turn grouping needed, since a tool_use's own message already carries `requestId`
  directly.

Measured against the newest monitor-cc and wise2627 sessions, then 4 more sessions for
robustness: **840 tool_use blocks across 6 sessions in 2 projects, 0 disagreements everywhere.**
None of the anticipated failure modes (streaming chunk without usage, aborted request, subagent
progress message, missing requestId) occurred even once. Two concrete findings shaped the design:

- **The current CC JSONL format splits one logical API response into multiple top-level
  `assistant` lines — one per content block** (thinking/text/tool_use each get their own line),
  all sharing the identical `requestId` and `usage` object. `extract_cache_turns`'s pre-existing
  per-`requestId` dedup and the new `update_request_numbers`'s first-seen-per-`requestId` logic
  both already handle this correctly with zero special-casing.
- **This project's own real usage never exercises the subagent/Task-tool path** — 0
  `agent-*.jsonl` files, 0 `type:progress` messages, 0 Task tool_use blocks across every session
  checked (workers here are separate tmux/CC sessions, not Task subagents). The subagent color
  path and the `req_num='?'` fallback for an unresolved `requestId` are both implemented and
  unit-tested on synthetic fixtures, but neither has ever been observed against real data — this
  is stated plainly rather than implied as verified.
- **Tool-input values across all 840 measured blocks were 100% string/int/bool/float** — zero
  dict/list-valued params (no TodoWrite use, no MCP tools, no Task tool in either project). The
  "no JSON braces or quotes" requirement for dict/list values is therefore implemented against an
  unobserved shape, kept deliberately minimal rather than heavily engineered.

## Design

**Numbering, additive only (`src/jsonl/jsonl_parser.py`):** `update_request_numbers(messages,
request_numbers)` mutates a persistent `{requestId: ordinal}` dict in place; insertion order
makes `len(request_numbers) + 1` the next ordinal, no separate counter. `create_tool_use_entry`
gained one new key, `request_id` (the owning message's own `requestId`, `''` when absent).
`parse_new_tool_calls`/`parse_new_tool_calls_isolated` both gained an optional trailing
`request_numbers: dict = None` param — every pre-existing caller (none of which actually turned
out to exist beyond `monitor_session.py`, see below) passes none, so the 9-tuple return stays
byte-identical. The subprocess path (`parse_new_tool_calls_isolated` with `last_position == 0`)
always builds its own `request_numbers` dict in the child process and returns it via the Queue (a
4th payload element, alongside the existing cache-state transfer) — this was the plumbing most at
risk of silently breaking, and is covered by a dedicated test spawning a REAL subprocess rather
than trusting the direct-path test alone.

**A stale DOCS.md claim, corrected while investigating callers:** `src/jsonl/DOCS.md` listed
`workers/worker_format.py`, `workers/worker_pane.py`, and `panes/token_pane.py` as callers of
`parse_new_tool_calls`. A caller-safety grep for the new optional param found this false — those
three modules call lower-level functions (`read_new_lines`, `parse_jsonl_lines`,
`extract_cache_turns`, `get_message_content`, `is_tool_use`) directly; `monitor_session.py` is the
ONLY real caller. Corrected in the same commit, since it was directly relevant to confirming the
new param's safety.

**State (`src/core/monitor.py`):** `request_numbers_by_file: Dict[Path, dict]`, mirroring
`tool_use_caches` exactly — same init/reset sites (new file, session change, `load_historical_main`).
`monitor_session.py::process_session_file` resolves `tool_call['req_num'] =
request_numbers.get(tool_call['request_id'], '?')` for every extracted call BEFORE dispatching to
the task/subagent/regular handlers, so `req_num` reaches the buffer without threading a new
parameter through each handler — they already pass the same dict through unchanged.

**Display scope — main pane shows only tool calls:** `process_session_file` stopped calling
`display_user_media`, `display_skill_activation`, `display_thinking`,
`display_user_prompt_from_jsonl`, `display_system_message`. Malformed-JSON `warning` events and
the session-change banner are kept (not covered by the exclusion list, and the warnings pane reads
proxy-side `_errors` — not main-session parse errors — so removing them would have silenced a
diagnostic class with no replacement).

**Dead-code cleanup, per the explicit instruction to grep repo-wide rather than leave dead call
sites:** once the five `display_*` functions lost their only caller, their formatter counterparts
in `src/format/formatter_events.py` (`format_user_prompt`, `format_system_message`,
`format_user_media`, `format_skill_activation`, `format_thinking`) also hit zero callers — the
whole module was deleted (its sixth function, `format_hook_annotation`, was already unreferenced
before this change and went with the module). `format_system_reminders` (`formatter.py`) was
found to be dead on arrival even before this milestone — the `system_reminders` field it formatted
was never populated anywhere in `jsonl_parser.py`/`jsonl_extractors.py` — and was removed too.
Exports updated in `src/core/__init__.py` and `src/format/__init__.py` accordingly.

**Format (`src/format/formatter.py`, rewritten):** `format_tool_call(tool_name, input_data,
output_data, req_num, is_subagent=False, is_error=False)` — `req N: ToolName` header (GREEN/BLUE
by subagent, unchanged color convention), `key: value` param lines (existing
`format_parameters`/`format_todo_list`/`format_task_parameters` special-casing kept — it already
produced readable non-JSON output), a blank separator, then the result (RED = the visible error
marker, same convention as before, no separate `[ERROR]` header needed since there's only one
header now). No timestamp, no char counts, no `→`/`←` arrows. `format_value` gained an optional
`depth` param (default unchanged) to flatten `dict`/`list` values into indented lines instead of
Python-repr braces/quotes, for the unobserved-but-still-guarded-against shape noted above.

**Copy/click mechanics simplified, not reinvented:** tool_call previously registered TWO copy
regions (`'request'`/`'response'`, keyed to the two separate headers). With one block per call, it
now falls through the SAME generic "first line of any event → `'all'` copy region" branch every
other event type already used — the special-cased branch was deleted outright rather than
adapted, since the generic mechanism already did exactly what was needed.
`serialize_main_event`'s tool_call case now calls `format_tool_call` directly (ANSI-stripped) for
clipboard text instead of reconstructing the text a second time, so clipboard content can never
drift from what the pane displays.

## Verification

- `dev/main_pane/probe_req_numbering.py` re-run at commit time: monitor-cc 154/154 agree,
  wise2627 83/83 agree (both grown since the investigation-phase run, live logs).
- New suite `dev/main_pane/tests/test_req_numbering_and_format.py`: 43/43 passed — covers
  `update_request_numbers` (first-seen order, non-qualifying/duplicate skip, incremental
  continuation), `create_tool_use_entry`'s `request_id`, the optional-param threading on BOTH the
  direct and the real-subprocess path, `format_tool_call`'s full shape (including error marking,
  subagent color, no-params, multiline, dict/list flatten, TodoWrite's kept special case), and
  `process_session_file`'s end-to-end tool-calls-only buffering with correct `req_num` attachment.
- `dev/click_ui/p2_copy_click_probe.py` updated for the new single-region copy behavior (an
  expected behavior change, not a regression) — 34/34 passed.
- `dev/pane_search/p4_main_pane_parity_test.py` updated — its synthetic fixture helper used
  `system_message` events, which no longer render; switched to `tool_call` events (the marker text
  lands in an uncolored param line, preserving the "clean surface for highlight assertions"
  property the old fixture relied on) — 77/77 passed, confirming the search-bar mechanics
  (drag-select, editor-style deletion, Enter-always-reruns, session-change reset) are completely
  unaffected by the rendering redesign.
- `dev/jsonl/A_extract_cache_turns_proof.py` (untouched function, caller-safety check only): its
  checked-in 2026-06 baseline has zero session overlap with the current corpus (pre-existing
  staleness, unrelated to this change) — a fresh capture+verify round-trip against 10 current real
  sessions passed 10/10, confirming `extract_cache_turns` still runs cleanly.

## Relevant Symbols / Paths

- `update_request_numbers`, `create_tool_use_entry` (`src/jsonl/jsonl_parser.py`)
- `request_numbers_by_file` (`src/core/monitor.py`)
- `process_session_file` (`src/core/monitor_session.py`)
- `format_tool_call`, `format_value` (`src/format/formatter.py`)
- `_format_event_to_lines`, `render_main_buffer`, `serialize_main_event` (`src/core/monitor_display.py`)
- `dev/main_pane/probe_req_numbering.py` — the investigation, re-runnable against the live corpus
- Ground-truth sessions (2026-09-05 snapshot): the newest `~/.claude/projects/-Users-brunowinter2000-Documents-ai-monitor-cc/*.jsonl` and `~/.claude/projects/-Users-brunowinter2000-Documents-wise2627/*.jsonl` files — live, growing logs; absolute counts in this entry reflect that one measurement pass, not a fixed corpus size
