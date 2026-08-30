"""
p6_flow_extra_suppress_probe.py — the total_tokens nuke no longer prepends an out-of-window msg.

Drives the REAL read path (`_parse_forwarded_log` -> `accumulate_dual_log` -> pane-style entry
attach -> `render_messages`) over recorded dual-log sessions and compares every rendered expanded
view against a BASELINE rendering of the same entries with the suppression disabled.

The baseline is produced in the same process by dropping the `_msg_idx_sub_by_flow_id` attachment
from the entries — `render_messages._render_flow_extra_messages` then falls back to the raw
touched-index set, which is exactly the pre-2026-08-30 behavior. Both sides therefore run
identical code everywhere else, so any diff is the suppression and nothing but.

Asserted as invariants, not fixed counts, so this keeps passing as the logs grow:

  1. Any entry with a suppressed index loses EXACTLY that index's prepended block: the baseline
     body ends with the new body verbatim, and the dropped prefix's `[N]` headers are precisely
     the suppressed indices. A mixed request (nuke + real strip out of window) therefore keeps its
     real prepend and loses only the nuke's.
  2. An entry whose out-of-window touches are all substantial renders byte-identical to baseline.
  3. An entry that prepended nothing in the baseline renders byte-identical (in-window guarantee).
  4. `parser.badge_flags` is byte-identical for every entry on both sides — the badge must not
     move at all.
  5. Every suppressed index is one the parser classifies as non-substantial, and every kept index
     is one it classifies as substantial (the render layer never re-derives the rule).

Usage (from project root):
    ./venv/bin/python dev/proxy_instrumentation/p6_flow_extra_suppress_probe.py
    ./venv/bin/python dev/proxy_instrumentation/p6_flow_extra_suppress_probe.py <stem> [<stem> ...]
"""

# INFRASTRUCTURE
import json
import re
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT))

# Recorded dual-log sessions are untracked data living in the main checkout, never duplicated
# into worktrees — code under test is imported from WORKTREE_ROOT above.
MAIN_REPO_ROOT = Path('/Users/brunowinter2000/Documents/ai/monitor-cc')
LOG_DIR = MAIN_REPO_ROOT / 'src' / 'logs' / 'dual_log'

DEFAULT_STEMS = (
    'api_requests_opus_monitor_cc_1788091735',
    'api_requests_opus_gh_cli_1787995963',
)

REPORT_DIR = Path(__file__).parent / 'md'
REPORT_PATH = REPORT_DIR / 'flow_extra_suppress_report.md'

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
_ACC_SHAPE = {
    'system': {}, 'tools': {}, 'messages': {}, 'fields': {},
    '_has_content_by_flow_id': {}, '_msg_idx_by_flow_id': {}, '_msg_idx_sub_by_flow_id': {},
}

# FUNCTIONS


# Load one recorded session exactly the way pane.py assembles it, messages retained for every
# entry (keep_last=None) so no lazy-load replay is needed per entry.
def _load_session(stem: str) -> list:
    from src.proxy_display.forwarded_parser import _parse_forwarded_log, _infer_model_family
    from src.proxy_display.parser import accumulate_dual_log
    entries, _ = _parse_forwarded_log(LOG_DIR / f'{stem}_forwarded.jsonl', 0, {}, keep_last=None)
    acc_s: dict = {}
    acc_i: dict = {}
    accumulate_dual_log(LOG_DIR / f'{stem}_stripped.jsonl', 0, acc_s)
    accumulate_dual_log(LOG_DIR / f'{stem}_injected.jsonl', 0, acc_i)
    for entry in entries:
        family = _infer_model_family(entry.get('model', ''))
        fam_s = acc_s.setdefault(family, json.loads(json.dumps(_ACC_SHAPE)))
        fam_i = acc_i.setdefault(family, json.loads(json.dumps(_ACC_SHAPE)))
        entry['_stripped_spans'] = fam_s
        entry['_injected_spans'] = fam_i
        entry['_strip_fns_lookup'] = fam_s.setdefault('_has_content_by_flow_id', {})
        entry['_inject_fns_lookup'] = fam_i.setdefault('_has_content_by_flow_id', {})
        entry['_strip_msgs_lookup'] = fam_s.setdefault('_msg_idx_by_flow_id', {})
        entry['_inject_msgs_lookup'] = fam_i.setdefault('_msg_idx_by_flow_id', {})
        entry['_strip_msgs_sub_lookup'] = fam_s.setdefault('_msg_idx_sub_by_flow_id', {})
        entry['_inject_msgs_sub_lookup'] = fam_i.setdefault('_msg_idx_sub_by_flow_id', {})
    return entries


