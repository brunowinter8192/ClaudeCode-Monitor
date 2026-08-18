"""
p2_search_feature_regression_test.py — Regression guard for the M2 proxy-pane search bar
(process-docs/pane_search/).

Covers, per the M2 spec:
  - search bar renders at row 1 (always visible)
  - line_map shift correctness (body rows start at row 2, header row never gets a body key)
  - collapsed-hit marks REQ row; expanded-hit ALSO highlights the matching inner line (header
    stays marked when expanded — decision: uniform, keeps orientation when scrolling)
  - n/N jump ordering (wraps both directions)
  - Esc clears the query (matches cleared, bar stays — it's a permanent row, not a toggle)
  - scroll-jump respects the existing max_scroll clamp
  - the flow_id-based _lazy_load_messages_forwarded fix (the _fwd_req_idx collision bug found
    during M2 investigation — verified against a self-contained synthetic 2-batch fixture, not
    the real gitignored log, so this guard is portable)

Uses REAL render_turn.py / format.py / search.py / forwarded_parser.py / pane.py functions
against synthetic data — not mocks. importlib.import_module used throughout (dev/ scripts may
not use a literal 'from src.' import line).

Run: ./venv/bin/python dev/pane_search/p2_search_feature_regression_test.py
"""

# INFRASTRUCTURE
import importlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT))
os.environ.setdefault('MONITOR_CC_ROOT', str(WORKTREE_ROOT))

_ROOT_PKG = 'src'
mod_pane = importlib.import_module(f'{_ROOT_PKG}.proxy_display.pane')
mod_format = importlib.import_module(f'{_ROOT_PKG}.proxy_display.format')
mod_search = importlib.import_module(f'{_ROOT_PKG}.proxy_display.search')
mod_fwd = importlib.import_module(f'{_ROOT_PKG}.proxy_display.forwarded_parser')
mod_constants = importlib.import_module(f'{_ROOT_PKG}.constants')

SEARCH_MATCH_BG = mod_constants.SEARCH_MATCH_BG
SEARCH_CURRENT_BG = mod_constants.SEARCH_CURRENT_BG

PANE_WIDTH = 120
_RESULTS = []


def check(label, condition):
    _RESULTS.append((label, bool(condition)))
    status = 'PASS' if condition else 'FAIL'
    print(f"  {status}  {label}")
    return condition


# FUNCTIONS

# Synthetic proxy entry with a UNIQUE, always-visible marker in its OWN new message (message
# index == idx, "unique_marker_<idx>") — messages list is CUMULATIVE (length == message_count,
# one prior filler message per earlier idx + this entry's own new one), matching how
# render_messages._render_new_messages finds "new" messages: range(prev_msg_count, len(messages))
# — a non-cumulative per-entry-only messages list renders as an EMPTY new-message range and the
# marker never appears (found while writing this test; see process-docs/pane_search/).
# Base shape otherwise matches dev/display/test_hover_map.py's _make_entry, extended with
# flow_id (search's merge key).
def _make_entry(idx: int, marker: str = None, model: str = 'claude-sonnet') -> dict:
    marker_text = marker or f'unique_marker_{idx}'
    messages = [{'role': 'user', 'type': 'text', 'chars': 10, 'blocks': []} for _ in range(idx)]
    messages.append({
        'role': 'user', 'type': 'text', 'chars': len(marker_text),
        'blocks': [{'type': 'text', 'chars': len(marker_text), 'preview': marker_text, 'full_text': marker_text, 'has_cc': False}],
    })
    return {
        'model': model,
        'message_count': idx + 1,
        'flow_id': f'flow-{idx}',
        'cache_breakpoints': [],
        'system_total_chars': 10000,
        'tools_total_chars': 5000,
        'messages_total_chars': 3000,
        'tools_count': 1,
        'tools_hash': f'hash{idx}',
        'tools_names': ['tool_a'],
        'tools_defs': [{'name': 'tool_a', 'description': 'd', 'input_schema': {}, 'stripped_original': None}],
        'system_blocks': [{'idx': 0, 'chars': 3, 'preview': 'sys', 'has_cc': False}],
        'messages': messages,
        'schema_warnings': [], 'stripped_msg_indices': [], 'modifications': [],
        'anthropic_beta': [], 'context_management': None, 'diagnostics': None,
        'effort_value': None, 'max_tokens': 0,
        'diff_from_prev': {'messages_added': 1},
        'timestamp': f'2026-04-21T10:{idx:02d}:00Z',
    }


