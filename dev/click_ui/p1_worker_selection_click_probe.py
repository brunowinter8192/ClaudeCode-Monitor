"""
P1 -- worker-selection click parity probe (Milestone 1: worker selection clickable in both
worker panes).

Proves, per pane, that after ONE real render pass:
  1. the click-region table (worker-proxy header markers; workers-pane header rows) contains one
     entry per worker at plausible coordinates
  2. dispatching a synthetic mouse click at those exact coordinates produces the SAME state
     change (selected worker name written to the IPC selection file, expand-state where
     applicable) as pressing the corresponding digit key

Covers:
  - src/proxy_display/worker_proxy_pane.py :: _format_worker_proxy_header header regions,
    _handle_worker_proxy_mouse vs _handle_worker_proxy_key
  - src/workers/worker_pane.py :: worker_line_map (whole-row hit area), _handle_workers_mouse
    vs _handle_workers_key

No live tmux/terminal needed -- module globals are seeded directly with synthetic worker lists;
IPC selection files are written to throwaway, probe-specific project_filter paths (hashed into
/tmp/monitor_cc_selected_worker_<hash>.txt by the real get_selection_file_path), cleaned up after
each check.

Run from project root or worktree root:
    ./venv/bin/python dev/click_ui/p1_worker_selection_click_probe.py
"""

# INFRASTRUCTURE
import importlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT))
os.environ.setdefault('MONITOR_CC_ROOT', str(WORKTREE_ROOT))

_ROOT_PKG = 'src'
wp = importlib.import_module(f'{_ROOT_PKG}.proxy_display.worker_proxy_pane')
wpane = importlib.import_module(f'{_ROOT_PKG}.workers.worker_pane')

_FAKE_PROXY_PROJECT = '/tmp/click_ui_probe_worker_proxy'
_FAKE_WORKERS_PROJECT = '/tmp/click_ui_probe_workers_pane'

_PASS = "\033[32mPASS\033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_RESULTS = []


def check(label, condition):
    _RESULTS.append((label, bool(condition)))
    print(f"  {_PASS if condition else _FAIL}  {label}")
    return condition


# FUNCTIONS

# Remove a probe-scoped IPC selection file, if present
def _clear_selection(get_path_fn, project_filter):
    path = get_path_fn(project_filter)
    if os.path.exists(path):
        os.remove(path)


# Read back a probe-scoped IPC selection file's content ('' if absent)
def _read_selection(get_path_fn, project_filter):
    path = get_path_fn(project_filter)
    if not os.path.exists(path):
        return ''
    return open(path, 'r', encoding='utf-8').read().strip()


# Worker-proxy pane: header-marker regions built one per worker; click == digit key
def test_worker_proxy_header_click():
    monitor = SimpleNamespace(active_project_filter=_FAKE_PROXY_PROJECT)
    workers = [{'name': 'alice'}, {'name': 'bob'}, {'name': 'carol'}]
    wp._worker_proxy_workers = workers
    _clear_selection(wp.get_selection_file_path, _FAKE_PROXY_PROJECT)

    wp._build_worker_proxy_output(monitor)
    regions = dict(wp._worker_proxy_header_regions)

    check("worker-proxy: one header region per worker", len(regions) == len(workers))
    check("worker-proxy: region targets match worker names",
          sorted(regions.values()) == sorted(w['name'] for w in workers))
    check("worker-proxy: region coordinates plausible (1-based, sc<=ec, er>=1)",
          all(sc >= 1 and ec >= sc and er >= 1 for (sc, ec, er) in regions))
    ordered = sorted(regions.keys(), key=lambda r: r[0])
    check("worker-proxy: header regions do not overlap",
          all(ordered[i][1] < ordered[i + 1][0] for i in range(len(ordered) - 1)))

    name_to_region = {name: rect for rect, name in regions.items()}
    for idx, w in enumerate(workers, 1):
        name = w['name']
        sc, ec, er = name_to_region[name]
        click_col = (sc + ec) // 2

        _clear_selection(wp.get_selection_file_path, _FAKE_PROXY_PROJECT)
        wp._worker_proxy_force_reload = False
        key_changed = wp._handle_worker_proxy_key(str(idx), monitor)
        key_selection = _read_selection(wp.get_selection_file_path, _FAKE_PROXY_PROJECT)
        key_reload = wp._worker_proxy_force_reload

        _clear_selection(wp.get_selection_file_path, _FAKE_PROXY_PROJECT)
        wp._worker_proxy_force_reload = False
        mouse_changed = wp._handle_worker_proxy_mouse(0, click_col, er, monitor)
        mouse_selection = _read_selection(wp.get_selection_file_path, _FAKE_PROXY_PROJECT)
        mouse_reload = wp._worker_proxy_force_reload

        check(f"worker-proxy: digit-key '{idx}' selects '{name}'",
              key_changed and key_selection == name and key_reload)
        check(f"worker-proxy: click at col {click_col} row {er} on '[{idx}]{name}' selects it",
              mouse_changed and mouse_selection == name and mouse_reload)
        check(f"worker-proxy: click/key parity for '{name}'", key_selection == mouse_selection)

    _clear_selection(wp.get_selection_file_path, _FAKE_PROXY_PROJECT)