# Render every entry's expanded message body; baseline=True removes the sub-lookups so
# _render_flow_extra_messages falls back to the raw touched set (pre-suppression behavior).
def _render_all(entries: list, baseline: bool) -> dict:
    from src.proxy_display.render_messages import render_messages
    from src.proxy_display.render_turn import _resolve_prev_same_family
    saved: list = []
    if baseline:
        for entry in entries:
            saved.append((entry.pop('_strip_msgs_sub_lookup', None),
                          entry.pop('_inject_msgs_sub_lookup', None)))
    out: dict = {}
    try:
        for idx, entry in enumerate(entries):
            if entry.get('messages') is None:
                continue
            prev = _resolve_prev_same_family(entries, idx)
            lines, _keys = render_messages(idx, entry, prev, entries, {}, 200)
            out[idx] = '\n'.join(lines)
    finally:
        if baseline:
            for entry, (s_sub, i_sub) in zip(entries, saved):
                if s_sub is not None:
                    entry['_strip_msgs_sub_lookup'] = s_sub
                if i_sub is not None:
                    entry['_inject_msgs_sub_lookup'] = i_sub
    return out


# The badge pair the REQ header renders, per entry, via the real parser.badge_flags
def _badges(entries: list) -> dict:
    from src.proxy_display.parser import badge_flags
    return {idx: badge_flags(entry) for idx, entry in enumerate(entries)}


# Out-of-window indices one entry would prepend, split into kept (substantial) and suppressed.
# covered_from is recovered by wrapping the real _render_flow_extra_messages during a render pass.
def _prepend_plan(entries: list) -> dict:
    from src.proxy_display import render_messages as rm
    from src.proxy_display.render_turn import _resolve_prev_same_family
    plan: dict = {}
    original = rm._render_flow_extra_messages

    def recorder(entry_idx, entry, messages, covered_from, expand_states, pane_width):
        fid = entry.get('flow_id', '')
        raw = (entry.get('_strip_msgs_lookup', {}).get(fid, set())
               | entry.get('_inject_msgs_lookup', {}).get(fid, set()))
        sub = (entry.get('_strip_msgs_sub_lookup', {}).get(fid, set())
               | entry.get('_inject_msgs_sub_lookup', {}).get(fid, set()))
        in_range = {m for m in raw if int(m) < covered_from and int(m) < len(messages)}
        plan[entry_idx] = {
            'kept': sorted(int(m) for m in in_range & sub),
            'suppressed': sorted(int(m) for m in in_range - sub),
        }
        return original(entry_idx, entry, messages, covered_from, expand_states, pane_width)

    rm._render_flow_extra_messages = recorder
    try:
        for idx, entry in enumerate(entries):
            if entry.get('messages') is None:
                continue
            prev = _resolve_prev_same_family(entries, idx)
            rm.render_messages(idx, entry, prev, entries, {}, 200)
    finally:
        rm._render_flow_extra_messages = original
    return plan


# Ground-truth per-index verdict straight from the raw dual-log lines, via the parser's own
# predicate — proves the render layer suppressed exactly the indices the parser calls insubstantial
def _raw_verdicts(stem: str) -> dict:
    from src.proxy_display.parser import _msg_delta_entry_is_substantial
    verdicts: dict = {}
    for side, is_injected in (('stripped', False), ('injected', True)):
        path = LOG_DIR / f'{stem}_{side}.jsonl'
        for raw_line in path.read_text(encoding='utf-8').splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                line = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            fid = line.get('flow_id', '')
            for midx, blks in (line.get('messages_delta') or {}).items():
                key = (fid, int(midx))
                verdicts[key] = verdicts.get(key, False) or _msg_delta_entry_is_substantial(blks, is_injected)
    return verdicts


_MSG_HEADER_RE = re.compile(r'^    \[\s*(\d+)\] ')


# Message indices of every `    [ N]` header line in a rendered body, in order
def _msg_header_indices(body: str) -> list:
    out = []
    for line in _ANSI_RE.sub('', body).splitlines():
        match = _MSG_HEADER_RE.match(line)
        if match:
            out.append(int(match.group(1)))
    return out


