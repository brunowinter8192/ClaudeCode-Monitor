# dev/display/test_hover_map.py — stripped-pair test restored to current architecture

## Problem

`test_stripped_msg_pair_alignment` in `dev/display/test_hover_map.py` (11-test suite for expand-model line_map correctness) failed with `ImportError: cannot import name '_parse_log_file' from src.proxy_display.parser` — the whole suite died before any test ran (10 other tests unaffected once reached).

`_parse_log_file` was removed from `src/proxy_display/parser.py` as part of the forwarded-log migration (see `process-docs/pipeline/pipe04_display.md` § Proxy Pane — Forwarded-Log Migration). The display path now parses via `parse_proxy_log_forwarded` / `_parse_forwarded_log` (`src/proxy_display/forwarded_parser.py`).

## Premise check — was the old test still meaningful on a 1:1 port?

No. The old test filtered entries by `e.get('stripped_msg_indices')` populated, then rendered via `render_messages`. `_parse_forwarded_log` unconditionally sets `stripped_msg_indices = []` (`forwarded_parser.py:117` — comment: "Placeholders for main-log-only fields; use_dual overlay path handles display"). A 1:1 port would always hit the `stripped: []` → skip branch: never actually exercising `render_messages`, silently green forever. Worse: even before the ImportError, the old test drove `render_messages` down its legacy non-dual branch (`use_dual=False`, `_render_stripped_block`) — a code path forwarded-log entries never take in production anymore.

## Decision: re-found on the current data surface (not prune)

Stripped-span data in the current architecture reaches an entry as `entry['_stripped_spans']` — a reference to the family accumulator built by `accumulate_dual_log` over the sibling `*_stripped.jsonl` dual-log, attached per-entry by `pane.py`'s `_refresh_proxy_data` (pane.py:429-442) alongside `_injected_spans` and four ownership-lookup dicts (`_strip_fns_lookup`, `_inject_fns_lookup`, `_strip_msgs_lookup`, `_inject_msgs_lookup`). `render_messages` branches on `use_dual = '_stripped_spans' in entry`.

Rewrote the test to mirror that production wiring exactly:
1. Glob `src/logs/dual_log/api_requests_*_forwarded.jsonl` newest-first (not a hardcoded filename — the old test's hardcoded `api_requests_opus_monitor_cc_1776783075.jsonl` no longer exists on disk; a stale timestamp silently degrades to the skip-branch as logs rotate, which is exactly the failure mode that let the premise go stale unnoticed for the old test).
2. For each candidate with a sibling `*_stripped.jsonl`: `_parse_forwarded_log(fwd_path, 0, {}, keep_last=None)` (keep_last=None → ALL entries get `messages` populated, per forwarded_parser.py:129-130 — same one-sweep semantics as `reconstruct_all_messages`).
3. `accumulate_dual_log(stripped_path, 0, acc)` to build the family accumulator.
4. Filter to entries whose own `flow_id` appears in `_has_content_by_flow_id` as `True` — the forwarded-architecture equivalent of "this request's stripped delta carried content" (replaces the old `stripped_msg_indices` filter).
5. Attach `_stripped_spans`/`_injected_spans` + the four lookup dicts per-entry (matching pane.py), then call `render_messages(entry, prev, [], {idx: True}, 150)` and assert `len(lines) == len(keys)`.

Net effect: the rewritten test exercises the REAL dual-color overlay path (`_render_block_spans`, `_lookup_spans`, `_render_flow_extra_messages`) that production actually runs — strictly more coverage of current behavior than the old test provided, so pruning (option b) was not the better call.

## Verification

Ran against the newest available real dual-log pair on disk (`api_requests_worker_25c51a2e_hover-map-test_1787222072_{forwarded,stripped}.jsonl`, 20 forwarded entries, 18 with stripped content): 5 tested entries, `len(lines)==len(keys)` held for all (35/47/138/114/222 lines respectively). Full suite: 45 passed, 0 failed.

Prototyped first as a throwaway `/tmp/probe_stripped.py` before folding into the real test file — confirmed the pane.py wiring reproduction produced correct render output before committing to the approach.

## Gotcha for future work on this test

The test's real-data source is `src/logs/dual_log/` — gitignored, environment-local, populated only by actually running the proxy. On a machine/checkout with no prior proxy sessions, all glob candidates are empty and the test hits its graceful skip (`assert_true(True, ...)`, counted as PASS). This is by design (mirrors the old test's `log_path.exists()` skip) but means the stripped-pair assertion provides zero signal on a clean environment — a regression here would only surface where real dual-log data exists.
