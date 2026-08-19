# INFRASTRUCTURE
import fcntl
import os
import subprocess
import sys

# From ghostty.py: Ghostty terminal UUID lookup for click-to-focus
from .ghostty import get_ghostty_terminal_id
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
