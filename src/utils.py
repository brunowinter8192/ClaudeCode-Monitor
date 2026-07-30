# INFRASTRUCTURE
from datetime import datetime
import re
import unicodedata

# From constants.py: Unified color palette
from .constants import RESET, YELLOW, WORKER_COL_WIDTH

_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')

# Return terminal cell width of a single character (2 for wide/emoji, 1 otherwise)
def _cell_width(ch: str) -> int:
    cp = ord(ch)
    if 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF:
        return 2
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return 2
    return 1

# FUNCTIONS

# Convert ISO timestamp to HH:MM:SS local time
def format_timestamp(iso_timestamp: str) -> str:
    if not iso_timestamp:
        return '00:00:00'
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
        return dt.astimezone().strftime('%H:%M:%S')
    except ValueError:
        return '00:00:00'

# Return first meaningful word of a tool call for compact inline display
def first_word_of_call(tool_name: str, tool_call_input: dict) -> str:
    if not tool_call_input:
        return ''
    if tool_name == 'Bash':
        cmd = tool_call_input.get('command', '')
        parts = cmd.split()
        return parts[0] if parts else ''
    if tool_name == 'Grep':
        pat = tool_call_input.get('pattern', '')
        parts = pat.split()
        return parts[0] if parts else ''
    if tool_name in ('Glob', 'Read', 'Edit', 'Write'):
        key = 'pattern' if tool_name == 'Glob' else 'file_path'
        return tool_call_input.get(key, '')
    return ''

# Convert ISO8601 UTC timestamp string to epoch float for age comparison
def _iso_to_float(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0.0

# Format worker-name prefix column with constant visual width (WORKER_COL_WIDTH + 3 chars)
def format_worker_prefix(name: str) -> str:
    if not name:
        return ' ' * (WORKER_COL_WIDTH + 3)
    if len(name) > WORKER_COL_WIDTH:
        name = name[:WORKER_COL_WIDTH - 1] + '\u2026'
    return f'{YELLOW}W:{name:<{WORKER_COL_WIDTH}}{RESET} '

# Return number of terminal rows a logical line occupies after visual wrap
def visual_line_count(line: str, pane_width: int) -> int:
    visible = _ANSI_ESCAPE_RE.sub('', line)
    if not visible:
        return 1
    return max(1, (len(visible) + pane_width - 1) // pane_width)

# Right-align copy_sym at the pane edge (1 space + sym_cells reserved); unchanged if no room
def append_copy_symbol(line: str, copy_sym: str, pane_width: int) -> str:
    stripped = _ANSI_ESCAPE_RE.sub('', line)
    sym_cells = _cell_width(copy_sym)
    visible_len = sum(_cell_width(ch) for ch in stripped)
    pad = pane_width - 1 - sym_cells - visible_len
    if pad >= 0:
        return line + ' ' * pad + ' ' + copy_sym
    return line

# Compute (rule_len, show_button) for a "'═' rule + prefix_text + button" header line: the
# decorative rule shrinks first (down to rule_min) to make room for the button; the button is
# only dropped when even the title text (prefix_text) can't fit alongside it at rule_min
def compute_header_rule_len(prefix_text: str, btn_label: str, rule_cap: int, pane_width: int,
                             rule_min: int = 4, gap: int = 1) -> tuple:
    full_rule_len = min(pane_width, rule_cap)
    if full_rule_len + len(prefix_text) + gap + len(btn_label) <= pane_width:
        return full_rule_len, True
    shrunk = pane_width - len(prefix_text) - gap - len(btn_label)
    if shrunk >= rule_min:
        return shrunk, True
    return max(0, min(full_rule_len, pane_width - len(prefix_text))), False

# Truncate line to pane_width terminal cells (ANSI- and wide-char-aware); append … if cut
def truncate_visible(line: str, pane_width: int) -> str:
    if pane_width <= 0:
        return line
    stripped = _ANSI_ESCAPE_RE.sub('', line)
    if sum(_cell_width(ch) for ch in stripped) <= pane_width:
        return line
    budget = pane_width - 1  # reserve 1 cell for …
    width = 0
    i = 0
    while i < len(line):
        m = _ANSI_ESCAPE_RE.match(line, i)
        if m:
            i = m.end()
            continue
        cw = _cell_width(line[i])
        if width + cw > budget:
            break
        width += cw
        i += 1
    return line[:i] + '\u2026'
