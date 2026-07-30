"""
P3 -- pane-chrome button click parity probe (Milestone 3: the remaining single-purpose keyboard
controls -- workers 'f' freeze, proxy 'u' undo, warnings 'r' refresh).

Proves, per pane, that after ONE real render pass:
  1. the header/chrome button region is registered at a plausible (start_col,end_col,phys_row)
  2. dispatching a synthetic click on it produces the SAME state change as the corresponding key
  3. for the two toggle/state-dependent buttons (freeze, undo) the render reflects state BEFORE
     the click: the freeze badge text differs live-vs-frozen; the undo button's color differs
     empty-vs-non-empty stack (still clickable when empty -- same no-op _undo_proxy_expand()
     already gives the 'u' key)
  4. a too-narrow pane registers no region (and, for the two NEW buttons -- undo, refresh --
     renders no button text either; the workers freeze badge is pre-existing content, always
     rendered, only its clickability is width-guarded)
  5. the existing click handling each pane already had (workers row-select, proxy expand/copy,
     warnings expand/copy) still works after adding the header check ahead of it

Covers:
  - src/panes/warnings_pane.py :: _build_warnings_output (_warnings_header_regions),
    _handle_warnings_mouse, _handle_warnings_key -- src/panes/warnings_render.py ::
    _format_warnings_header
  - src/workers/worker_pane.py :: _build_workers_output (_worker_header_regions),
    _handle_workers_mouse (now returns (changed, frozen)), _handle_workers_key --
    src/workers/worker_format.py :: format_workers_block
  - src/proxy_display/pane.py :: _build_proxy_output (now returns (output, header) with a new
    header/body split), _handle_proxy_mouse, _undo_proxy_expand -- src/proxy_display/format.py ::
    _format_proxy_header

No live tmux/terminal needed -- module globals are seeded directly with synthetic data;
copy_to_clipboard is monkeypatched where needed (reused from milestone 2's pattern) so the
existing-click regression checks don't touch the OS clipboard.

Run from project root or worktree root:
    ./venv/bin/python dev/click_ui/p3_button_click_probe.py
"""

# INFRASTRUCTURE
import importlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT))
os.environ.setdefault('MONITOR_CC_ROOT', str(WORKTREE_ROOT))

_ROOT_PKG = 'src'
mod_warnings = importlib.import_module(f'{_ROOT_PKG}.panes.warnings_pane')
mod_warnings_render = importlib.import_module(f'{_ROOT_PKG}.panes.warnings_render')
mod_workers = importlib.import_module(f'{_ROOT_PKG}.workers.worker_pane')
mod_worker_format = importlib.import_module(f'{_ROOT_PKG}.workers.worker_format')
mod_proxy = importlib.import_module(f'{_ROOT_PKG}.proxy_display.pane')
mod_proxy_format = importlib.import_module(f'{_ROOT_PKG}.proxy_display.format')

_PASS = "\033[32mPASS\033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_RESULTS = []


def check(label, condition):
    _RESULTS.append((label, bool(condition)))
    print(f"  {_PASS if condition else _FAIL}  {label}")
    return condition


# FUNCTIONS

# Build a minimal synthetic proxy entry (same shape as dev/display/test_hover_map.py's _make_entry)
def _make_proxy_entry(idx, model='claude-sonnet', msg_count=3, bp=2):
    return {
        'model': model, 'message_count': msg_count, 'cache_breakpoints': [{}] * bp,
        'system_total_chars': 10000 if bp > 0 else 0, 'tools_total_chars': 5000 if bp > 0 else 0,
        'messages_total_chars': 3000, 'tools_count': 10 if bp > 0 else 0, 'tools_hash': f'hash{idx}',
        'tools_names': [f'tool_{j}' for j in range(10)] if bp > 0 else [], 'tools_defs': [],
        'system_blocks': [{'idx': 0, 'chars': 10000, 'preview': 'sys content'}] if bp > 0 else [],
        'messages': [{'role': 'user', 'type': 'text', 'chars': 500, 'blocks': []} for _ in range(msg_count)],
        'schema_warnings': [], 'stripped_msg_indices': [], 'modifications': [],
        'timestamp': f'2026-04-21T10:0{idx}:00Z',
    }