# One session: render both ways, compare, return (result_rows, stats)
def _check_session(stem: str) -> tuple:
    entries = _load_session(stem)
    plan = _prepend_plan(entries)
    after = _render_all(entries, baseline=False)
    before = _render_all(entries, baseline=True)
    badges_after = _badges(entries)
    verdicts = _raw_verdicts(stem)

    suppressing = [i for i, p in plan.items() if p['suppressed']]
    fully_suppressed = [i for i, p in plan.items() if p['suppressed'] and not p['kept']]
    kept_only = [i for i, p in plan.items() if p['kept'] and not p['suppressed']]
    untouched = [i for i in after if i not in plan]

    # 1. an entry with suppressed indices loses exactly those blocks and nothing else: the
    # baseline body ends with the new body verbatim, and the dropped prefix carries precisely
    # the suppressed indices' [N] headers
    c1_bad = []
    for idx in suppressing:
        if not before[idx].endswith(after[idx]) or after[idx] == before[idx]:
            c1_bad.append((idx, 'tail-not-preserved'))
            continue
        dropped = before[idx][:len(before[idx]) - len(after[idx])]
        if _msg_header_indices(dropped) != plan[idx]['suppressed']:
            c1_bad.append((idx, f'dropped={_msg_header_indices(dropped)} want={plan[idx]["suppressed"]}'))
            continue
        if _msg_header_indices(after[idx])[:len(plan[idx]['kept'])] != plan[idx]['kept']:
            c1_bad.append((idx, 'kept prepend missing from new body'))

    # 2. entries whose out-of-window touches are all substantial are byte-identical to baseline
    c2_bad = [idx for idx in kept_only if after[idx] != before[idx]]

    # 3. entries that never prepended are byte-identical (in-window guarantee)
    c3_bad = [idx for idx in untouched if after[idx] != before[idx]]

    # 4. badges identical on both sides (the sub-lookup must not reach badge_flags)
    saved = [(e.pop('_strip_msgs_sub_lookup', None), e.pop('_inject_msgs_sub_lookup', None)) for e in entries]
    badges_before = _badges(entries)
    for entry, (s_sub, i_sub) in zip(entries, saved):
        if s_sub is not None:
            entry['_strip_msgs_sub_lookup'] = s_sub
        if i_sub is not None:
            entry['_inject_msgs_sub_lookup'] = i_sub
    c4_bad = [i for i in badges_after if badges_after[i] != badges_before[i]]

    # 5. suppressed/kept split matches the parser's own per-index verdict
    c5_bad = []
    for idx, p in plan.items():
        fid = entries[idx].get('flow_id', '')
        for m in p['suppressed']:
            if verdicts.get((fid, m), False):
                c5_bad.append(('suppressed-but-substantial', idx, m))
        for m in p['kept']:
            if not verdicts.get((fid, m), False):
                c5_bad.append(('kept-but-insubstantial', idx, m))

    rows = [
        ('suppressed_blocks_dropped_exactly', not c1_bad,
         f'{len(suppressing)} entries drop an insubstantial prepend ({len(fully_suppressed)} of '
         f'them lose it entirely, the rest are mixed and keep their real one); dropped prefix '
         f'matches the suppressed indices and the tail is verbatim; bad={c1_bad[:5]}'),
        ('substantial_only_identical', not c2_bad,
         f'{len(kept_only)} entries prepend only substantial indices; byte-identical to '
         f'baseline; bad={c2_bad[:5]}'),
        ('no_flow_extra_identical', not c3_bad,
         f'{len(untouched)} entries never prepended; byte-identical to baseline; bad={c3_bad[:5]}'),
        ('badges_unchanged', not c4_bad,
         f'{len(badges_after)} entries compared via parser.badge_flags; changed={c4_bad[:5]}'),
        ('split_matches_parser_verdict', not c5_bad,
         f'{sum(len(p["suppressed"]) for p in plan.values())} suppressed / '
         f'{sum(len(p["kept"]) for p in plan.values())} kept indices cross-checked against '
         f'_msg_delta_entry_is_substantial; bad={c5_bad[:5]}'),
    ]
    stats = {
        'entries_rendered': len(after),
        'entries_prepending_before': len([i for i, p in plan.items() if p['kept'] or p['suppressed']]),
        'entries_prepending_after': len([i for i, p in plan.items() if p['kept']]),
        'indices_suppressed': sum(len(p['suppressed']) for p in plan.values()),
        'indices_kept': sum(len(p['kept']) for p in plan.values()),
    }
    return rows, stats


# ORCHESTRATOR
def main() -> None:
    stems = sys.argv[1:] or list(DEFAULT_STEMS)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    lines = ['# Flow-extra suppression probe — total_tokens nuke no longer prepends', '']
    lines.append('Each session is rendered twice in one process: once with the parser\'s')
    lines.append('substantial-index lookups attached (current behavior) and once without them')
    lines.append('(baseline = pre-suppression fallback path). Diffs are the suppression only.')
    lines.append('')
    all_pass = True
    for stem in stems:
        if not (LOG_DIR / f'{stem}_forwarded.jsonl').exists():
            print(f'SKIP {stem} — no recorded forwarded log')
            lines.append(f'## `{stem}` — SKIPPED (log not on disk)')
            lines.append('')
            continue
        rows, stats = _check_session(stem)
        lines.append(f'## `{stem}`')
        lines.append('')
        lines.append('| metric | value |')
        lines.append('|---|---|')
        for key, value in stats.items():
            lines.append(f'| {key} | {value} |')
        lines.append('')
        lines.append('| check | pass | detail |')
        lines.append('|---|---|---|')
        print(f'\n== {stem}  ' + '  '.join(f'{k}={v}' for k, v in stats.items()))
        for label, ok, detail in rows:
            all_pass = all_pass and ok
            lines.append(f'| {label} | {"PASS" if ok else "FAIL"} | {detail} |')
            print(('PASS' if ok else 'FAIL'), label, '-', detail)
        lines.append('')
    lines.append(f'## Overall: {"ALL PASS" if all_pass else "FAILURES PRESENT"}')
    REPORT_PATH.write_text('\n'.join(lines) + '\n')
    print(f'\nReport written: {REPORT_PATH}')
    print('ALL PASS' if all_pass else 'FAILURES PRESENT')
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
