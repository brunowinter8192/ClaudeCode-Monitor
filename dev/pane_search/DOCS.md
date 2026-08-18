# dev/pane_search/

## Purpose

Feasibility measurement + regression coverage for the proxy-pane search feature
(`src/proxy_display/`, main pane only — `pane.py`, `format.py`, `render_turn.py`,
`forwarded_parser.py`, `search.py`). Milestone 1 (`p1_*`) probed the cost of candidate message-
reconstruction strategies on real forwarded-delta logs — measurement only, no feature code.
Milestone 2 (`p2_*`) is the regression suite for the implemented feature: permanent row-1
search bar, one-sweep reconstruction, real-render-based matching, and the `flow_id`-based
`_lazy_load_messages_forwarded` fix found during M2 investigation. See
`process-docs/pane_search/` for the investigation trail.

## Scripts

### p1_full_sweep_cost_probe.py (403 LOC)

**Purpose:** Compares two reconstruction strategies on a real `_forwarded.jsonl` log:
per-entry lazy-load (replay-from-byte-0 per entry, O(N) replays) vs one-sweep reconstruction
(single pass, deque eviction removed, keeps messages for all entries).

dev/ scripts may not import `src/` — the delta-accumulation algorithm
(`_dict_to_list`/`_apply_delta_to_list`/family accumulator/deque-bound eviction) is
reimplemented locally, mirroring `src/proxy_display/forwarded_parser.py`'s
`_parse_forwarded_log`/`_lazy_load_messages_forwarded` (same per-line I/O + `json.loads` +
delta-apply work). Message summarization is simplified to chars-only — real
`src/proxy/message_summary.py` adds per-block-type detail irrelevant to the O(N) file-replay
cost measured here; both strategies share the same local summarizer, so the comparison is
apples-to-apples.

Measures: summed + per-entry wall time for lazy-load-ALL-entries (`_lazy_load_one`, linear-fit
slope quantifies the O(idx)-per-call / O(N^2)-total growth), one-sweep total wall time
(`_sweep_parse(fwd_path, keep_last=None)`), and peak/current traced RAM (`tracemalloc`,
`gc.collect()` + `clear_traces()` isolation) for one-sweep vs the keep-last-10 baseline.

**Usage (from project root):**
```bash
./venv/bin/python dev/pane_search/p1_full_sweep_cost_probe.py [fwd_log_path]
```
Defaults to the largest forwarded log available on the dev machine as of 2026-08-18
(`/Users/brunowinter2000/Documents/ai/monitor-cc/src/logs/dual_log/api_requests_opus_wise2627_1786984319_forwarded.jsonl`,
main-repo path — gitignored, absent from worktrees). Pass an explicit path to measure a
different log.

**Output:** writes `dev/pane_search/md/p1_full_sweep_cost_report.md`; prints a one-line summary
(entries/lazy_sum_ms/sweep_ms/ram_delta_kb) to stdout.

**Reads:** `_forwarded.jsonl` dual-log (positional arg or default path).
**Writes:** `dev/pane_search/md/p1_full_sweep_cost_report.md`; stdout summary line.
**Called by:** manual invocation only.
**Calls out:** stdlib only (`json`, `tracemalloc`, `gc`, `collections.deque`) — no `src/` imports.

---

### p2_search_feature_regression_test.py (328 LOC)

**Purpose:** Regression guard for the implemented M2 search feature. Unlike `p1_*` (fully
reimplemented, no `src/` imports), this file DOES exercise real `src/` code — via
`importlib.import_module('src...')` (the sanctioned workaround for the dev-import-block hook,
precedent: `dev/timer-loop/test_abort_stamp_scope.py`), not a literal `from src.` line. Covers:
bar renders at row 1 (empty + populated query text); line_map/copy_rows shift correctness
(header row never gets a body key, body starts at row 2); collapsed-hit marks the REQ header row
only; expanded-hit marks BOTH the header AND the matching inner content line (decision: header
stays marked when expanded); `n`/`N` jump ordering (wraps both directions, no-ops with zero
matches); Esc clears query+matches but the bar itself is never hidden (it's a permanent row, not
a toggle); scroll-jump reuses the existing `_proxy_just_expanded`/`item_positions` clamp and is
idempotent across repeated renders at the same offset; the `flow_id`-based
`_lazy_load_messages_forwarded` fix, verified against a SELF-CONTAINED synthetic 2-batch
forwarded-delta JSONL fixture (not the real gitignored log) reproducing the exact
`_fwd_req_idx`-collision scenario found during investigation — portable, no dependency on any
one dev machine's log files.

Synthetic entries (`_make_entry`) use a per-index unique marker embedded in that entry's own NEW
message (`messages` list built CUMULATIVE — length == `message_count`, one filler message per
earlier index plus this entry's own marked one) — `render_messages._render_new_messages` finds
"new" messages via `range(prev_msg_count, len(messages))`, so a non-cumulative per-entry-only
messages list silently renders an EMPTY new-message range and the marker never appears (a mistake
made and caught while writing this test — see `process-docs/pane_search/`). The marker is
deliberately NOT placed in `system_blocks` — that section is a NESTED collapsible
(`('sys', entry_idx)`) not shown by `_render_req_expanded` unless that sub-toggle is ALSO
expanded, so it's a poor choice for asserting "found in the always-visible expanded view".

**Usage (from project root):**
```bash
./venv/bin/python dev/pane_search/p2_search_feature_regression_test.py
```

**Output:** PASS/FAIL per check to stdout; writes `dev/pane_search/md/p2_search_feature_regression_test_<timestamp>.md`; exits 1 if any check fails.

**Reads:** nothing external — seeds `src.proxy_display.pane` module state with synthetic
entries directly; the flow_id-fix test writes a throwaway forwarded-delta JSONL fixture under
`tempfile.mkdtemp()`, removed after the check.
**Writes:** `dev/pane_search/md/p2_search_feature_regression_test_<timestamp>.md`.
**Called by:** run manually — regression guard for the M2 search feature; re-run after any change
to `pane.py`'s search state/handlers, `format.py`'s `format_proxy_block`/`_apply_row_backgrounds`,
`render_turn.py`'s search-marker embedding, `search.py`, or `forwarded_parser.py`'s
`_lazy_load_messages_forwarded`/`reconstruct_all_messages`.
**Calls out:** `src.proxy_display.pane`, `src.proxy_display.format`, `src.proxy_display.search`,
`src.proxy_display.forwarded_parser`, `src.constants` — loaded via `importlib.import_module`.
