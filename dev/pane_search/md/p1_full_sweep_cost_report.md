# P1 — Full-Sweep Reconstruction Cost Probe

Milestone 1 measurement for the proxy-pane search feature (`src/proxy_display/`). Compares
per-entry lazy-load (replay-from-0 per entry, mirrors `_lazy_load_messages_forwarded`) against
one-sweep reconstruction (single pass, deque bound removed, mirrors `_parse_forwarded_log`) for
the cost of making ALL entries' messages searchable. No feature code — measurement only.

Methodology note: dev/ scripts must not import `src/`, so the delta-accumulation algorithm is
reimplemented locally in this probe (`_sweep_parse`/`_lazy_load_one`), mirroring
`src/proxy_display/forwarded_parser.py`'s `_parse_forwarded_log`/`_lazy_load_messages_forwarded`
structurally (same per-line I/O + json.loads + delta-apply work). Message summarization is
simplified to chars-only (real `_summarize_message` adds per-block-type detail irrelevant to the
O(N) file-replay cost measured here); both strategies below share this same local summarizer.

## Log measured

- File: `api_requests_opus_wise2627_1786984319_forwarded.jsonl`
- Path: `/Users/brunowinter2000/Documents/ai/monitor-cc/src/logs/dual_log/api_requests_opus_wise2627_1786984319_forwarded.jsonl`
- Size: 6,836,951 bytes (6.84 MB)
- `forwarded_delta` entries (N): 181
- Model families present: haiku, opus
- Final `message_count` per family (conversation length at last entry): haiku=1, opus=529
- Aggregate `messages_total_chars` summed over all 181 entries: 608,943,493 chars

## Wall time

| Strategy | Total wall time | Within 1s interactive budget? |
|---|---|---|
| Per-entry lazy-load, ALL 181 entries (sum) | 2766.4 ms | NO |
| One-sweep reconstruction (single pass, all entries retained) | 34.14 ms | YES |
| Baseline: current parse behavior (keep-last-10 window) | 35.07 ms | YES |

One-sweep is **81x faster** than summed per-entry lazy-load for N=181.

**Per-entry lazy-load curve — does cost grow with entry index?**

Linear fit over per-entry replay time vs entry index: slope = 0.1434 ms/index-step,
intercept = 2.3759 ms. First-10-entries avg = 0.632 ms;
last-10-entries avg = 29.469 ms → **47x growth** from first to last
entry — consistent with the O(idx) replay-from-0 cost per call, i.e. summed cost is O(N^2).

| entry idx | lazy-load time (ms) |
|---|---|
| 0 | 0.107 |
| 45 | 10.077 |
| 90 | 15.080 |
| 135 | 20.600 |
| 180 | 30.678 |

## Peak RAM

Traced via `tracemalloc`, isolated per scenario (`gc.collect()` + `clear_traces()` before each
parse). "Baseline" = current production behavior (keep-last-10,
messages=None outside the window). "One-sweep" = same parse, deque bound removed (all N entries
retain messages simultaneously).

| Scenario | Traced current | Traced peak |
|---|---|---|
| Baseline (keep-last-10) | 243.5 KB | 3901.5 KB |
| One-sweep (all 181 entries retained) | 631.3 KB | 4046.7 KB |
| **Delta (one-sweep minus baseline)** | **+387.7 KB** | **+145.3 KB** |

The delta is a modest 388 KB in absolute terms — not because per-entry content is
small (aggregate `messages_total_chars` summed across all 181 entries is
608,943,493 chars, since each entry's total counts its WHOLE
cumulative conversation at that point), but because unchanged messages are already reused across
accumulator snapshots (each new_summaries list is a shallow copy of the previous one — untouched
indices keep pointing at the same summary dict object, mirroring the sharing behavior documented
in `forwarded_parser.py`'s own comment on `_parse_forwarded_log`). Retaining `entry['messages']`
for all N entries mostly retains N extra *list* objects pointing at already-live summary dicts,
not N independent copies of the conversation content — without that sharing, one-sweep's RAM
cost would be orders of magnitude higher.

## Conclusion

For N=181 entries (6.8 MB forwarded log): per-entry lazy-load of ALL
entries costs 2766 ms (over the
~1s interactive budget), growing ~quadratically with entry count —
**not viable** as a search-triggered operation past roughly N=83 entries (crude
estimate from the observed per-entry linear-growth slope: total-time ~ slope * N^2 / 2 = budget).

One-sweep reconstruction costs 34.1 ms for the same log — **well within**
the 1s budget, and its RAM cost over the current keep-last-10 baseline is
marginal (+387.7 KB) thanks to the accumulator's existing shared-reference pattern.
It scales with file size, not N^2 — for logs an order of magnitude larger than this one,
one-sweep should stay well under budget while per-entry lazy-load would not.

**Cache-after-first-sweep:** given one-sweep is already comfortably fast for this real log, a
cache is not required to hit the 1s budget at this scale. It becomes worth adding once forwarded
logs grow large enough (multi-session, multi-MB) that a single sweep approaches the budget on
every Enter keypress — caching the sweep result keyed on file byte-position (re-sweep only the
delta since last cache) would keep repeat searches near-instant without re-reading the whole file.
