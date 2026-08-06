"""
Drives the real proxy_display render path (accumulate_dual_log -> pane-style entry attach ->
_build_req_header_line + render_messages) over the recorded session
api_requests_opus_websearch_1786052022 (CC 2.1.223, mid-conversation system messages) to verify:

  1. Per-flow msg-index tracking + inline out-of-window rendering: a request's strip/inject
     spans render at their [N] position in its OWN expanded view even when that index sits
     below the rendered delta window (the phantom-badge case).
  2. Neighbor-bleed fix: a request that did not itself touch a message index never renders
     another flow's span there, even though the underlying acc dict is shared by reference.
  3. fields_delta no longer feeds the badge (has_content), fields section untouched.
  4. The removed ⚠S warn badge never renders; ⚠T (tools_hash) still does.

Usage (from project root):
    ./venv/bin/python dev/proxy_instrumentation/p3_badge_inline_probe.py
"""

# INFRASTRUCTURE
import json
import re
import sys
import tempfile
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT))

# Recorded dual-log sessions live in the main project checkout (untracked data, not
# duplicated into worktrees) — code under test is imported from WORKTREE_ROOT above.
MAIN_REPO_ROOT = Path('/Users/brunowinter2000/Documents/ai/monitor-cc')
LOG_DIR = MAIN_REPO_ROOT / 'src' / 'logs' / 'dual_log'
STEM = 'api_requests_opus_websearch_1786052022'

REPORT_DIR = Path(__file__).parent / 'md'
REPORT_PATH = REPORT_DIR / 'badge_inline_probe_report.md'

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
DIM_YELLOW_BG = '\033[48;2;94;81;47m'
DIM_GREEN_BG = '\033[48;2;38;74;46m'

# FUNCTIONS

# Load the recorded session through the exact accumulate_dual_log -> pane.py attach path
def _load_session_impl():
    from src.proxy_display.forwarded_parser import _parse_forwarded_log, _infer_model_family
    from src.proxy_display.parser import accumulate_dual_log
    fwd_path = LOG_DIR / f'{STEM}_forwarded.jsonl'
    stripped_path = LOG_DIR / f'{STEM}_stripped.jsonl'
    injected_path = LOG_DIR / f'{STEM}_injected.jsonl'
    entries, _ = _parse_forwarded_log(fwd_path, 0, {})
    acc_stripped: dict = {}
    acc_injected: dict = {}
    accumulate_dual_log(stripped_path, 0, acc_stripped)
    accumulate_dual_log(injected_path, 0, acc_injected)
    for entry in entries:
        family = _infer_model_family(entry.get('model', ''))
        fam_s = acc_stripped.setdefault(
            family, {'system': {}, 'tools': {}, 'messages': {}, 'fields': {}, '_has_content_by_flow_id': {}, '_msg_idx_by_flow_id': {}}
        )
        fam_i = acc_injected.setdefault(
            family, {'system': {}, 'tools': {}, 'messages': {}, 'fields': {}, '_has_content_by_flow_id': {}, '_msg_idx_by_flow_id': {}}
        )
        entry['_stripped_spans'] = fam_s
        entry['_injected_spans'] = fam_i
        entry['_strip_fns_lookup'] = fam_s.setdefault('_has_content_by_flow_id', {})
        entry['_inject_fns_lookup'] = fam_i.setdefault('_has_content_by_flow_id', {})
        entry['_strip_msgs_lookup'] = fam_s.setdefault('_msg_idx_by_flow_id', {})
        entry['_inject_msgs_lookup'] = fam_i.setdefault('_msg_idx_by_flow_id', {})
    return entries


def _entry_idx(entries: list, flow_prefix: str) -> int:
    for i, e in enumerate(entries):
        if e.get('flow_id', '').startswith(flow_prefix):
            return i
    raise AssertionError(f'flow_id prefix {flow_prefix} not found')


