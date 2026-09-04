# 2026-09-04 — msgs' sys/tool lines show original chars, plus whole-stripped tools

Continues the 2026-09-03 sys/tool-delta-line and wire-delta-tail work in this area. `sys[i]`/
`tool[Name]` lines showed the FORWARDED (wire) size and a changed/new tag, but never what the
proxy itself did to that content — the exact gap the msg-line `−N +M → Wc` tail closed a day
earlier for msgs and blocks. This closes it for sys/tool lines too, and surfaces a class of tool
that never had a line at all: one the proxy strips WHOLE, which is absent from the wire on every
request and therefore invisible to a wire-based comparison.

## The central open question, and how it was answered before writing any code

The stripped stream's `tools_delta` records a whole-tool removal as `{"whole": True}` — no text,
no size. Showing "how big was this before the proxy removed it" therefore needs a size from
somewhere else. The candidate: the LAST `_original` request's own `tools` list, already parsed by
`load_timeline` for every other purpose this package has. Measured with a throwaway probe before
any implementation, then formalized as `dev/dual_log_cli/probe_sys_tool_original_chars.py`:

- **336/336 (100%)** whole-stripped tool name-instances across 42 sessions found in that same
  session's own last-request tools list. Always the same 8 names (`Agent`, `Artifact`,
  `AskUserQuestion`, `DeferredToolPlaceholder`, `ReportFindings`, `ScheduleWakeup`, `ToolSearch`,
  `Workflow`).
- **Tool content stability:** 0 hash mismatches across 45 sessions comparing any earlier request's
  own tool-by-name content against the last request's. CC's own tool definitions never change
  within a session.
- **System block stability**, scoped to the only indices ever stripped (1, 2, 3): 0 length or
  content mismatches across 44 sessions comparing the conversation family's FIRST real request
  against its LAST.

This is what makes "look up the ORIGINAL size in the last request's own payload, for ANY earlier
request's line" safe — not just for whole-stripped tools, but for every sys/tool line, transformed
or not: for an untouched line the original and wire value are identical anyway (nothing was
stripped), so the swap is invisible there and only matters where it was supposed to.

## The other open question: does system/tools have the same write-side lag messages does

The 2026-08-30 messages overlay needed a lag correction (`_lag_msg_idx_by_flow_id`) because CC's
trailing total_tokens message arrives list-shaped the same request it's nuked, and the diff
engine's `_ops_from_content_change` cannot diff list content — the strip gets recorded one request
late. Checked whether system/tools has an analogous trap before assuming either way: read
`src/proxy/diff_engine.py`'s `_diff_system`/`_diff_tools` — both compute a DIRECT diff of that
SAME request's own original vs. forwarded halves, with no historical ops-accumulation chain at
all. Structurally there is no shape-ambiguity window for a delayed recording. Verified against the
task's own cited example (`opus_monitor_cc_1788464543`'s first real request): the stripped and
injected streams' own `system_delta` lines both carry the exact same `flow_id`
`request_boundaries` marks as that request's owner, and their recorded numbers match exactly —
stripped sys 1/2/3 = 57/907/1210 chars, injected 1/39307/1 chars, both matching a direct lookup of
`payload["system"][1/2/3]`'s text length. No lag correction was added; `build_sys_tool_overlay`
has no `_lag_*` set to consult.

## Design

`accumulate_dual_log` (`src/proxy_display/parser.py`) gained two purely-additive per-flow dicts,
`_sys_idx_by_flow_id`/`_tool_name_by_flow_id`, mirroring the existing `_msg_idx_by_flow_id` — no
existing key touched, and the proxy pane's own consumption (which pre-seeds its accumulator dict
with a fixed key set, same as it already does for `_lag_msg_idx_by_flow_id`) is unaffected since it
never reads either new key.

`overlay.py` gained a sibling to `build_overlay`: `build_sys_tool_overlay(session, family,
boundaries)` returns `(sys_overlay, tools_overlay)`, reusing `accumulate_dual_log` a second time
(an independent accumulator — an extra ~11 ms per the existing wire-delta-tail measurement,
negligible) rather than hand-rolling a second parser. `_owners_by_index` was refactored to share a
new `_owners_by_flow_key` helper with the new function — a pure refactor, re-verified against
`test_msgs_overlay.py`'s existing 13 checks.