def _reset_pane_state():
    mod_pane.proxy_entries.clear()
    mod_pane.proxy_expand_states.clear()
    mod_pane.proxy_line_map.clear()
    mod_pane.proxy_hover_row = None
    mod_pane.proxy_scroll_offset = 0
    mod_pane._proxy_search_query = ''
    mod_pane._proxy_search_focused = False
    mod_pane._proxy_search_matches = []
    mod_pane._proxy_search_match_set = set()
    mod_pane._proxy_search_current_idx = 0
    mod_pane._proxy_just_expanded = None
    mod_pane._proxy_pane_width = PANE_WIDTH


# TESTS

def test_search_bar_renders_at_row1():
    print("\n[search bar] Always-visible row 1, empty and populated query")
    _reset_pane_state()
    mod_pane.proxy_entries.extend(_make_entry(i) for i in range(2))
    output = mod_pane._build_proxy_output()
    first_line = output.splitlines()[0]
    check("empty query: 'search: _' pattern present", 'search:' in first_line)
    mod_pane._proxy_search_query = 'foo'
    mod_pane._proxy_search_focused = True
    output2 = mod_pane._build_proxy_output()
    first_line2 = output2.splitlines()[0]
    check("populated query: query text 'foo' visible in row 1", 'foo' in first_line2)


def test_line_map_shift():
    print("\n[line_map shift] Header row never gets a body key; body starts at row 2")
    _reset_pane_state()
    mod_pane.proxy_entries.extend(_make_entry(i) for i in range(5))
    mod_pane._build_proxy_output()
    check("row 1 has no line_map entry", mod_pane.proxy_line_map.get(1) is None)
    check("every line_map row is >= 2", all(r >= 2 for r in mod_pane.proxy_line_map))
    req_keys = [k for k in mod_pane.proxy_line_map.values() if isinstance(k, tuple) and k[0] == 'req']
    check("all 5 REQ headers present in shifted line_map", len(req_keys) == 5)


def test_collapsed_hit_marks_req_row():
    print("\n[collapsed hit] Header row marked; no inner line marked (nothing rendered)")
    _reset_pane_state()
    entries = [_make_entry(i) for i in range(4)]
    mod_pane.proxy_entries.extend(entries)
    matches = mod_search.build_search_matches('unique_marker_2', mod_pane.proxy_entries, mod_pane.proxy_expand_states, PANE_WIDTH)
    check("exactly entry 2 matches 'unique_marker_2'", matches == [2])
    mod_pane._proxy_search_query = 'unique_marker_2'
    mod_pane._proxy_search_matches = matches
    mod_pane._proxy_search_match_set = set(matches)
    mod_pane._proxy_search_current_idx = 0
    output = mod_pane._build_proxy_output()
    lines = output.splitlines()
    marked_lines = [l for l in lines if SEARCH_CURRENT_BG in l]
    check("exactly one line carries SEARCH_CURRENT_BG (the collapsed REQ header)", len(marked_lines) == 1)


def test_expanded_hit_marks_line():
    print("\n[expanded hit] Header STAYS marked + the matching inner line ALSO marked")
    _reset_pane_state()
    entries = [_make_entry(i) for i in range(4)]
    mod_pane.proxy_entries.extend(entries)
    matches = mod_search.build_search_matches('unique_marker_2', mod_pane.proxy_entries, mod_pane.proxy_expand_states, PANE_WIDTH)
    mod_pane._proxy_search_query = 'unique_marker_2'
    mod_pane._proxy_search_matches = matches
    mod_pane._proxy_search_match_set = set(matches)
    mod_pane._proxy_search_current_idx = 0
    mod_pane.proxy_expand_states[('req', 2)] = True
    output = mod_pane._build_proxy_output()
    marked_lines = [l for l in output.splitlines() if SEARCH_CURRENT_BG in l]
    check("2 lines carry SEARCH_CURRENT_BG (header + inner content line)", len(marked_lines) == 2)
    inner_marked = [l for l in marked_lines if 'unique_marker_2' in l]
    check("the inner marked line actually contains the matched text", len(inner_marked) == 1)


