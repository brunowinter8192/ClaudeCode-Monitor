#!/usr/bin/env python3
"""Unit tests for the per-project monitor button's pure/branch logic (src/menubar/system.py).

Covers: tmux session-name derivation is reused from tmux_launcher.py (never re-derived locally),
the kill-then-relaunch branch given check_session_exists (a click always ends in a fresh
_launch_monitor call; kill_session only fires when a stale session exists), the launch command
built for a cwd containing a space (quoting safety — a fixed shell string built via shlex.quote,
not raw interpolation), and python3 resolution actually reading the plist's Homebrew-first PATH
instead of falling back to a bare launchd-shaped os.environ, and that _launch_monitor uses the
native AppleScript path unconditionally — no Ghostty-version gate, no 'open -na Ghostty.app'
fallback (removed 2026-09-04; the fallback spawned a second Ghostty process instance that broke
click-to-focus for every other window). Does not exercise the actual Ghostty/osascript I/O (see
process-docs/menubar_per_project/ for the live launch verification this was paired with).

No AppKit/rumps import needed — src/menubar/system.py has no AppKit dependency (see its DOCS.md
Purpose line). importlib.import_module used for the src.menubar import, not `from src.` — see
src/hooks/block_dev_imports_src.py.

Run: python3 dev/menubar_per_project/test_open_or_focus_monitor.py
"""

# INFRASTRUCTURE
import importlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

_system_mod = importlib.import_module('src.menubar.system')
_tmux_launcher_mod = importlib.import_module('src.tmux_launcher')

# ORCHESTRATOR

def test_open_or_focus_monitor_workflow() -> None:
    failures = []
    _test_session_name_reused_not_rederived(failures)
    _test_launch_cmd_quotes_cwd_with_space(failures)
    _test_existing_session_killed_then_relaunched(failures)
    _test_branch_launches_when_session_absent(failures)
    _test_empty_cwd_is_noop(failures)
    _test_resolve_python3_uses_plist_path_under_bare_environ(failures)
    _test_launch_monitor_uses_native_path_only(failures)
    if failures:
        print(f"FAILED: {len(failures)} case(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")

# FUNCTIONS

# Print one PASS/FAIL line; append desc to failures on mismatch
def _check(failures: list, desc: str, ok: bool, detail: str) -> None:
    status = "OK  " if ok else "FAIL"
    print(f"  [{status}] {desc}: {detail}")
    if not ok:
        failures.append(desc)

# system.py must import generate_session_name/check_session_exists from tmux_launcher.py — the
# same object, never a locally re-derived hash function
def _test_session_name_reused_not_rederived(failures: list) -> None:
    cwd = '/tmp/some project'
    expected = _tmux_launcher_mod.generate_session_name(cwd)
    _check(failures, 'system.generate_session_name IS tmux_launcher.generate_session_name',
          _system_mod.generate_session_name is _tmux_launcher_mod.generate_session_name,
          f'{_system_mod.generate_session_name!r}')
    _check(failures, 'session name for a cwd with a space matches tmux_launcher exactly',
          _system_mod.generate_session_name(cwd) == expected,
          f'got={_system_mod.generate_session_name(cwd)!r} expected={expected!r}')
    _check(failures, 'session name has the monitor_cc_<8-hex> shape',
          expected.startswith('monitor_cc_') and len(expected) == len('monitor_cc_') + 8,
          f'name={expected!r}')

# A cwd with a space (and a shell metacharacter) must round-trip through shlex as ONE argument —
# proves the command is built via quoting, not raw interpolation
def _test_launch_cmd_quotes_cwd_with_space(failures: list) -> None:
    root = Path('/Users/x/monitor-cc')
    py3 = '/opt/homebrew/bin/python3'
    cwd = '/tmp/my project; rm -rf /'
    cmd = _system_mod._build_monitor_launch_cmd(root, py3, cwd)
    cd_part, run_part = cmd.split(' && ', 1)
    parsed = shlex.split(run_part)
    _check(failures, 'cd target is the given root, shell-quoted',
          cd_part == f'cd {shlex.quote(str(root))}', f'cd_part={cd_part!r}')
    _check(failures, 'cwd survives shlex round-trip as exactly one argument (not split/executed)',
          parsed == [py3, 'workflow.py', '--project', cwd], f'parsed={parsed!r}')

# Already-running session (check_session_exists → True) must be killed, then ALWAYS relaunched
# fresh — never a focus-only no-op (a stale session can outlive its Ghostty window)
def _test_existing_session_killed_then_relaunched(failures: list) -> None:
    calls = _run_open_or_focus_monitor_with_stubs(session_exists=True, cwd='/tmp/existing-project')
    expected_name = _tmux_launcher_mod.generate_session_name('/tmp/existing-project')
    _check(failures, 'existing session → kill_session called with the derived session name',
          calls['kill'] == expected_name, f'calls={calls!r}')
    _check(failures, 'existing session → _launch_monitor called with the row cwd afterwards',
          calls['launch'] == '/tmp/existing-project', f'calls={calls!r}')