# Mirrors render_turn.py's prev_same lookup: nearest earlier entry of the same model family
def _prev_same_family(entries: list, idx: int):
    from src.proxy_display.forwarded_parser import _infer_model_family
    fam = _infer_model_family(entries[idx].get('model', ''))
    for i in range(idx - 1, -1, -1):
        if _infer_model_family(entries[i].get('model', '')) == fam:
            return entries[i]
    return None


def _header_words(entry: dict) -> str:
    from src.proxy_display.render_turn import _build_req_header_line
    header = _build_req_header_line(
        entry, entry_idx=0, num_label='#1', req_symbol='▶', model_short='opus',
        msg_count=entry.get('message_count', 0), mods_str='', warn_str='', pane_width=250,
        copy_feedback=None,
    )
    visible = _ANSI_RE.sub('', header)
    return ' '.join(w for w in ('strip', 'inject') if re.search(rf'\b{w}\b', visible))


# entry['messages'] is only populated for the last PROXY_MESSAGES_KEEP_LAST entries (deque
# window in _parse_forwarded_log); older entries need the same lazy-load pane.py triggers on
# expand of a scrolled-past request.
def _ensure_messages_loaded(entry: dict) -> None:
    from src.proxy_display.forwarded_parser import _lazy_load_messages_forwarded
    if entry.get('messages') is None:
        fwd_path = LOG_DIR / f'{STEM}_forwarded.jsonl'
        assert _lazy_load_messages_forwarded(entry, fwd_path), 'lazy-load of messages failed'


def _render_body(entries: list, idx: int) -> str:
    from src.proxy_display.render_messages import render_messages
    _ensure_messages_loaded(entries[idx])
    prev = _prev_same_family(entries, idx)
    if prev is not None:
        _ensure_messages_loaded(prev)
    lines, _keys = render_messages(entries[idx], prev, entries, {}, 200)
    return '\n'.join(lines)


# Case 1/2/3: flow badges + inline span for a specific msg index, olive-original + green-filler
def _check_span_case(entries: list, flow_prefix: str, msg_idx: int, expected_badge: str, orig_snippet: str, inj_snippet: str, label: str) -> dict:
    idx = _entry_idx(entries, flow_prefix)
    words = _header_words(entries[idx])
    body = _render_body(entries, idx)
    tag = f'[{msg_idx:3d}]'
    has_tag = tag in body
    has_olive = DIM_YELLOW_BG in body and orig_snippet in _ANSI_RE.sub('', body)
    has_green = DIM_GREEN_BG in body and inj_snippet in _ANSI_RE.sub('', body)
    ok = (words == expected_badge) and has_tag and has_olive and has_green
    return {
        'label': label, 'flow_id': entries[idx].get('flow_id', ''), 'ok': ok,
        'detail': f'badge={words!r} (want {expected_badge!r}), [{msg_idx}] present={has_tag}, olive={has_olive}, green={has_green}',
    }


# Case 4: empty-delta flow badges nothing and shows none of a neighbor flow's spans
def _check_empty_flow_no_bleed(entries: list, flow_prefix: str, foreign_msg_idx: int) -> dict:
    from src.proxy_display.render_messages import _lookup_spans
    idx = _entry_idx(entries, flow_prefix)
    entry = entries[idx]
    words = _header_words(entry)
    body = _render_body(entries, idx)
    no_badge = words == ''
    no_span_in_body = DIM_YELLOW_BG not in body and DIM_GREEN_BG not in body
    i_blk, s_blk = _lookup_spans(entry, foreign_msg_idx, 0, True)
    no_foreign_span = (i_blk == [] and s_blk == [])
    ok = no_badge and no_span_in_body and no_foreign_span
    return {
        'label': 'empty_delta_no_bleed', 'flow_id': entry.get('flow_id', ''), 'ok': ok,
        'detail': f'badge={words!r} (want none), spans_in_own_body={not no_span_in_body}, '
                  f'foreign_lookup(msg={foreign_msg_idx})={not no_foreign_span}',
    }


