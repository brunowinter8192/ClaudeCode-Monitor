"""
tt_delta_skip_replay.py — before/after replay proving the total_tokens delta-skip.

Replays a recorded _original.jsonl through the REAL production pass pipeline
(`apply_modification_rules`, which is what produces `all_ops` in `addon.py`), then feeds
(orig_payload, fwd_payload, all_ops) into the REAL `_build_stripped_injected_deltas` — the same
call `addon.py` makes. The resulting dual-log lines are then run through the REAL read-side
`accumulate_dual_log`, so the reported badge signal is the one the pane would compute.

Why a dedicated replay: `dev/proxy_dual_log/verify_strip_inject.py` calls the delta builder
WITHOUT `all_ops`, so its message section produces no spans at all and it is structurally blind
to this change (independently, it raises KeyError 'spans' on current logs — `_diff_messages` no
longer emits that key; pre-existing, untouched). `dev/proxy_instrumentation/p2_badge_words_probe.py`
and `p3_badge_inline_probe.py` reference recorded sessions that no longer exist on disk.

`--baseline` restores the pre-fix behavior by monkeypatching the class regex to something that
matches nothing, so both sides of the comparison run through identical code otherwise.

Usage (from project root):
    ./venv/bin/python dev/proxy_dual_log/tt_delta_skip_replay.py <stem>
    ./venv/bin/python dev/proxy_dual_log/tt_delta_skip_replay.py <stem> --baseline
    ./venv/bin/python dev/proxy_dual_log/tt_delta_skip_replay.py <stem> --compare

`--compare` runs both modes in one process and diffs every entry byte-wise (json, sort_keys).
"""

# INFRASTRUCTURE
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent.resolve()
WORKTREE_ROOT = _SCRIPT_DIR.parents[1]
sys.path.insert(0, str(WORKTREE_ROOT))

# Recorded dual-logs are untracked data living in the main checkout, not duplicated into worktrees.
MAIN_REPO_ROOT = Path('/Users/brunowinter2000/Documents/ai/monitor-cc')
LOG_DIR = MAIN_REPO_ROOT / 'src' / 'logs' / 'dual_log'

TT_RE = re.compile(r'^<total_tokens>\d+ tokens left</total_tokens>$')
# Matches nothing (empty alternation is impossible to satisfy against a non-empty pattern anchor)
NEVER_RE = re.compile(r'(?!x)x')


# FUNCTIONS

def _load_jsonl(path: Path) -> list:
    entries = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


# True when the message is a genuine role='system' total_tokens marker (the target class)
def _is_tt_msg(msg: dict) -> bool:
    if msg.get('role') != 'system':
        return False
    content = msg.get('content', '')
    if isinstance(content, str):
        return bool(TT_RE.match(content.strip()))
    if isinstance(content, list):
        return (len(content) == 1 and isinstance(content[0], dict)
                and content[0].get('type') == 'text'
                and bool(TT_RE.match(str(content[0].get('text', '')).strip())))
    return False


# Replay every request of one session; returns list of (request_id, stripped_entry, injected_entry)
def replay(stem: str, baseline: bool) -> list:
    from src.proxy import strip_inject_delta as sid
    from src.proxy.rules import apply_modification_rules

    saved_re = sid._TOTAL_TOKENS_NUKE_RE
    if baseline:
        sid._TOTAL_TOKENS_NUKE_RE = NEVER_RE
    try:
        orig_entries = _load_jsonl(LOG_DIR / f'{stem}_original.jsonl')
        out = []
        prev_s = None
        prev_i = None
        for entry in orig_entries:
            orig_payload = entry.get('payload', {})
            if not orig_payload.get('messages'):
                continue
            model = entry.get('model', '') or orig_payload.get('model', '')
            family = 'haiku' if 'haiku' in model.lower() else ('sonnet' if 'sonnet' in model.lower() else 'opus')
            replayed = json.loads(json.dumps(orig_payload))
            result = apply_modification_rules(replayed, family, str(MAIN_REPO_ROOT), None)
            fwd_payload, all_ops = result[0], result[-1]
            rid = entry.get('request_id', '') or f'req{len(out)}'
            s_entry, i_entry, new_s, new_i = sid._build_stripped_injected_deltas(
                orig_payload, fwd_payload, rid, prev_s, prev_i, model, all_ops,
            )
            prev_s, prev_i = new_s, new_i
            s_entry['flow_id'] = rid
            i_entry['flow_id'] = rid
            out.append((rid, s_entry, i_entry, orig_payload))
        return out
    finally:
        sid._TOTAL_TOKENS_NUKE_RE = saved_re


# Run the REAL read-side accumulator over the replayed stripped entries -> {flow_id: has_content}
def has_content_map(entries: list, which: int) -> dict:
    from src.proxy_display.parser import accumulate_dual_log
    with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as f:
        for row in entries:
            f.write(json.dumps(row[which]) + '\n')
        tmp = Path(f.name)
    acc: dict = {}
    try:
        accumulate_dual_log(tmp, 0, acc)
    finally:
        tmp.unlink()
    merged: dict = {}
    for fam in acc.values():
        merged.update(fam.get('_has_content_by_flow_id', {}))
    return merged


