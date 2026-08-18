"""
p1_full_sweep_cost_probe.py — Milestone 1 measurement probe for the proxy-pane search feature.

Core cost question: the pane keeps `messages=None` for all entries outside the last-10
window (`PROXY_MESSAGES_KEEP_LAST` in `src/constants.py`); searching ALL requests' content
requires reconstructing every entry's messages. Two candidate strategies, measured on a real
forwarded-delta log:

  1. Per-entry lazy-load: replay the forwarded delta stream from byte 0 per entry (mirrors
     `forwarded_parser._lazy_load_messages_forwarded`) — timed for ALL entries, summed + curve.
  2. One-sweep reconstruction: a single pass over the forwarded log that reconstructs and
     KEEPS messages for every entry (mirrors `forwarded_parser._parse_forwarded_log` with its
     deque eviction removed — the parser already walks the whole file for delta accumulation;
     the sweep variant just doesn't discard).

dev/ scripts must not import from src/ — the delta-accumulation algorithm
(`_dict_to_list`/`_apply_delta_to_list`/family accumulator/deque-bound eviction) is
reimplemented locally below, mirroring `src/proxy_display/forwarded_parser.py`. Message
summarization is simplified to a chars-only count (real `src/proxy/message_summary.py` adds
per-block-type detail — irrelevant to the O(N) file-replay cost this probe measures, which is
dominated by repeated file I/O + json.loads, not summarizer detail). Both candidate strategies
below share this SAME local summarizer, so the relative comparison is apples-to-apples.

RAM measured via tracemalloc (traced current/peak bytes), isolated per scenario via
gc.collect() + tracemalloc.clear_traces().

Writes dev/pane_search/md/p1_full_sweep_cost_report.md.

Usage (from project root):
    ./venv/bin/python dev/pane_search/p1_full_sweep_cost_probe.py [fwd_log_path]
"""

# INFRASTRUCTURE
import gc
import json
import sys
import time
import tracemalloc
from collections import deque
from pathlib import Path

# Main-repo dual_log dir is gitignored and absent from this worktree — real data lives only
# on the dev machine at this fixed path (largest forwarded log available as of 2026-08-18).
_DEFAULT_FWD_LOG = Path(
    '/Users/brunowinter2000/Documents/ai/monitor-cc/src/logs/dual_log/'
    'api_requests_opus_wise2627_1786984319_forwarded.jsonl'
)
_REPORT_PATH = Path(__file__).resolve().parent / 'md' / 'p1_full_sweep_cost_report.md'
_SEARCH_BUDGET_S = 1.0
_KEEP_LAST_BASELINE = 10  # mirrors PROXY_MESSAGES_KEEP_LAST

# FUNCTIONS

# Mirrors forwarded_parser._infer_model_family
def _infer_model_family(model: str) -> str:
    m = model.lower()
    if 'haiku' in m:
        return 'haiku'
    if 'sonnet' in m:
        return 'sonnet'
    return 'opus'

# Mirrors forwarded_parser._dict_to_list_fwd
def _dict_to_list(delta: dict, count: int) -> list:
    lst = [None] * count
    for idx_str, elem in delta.items():
        i = int(idx_str)
        if i < count:
            lst[i] = elem
    return lst

# Mirrors forwarded_parser._apply_delta_to_list
def _apply_delta_to_list(prev_list: list, delta: dict, count: int) -> list:
    lst = list(prev_list)
    for idx_str, elem in delta.items():
        i = int(idx_str)
        while len(lst) <= i:
            lst.append(None)
        lst[i] = elem
    if len(lst) > count:
        lst = lst[:count]
    elif len(lst) < count:
        lst.extend([None] * (count - len(lst)))
    return lst

# Simplified stand-in for proxy.message_summary._summarize_message — chars-only (see module
# docstring for why this suffices for the file-replay cost being measured here).
def _summarize(msg) -> dict:
    if not isinstance(msg, dict):
        return {'chars': 0}
    content = msg.get('content', '')
    if isinstance(content, str):
        chars = len(content)
    elif isinstance(content, list):
        chars = sum(len(json.dumps(b)) for b in content if isinstance(b, dict))
    else:
        chars = 0
    return {'role': msg.get('role', ''), 'chars': chars}