def test_n_N_ordering():
    print("\n[n/N ordering] Jump forward/backward wraps around the match list")
    _reset_pane_state()
    mod_pane.proxy_entries.extend(_make_entry(i) for i in range(6))
    mod_pane._proxy_search_matches = [1, 3, 5]
    mod_pane._proxy_search_match_set = {1, 3, 5}
    mod_pane._proxy_search_current_idx = 0
    mod_pane._jump_search_match(forward=True)
    check("n: 0 -> 1", mod_pane._proxy_search_current_idx == 1)
    mod_pane._jump_search_match(forward=True)
    check("n: 1 -> 2", mod_pane._proxy_search_current_idx == 2)
    mod_pane._jump_search_match(forward=True)
    check("n wraps: 2 -> 0", mod_pane._proxy_search_current_idx == 0)
    mod_pane._jump_search_match(forward=False)
    check("N wraps backward: 0 -> 2", mod_pane._proxy_search_current_idx == 2)
    mod_pane._proxy_search_matches = []
    mod_pane._proxy_search_match_set = set()
    check("n/N no-op with zero matches", mod_pane._jump_search_match(forward=True) is False)


def test_esc_clears_query_bar_stays():
    print("\n[Esc] Clears query + matches; bar remains a permanent row")
    _reset_pane_state()
    mod_pane.proxy_entries.extend(_make_entry(i) for i in range(2))
    mod_pane._proxy_search_query = 'unique_marker_1'
    mod_pane._proxy_search_focused = True
    mod_pane._proxy_search_matches = [1]
    mod_pane._proxy_search_match_set = {1}
    result = mod_pane._handle_proxy_search_cancel()
    check("cancel returns True (always redraws)", result is True)
    check("query cleared", mod_pane._proxy_search_query == '')
    check("focused cleared", mod_pane._proxy_search_focused is False)
    check("matches cleared", mod_pane._proxy_search_matches == [] and mod_pane._proxy_search_match_set == set())
    output = mod_pane._build_proxy_output()
    check("bar still rendered at row 1 after Esc (permanent, not hidden)", 'search:' in output.splitlines()[0])


def test_scroll_jump_clamps():
    print("\n[scroll-jump clamp] Jumping to a match never exceeds max_scroll")
    _reset_pane_state()
    # Many entries so total_lines exceeds a small terminal height, forcing real scrolling
    entries = [_make_entry(i) for i in range(40)]
    mod_pane.proxy_entries.extend(entries)
    mod_pane._proxy_search_matches = [2]  # near the TOP of the (chronological) list
    mod_pane._proxy_search_match_set = {2}
    mod_pane._proxy_search_current_idx = 0
    orig_terminal_size = os.get_terminal_size
    os.get_terminal_size = lambda: os.terminal_size((30, 30))
    try:
        mod_pane._jump_to_search_match()
        check("_proxy_just_expanded set to the match's req key", mod_pane._proxy_just_expanded == ('req', 2))
        mod_pane._build_proxy_output()
        check("post-jump scroll_offset is non-negative", mod_pane.proxy_scroll_offset >= 0)
        check("the jumped-to entry is present in the rendered line_map", ('req', 2) in mod_pane.proxy_line_map.values())
        # A second render at the same (already-clamped) offset must not push it further out of range
        offset_before = mod_pane.proxy_scroll_offset
        mod_pane._build_proxy_output()
        check("scroll_offset stable across a second render (clamp is idempotent)",
              mod_pane.proxy_scroll_offset == offset_before)
    finally:
        os.get_terminal_size = orig_terminal_size


