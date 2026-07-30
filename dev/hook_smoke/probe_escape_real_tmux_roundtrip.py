# INFRASTRUCTURE
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# add src/ to path so menubar.focus_controller is importable without 'from src.' prefix
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
from menubar import focus_controller  # noqa: E402

_REPORT_DIR = Path(__file__).parent / 'md'
_SESSION = f'monitor-cc-escape-probe-{uuid.uuid4().hex[:8]}'

# Reads exactly one raw byte in cbreak mode (no line-buffering, no Enter needed) and prints its
# repr — proves the exact byte the pane received, independent of any VT100 escape-sequence
# interpretation the terminal itself might otherwise apply to a bare ESC.
_READER_SRC = (
    "import sys, tty, termios\n"
    "fd = sys.stdin.fileno()\n"
    "old = termios.tcgetattr(fd)\n"
    "try:\n"
    "    tty.setcbreak(fd)\n"
    "    c = sys.stdin.read(1)\n"
    "finally:\n"
    "    termios.tcsetattr(fd, termios.TCSADRAIN, old)\n"
    "print('GOT_BYTE:' + repr(c))\n"
)


# ORCHESTRATOR

# Create a throwaway tmux session running a one-byte stdin reader, send Escape through the real
# _send_escape_key (production send path), capture the pane before/after, write the report.
def probe_workflow() -> None:
    reader_path = Path(tempfile.gettempdir()) / f'{_SESSION}_reader.py'
    reader_path.write_text(_READER_SRC)
    # Single shell-string trailing arg (not a bare argv list) so tmux runs it via $SHELL -c and
    # keeps the pane alive after the reader exits — a bare execvp of `python3 <path>` let the
    # pane die before send-keys could reach it in an earlier version of this probe.
    subprocess.run(['tmux', 'new-session', '-d', '-s', _SESSION,
                     f'python3 {reader_path}; sleep 30'], check=True)
    try:
        time.sleep(0.5)   # let the reader enter cbreak mode
        exists_before = _has_session()
        before = _capture_pane()
        cmd_sent = ['tmux', 'send-keys', '-t', _SESSION, 'Escape']
        sent = focus_controller._send_escape_key(_SESSION)
        time.sleep(0.5)   # let the reader print + tmux render it
        after = _capture_pane()
        _write_report(exists_before, before, after, sent, cmd_sent)
    finally:
        subprocess.run(['tmux', 'kill-session', '-t', _SESSION], capture_output=True)
        reader_path.unlink(missing_ok=True)


# FUNCTIONS

def _has_session() -> bool:
    r = subprocess.run(['tmux', 'has-session', '-t', _SESSION], capture_output=True)
    return r.returncode == 0

def _capture_pane() -> str:
    r = subprocess.run(['tmux', 'capture-pane', '-p', '-t', _SESSION], capture_output=True, text=True)
    return r.stdout

# Render the round-trip result as a markdown report under md/
def _write_report(exists_before: bool, before: str, after: str, sent: bool, cmd_sent: list) -> None:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    out_path = _REPORT_DIR / f'{ts}_escape_real_tmux_roundtrip.md'
    arrived = "GOT_BYTE:'\\x1b'" in after
    lines = []
    lines.append('# Real tmux round-trip — Escape key via _send_escape_key\n')
    lines.append(f'Run: {datetime.now(timezone.utc).isoformat()}\n')
    lines.append(f'Session: `{_SESSION}`\n')
    lines.append(f'`tmux has-session` before send: **{exists_before}**\n')
    lines.append(f'Exact command sent by `_send_escape_key`: `{" ".join(cmd_sent)}`\n')
    lines.append(f'`_send_escape_key` return value: **{sent}**\n')
    lines.append('## Pane capture BEFORE Escape\n')
    lines.append('```')
    lines.append(before.rstrip('\n') or '(empty)')
    lines.append('```\n')
    lines.append('## Pane capture AFTER Escape\n')
    lines.append('```')
    lines.append(after.rstrip('\n') or '(empty)')
    lines.append('```\n')
    lines.append(f'## Result\n')
    lines.append(f'Escape byte (`\\x1b`) arrived at the reader process: **{arrived}**')
    lines.append('')
    out_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'exists_before={exists_before} sent={sent} arrived={arrived}')
    print(f'Report written: {out_path}')
    if not (exists_before and sent and arrived):
        sys.exit(1)


if __name__ == '__main__':
    probe_workflow()
