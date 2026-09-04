# INFRASTRUCTURE
import fcntl
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# From ghostty.py: Ghostty terminal UUID lookup for click-to-focus
from .ghostty import get_ghostty_terminal_id, get_ghostty_terminal_id_for_tty
# From paths.py: APP_SUPPORT-relative PID lock file + Monitor_CC checkout root
from .paths import PID_FILE as _LOCK_PATH, MONITOR_CC_ROOT
# From tmux_launcher.py: canonical tmux session-name derivation for a project cwd — the
# per-project monitor button must resolve the SAME session a manually-run
# 'python3 workflow.py --project <cwd>' would create; never re-derive the hash locally.
# kill_session backs the monitor button's kill-then-relaunch flow (a stale session whose Ghostty
# window was closed must not be a silent no-op — see _open_or_focus_monitor).
from ..tmux_launcher import generate_session_name, check_session_exists, kill_session

_LAUNCHD_LABEL = 'com.brunowinter.monitor-cc-menubar'
_PLIST_PATH = Path(__file__).resolve().parent / f'{_LAUNCHD_LABEL}.plist'   # PATH source for _resolve_launch_python3

# ORCHESTRATOR

# Entry point: set LSUIElement env (no Dock icon), acquire singleton lock, create app, start run loop
def run() -> None:
    os.environ.setdefault('LSUIElement', '1')
    _lock_fh = _acquire_singleton_lock()
    if _lock_fh is None:
        print('Another menubar instance is already running, exiting.', file=sys.stderr)
        sys.exit(0)   # exit 0 — launchd KeepAlive only respawns on non-zero exit
    from .app import CCMenuBarApp  # lazy — breaks app→system→app circular import
    app = CCMenuBarApp()
    app.run()

# FUNCTIONS

# Acquire exclusive fcntl lock on PID_FILE (APP_SUPPORT/menubar.pid); returns open file handle on success, None if locked
# Caller must keep the file handle alive (do not close/GC) — fcntl locks are released when the fd is closed
def _acquire_singleton_lock():
    fh = open(_LOCK_PATH, 'w')
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fcntl.fcntl(fh, fcntl.F_SETFD, fcntl.FD_CLOEXEC)   # auto-release on os.execv restart
    fh.write(str(os.getpid()))
    fh.flush()
    return fh

# Focus Ghostty terminal for cwd; prefers UUID-based focus, falls back to cwd-match
def _focus_session(cwd: str) -> None:
    import datetime
    import time
    from .menubar_log import log_menubar
    _t0 = time.monotonic()
    term_id = get_ghostty_terminal_id(cwd)
    lookup_ms = (time.monotonic() - _t0) * 1000
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if term_id:
        safe_id = term_id.replace('"', '\\"')
        script = (
            'tell application "Ghostty"\n'
            f'  focus terminal id "{safe_id}"\n'
            'end tell'
        )
        label = f'id={term_id}'
    else:
        safe_cwd = cwd.replace('"', '\\"')
        script = (
            'tell application "Ghostty"\n'
            '  try\n'
            f'    focus (first terminal whose working directory is "{safe_cwd}")\n'
            '    return "MATCH"\n'
            '  on error errMsg number errNum\n'
            '    return "MISS:" & errNum & ":" & errMsg\n'
            '  end try\n'
            'end tell'
        )
        label = f'cwd={cwd}'
    _t1 = time.monotonic()
    try:
        r = subprocess.run(['osascript', '-e', script], capture_output=True, timeout=3)
        osascript_ms = (time.monotonic() - _t1) * 1000
        out = r.stdout.decode(errors='replace').strip()
        if r.returncode != 0:
            msg = f'{ts} ERR rc={r.returncode} {label} stderr={r.stderr.decode(errors="replace").strip()} lookup_ms={lookup_ms:.1f} osascript_ms={osascript_ms:.1f}\n'
        elif out.startswith('MISS:'):
            msg = f'{ts} MISS {label} reason={out[5:]} lookup_ms={lookup_ms:.1f} osascript_ms={osascript_ms:.1f}\n'
        else:
            msg = f'{ts} OK {label} lookup_ms={lookup_ms:.1f} osascript_ms={osascript_ms:.1f}\n'
    except subprocess.TimeoutExpired:
        osascript_ms = (time.monotonic() - _t1) * 1000
        msg = f'{ts} TIMEOUT {label} lookup_ms={lookup_ms:.1f} osascript_ms={osascript_ms:.1f}\n'
    with open('/tmp/monitor-cc-menubar_focus.log', 'a') as fh:
        fh.write(msg)
    log_menubar('latency', f'focus lookup_ms={lookup_ms:.1f} osascript_ms={osascript_ms:.1f} {label}')