# Workers pane: whole-row hit area (worker_line_map); one header-row region per worker; click ==
# digit key (expand/collapse + select)
def test_workers_pane_row_click():
    project_filter = _FAKE_WORKERS_PROJECT
    workers = [
        {'name': 'w1', 'status': 'working', 'purpose': 'run the build'},
        {'name': 'w2', 'status': 'idle', 'purpose': ''},
    ]
    wpane.worker_expand_states.clear()
    wpane.worker_scroll_offsets.clear()
    wpane.worker_cache_expand_states.clear()
    wpane.worker_turns.clear()
    wpane.worker_selected_name = None
    wpane.worker_scroll_offset = 0
    _clear_selection(wpane.get_selection_file_path, project_filter)

    wpane._build_workers_output(workers, frozen=False)
    line_map = dict(wpane.worker_line_map)

    header_row_of = {}
    for row in sorted(line_map):
        name = line_map[row]
        if name not in header_row_of:
            header_row_of[name] = row

    check("workers-pane: one header-row region per worker",
          set(header_row_of) == {w['name'] for w in workers})
    check("workers-pane: header-row coordinates plausible (row>=1)",
          all(row >= 1 for row in header_row_of.values()))

    click_col = 5
    for idx, w in enumerate(workers, 1):
        name = w['name']
        row = header_row_of[name]

        wpane.worker_expand_states.clear()
        wpane.worker_selected_name = None
        _clear_selection(wpane.get_selection_file_path, project_filter)
        key_changed, _ = wpane._handle_workers_key(str(idx), workers, False, project_filter)
        key_selection = _read_selection(wpane.get_selection_file_path, project_filter)
        key_expanded = wpane.worker_expand_states.get(name, False)
        key_selected_name = wpane.worker_selected_name

        wpane.worker_expand_states.clear()
        wpane.worker_selected_name = None
        _clear_selection(wpane.get_selection_file_path, project_filter)
        mouse_changed = wpane._handle_workers_mouse(0, click_col, row, project_filter)
        mouse_selection = _read_selection(wpane.get_selection_file_path, project_filter)
        mouse_expanded = wpane.worker_expand_states.get(name, False)
        mouse_selected_name = wpane.worker_selected_name

        check(f"workers-pane: digit-key '{idx}' expands+selects '{name}'",
              key_changed and key_expanded and key_selected_name == name and key_selection == name)
        check(f"workers-pane: click on row {row} ('{name}') produces same expand+select",
              mouse_changed and mouse_expanded and mouse_selected_name == name and mouse_selection == name)
        check(f"workers-pane: click/key parity for '{name}'",
              (key_expanded, key_selected_name, key_selection) == (mouse_expanded, mouse_selected_name, mouse_selection))

    scroll_row = next(iter(header_row_of.values()))
    wpane.worker_scroll_offsets.clear()
    scroll_ok = wpane._handle_workers_mouse(64, click_col, scroll_row, project_filter)
    check("workers-pane: scroll wheel on a worker row still handled (no collision)", scroll_ok)

    _clear_selection(wpane.get_selection_file_path, project_filter)


# ORCHESTRATOR

def run_probe_workflow():
    print("=" * 70)
    print("worker-selection click probe -- worker-proxy header + workers-pane row")
    print("=" * 70)
    test_worker_proxy_header_click()
    test_workers_pane_row_click()

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
    out_path = md_dir / f"p1_worker_selection_click_probe_{stamp}.md"
    lines = [
        f"# P1 -- worker-selection click probe run ({datetime.now(timezone.utc).isoformat()})",
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