# One full pass over fwd_path, reconstructing system/tools/messages per model family via delta
# accumulation (mirrors forwarded_parser._parse_forwarded_log). keep_last bounds how many
# trailing entries retain their messages list (deque eviction) — keep_last=None retains ALL
# entries' messages (the "one-sweep" candidate). Returns (entries, elapsed_seconds).
def _sweep_parse(fwd_path: Path, keep_last) -> tuple:
    acc_by_family: dict = {}
    entries: list = []
    recent_window: deque = deque()
    t0 = time.perf_counter()
    with open(fwd_path, 'r', encoding='utf-8') as f:
        req_idx = 0
        while True:
            raw = f.readline()
            if not raw:
                break
            line = raw.strip()
            if not line:
                continue
            try:
                fwd_e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if fwd_e.get('type') != 'forwarded_delta':
                continue
            family = _infer_model_family(fwd_e.get('model', ''))
            is_first = fwd_e.get('is_first', False)
            counts = fwd_e.get('counts', {})
            sys_cnt, tools_cnt, msg_cnt = counts.get('system', 0), counts.get('tools', 0), counts.get('messages', 0)
            prev = acc_by_family.get(family) if not is_first else None
            if is_first:
                new_system = _dict_to_list(fwd_e.get('system_delta') or {}, sys_cnt)
                new_tools = _dict_to_list(fwd_e.get('tools_delta') or {}, tools_cnt)
                raw_msgs = _dict_to_list(fwd_e.get('messages_delta') or {}, msg_cnt)
                new_summaries = [_summarize(m) for m in raw_msgs]
            else:
                base = prev if prev else {'system': [], 'tools': [], 'messages': []}
                new_system = _apply_delta_to_list(base['system'], fwd_e.get('system_delta') or {}, sys_cnt)
                new_tools = _apply_delta_to_list(base['tools'], fwd_e.get('tools_delta') or {}, tools_cnt)
                new_summaries = list(base['messages'])
                for idx_str, raw_msg in (fwd_e.get('messages_delta') or {}).items():
                    i = int(idx_str)
                    while len(new_summaries) <= i:
                        new_summaries.append({})
                    new_summaries[i] = _summarize(raw_msg)
                if len(new_summaries) > msg_cnt:
                    new_summaries = new_summaries[:msg_cnt]
                elif len(new_summaries) < msg_cnt:
                    new_summaries.extend([{}] * (msg_cnt - len(new_summaries)))
            acc_by_family[family] = {'system': new_system, 'tools': new_tools, 'messages': new_summaries}
            entry = {
                'model': fwd_e.get('model', ''),
                'message_count': msg_cnt,
                'messages_total_chars': sum(s.get('chars', 0) for s in new_summaries),
                '_fwd_req_idx': req_idx,
                'messages': None,
            }
            entries.append(entry)
            recent_window.append((entry, new_summaries))
            if keep_last is not None and len(recent_window) > keep_last:
                recent_window.popleft()
            req_idx += 1
    for win_entry, summaries in recent_window:
        win_entry['messages'] = list(summaries)
    elapsed = time.perf_counter() - t0
    return entries, elapsed

# Replay fwd_path from byte 0 to target_idx, reconstructing messages for ONE entry's family
# (mirrors forwarded_parser._lazy_load_messages_forwarded). Returns reconstructed summaries.
def _lazy_load_one(fwd_path: Path, target_idx: int, target_family: str) -> list:
    temp_acc: dict = {}
    with open(fwd_path, 'r', encoding='utf-8') as f:
        req_idx = 0
        while True:
            raw = f.readline()
            if not raw:
                break
            line = raw.strip()
            if not line:
                continue
            try:
                fwd_e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if fwd_e.get('type') != 'forwarded_delta':
                continue
            family = _infer_model_family(fwd_e.get('model', ''))
            is_first = fwd_e.get('is_first', False)
            msg_cnt = fwd_e.get('counts', {}).get('messages', 0)
            if is_first:
                raw_msgs = _dict_to_list(fwd_e.get('messages_delta') or {}, msg_cnt)
                summaries = [_summarize(m) for m in raw_msgs]
            else:
                summaries = list(temp_acc.get(family, []))
                for idx_str, raw_msg in (fwd_e.get('messages_delta') or {}).items():
                    i = int(idx_str)
                    while len(summaries) <= i:
                        summaries.append({})
                    summaries[i] = _summarize(raw_msg)
                if len(summaries) > msg_cnt:
                    summaries = summaries[:msg_cnt]
                elif len(summaries) < msg_cnt:
                    summaries.extend([{}] * (msg_cnt - len(summaries)))
            temp_acc[family] = summaries
            if req_idx == target_idx:
                return list(temp_acc.get(target_family, []))
            req_idx += 1
    return []

# Traced current/peak bytes (tracemalloc) for one _sweep_parse scenario. gc.collect() +
# clear_traces() before the parse isolates this scenario's allocations from any prior one.
def _traced_sweep(fwd_path: Path, keep_last) -> tuple:
    gc.collect()
    tracemalloc.clear_traces()
    entries, elapsed = _sweep_parse(fwd_path, keep_last)
    current, peak = tracemalloc.get_traced_memory()
    return entries, elapsed, current, peak