# Find the tty of the 'tmux attach'/'tmux attach-session' client for tmux_session_name, via one
# ps scan; exact match on the '-t' argument (not substring — 'worker-x' must not match
# 'worker-x-extended'). Returns None if no such client is currently running (viewer window closed).
def _find_worker_viewer_tty(tmux_session_name: str) -> Optional[str]:
    try:
        r = subprocess.run(['ps', '-A', '-o', 'pid=,tty=,args='],
                            capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=3)
    except Exception:
        return None
    for line in r.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        _pid, tty, args = parts
        if tty == '??':
            continue
        tokens = args.split()
        if len(tokens) < 3 or tokens[0] != 'tmux' or tokens[1] not in ('attach', 'attach-session'):
            continue
        if '-t' not in tokens:
            continue
        t_idx = tokens.index('-t')
        if t_idx + 1 < len(tokens) and tokens[t_idx + 1] == tmux_session_name:
            return tty
    return None

# Focus the Ghostty viewer window for a worker's tmux session ('tmux attach -t <session>').
# NO-OP (one log_menubar line stating why) when no attach client is currently running for this
# session (viewer window closed — user decision: deliberately does nothing, no fallback) or its
# tty isn't yet mapped in ghostty.py's OSC2 probe cache. No 'activate' in the AppleScript (see
# process-docs/ghostty_foreground/ — app-level activate brings Ghostty forward on EVERY space).
def _focus_worker(tmux_session_name: str) -> None:
    import time
    from .menubar_log import log_menubar
    _t0 = time.monotonic()
    tty = _find_worker_viewer_tty(tmux_session_name)
    lookup_ms = (time.monotonic() - _t0) * 1000
    if tty is None:
        log_menubar('latency', f'focus_worker session={tmux_session_name} lookup_ms={lookup_ms:.1f} '
                                f'NO-OP reason=no_attach_client')
        return
    term_id = get_ghostty_terminal_id_for_tty(tty)
    if term_id is None:
        log_menubar('latency', f'focus_worker session={tmux_session_name} tty={tty} lookup_ms={lookup_ms:.1f} '
                                f'NO-OP reason=tty_unmapped')
        return
    safe_id = term_id.replace('"', '\\"')
    script = (
        'tell application "Ghostty"\n'
        f'  focus terminal id "{safe_id}"\n'
        'end tell'
    )
    _t1 = time.monotonic()
    try:
        subprocess.run(['osascript', '-e', script], capture_output=True, text=True,
                        encoding='utf-8', errors='replace', timeout=3)
    except subprocess.TimeoutExpired:
        pass
    osascript_ms = (time.monotonic() - _t1) * 1000
    log_menubar('latency', f'focus_worker session={tmux_session_name} lookup_ms={lookup_ms:.1f} '
                            f'osascript_ms={osascript_ms:.1f} id={term_id}')

# Resolve the python3 binary the same way the launchd-managed menubar's shell would: read
# EnvironmentVariables/PATH from the plist TEMPLATE (com.brunowinter.monitor-cc-menubar.plist —
# the Homebrew-first PATH launchd installs, not this process's own os.environ, which under
# launchd lacks Homebrew — see paths.py/DOCS.md "launchd PATH inheritance") and resolve 'python3'
# against it. The template is NOT valid XML on its own (it carries unsubstituted <BUNDLE_LAUNCHER>/
# <PROJECT_ROOT> placeholder tags — real values are only filled in by setup_menubar.py's plain-text
# .replace() at install time, into a COPY under ~/Library/LaunchAgents/) — plistlib.load would
# raise on the template every time, so PATH is pulled out with a plain regex on the raw text
# instead. Falls back to the running process's own PATH, then the bare command name, if the
# template is unreadable/PATH-less — never raises.
_PLIST_PATH_KEY_RE = re.compile(
    r'<key>\s*PATH\s*</key>\s*<string>([^<]*)</string>', re.DOTALL)

def _resolve_launch_python3() -> str:
    try:
        content = _PLIST_PATH.read_text(encoding='utf-8')
        m = _PLIST_PATH_KEY_RE.search(content)
        path_value = m.group(1).strip() if m else None
    except Exception:
        path_value = None
    if not path_value:
        path_value = os.environ.get('PATH', '')
    return shutil.which('python3', path=path_value) or 'python3'