`render.py`'s `_req_delta_lines` was rewritten rather than extended in place: each line's leading
chars now comes from a lookup into `data["payload"]`'s own `system`/`tools` lists by index/name
(parsed from the label — `_sys_index_from_label`/`_tool_name_from_label` — rather than touching
`timeline._sys_lines`/`_tool_lines`'s item dicts at all, keeping the blast radius to render.py
alone), falling back to the item's own wire chars whenever the lookup can't resolve. That fallback
is not just a compatibility shim — every existing hand-built test fixture in this area carries no
`"payload"` key at all, so the fallback is what keeps `test_msgs_sys_delta.py`'s 26 checks and
`test_msgs_overlay.py`'s 13 checks passing byte-for-byte unchanged. A whole-stripped tool has no
wire line to attach to, so it is synthesized — matched to the marker whose OWN `flow_id` the
overlay recorded (never a req NUMBER, which a re-fire could make ambiguous), and skipped silently
when its name can't be resolved in `orig_tools` rather than guessing a size.

`_run_msgs` (`__main__.py`) now also calls `build_sys_tool_overlay` and threads it into
`render_msgs`. `_run_expand`/`_run_search`/`_run_sessions` were not touched.

## Verification

- New suite `dev/dual_log_cli/tests/test_msgs_sys_tool_overlay.py` (14 checks): untouched line
  byte-identical with an empty overlay supplied; a transformed system line switches to original
  chars and shows the tail (reproducing the corpus numbers above); a desc-stripped tool the same;
  a whole-stripped tool synthesized standalone with full strip and wire 0; a whole-stripped tool
  scoped to a DIFFERENT flow_id produces no line under the wrong marker; an unresolvable
  whole-stripped name is skipped; a missing `sys_tool_overlay` argument renders identically to an
  explicit empty one.
- Full re-run of all 8 suites in `dev/dual_log_cli/tests/`, all passing: `test_msgs_blocks` 13/13,
  `test_msgs_overlay` 13/13, `test_msgs_sys_delta` 26/26 (unchanged), `test_msgs_sys_tool_overlay`
  14/14, `test_msgs_usage` 13/13, `test_search_chars` 17/17, `test_sidecar_exclusion` 13/13,
  `test_tool_name_comparison` 14/14.
- Real invocation, `msgs monitor_cc_1788464543 0 12`: REQ 1's separator now shows `sys[1] 57c −57
  +1 → 1c`, `sys[2] 907c −907 +39,307 → 39,307c`, `sys[3] 1,210c −1,210 +1 → 1c` (exact original
  chars + tail), 7 desc-stripped `tool[...]` lines the same way, and 8 new synthesized
  whole-stripped-tool lines (`tool[Agent] 3,172c −3,172 +0 → 0c`, etc.) that never appeared before;
  REQ 2-5 render unaffected.
- `expand`, `search`, `sessions` confirmed unaffected by direct invocation on the same session —
  none of the three touch `render_msgs`/`_req_delta_lines`/`build_sys_tool_overlay` at all.

## Relevant Symbols / Paths

- `_req_delta_lines`, `_delta_line`, `_sys_index_from_label`, `_tool_name_from_label`
  (`src/dual_log_cli/render.py`)
- `build_sys_tool_overlay`, `_owners_by_flow_key`, `_system_overlay`, `_tools_overlay`
  (`src/dual_log_cli/overlay.py`)
- `_sys_idx_by_flow_id`, `_tool_name_by_flow_id` (`src/proxy_display/parser.py`'s
  `accumulate_dual_log`)
- `_diff_system`, `_diff_tools` (`src/proxy/diff_engine.py`) — the structural reason no lag applies
- `dev/dual_log_cli/probe_sys_tool_original_chars.py` — the corpus measurement backing the
  original-chars design decision, re-runnable against the live corpus
- Ground truth for the worked example: `src/logs/dual_log/api_requests_opus_monitor_cc_1788464543_*.jsonl`