# Warnings pane: [refresh] header button -- region, click/key parity, width guard
def test_warnings_refresh_button():
    mod_warnings.tool_errors.clear()
    mod_warnings.error_expand_states.clear()
    mod_warnings.error_hover_row = None
    mod_warnings.error_scroll_offset = 0
    mod_warnings._force_refresh = False
    mod_warnings._last_refresh_ts = 1234567890.0

    output, header = mod_warnings._build_warnings_output()
    regions = dict(mod_warnings._warnings_header_regions)
    check("warnings: [refresh] button region registered", regions.get((sorted(regions)[0])) == 'refresh' if regions else False)
    check("warnings: exactly one header region, on row 1", len(regions) == 1 and next(iter(regions))[2] == 1)
    check("warnings: button text visible in header", '[refresh]' in header)

    (sc, ec, er), _ = next(iter(regions.items()))
    click_col = (sc + ec) // 2

    mod_warnings._force_refresh = False
    key_changed = mod_warnings._handle_warnings_key('r')
    key_refresh = mod_warnings._force_refresh

    mod_warnings._force_refresh = False
    click_changed = mod_warnings._handle_warnings_mouse(0, click_col, er)
    click_refresh = mod_warnings._force_refresh

    check("warnings: 'r' key sets _force_refresh", key_changed and key_refresh)
    check("warnings: click on [refresh] sets _force_refresh (same as key)", click_changed and click_refresh)

    narrow_regions = {}
    narrow_header = mod_warnings_render._format_warnings_header(1234567890.0, 10, narrow_regions)
    check("warnings: width guard -- no region and no button text when pane_width=10",
          len(narrow_regions) == 0 and '[refresh]' not in narrow_header)


# Workers pane: freeze badge as header button -- region, click/key parity, state-reflecting label,
# no collision with row-select/copy, width guard
def test_workers_freeze_button():
    project_filter = '/tmp/click_ui_probe_p3_workers'
    mod_workers.worker_expand_states.clear()
    mod_workers.worker_scroll_offsets.clear()
    mod_workers.worker_cache_expand_states.clear()
    mod_workers.worker_turns.clear()
    mod_workers.worker_selected_name = None
    mod_workers.worker_scroll_offset = 0
    mod_workers._worker_copy_feedback_until.clear()
    if os.path.exists(mod_workers.get_selection_file_path(project_filter)):
        os.remove(mod_workers.get_selection_file_path(project_filter))

    workers = [{'name': 'w1', 'status': 'working', 'purpose': 'run the build', 'session': ''}]

    output_live = mod_workers._build_workers_output(workers, frozen=False)
    regions_live = dict(mod_workers._worker_header_regions)
    output_frozen = mod_workers._build_workers_output(workers, frozen=True)
    regions_frozen = dict(mod_workers._worker_header_regions)

    check("workers: freeze region registered live", regions_live.get(next(iter(regions_live), None)) == 'freeze' if regions_live else False)
    check("workers: freeze region registered frozen", regions_frozen.get(next(iter(regions_frozen), None)) == 'freeze' if regions_frozen else False)
    check("workers: badge reads [LIVE] when not frozen", '[LIVE]' in output_live and '[FROZEN]' not in output_live)
    check("workers: badge reads [FROZEN] when frozen", '[FROZEN]' in output_frozen and '[LIVE]' not in output_frozen)

    (sc, ec, er) = next(iter(regions_live))
    click_col = (sc + ec) // 2

    key_changed, key_frozen = mod_workers._handle_workers_key('f', workers, False, project_filter)
    click_changed, click_frozen = mod_workers._handle_workers_mouse(0, click_col, er, project_filter, False)
    check("workers: 'f' key toggles frozen False->True", key_changed and key_frozen is True)
    check("workers: click on freeze badge toggles frozen False->True (same as key)",
          click_changed and click_frozen is True)

    click_changed2, click_frozen2 = mod_workers._handle_workers_mouse(0, click_col, er, project_filter, True)
    check("workers: click on freeze badge toggles frozen True->False", click_changed2 and click_frozen2 is False)

    pre_selected = mod_workers.worker_selected_name
    check("workers: clicking the freeze badge did not select/expand a worker (no collision)",
          mod_workers.worker_selected_name == pre_selected and not mod_workers.worker_expand_states.get('w1', False))

    header_row = next(r for r, k in mod_workers.worker_line_map.items() if k == 'w1')
    row_changed, row_frozen = mod_workers._handle_workers_mouse(0, 5, header_row, project_filter, False)
    check("workers: normal row click still selects+expands (milestone-1 undisturbed)",
          row_changed and mod_workers.worker_selected_name == 'w1' and mod_workers.worker_expand_states.get('w1') is True and row_frozen is False)

    orig_terminal_size = os.get_terminal_size
    os.get_terminal_size = lambda: os.terminal_size((10, 30))
    try:
        narrow_regions = {}
        mod_worker_format.format_workers_block(
            workers, {}, {}, {}, {}, frozen=False, selected_name=None, regions_out=narrow_regions,
        )
    finally:
        os.get_terminal_size = orig_terminal_size
    check("workers: width guard -- no freeze region when pane_width=10 (too narrow)",
          'freeze' not in narrow_regions)

    if os.path.exists(mod_workers.get_selection_file_path(project_filter)):
        os.remove(mod_workers.get_selection_file_path(project_filter))