# Build the fixed shell command line for the monitor launch window: 'cd <root> && <python3>
# workflow.py --project <cwd>' — the same command the user runs by hand today. root and cwd are
# individually shell-quoted (shlex.quote) so a cwd containing spaces or shell metacharacters
# cannot break the command or inject anything; python3_path is quoted for the same reason
# (Homebrew prefixes are safe today, but the resolution is dynamic).
def _build_monitor_launch_cmd(root: Path, python3_path: str, cwd: str) -> str:
    return (f'cd {shlex.quote(str(root))} && '
            f'{shlex.quote(python3_path)} workflow.py --project {shlex.quote(cwd)}')

# Escape a string for embedding inside a double-quoted AppleScript string literal
def _applescript_quote(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

# Open a NEW Ghostty window running shell_cmd in the foreground via native AppleScript (PR
# #11208, Ghostty 1.3+ — ported from the iterative-dev plugin's tmux_spawn.sh:open_tmux_viewer).
# The ONLY launch path (2026-09-04: the 'open -na Ghostty.app' fallback this used to gate to was
# removed — see _launch_monitor's docstring). '; exit' after shell_cmd: once the launched process
# returns (tmux session detached/killed), the shell exits and the window closes — same shape as
# the worker-viewer window, and the mechanism that keeps 'closing the window detaches the tmux
# session' true for this button too.
def _launch_monitor_ghostty_native(shell_cmd: str):
    script = (
        'tell application "Ghostty"\n'
        '  activate\n'
        '  set win to new window\n'
        '  set t to terminal 1 of selected tab of win\n'
        f'  input text {_applescript_quote(shell_cmd + "; exit")} to t\n'
        '  send key "enter" to t\n'
        'end tell'
    )
    return subprocess.run(['osascript', '-e', script], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=10)

# Open a new Ghostty window that launches the monitor for cwd ('cd <root> && python3
# workflow.py --project <cwd>', the exact command a user runs by hand — see
# _build_monitor_launch_cmd). ALWAYS uses the native AppleScript path (_launch_monitor_ghostty_
# native), unconditionally — no Ghostty-version gate, no 'open -na Ghostty.app' fallback.
# 2026-09-04 removal: the fallback used to fire whenever 'ghostty +version' failed to resolve
# (the CLI binary lives only under /Applications/Ghostty.app/Contents/MacOS, never on the
# menubar's launchd PATH, so the version lookup always failed in production and the fallback
# ALWAYS fired there). 'open -na Ghostty.app' spawns a brand-new, SEPARATE Ghostty process
# instance — observed live 2026-09-04: from then on every 'tell application "Ghostty"' AppleScript
# call (desktop_detection.py, ghostty.py's tty→UUID probe, _focus_session/_focus_worker) answered
# from that second instance instead of the real one, losing every other window's click-to-focus.
# A failing osascript now stays a logged 'launch FAILED' line — a tripwire, not a fallback.
def _launch_monitor(cwd: str) -> None:
    from .menubar_log import log_menubar
    python3_path = _resolve_launch_python3()
    shell_cmd = _build_monitor_launch_cmd(MONITOR_CC_ROOT, python3_path, cwd)
    r = _launch_monitor_ghostty_native(shell_cmd)
    if r.returncode != 0:
        log_menubar('monitor', f'launch FAILED cwd={cwd} rc={r.returncode} '
                                f'stderr={r.stderr.strip()}')
    else:
        log_menubar('monitor', f'launch OK cwd={cwd}')

# Click handler for the panel's per-project monitor button (app.py:_PanelController.openMonitor_).
# Session name comes from tmux_launcher.py:generate_session_name — the SAME derivation
# 'python3 workflow.py --project <cwd>' uses internally, never re-derived here. ALWAYS ends in a
# fresh monitor in a new Ghostty window: the inherited worker-viewer 'focus, or no-op if the
# window is already closed' behavior (_focus_worker) is deliberately NOT reused here — a
# monitor_cc_<hash> session can outlive its Ghostty window (window closed, tmux session left
# running headless), and a click must never be a silent no-op for this button. If the session
# already exists it is killed first (tmux_launcher.py:kill_session), then _launch_monitor(cwd)
# opens the new window unconditionally.
def _open_or_focus_monitor(cwd: str) -> None:
    if not cwd:
        return
    session_name = generate_session_name(cwd)
    if check_session_exists(session_name):
        kill_session(session_name)
    _launch_monitor(cwd)
