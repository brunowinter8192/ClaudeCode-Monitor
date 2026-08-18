# INFRASTRUCTURE
from typing import List

from ..utils import _ANSI_ESCAPE_RE
from ..format.token_format import _format_turn_header_line, _format_cache_call, _call_thinking_meta, _render_expanded_call_lines

# FUNCTIONS

# True when a call's own header line OR its FORCE-rendered expanded detail content (ignoring
# this call's own expand_states toggle — the whole point is to also find matches in currently-
# collapsed calls) contains query, case-insensitive. Uses the REAL render functions
# (_format_cache_call/_render_expanded_call_lines), not a duplicated serializer — guarantees
# "exactly what this call's expanded view shows" can never diverge from token_format.py.
def _call_matches_query(call: dict, request_num: int, wide: bool, response_rid_map: dict, q: str) -> bool:
    has_thinking, sig_chars = _call_thinking_meta(call)
    header = _format_cache_call(
        '▼', call.get('cache_read', 0), call.get('cache_creation', 0), call.get('direct', 0),
        call.get('output_tokens', 0), wide, request_num, has_thinking, sig_chars,
    )
    if q in _ANSI_ESCAPE_RE.sub('', header).lower():
        return True
    exp_lines, _keys = _render_expanded_call_lines(call, response_rid_map)
    return any(q in _ANSI_ESCAPE_RE.sub('', line).lower() for line in exp_lines)

# Build the ordered list of match keys whose content matches query (case-insensitive). A match
# key is either (turn_idx, call_idx) — found in that call's own header or force-expanded detail
# content — or ('turn', turn_idx) — found in the turn's own prompt/timestamp line (turns have
# no expand state, so there is nothing to force-expand there). Order: turn-idx ascending, and
# within a turn, the turn's own key (if it matches) before its calls' keys — mirrors the real
# render's top-to-bottom line order, so n/N steps through matches in the same order they'd be
# encountered while scrolling. No expand_states param (unlike proxy_display.search's
# build_search_matches) — calls have no nested sub-toggles to force-expand as-is, everything in
# a call's own detail block is unconditionally shown once the call itself is expanded.
def build_token_search_matches(query: str, turns: list, pane_width: int, response_rid_map: dict = None) -> List:
    if not query:
        return []
    q = query.lower()
    wide = pane_width >= 60
    matches = []
    request_num = 0
    for turn_idx, turn in enumerate(turns):
        turn_line = _format_turn_header_line(turn_idx, turn, pane_width)
        if q in _ANSI_ESCAPE_RE.sub('', turn_line).lower():
            matches.append(('turn', turn_idx))
        for call_idx, call in enumerate(turn.get('api_calls', [])):
            request_num += 1
            if _call_matches_query(call, request_num, wide, response_rid_map, q):
                matches.append((turn_idx, call_idx))
    return matches
