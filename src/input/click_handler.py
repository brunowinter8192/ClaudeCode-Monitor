# INFRASTRUCTURE
import os
import select
import subprocess
import sys
import termios
import time
import tty
from typing import Any, Dict, Optional, Tuple

_original_terminal_settings = None
_stdin_fd: int = -1

# ORCHESTRATOR
def setup_keyboard_input() -> bool:
    success = set_raw_stdin()
    return success

# FUNCTIONS

# Sets stdin to raw mode for reading keypresses
def set_raw_stdin() -> bool:
    global _original_terminal_settings, _stdin_fd
    try:
        _stdin_fd = sys.stdin.fileno()
        _original_terminal_settings = termios.tcgetattr(_stdin_fd)
        tty.setcbreak(_stdin_fd)
        return True
    except Exception:
        return False

# Restores original terminal settings
def restore_terminal() -> None:
    global _original_terminal_settings
    if _original_terminal_settings is not None:
        try:
            fd = sys.stdin.fileno()
            termios.tcsetattr(fd, termios.TCSADRAIN, _original_terminal_settings)
        except Exception:
            pass

# Blocks until stdin has bytes available or timeout expires; does not read
def wait_for_input(timeout: float) -> None:
    if _stdin_fd >= 0:
        select.select([_stdin_fd], [], [], timeout)
    else:
        time.sleep(timeout)

# Number of UTF-8 continuation bytes expected after this lead byte, per the bit pattern:
# 0xxxxxxx=ASCII(0), 110xxxxx=+1, 1110xxxx=+2, 11110xxx=+3. A stray continuation byte or
# invalid lead (e.g. 10xxxxxx alone) returns 0 — decoded alone via errors='replace', same as
# today's single-byte behavior; a real multi-byte lead always matches one of the first three.
def _utf8_continuation_count(lead_byte: int) -> int:
    if lead_byte & 0x80 == 0x00:
        return 0
    if lead_byte & 0xE0 == 0xC0:
        return 1
    if lead_byte & 0xF0 == 0xE0:
        return 2
    if lead_byte & 0xF8 == 0xF0:
        return 3
    return 0

# Reads one keypress from stdin fd without blocking (bypasses Python buffering). Reads the lead
# byte first (non-blocking select, unchanged fast path for "nothing pending" -> None), then — for
# a multi-byte UTF-8 lead byte — reads the expected continuation bytes (each via the SAME
# 0.005s-timeout select pattern read_mouse_event already uses for its own byte-wise ESC-sequence
# reads) and decodes the whole sequence together. Plain ASCII keys (the overwhelming majority)
# take 0 extra reads — byte-for-byte identical to the pre-fix code path. Without this, a
# multi-byte character (em-dash, ä/ö/ü, emoji) arrived as N separate invalid single-byte decodes,
# each replaced with U+FFFD ('�') — fixed 2026-08-18, see process-docs/pane_search/.
# A read error here propagates to the caller's own outer try/except (every pane loop wraps its
# drain loop in try/except Exception: log_pane_error(...)) rather than being swallowed silently.
def read_keypress() -> Optional[str]:
    if select.select([_stdin_fd], [], [], 0)[0]:
        data = os.read(_stdin_fd, 1)
        if not data:
            return None
        n_continuation = _utf8_continuation_count(data[0])
        for _ in range(n_continuation):
            if not select.select([_stdin_fd], [], [], 0.005)[0]:
                break
            more = os.read(_stdin_fd, 1)
            if not more:
                break
            data += more
        return data.decode('utf-8', errors='replace')
    return None

# Returns subagent index (1-9) if digit pressed, None otherwise
def parse_digit_key(char: str) -> Optional[int]:
    if char and char in '123456789':
        index = int(char)
        return index
    return None

# Gets agent_id by index from sorted metadata
def get_agent_by_index(index: int, subagent_metadata: Dict[str, dict]) -> Optional[str]:
    if not subagent_metadata:
        return None
    sorted_agents = sorted(subagent_metadata.items(), key=lambda x: x[1]['timestamp'])
    if 1 <= index <= len(sorted_agents):
        agent_id = sorted_agents[index - 1][0]
        return agent_id
    return None

# Enables SGR mouse reporting (all-motion events)
def enable_mouse() -> None:
    sys.stdout.write('\033[?1003h\033[?1006h')
    sys.stdout.flush()

# Disables SGR mouse reporting
def disable_mouse() -> None:
    sys.stdout.write('\033[?1003l\033[?1006l')
    sys.stdout.flush()

# Enables SGR mouse reporting (button clicks only, no motion/wheel — tmux handles scrolling)
def enable_mouse_clicks() -> None:
    sys.stdout.write('\033[?1000h\033[?1006h')
    sys.stdout.flush()

# Disables click-only mouse reporting
def disable_mouse_clicks() -> None:
    sys.stdout.write('\033[?1000l\033[?1006l')
    sys.stdout.flush()

# Walk backwards from hover_row to find nearest parent key in line_map; None if nothing found
def resolve_parent_key(line_map: Dict[int, Any], hover_row: Optional[int]) -> Any:
    if hover_row is None:
        return None
    for r in range(hover_row, 0, -1):
        k = line_map.get(r)
        if k is not None:
            return k
    return None

# Copy text to macOS clipboard via pbcopy
def copy_to_clipboard(text: str) -> None:
    subprocess.run(['pbcopy'], input=text, text=True, capture_output=True)

# Reads SGR mouse event after escape char; returns (button, col, row) for press/motion, None otherwise
def read_mouse_event(first_char: str) -> Optional[Tuple[int, int, int]]:
    if first_char != '\033':
        return None

    seq = ''
    terminator = None

    for _ in range(32):
        ready = select.select([_stdin_fd], [], [], 0.005)[0]
        if not ready:
            return None
        try:
            data = os.read(_stdin_fd, 1)
            if not data:
                return None
            ch = data.decode('utf-8', errors='replace')
        except Exception:
            return None
        if ch in ('M', 'm'):
            terminator = ch
            break
        seq += ch

    if terminator != 'M':
        # 'm' = SGR release event — return sentinel to distinguish from bare ESC (None)
        return (-1, -1, -1) if terminator == 'm' else None

    if not seq.startswith('[<'):
        return None

    try:
        parts = seq[2:].split(';')
        if len(parts) != 3:
            return None
        button = int(parts[0])
        col = int(parts[1])
        row = int(parts[2])
        return (button, col, row)
    except (ValueError, IndexError):
        return None