# Classify a request by what its ORIGINAL payload + baseline delta contained
def classify(base_s: dict, orig_payload: dict) -> str:
    md = base_s.get('messages_delta', {})
    if not md:
        return 'no_msg_delta'
    msgs = orig_payload.get('messages', [])
    tt_only = True
    has_tt = False
    for midx in md:
        i = int(midx)
        is_tt = i < len(msgs) and _is_tt_msg(msgs[i])
        has_tt = has_tt or is_tt
        tt_only = tt_only and is_tt
    if tt_only:
        return 'pure_total_tokens'
    return 'mixed' if has_tt else 'real_strip'


def _canon(entry: dict) -> str:
    return json.dumps({k: v for k, v in entry.items() if k != 'timestamp'}, sort_keys=True)


# ORCHESTRATOR

def compare_workflow(stem: str) -> int:
    base = replay(stem, baseline=True)
    new = replay(stem, baseline=False)
    assert len(base) == len(new), f'replay length mismatch {len(base)} vs {len(new)}'

    base_hc_s = has_content_map(base, 1)
    new_hc_s = has_content_map(new, 1)
    base_hc_i = has_content_map(base, 2)
    new_hc_i = has_content_map(new, 2)

    buckets: dict = {}
    changed_unexpectedly = []
    unchanged_tt = []
    for (rid, bs, bi, orig_payload), (_rid2, ns, ni, _op2) in zip(base, new):
        cls = classify(bs, orig_payload)
        buckets.setdefault(cls, []).append(rid)
        identical = _canon(bs) == _canon(ns) and _canon(bi) == _canon(ni)
        if cls in ('real_strip', 'no_msg_delta') and not identical:
            changed_unexpectedly.append((rid, cls))
        if cls == 'pure_total_tokens' and ns.get('messages_delta'):
            unchanged_tt.append(rid)

    print(f'\ntt_delta_skip_replay — {stem}')
    print(f'  requests replayed: {len(base)}\n')
    print('  classification (by BASELINE delta + original payload):')
    for cls in ('pure_total_tokens', 'mixed', 'real_strip', 'no_msg_delta'):
        print(f'    {cls:<20} {len(buckets.get(cls, []))}')

    b_md_s = sum(1 for r in base if r[1].get('messages_delta'))
    n_md_s = sum(1 for r in new if r[1].get('messages_delta'))
    b_md_i = sum(1 for r in base if r[2].get('messages_delta'))
    n_md_i = sum(1 for r in new if r[2].get('messages_delta'))
    print(f'\n  entries with messages_delta   stripped: {b_md_s} -> {n_md_s}')
    print(f'  entries with messages_delta   injected: {b_md_i} -> {n_md_i}')
    print(f'  has_content True (stripped):  {sum(base_hc_s.values())} -> {sum(new_hc_s.values())}')
    print(f'  has_content True (injected):  {sum(base_hc_i.values())} -> {sum(new_hc_i.values())}')

    real_ids = set(buckets.get('real_strip', []))
    real_identical = sum(
        1 for (rid, bs, bi, _o), (_r, ns, ni, _o2) in zip(base, new)
        if rid in real_ids and _canon(bs) == _canon(ns) and _canon(bi) == _canon(ni)
    )
    print(f'\n  real_strip entries byte-identical before/after: {real_identical}/{len(real_ids)}')

    tt_ids = set(buckets.get('pure_total_tokens', []))
    tt_quiet = sum(1 for rid in tt_ids if new_hc_s.get(rid) is False and new_hc_i.get(rid) is False)
    print(f'  pure_total_tokens requests now has_content False (both sides): {tt_quiet}/{len(tt_ids)}')

    ok = not changed_unexpectedly and not unchanged_tt and tt_quiet == len(tt_ids)
    if changed_unexpectedly:
        print(f'\n  UNEXPECTED CHANGES: {changed_unexpectedly[:10]}')
    if unchanged_tt:
        print(f'\n  TOTAL_TOKENS STILL EMITTING: {unchanged_tt[:10]}')
    print(f'\n{"PASS" if ok else "FAIL"}\n')
    return 0 if ok else 1


def single_workflow(stem: str, baseline: bool) -> int:
    rows = replay(stem, baseline=baseline)
    md = sum(1 for r in rows if r[1].get('messages_delta'))
    print(f'{stem} baseline={baseline}: {len(rows)} requests, {md} with stripped messages_delta')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('stem', help='log stem, e.g. api_requests_opus_monitor_cc_1788011077')
    ap.add_argument('--baseline', action='store_true', help='run with the skip disabled')
    ap.add_argument('--compare', action='store_true', help='run both modes and diff every entry')
    args = ap.parse_args()
    if args.compare:
        sys.exit(compare_workflow(args.stem))
    sys.exit(single_workflow(args.stem, args.baseline))