# Per-entry _lazy_load_one wall time for every entry in the baseline entries list — the cost a
# naive "reconstruct all entries via lazy-load" search trigger would pay. Each replay walks the
# file from byte 0 to that entry's index, so summed cost grows with N^2.
def _measure_lazy_load_all(entries: list, fwd_path: Path) -> list:
    times = []
    for entry in entries:
        family = _infer_model_family(entry['model'])
        t0 = time.perf_counter()
        _lazy_load_one(fwd_path, entry['_fwd_req_idx'], family)
        times.append(time.perf_counter() - t0)
    return times

# Least-squares slope+intercept of y over index 0..N-1 (no numpy dependency) — quantifies the
# per-entry lazy-load growth rate in seconds/index-step.
def _linear_fit(values: list) -> tuple:
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    den = sum((x - mean_x) ** 2 for x in xs)
    slope = num / den if den else 0.0
    intercept = mean_y - slope * mean_x
    return slope, intercept

# Entry/message/char counts from a fully-populated entries list. messages_total_chars is
# computed pre-window-truncation, so it's valid on every entry regardless of keep_last.
def _log_stats(entries: list) -> dict:
    families = sorted({_infer_model_family(e['model']) for e in entries})
    final_msg_count_by_family = {}
    for family in families:
        fam_entries = [e for e in entries if _infer_model_family(e['model']) == family]
        final_msg_count_by_family[family] = fam_entries[-1]['message_count']
    return {
        'n_entries': len(entries),
        'families': families,
        'final_msg_count_by_family': final_msg_count_by_family,
        'total_messages_total_chars': sum(e['messages_total_chars'] for e in entries),
    }

