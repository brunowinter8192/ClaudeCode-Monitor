"""
P4 -- gpu + news pane button probe (Milestone 4: the last keyboard-only controls).

Proves:
  1. gpu digit keys 1-9 need NO new button -- the pre-existing per-server [start]/[stop]/
     [restart] button already registered in _button_regions computes the SAME action and fires
     the SAME rag-cli subprocess call as _toggle_server(idx, presets) (what the digit key calls).
     Asserted by comparing captured subprocess.Popen args + resulting _toggle_state entry between
     the two paths, for both a stopped preset (start) and a running+healthy preset (stop).
  2. gpu's new [refresh] header button and news's new [refresh] header button: region registered
     after a render, disjoint from every pre-existing button region (different phys_row), and the
     dispatch loop correctly special-cases action=='refresh' before falling into the pre-existing
     _fire_button/_fire_pipeline branch (verified by replicating run_gpu_loop's / run_news_loop's
     exact inline dispatch snippet, since neither loop factors mouse dispatch into a standalone
     function -- same documented boundary as milestone 2's main-pane 'y' key: the local `force_
     refresh`/`input_changed` variables inside the blocking loop are not independently reachable
     without running that loop for real).
  3. narrow pane: [refresh] gets no text and no region in both panes; the pre-existing per-row
     buttons are NOT touched by the width-guard fix (unrelated, out of scope) and are not asserted
     on for the narrow case.
  4. news pane's existing [run pipeline] click dispatch is unchanged by the new action=='refresh'
     branch (regression check).

No live tmux/terminal, no real rag-cli or news pipeline subprocess: subprocess.Popen is
monkeypatched per module to a capturing stub (mirrors milestone 2/3's copy_to_clipboard pattern).
gpu_pane.status.PRESET_NAMES (resolved once at import time via a REAL `rag-cli server presets`
subprocess call) is monkeypatched to a fixed synthetic list so the probe is deterministic
regardless of what's actually running on this machine.

Run from project root or worktree root:
    ./venv/bin/python dev/click_ui/p4_gpu_news_button_probe.py
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
mod_gpu = importlib.import_module(f'{_ROOT_PKG}.gpu_pane.pane')
mod_news = importlib.import_module(f'{_ROOT_PKG}.news_pane.pane')

_PASS = "\033[32mPASS\033[0m"
_FAIL = "\033[31mFAIL\033[0m"
_RESULTS = []


def check(label, condition):
    _RESULTS.append((label, bool(condition)))
    print(f"  {_PASS if condition else _FAIL}  {label}")
    return condition


# FUNCTIONS

# Monkeypatch mod.subprocess.Popen with a capturing stub (no real process launched); returns the
# capture list of Popen call (args, kwargs) tuples
def _patch_popen(mod):
    captured = []

    class _FakePopen:
        def __init__(self, *args, **kwargs):
            captured.append((args, kwargs))

    mod.subprocess.Popen = _FakePopen
    return captured


# Build a synthetic gpu preset status dict
def _make_preset(name, running, healthy, port=None, pid=None):
    return {
        'name': name, 'kind': 'preset', 'running': running, 'healthy': healthy,
        'port': port, 'pid': pid, 'rss_mb': None, 'idle_seconds': None,
        'idle_state_missing': False, 'model_name': None,
    }


# Replicate run_gpu_loop's exact inline button-region dispatch (not a standalone function in the
# real loop); returns 'refresh' | (action, target) | None -- same three outcomes the real loop's
# local force_refresh/input_changed assignment produces
def _dispatch_gpu_click(col, row):
    for (sc, ec, er), (action, target) in list(mod_gpu._button_regions.items()):
        if row == er and sc <= col <= ec:
            if action == 'refresh':
                return 'refresh'
            if target not in mod_gpu._toggle_state:
                mod_gpu._fire_button(action, target)
                return (action, target)
            return None
    return None


# Replicate run_news_loop's exact inline button-region dispatch
def _dispatch_news_click(col, row):
    for (sc, ec, er), (action, target) in list(mod_news._button_regions.items()):
        if row == er and sc <= col <= ec:
            if action == 'refresh':
                return 'refresh'
            if not mod_news._is_running():
                mod_news._fire_pipeline()
                return 'run_pipeline'
            return None
    return None


# gpu pane: digit-key vs existing per-server button -- same action, same subprocess call, same
# _toggle_state entry (no new button needed for 1-9)
def test_gpu_digit_key_covered_by_existing_button():
    orig_names = mod_gpu.PRESET_NAMES
    mod_gpu.PRESET_NAMES = ['preset-a', 'preset-b']
    try:
        presets = [
            _make_preset('preset-a', running=False, healthy=False),
            _make_preset('preset-b', running=True, healthy=True, port=8001, pid=999),
        ]
        mod_gpu._toggle_state.clear()
        output = mod_gpu._render_pane(150, 30, presets, [], [], [], {}, [])
        regions = dict(mod_gpu._button_regions)

        preset_regions = {name: rect for rect, (action, name) in regions.items()
                           if name in ('preset-a', 'preset-b')}
        check("gpu: both preset rows have a button region", len(preset_regions) == 2)
        refresh_regions = {rect: v for rect, v in regions.items() if v == ('refresh', 'refresh')}
        check("gpu: preset button rows are disjoint from the [refresh] header row",
              all(rect[2] != next(iter(refresh_regions))[2] for rect in preset_regions.values()) if refresh_regions else False)

        for idx, (name, expect_action) in enumerate([('preset-a', 'start'), ('preset-b', 'stop')]):
            rect, (btn_action, btn_target) = next((r, v) for r, v in regions.items() if v[1] == name)
            check(f"gpu: registered button action for '{name}' is '{expect_action}'",
                  btn_action == expect_action)

            mod_gpu._toggle_state.clear()
            key_captured = _patch_popen(mod_gpu)
            mod_gpu._toggle_server(idx, presets)
            key_popen_calls = list(key_captured)
            key_toggle_state = dict(mod_gpu._toggle_state)

            mod_gpu._toggle_state.clear()
            click_captured = _patch_popen(mod_gpu)
            sc, ec, er = rect
            result = _dispatch_gpu_click((sc + ec) // 2, er)
            click_popen_calls = list(click_captured)
            click_toggle_state = dict(mod_gpu._toggle_state)

            check(f"gpu: click on '{name}' button dispatched (matched region, fired)",
                  result == (btn_action, name))
            check(f"gpu: click/digit-key parity for '{name}' -- same subprocess.Popen args",
                  key_popen_calls == click_popen_calls and len(key_popen_calls) == 1)
            check(f"gpu: click/digit-key parity for '{name}' -- same _toggle_state action label "
                  "(timestamps differ by real elapsed time between the two calls, not compared)",
                  name in key_toggle_state and name in click_toggle_state
                  and key_toggle_state[name][0] == click_toggle_state[name][0])
    finally:
        mod_gpu.PRESET_NAMES = orig_names
        mod_gpu._toggle_state.clear()


# gpu pane: new [refresh] header button -- region, dispatch, width guard
def test_gpu_refresh_button():
    orig_names = mod_gpu.PRESET_NAMES
    mod_gpu.PRESET_NAMES = ['preset-a']
    try:
        presets = [_make_preset('preset-a', running=False, healthy=False)]
        output = mod_gpu._render_pane(150, 30, presets, [], [], [], {}, [])
        regions = dict(mod_gpu._button_regions)
        refresh_entries = [(r, v) for r, v in regions.items() if v == ('refresh', 'refresh')]
        check("gpu: [refresh] button region registered", len(refresh_entries) == 1)
        check("gpu: [refresh] button on row 1", refresh_entries[0][0][2] == 1)
        check("gpu: [refresh] button text visible in header line",
              '[refresh]' in output.split('\n')[0])

        (sc, ec, er), _ = refresh_entries[0]
        result = _dispatch_gpu_click((sc + ec) // 2, er)
        check("gpu: click on [refresh] is recognized as the refresh action (same as 'r' key branch)",
              result == 'refresh')

        narrow_output = mod_gpu._render_pane(20, 30, presets, [], [], [], {}, [])
        narrow_regions = dict(mod_gpu._button_regions)
        check("gpu: width guard -- no [refresh] region when pane_width=20 (too narrow)",
              ('refresh', 'refresh') not in narrow_regions.values())
        check("gpu: width guard -- no [refresh] text in header when too narrow",
              '[refresh]' not in narrow_output.split('\n')[0])
    finally:
        mod_gpu.PRESET_NAMES = orig_names


# news pane: new [refresh] header button -- region, dispatch, width guard, no collision with
# [run pipeline]
def test_news_refresh_button():
    status = {'doc_count': 5, 'chunk_count': 50, 'last_run_ts': '2026-01-01 00:00:00'}
    output = mod_news._render_pane(120, 30, status, running=False)
    regions = dict(mod_news._button_regions)
    refresh_entries = [(r, v) for r, v in regions.items() if v == ('refresh', 'refresh')]
    run_entries = [(r, v) for r, v in regions.items() if v == ('run', 'pipeline')]
    check("news: [refresh] button region registered", len(refresh_entries) == 1)
    check("news: [run pipeline] button region still registered (unchanged)", len(run_entries) == 1)
    check("news: [refresh] and [run pipeline] rows are disjoint (no collision)",
          refresh_entries[0][0][2] != run_entries[0][0][2])
    check("news: [refresh] button text visible in header line", '[refresh]' in output.split('\n')[0])

    (sc, ec, er), _ = refresh_entries[0]
    result = _dispatch_news_click((sc + ec) // 2, er)
    check("news: click on [refresh] is recognized as the refresh action (same as 'r' key branch)",
          result == 'refresh')

    # Regression: [run pipeline] click still fires the pipeline (existing behavior unchanged)
    captured = _patch_popen(mod_news)
    mod_news._pipeline_proc = None
    (rsc, rec, rer), _ = run_entries[0]
    run_result = _dispatch_news_click((rsc + rec) // 2, rer)
    check("news: [run pipeline] click still fires the pipeline (regression)",
          run_result == 'run_pipeline' and len(captured) == 1)

    narrow_output = mod_news._render_pane(15, 30, status, running=False)
    narrow_regions = dict(mod_news._button_regions)
    check("news: width guard -- no [refresh] region when pane_width=15 (too narrow)",
          ('refresh', 'refresh') not in narrow_regions.values())
    check("news: width guard -- no [refresh] text in header when too narrow",
          '[refresh]' not in narrow_output.split('\n')[0])


# ORCHESTRATOR

def run_probe_workflow():
    print("=" * 70)
    print("gpu + news pane button probe")
    print("=" * 70)
    test_gpu_digit_key_covered_by_existing_button()
    test_gpu_refresh_button()
    test_news_refresh_button()

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
    out_path = md_dir / f"p4_gpu_news_button_probe_{stamp}.md"
    lines = [
        f"# P4 -- gpu + news pane button probe run ({datetime.now(timezone.utc).isoformat()})",
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
