# INFRASTRUCTURE
from typing import List

from ..utils import _ANSI_ESCAPE_RE
from .format import _is_standalone_entry
from .render_turn import _render_req_expanded, _resolve_prev_same_family

# FUNCTIONS

# True when entry's expanded-view content (system/tools/messages/fields/beta/directives —
# "exactly what that request's expanded view shows") contains query, case-insensitive.
# Calls the REAL render function forced-expanded (regardless of the entry's own current
# expand_states toggle) so match determination can never diverge from what's actually
# displayed once the user expands it. Nested drill-down states (fields/beta/tools-desc) are
# left as-is — matching reflects exactly what's currently visible for those sub-toggles.
def _entry_matches_query(entry_idx: int, entries: list, expand_states: dict, pane_width: int, query: str) -> bool:
    entry = entries[entry_idx]
    is_standalone = _is_standalone_entry(entry)
    prev_same = _resolve_prev_same_family(entries, entry_idx)
    lines, _keys = _render_req_expanded(entry_idx, entry, entries, is_standalone, prev_same, expand_states, pane_width)
    q = query.lower()
    return any(q in _ANSI_ESCAPE_RE.sub('', line).lower() for line in lines)

# Build the ordered list of entry_idx whose expanded-view content matches query
# (case-insensitive). Requires entry['messages'] populated on every entry — caller runs a
# one-sweep reconstruction (forwarded_parser.reconstruct_all_messages) first.
# Cost: ~20ms / 190 entries measured on a real 6.8MB forwarded log (process-docs/pane_search/).
def build_search_matches(query: str, entries: list, expand_states: dict, pane_width: int) -> List[int]:
    if not query:
        return []
    return [
        entry_idx for entry_idx in range(len(entries))
        if _entry_matches_query(entry_idx, entries, expand_states, pane_width, query)
    ]
