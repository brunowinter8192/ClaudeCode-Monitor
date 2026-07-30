# INFRASTRUCTURE
from typing import Dict, Optional, Tuple

from ..constants import RESET, YELLOW, DIM, WHITE, PROXY_MESSAGES_KEEP_LAST
from .format import _is_standalone_entry
# From utils.py: strip ANSI codes to measure visible column offsets
from ..utils import _ANSI_ESCAPE_RE

# FUNCTIONS

# Build header line listing workers; populates regions_out with (start_col,end_col,phys_row)->name click targets
def _format_worker_proxy_header(workers: list, current_worker: Optional[str],
                                 pane_width: int = 80,
                                 regions_out: Optional[Dict[Tuple[int, int, int], str]] = None) -> str:
    label = f"{YELLOW}WORKER-PROXY{RESET}  "
    if regions_out is not None:
        regions_out.clear()
    if not workers:
        return label + f"{DIM}no workers{RESET}"
    parts = []
    visible_col = len(_ANSI_ESCAPE_RE.sub('', label))
    for i, w in enumerate(workers, 1):
        name = w['name']
        star = '*' if name == current_worker else ''
        marker = f"[{i}{star}]{name}" if name == current_worker else f"[{i}]{name}"
        color = WHITE if name == current_worker else DIM
        parts.append(f"{color}{marker}{RESET}")
        if regions_out is not None:
            start_row, start_col = divmod(visible_col, pane_width)
            end_row, end_col = divmod(visible_col + len(marker) - 1, pane_width)
            if start_row == end_row:
                regions_out[(start_col + 1, end_col + 1, start_row + 1)] = name
        visible_col += len(marker) + 2
    return label + '  '.join(parts)

# Extract entry_idx from any proxy line_map key variant (shared with pane.py pattern)
def _wp_entry_idx_from_key(key) -> Optional[int]:
    if isinstance(key, int):
        return key
    if isinstance(key, tuple):
        if isinstance(key[0], str):
            return key[1]
        if isinstance(key[0], int):
            return key[0]
    return None

# Walk backward from k-1 to find first non-standalone entry idx (prev_same reference)
def _resolve_prev_same_wp(entries: list, k: int) -> Optional[int]:
    for i in range(k - 1, -1, -1):
        if not _is_standalone_entry(entries[i]):
            return i
    return None

# Strip messages from all entries outside the keep-last window that are not expanded
def _strip_inactive_wp_messages(entries: list, expand_states: dict) -> None:
    cutoff = max(0, len(entries) - PROXY_MESSAGES_KEEP_LAST)
    for i in range(cutoff):
        e = entries[i]
        if e.get('messages') is None:
            continue
        is_active = (
            expand_states.get(i, False) or
            expand_states.get(('req', i), False) or
            expand_states.get((i, 'neg_delta'), False)
        )
        if not is_active:
            del e['messages']
