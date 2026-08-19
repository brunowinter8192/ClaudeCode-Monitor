# INFRASTRUCTURE
import fcntl
import os
import subprocess
import sys
from typing import Optional

# From ghostty.py: Ghostty terminal UUID lookup for click-to-focus
from .ghostty import get_ghostty_terminal_id, get_ghostty_terminal_id_for_tty
# From paths.py: APP_SUPPORT-relative PID lock file
from .paths import PID_FILE as _LOCK_PATH

_LAUNCHD_LABEL = 'com.brunowinter.monitor-cc-menubar'

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
