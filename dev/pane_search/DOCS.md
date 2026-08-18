# dev/pane_search/

## Purpose

Feasibility measurements for the planned proxy-pane search feature (`src/proxy_display/`).
The pane keeps `messages=None` outside the last-`PROXY_MESSAGES_KEEP_LAST` window; searching
ALL requests' content requires reconstructing every entry's messages. Scripts here probe the
cost of candidate reconstruction strategies on real forwarded-delta logs — measurement only,
no feature code.

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