# Format the full markdown report body from all measured numbers.
def _build_report_md(fwd_path: Path, file_size_bytes: int, stats: dict,
                      base_elapsed: float, base_current: int, base_peak: int,
                      sweep_elapsed: float, sweep_current: int, sweep_peak: int,
                      lazy_times: list) -> str:
    n = stats['n_entries']
    lazy_sum = sum(lazy_times)
    slope, intercept = _linear_fit(lazy_times)
    fam_line = ', '.join(f"{fam}={cnt}" for fam, cnt in stats['final_msg_count_by_family'].items())
    sample_idxs = sorted(set([0, n // 4, n // 2, (3 * n) // 4, n - 1]))
    sample_rows = '\n'.join(f"| {i} | {lazy_times[i] * 1000:.3f} |" for i in sample_idxs)
    first10_avg = sum(lazy_times[:10]) / min(10, n) * 1000
    last10_avg = sum(lazy_times[-10:]) / min(10, n) * 1000
    growth_ratio = (last10_avg / first10_avg) if first10_avg else float('inf')
    speedup = lazy_sum / sweep_elapsed if sweep_elapsed else float('inf')
    ram_delta_kb = (sweep_current - base_current) / 1024
    ram_peak_delta_kb = (sweep_peak - base_peak) / 1024

    lazy_viable = lazy_sum <= _SEARCH_BUDGET_S
    sweep_viable = sweep_elapsed <= _SEARCH_BUDGET_S
    n_at_budget = int((_SEARCH_BUDGET_S / slope) ** 0.5) if slope > 0 else None

    return f"""# P1 — Full-Sweep Reconstruction Cost Probe

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

- File: `{fwd_path.name}`
- Path: `{fwd_path}`
- Size: {file_size_bytes:,} bytes ({file_size_bytes / 1e6:.2f} MB)
- `forwarded_delta` entries (N): {n}
- Model families present: {', '.join(stats['families'])}
- Final `message_count` per family (conversation length at last entry): {fam_line}
- Aggregate `messages_total_chars` summed over all {n} entries: {stats['total_messages_total_chars']:,} chars

## Wall time

| Strategy | Total wall time | Within {_SEARCH_BUDGET_S:.0f}s interactive budget? |
|---|---|---|
| Per-entry lazy-load, ALL {n} entries (sum) | {lazy_sum * 1000:.1f} ms | {'YES' if lazy_viable else 'NO'} |
| One-sweep reconstruction (single pass, all entries retained) | {sweep_elapsed * 1000:.2f} ms | {'YES' if sweep_viable else 'NO'} |
| Baseline: current parse behavior (keep-last-{_KEEP_LAST_BASELINE} window) | {base_elapsed * 1000:.2f} ms | YES |

One-sweep is **{speedup:.0f}x faster** than summed per-entry lazy-load for N={n}.

**Per-entry lazy-load curve — does cost grow with entry index?**

Linear fit over per-entry replay time vs entry index: slope = {slope * 1000:.4f} ms/index-step,
intercept = {intercept * 1000:.4f} ms. First-10-entries avg = {first10_avg:.3f} ms;
last-10-entries avg = {last10_avg:.3f} ms → **{growth_ratio:.0f}x growth** from first to last
entry — consistent with the O(idx) replay-from-0 cost per call, i.e. summed cost is O(N^2).

| entry idx | lazy-load time (ms) |
|---|---|
{sample_rows}

## Peak RAM

Traced via `tracemalloc`, isolated per scenario (`gc.collect()` + `clear_traces()` before each
parse). "Baseline" = current production behavior (keep-last-{_KEEP_LAST_BASELINE},
messages=None outside the window). "One-sweep" = same parse, deque bound removed (all N entries
retain messages simultaneously).

| Scenario | Traced current | Traced peak |
|---|---|---|
| Baseline (keep-last-{_KEEP_LAST_BASELINE}) | {base_current / 1024:.1f} KB | {base_peak / 1024:.1f} KB |
| One-sweep (all {n} entries retained) | {sweep_current / 1024:.1f} KB | {sweep_peak / 1024:.1f} KB |
| **Delta (one-sweep minus baseline)** | **{ram_delta_kb:+.1f} KB** | **{ram_peak_delta_kb:+.1f} KB** |

The delta is a modest {ram_delta_kb:.0f} KB in absolute terms — not because per-entry content is
small (aggregate `messages_total_chars` summed across all {n} entries is
{stats['total_messages_total_chars']:,} chars, since each entry's total counts its WHOLE
cumulative conversation at that point), but because unchanged messages are already reused across
accumulator snapshots (each new_summaries list is a shallow copy of the previous one — untouched
indices keep pointing at the same summary dict object, mirroring the sharing behavior documented
in `forwarded_parser.py`'s own comment on `_parse_forwarded_log`). Retaining `entry['messages']`
for all N entries mostly retains N extra *list* objects pointing at already-live summary dicts,
not N independent copies of the conversation content — without that sharing, one-sweep's RAM
cost would be orders of magnitude higher.

## Conclusion

For N={n} entries ({file_size_bytes / 1e6:.1f} MB forwarded log): per-entry lazy-load of ALL
entries costs {lazy_sum * 1000:.0f} ms ({'over' if not lazy_viable else 'under'} the
~{_SEARCH_BUDGET_S:.0f}s interactive budget), growing ~quadratically with entry count —
**not viable** as a search-triggered operation past roughly N={n_at_budget} entries (crude
estimate from the observed per-entry linear-growth slope: total-time ~ slope * N^2 / 2 = budget).

One-sweep reconstruction costs {sweep_elapsed * 1000:.1f} ms for the same log — **well within**
the 1s budget, and its RAM cost over the current keep-last-{_KEEP_LAST_BASELINE} baseline is
marginal ({ram_delta_kb:+.1f} KB) thanks to the accumulator's existing shared-reference pattern.
It scales with file size, not N^2 — for logs an order of magnitude larger than this one,
one-sweep should stay well under budget while per-entry lazy-load would not.

**Cache-after-first-sweep:** given one-sweep is already comfortably fast for this real log, a
cache is not required to hit the 1s budget at this scale. It becomes worth adding once forwarded
logs grow large enough (multi-session, multi-MB) that a single sweep approaches the budget on
every Enter keypress — caching the sweep result keyed on file byte-position (re-sweep only the
delta since last cache) would keep repeat searches near-instant without re-reading the whole file.
"""

# ORCHESTRATOR

def probe_workflow(fwd_path: Path) -> None:
    if not fwd_path.exists():
        raise FileNotFoundError(f'forwarded log not found: {fwd_path}')
    tracemalloc.start()
    file_size_bytes = fwd_path.stat().st_size

    base_entries, base_elapsed, base_current, base_peak = _traced_sweep(fwd_path, _KEEP_LAST_BASELINE)
    stats = _log_stats(base_entries)

    lazy_times = _measure_lazy_load_all(base_entries, fwd_path)
    del base_entries
    gc.collect()

    sweep_entries, sweep_elapsed, sweep_current, sweep_peak = _traced_sweep(fwd_path, None)
    del sweep_entries
    gc.collect()

    report_md = _build_report_md(
        fwd_path, file_size_bytes, stats,
        base_elapsed, base_current, base_peak,
        sweep_elapsed, sweep_current, sweep_peak,
        lazy_times,
    )
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(report_md, encoding='utf-8')
    print(f'entries={stats["n_entries"]} lazy_sum_ms={sum(lazy_times) * 1000:.1f} '
          f'sweep_ms={sweep_elapsed * 1000:.2f} ram_delta_kb={(sweep_current - base_current) / 1024:+.1f}')
    print(f'Report written to {_REPORT_PATH}')


if __name__ == '__main__':
    _arg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_FWD_LOG
    probe_workflow(_arg_path)