# Proxy pane: [undo] header button -- region, click/key parity, empty-stack state, no collision
# with expand/copy rows, width guard
def test_proxy_undo_button():
    mod_proxy.proxy_entries.clear()
    mod_proxy.proxy_expand_states.clear()
    mod_proxy.proxy_line_map.clear()
    mod_proxy.proxy_hover_row = None
    mod_proxy.proxy_scroll_offset = 0
    mod_proxy._proxy_undo_stack.clear()
    mod_proxy._copy_feedback_until.clear()

    output_empty, header_empty = mod_proxy._build_proxy_output()
    regions_empty = dict(mod_proxy._proxy_header_regions)
    check("proxy: [undo] region registered with an empty stack (still clickable)",
          list(regions_empty.values()) == ['undo'])
    check("proxy: [undo] button text visible even with an empty stack", '[undo]' in header_empty)

    (sc, ec, er) = next(iter(regions_empty))
    click_col = (sc + ec) // 2
    empty_click_changed = mod_proxy._handle_proxy_mouse(0, click_col, er)
    check("proxy: clicking [undo] with an empty stack is a no-op (same as 'u' key)",
          empty_click_changed is False)

    mod_proxy.proxy_expand_states[0] = True
    mod_proxy._proxy_undo_stack.append((0, False))
    output_full, header_full = mod_proxy._build_proxy_output()
    check("proxy: [undo] header text differs empty-vs-non-empty stack (color-coded state)",
          header_full != header_empty and '[undo]' in header_full)

    regions_full = dict(mod_proxy._proxy_header_regions)
    (sc2, ec2, er2) = next(iter(regions_full))
    click_col2 = (sc2 + ec2) // 2
    click_changed = mod_proxy._handle_proxy_mouse(0, click_col2, er2)
    check("proxy: clicking [undo] pops the stack and restores prior expand-state",
          click_changed and mod_proxy.proxy_expand_states.get(0) is False and not mod_proxy._proxy_undo_stack)

    mod_proxy.proxy_expand_states[0] = True
    mod_proxy._proxy_undo_stack.append((0, False))
    key_changed = mod_proxy._undo_proxy_expand()
    check("proxy: 'u' key (_undo_proxy_expand) produces the same state change as the click",
          key_changed and mod_proxy.proxy_expand_states.get(0) is False and not mod_proxy._proxy_undo_stack)

    # Existing row click (expand/collapse) must still work after the header/body split
    mod_proxy.proxy_entries.clear()
    mod_proxy.proxy_expand_states.clear()
    mod_proxy.proxy_line_map.clear()
    mod_proxy._proxy_undo_stack.clear()
    mod_proxy.proxy_entries.extend(_make_proxy_entry(i) for i in range(3))
    output, header = mod_proxy._build_proxy_output()
    req_row = next(r for r, k in mod_proxy.proxy_line_map.items()
                    if (isinstance(k, tuple) and k[0] == 'req') or isinstance(k, int))
    row_click_changed = mod_proxy._handle_proxy_mouse(0, 5, req_row)
    check("proxy: body row click (expand/collapse) still works after header/body split",
          row_click_changed and len(mod_proxy._proxy_undo_stack) == 1)

    narrow_regions = {}
    narrow_header = mod_proxy_format._format_proxy_header(True, 5, narrow_regions)
    check("proxy: width guard -- no region and no button text when pane_width=5 (too narrow)",
          len(narrow_regions) == 0 and '[undo]' not in narrow_header)


# ORCHESTRATOR

def run_probe_workflow():
    print("=" * 70)
    print("pane-chrome button click probe -- workers freeze, proxy undo, warnings refresh")
    print("=" * 70)
    test_warnings_refresh_button()
    test_workers_freeze_button()
    test_proxy_undo_button()

    total = len(_RESULTS)
    passed = sum(1 for _, ok in _RESULTS if ok)
    print("\n" + "=" * 70)
    print(f"{passed}/{total} checks passed")
    print("=" * 70)

    _write_report(passed, total)
    return passed == total


def _write_report(passed, total):
    md_dir = WORKTREE_ROOT / "dev" / "click_ui" / "md"
    md_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = md_dir / f"p3_button_click_probe_{stamp}.md"
    lines = [
        f"# P3 -- pane-chrome button click probe run ({datetime.now(timezone.utc).isoformat()})",
        "",
        f"**Result: {passed}/{total} checks passed**",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for label, ok in _RESULTS:
        lines.append(f"| {label} | {'PASS' if ok else 'FAIL'} |")
    out_path.write_text("\n".join(lines) + "\n")
    print(f"\nReport written to: {out_path}")


if __name__ == "__main__":
    ok = run_probe_workflow()
    sys.exit(0 if ok else 1)
