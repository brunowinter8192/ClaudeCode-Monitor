# dev/main_pane/

## Role

Measurement and regression coverage for the main pane's 2026-09 tool-calls-only redesign — the
main pane now shows only tool calls, numbered `req N` by the same requestId ordinal the tokens
pane shows as `REQ #N`, instead of the old `call_number`-based `REQUEST #N`/`RESPONSE #N` pair.
Shares its name with `process-docs/main_pane/`, the area covering the investigation, design, and
verification for this redesign.

## Scripts

### probe_req_numbering.py (200 LOC)

**Purpose:** The pre-implementation measurement this milestone was designed against. For a given
session JSONL, computes the "tokens-pane way" of numbering a request (`_tokens_pane_req_numbers`
— via the REAL `jsonl_cache_turns.extract_cache_turns` plus the same `request_num += 1`-per-
api_call loop `format_cache_tracker` uses, so there is no chance of subtly diverging from what the
tokens pane itself shows) against the "main-pane way" (`_main_pane_req_numbers` — a single global
counter over qualifying `assistant` messages in file order, first-seen-per-requestId). Reports,
per session: total tool_use blocks, how many agree, and a cause breakdown for every disagreement
(subagent/no-requestId-path, missing requestId, never-qualifying on either side, or a genuine
numeric mismatch). Measured 2026-09 against 6 real sessions (2 projects, 840 tool_use blocks
total): **0 disagreements everywhere** — the design this probe validated is exactly what shipped
in `jsonl_parser.update_request_numbers`/`create_tool_use_entry`.
**Reads:** any session JSONL path(s) given as argv.
**Writes:** `md/req_numbering_probe_report.md`.
**Usage:** `python3 dev/main_pane/probe_req_numbering.py <jsonl_path> [<jsonl_path> ...]`

### tests/test_req_numbering_and_format.py (332 LOC)

**Purpose:** Regression suite for the shipped redesign (43 checks). Placed under `tests/`
(pytest-shaped filename) so `src.hooks.block_dev_imports_src`'s regression-suite exemption
applies — needs literal `from src....` imports across four modules.
- `jsonl_parser.update_request_numbers`: first-seen ordinal assignment, non-qualifying/duplicate
  requestId skipped, incremental continuation across separate calls (mirrors the real poll-cycle
  usage).
- `jsonl_parser.create_tool_use_entry`: the new additive `request_id` key, including the
  graceful empty-string fallback for a message with no `requestId` at all (the untested-in-
  practice subagent/progress path).
- `jsonl_parser.parse_new_tool_calls`/`parse_new_tool_calls_isolated`: the optional
  `request_numbers` param is additive (byte-identical return tuple when omitted); populates
  correctly on the direct (`last_position != 0`) path AND the subprocess path
  (`last_position == 0`, a REAL subprocess spawned — this is the plumbing most likely to silently
  break, since the Queue payload gained a 4th element).
- `format.formatter.format_tool_call`: the new single-block shape (`req N: Tool` header, `key:
  value` params, blank line, result — no timestamp/arrows/char-counts), RED error marking, GREEN/
  BLUE subagent color, the no-params case, multi-line value indentation (byte-identical to the
  pre-redesign convention), and the dict/list flatten (no JSON braces or quotes — an unobserved
  shape in real data, see the probe above, but still covered since the milestone explicitly
  requires it). `TodoWrite`'s special-cased readable output confirmed kept.
- `core.monitor_session.process_session_file`: end-to-end — only `tool_call`/`warning` events
  reach `main_event_buffer` (no `user_prompt`/`user_media`/`thinking`/`skill_activation`/
  `system_message`, confirming the deleted display call sites stay deleted), and the buffered
  `req_num` matches the value `update_request_numbers` computed for that request.
**Reads:** synthetic JSONL written to `tempfile` per test — no real session data.
**Writes:** nothing persistent — prints PASS/FAIL to stdout.
**Usage:** `python3 dev/main_pane/tests/test_req_numbering_and_format.py`

## Gotchas

- `probe_req_numbering.py`'s "main-pane way" re-derivation and the shipped
  `jsonl_parser.update_request_numbers` are two independently-written implementations of the same
  rule (by design — the probe existed BEFORE the implementation, as the investigation that decided
  the design) — they are not literally the same code. If either ever changes, re-run the probe
  against a fresh session to confirm they still agree; the regression suite locks the SHIPPED
  function's behavior on synthetic fixtures, not agreement with this probe's own copy.
- The CC JSONL format observed 2026-09 splits one logical API response into multiple top-level
  `assistant` lines (one per content block — thinking/text/tool_use each their own line), all
  sharing the same `requestId` and `usage` object. `update_request_numbers` and
  `jsonl_cache_turns.extract_cache_turns`'s pre-existing per-requestId dedup both already handle
  this correctly (first-seen-wins for the ordinal; dedup-and-merge for the tokens pane's api_call
  rows) — this shape is why the probe found 0 disagreements without needing new dedup logic.