# Case 5: synthetic fields-only delta line must not badge; fields section stays populated
def _check_fields_only_no_badge() -> dict:
    from src.proxy_display.parser import accumulate_dual_log
    line = json.dumps({
        'type': 'stripped_delta', 'request_id': 'synthetic', 'timestamp': '2026-01-01T00:00:00Z',
        'model': 'claude-opus-5', 'is_first': False, 'counts': {'system': 4, 'tools': 8, 'messages': 4},
        'system_delta': {}, 'tools_delta': {}, 'messages_delta': {},
        'fields_delta': {'max_tokens': '999'}, 'fn_map': {}, 'flow_id': 'synthetic_fields_only',
    })
    with tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False) as f:
        f.write(line + '\n')
        tmp_path = Path(f.name)
    acc: dict = {}
    try:
        accumulate_dual_log(tmp_path, 0, acc)
    finally:
        tmp_path.unlink()
    has_content = acc.get('opus', {}).get('_has_content_by_flow_id', {}).get('synthetic_fields_only')
    fields_kept = acc.get('opus', {}).get('fields', {}).get('max_tokens') == '999'
    ok = (has_content is False) and fields_kept
    return {
        'label': 'synthetic_fields_only_no_badge', 'flow_id': 'synthetic_fields_only', 'ok': ok,
        'detail': f'has_content={has_content} (want False), fields_kept={fields_kept} (want True)',
    }


# Case 6: no ⚠S badge in any rendered header over the whole session; ⚠T logic intact in source
def _check_no_warn_s(entries: list) -> dict:
    from src.proxy_display.format import format_proxy_block
    output, _total = format_proxy_block(entries, expand_states={}, pane_height=2000, pane_width=250)
    visible = _ANSI_RE.sub('', output)
    no_warn_s = '⚠S' not in visible
    src = (WORKTREE_ROOT / 'src' / 'proxy_display' / 'render_turn.py').read_text()
    warn_t_in_source = '⚠T' in src
    warn_s_in_source = '⚠S' in src
    ok = no_warn_s and warn_t_in_source and not warn_s_in_source
    return {
        'label': 'no_warn_s_badge', 'flow_id': '(all)', 'ok': ok,
        'detail': f'⚠S in rendered output={not no_warn_s} (want False), '
                  f'⚠T in render_turn.py source={warn_t_in_source} (want True), '
                  f'⚠S in render_turn.py source={warn_s_in_source} (want False)',
    }


# ORCHESTRATOR
def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    entries = _load_session_impl()
    results = [
        _check_span_case(
            entries, 'fa0ba243', 1, 'strip inject',
            'The following deferred tools are now available via ToolSearch',
            '.', 'msg1_deferred_tools_notice_below_window',
        ),
        _check_span_case(
            entries, '9f02e2cd', 33, 'strip inject',
            "The task tools haven't been used recently",
            '.', 'msg33_task_tools_nag_outside_window_core_case',
        ),
        _check_span_case(
            entries, '9f75f100', 38, 'strip inject',
            '[SYSTEM NOTIFICATION - NOT USER INPUT]',
            'background done — check worker or other process',
            'msg38_bg_notification',
        ),
        _check_empty_flow_no_bleed(entries, '01e683fe', foreign_msg_idx=1),
        _check_fields_only_no_badge(),
        _check_no_warn_s(entries),
    ]
    lines = ['# Badge-inline probe — per-flow span visibility + neighbor-bleed fix', '']
    lines.append(f'Session: `{STEM}` ({len(entries)} forwarded entries)')
    lines.append('')
    lines.append('| case | flow_id | pass | detail |')
    lines.append('|---|---|---|---|')
    all_pass = True
    for r in results:
        all_pass = all_pass and r['ok']
        lines.append(f"| {r['label']} | {r['flow_id']} | {'PASS' if r['ok'] else 'FAIL'} | {r['detail']} |")
    lines.append('')
    lines.append(f"## Overall: {'ALL PASS' if all_pass else 'FAILURES PRESENT'}")
    REPORT_PATH.write_text('\n'.join(lines))
    print(f'Report written: {REPORT_PATH}')
    for r in results:
        print(('PASS' if r['ok'] else 'FAIL'), r['label'], '-', r['detail'])
    print('ALL PASS' if all_pass else 'FAILURES PRESENT')
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