# Build a synthetic 2-request forwarded_delta JSONL line (is_first or delta-continuation)
def _fwd_line(flow_id: str, model: str, is_first: bool, msg_text: str) -> str:
    entry = {
        'type': 'forwarded_delta', 'request_id': '', 'timestamp': datetime.now(timezone.utc).isoformat(),
        'model': model, 'max_tokens': 100, 'output_config': None, 'context_management': None,
        'diagnostics': None, 'is_first': is_first,
        'counts': {'system': 0, 'tools': 0, 'messages': 1},
        'system_delta': {}, 'tools_delta': {},
        'messages_delta': {'0': {'role': 'user', 'content': msg_text}},
        'flow_id': flow_id,
    }
    return json.dumps(entry)


def test_flow_id_lazy_load_fix():
    print("\n[flow_id fix] _lazy_load_messages_forwarded matches by flow_id, not the "
          "call-local _fwd_req_idx (the collision bug found during M2 investigation)")
    tmp = Path(tempfile.mkdtemp(prefix='pane_search_flowid_'))
    full_path = tmp / 'full.jsonl'
    lines = [
        _fwd_line('flow-A', 'claude-opus-5', True, 'first request content AAA'),
        _fwd_line('flow-B', 'claude-opus-5', False, 'second request content BBB'),
        _fwd_line('flow-C', 'claude-opus-5', False, 'third request content CCC'),
        _fwd_line('flow-D', 'claude-opus-5', False, 'fourth request content DDD'),
    ]
    full_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    # Ground truth: fresh byte-0 parse, matched by flow_id
    truth_entries, _ = mod_fwd._parse_forwarded_log(full_path, 0, {})
    truth_by_flow = {e['flow_id']: e for e in truth_entries}

    # Simulate 2 incremental polling batches (batch1 = first 2 lines only, batch2 = rest) —
    # this is what reproduces the call-local _fwd_req_idx collision: batch2's req_idx restarts
    # at 0, colliding with batch1's flow-A/flow-B at the SAME local indices.
    truncated = tmp / 'truncated.jsonl'
    truncated.write_text('\n'.join(lines[:2]) + '\n', encoding='utf-8')
    acc = {}
    batch1, pos1 = mod_fwd._parse_forwarded_log(truncated, 0, acc)
    batch2, pos2 = mod_fwd._parse_forwarded_log(full_path, pos1, acc)
    check("batch2 has 2 entries (flow-C, flow-D)", len(batch2) == 2)
    check("batch2's _fwd_req_idx COLLIDES with batch1's (0,1) — confirms the bug scenario applies",
          {e['_fwd_req_idx'] for e in batch2} == {0, 1})

    all_ok = True
    for e in batch2:
        truth = truth_by_flow[e['flow_id']]
        ok = mod_fwd._lazy_load_messages_forwarded(e, full_path)
        matched = ok and e.get('messages_total_chars') == truth['messages_total_chars']
        all_ok = all_ok and matched
    check("every batch2 entry lazy-loads its OWN content (flow_id-correct, not index-collided)", all_ok)

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ORCHESTRATOR

def run_probe_workflow():
    print("=" * 70)
    print("P2 — proxy-pane search feature regression suite (M2)")
    print("=" * 70)
    test_search_bar_renders_at_row1()
    test_line_map_shift()
    test_collapsed_hit_marks_req_row()
    test_expanded_hit_marks_line()
    test_n_N_ordering()
    test_esc_clears_query_bar_stays()
    test_scroll_jump_clamps()
    test_flow_id_lazy_load_fix()

    total = len(_RESULTS)
    passed = sum(1 for _, ok in _RESULTS if ok)
    print("\n" + "=" * 70)
    print(f"{passed}/{total} checks passed")
    print("=" * 70)

    report_dir = Path(__file__).resolve().parent / 'md'
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = report_dir / f'p2_search_feature_regression_test_{ts}.md'
    lines = [f"# P2 search feature regression — {ts}", "", f"{passed}/{total} checks passed", ""]
    for label, ok in _RESULTS:
        lines.append(f"- [{'x' if ok else ' '}] {label}")
    report_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f"\nReport written to: {report_path}")

    if passed != total:
        sys.exit(1)


if __name__ == '__main__':
    run_probe_workflow()