# No running session (check_session_exists → False) must launch a new window, no kill needed
def _test_branch_launches_when_session_absent(failures: list) -> None:
    calls = _run_open_or_focus_monitor_with_stubs(session_exists=False, cwd='/tmp/new-project')
    _check(failures, 'no session → _launch_monitor called with the row cwd',
          calls['launch'] == '/tmp/new-project', f'calls={calls!r}')
    _check(failures, 'no session → kill_session NOT called',
          calls['kill'] is None, f'calls={calls!r}')

# Empty cwd (an unresolved _cwd_map entry) is a no-op — mirrors focusSession_/focusWorker_'s guard
def _test_empty_cwd_is_noop(failures: list) -> None:
    calls = _run_open_or_focus_monitor_with_stubs(session_exists=True, cwd='')
    _check(failures, 'empty cwd short-circuits before any tmux/kill/launch call',
          calls == {'checked': None, 'kill': None, 'launch': None}, f'calls={calls!r}')

# _resolve_launch_python3 must resolve the Homebrew python3 by reading the plist template's
# PATH — NOT this process's own os.environ, which under real launchd has no Homebrew (regression
# guard: the plist template is not valid XML on its own — plistlib.load raises on its
# unsubstituted <BUNDLE_LAUNCHER>/<PROJECT_ROOT> tags — an earlier version of this function
# silently swallowed that and fell back to os.environ, passing only by accident in a dev shell
# that already had Homebrew on PATH). Spawns a real subprocess with a bare launchd-shaped PATH
# (no Homebrew) to prove the plist read, not the ambient shell, is what resolves it.
def _test_resolve_python3_uses_plist_path_under_bare_environ(failures: list) -> None:
    bare_env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'}
    repo_root = Path(__file__).resolve().parent.parent.parent
    r = subprocess.run(
        [sys.executable, '-c',
         "import importlib; m = importlib.import_module('src.menubar.system'); "
         "print(m._resolve_launch_python3())"],
        cwd=str(repo_root), env=bare_env, capture_output=True, text=True, timeout=10)
    resolved = r.stdout.strip()
    _check(failures, 'python3 resolved under a bare (no-Homebrew) PATH is still the Homebrew one',
          resolved.startswith('/opt/homebrew/') or resolved.startswith('/usr/local/'),
          f'resolved={resolved!r} stderr={r.stderr.strip()!r}')

# Regression guard (2026-09-04): the 'ghostty +version' gate + 'open -na Ghostty.app' fallback
# were removed — the fallback spawns a SEPARATE Ghostty process instance, which then answers every
# 'tell application "Ghostty"' AppleScript call instead of the real one, losing click-to-focus for
# every other window. Asserts both symbols are gone AND that _launch_monitor calls the native
# path unconditionally (stubbed — no real osascript/Ghostty I/O).
def _test_launch_monitor_uses_native_path_only(failures: list) -> None:
    _check(failures, '_ghostty_version removed from system.py',
          not hasattr(_system_mod, '_ghostty_version'),
          f'hasattr={hasattr(_system_mod, "_ghostty_version")}')
    _check(failures, '_launch_monitor_ghostty_fallback removed from system.py',
          not hasattr(_system_mod, '_launch_monitor_ghostty_fallback'),
          f'hasattr={hasattr(_system_mod, "_launch_monitor_ghostty_fallback")}')

    class _FakeResult:
        returncode = 0
        stderr = ''

    calls = {'native': None}
    orig = _system_mod._launch_monitor_ghostty_native
    _system_mod._launch_monitor_ghostty_native = (
        lambda shell_cmd: calls.__setitem__('native', shell_cmd) or _FakeResult())
    try:
        _system_mod._launch_monitor('/tmp/native-path-project')
    finally:
        _system_mod._launch_monitor_ghostty_native = orig
    _check(failures, '_launch_monitor calls _launch_monitor_ghostty_native unconditionally',
          calls['native'] is not None and '/tmp/native-path-project' in calls['native'],
          f'calls={calls!r}')

# Monkeypatch check_session_exists/kill_session/_launch_monitor on the real module, call
# _open_or_focus_monitor(cwd), restore originals, return what was recorded
def _run_open_or_focus_monitor_with_stubs(session_exists: bool, cwd: str) -> dict:
    calls = {'checked': None, 'kill': None, 'launch': None}
    orig = (_system_mod.check_session_exists, _system_mod.kill_session, _system_mod._launch_monitor)
    _system_mod.check_session_exists = lambda name: calls.__setitem__('checked', name) or session_exists
    _system_mod.kill_session = lambda name: calls.__setitem__('kill', name)
    _system_mod._launch_monitor = lambda c: calls.__setitem__('launch', c)
    try:
        _system_mod._open_or_focus_monitor(cwd)
    finally:
        (_system_mod.check_session_exists, _system_mod.kill_session,
         _system_mod._launch_monitor) = orig
    return calls


if __name__ == '__main__':
    test_open_or_focus_monitor_workflow()
