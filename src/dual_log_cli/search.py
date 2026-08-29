# INFRASTRUCTURE
from .timeline import iter_block_texts

SNIPPET_RADIUS = 55

# FUNCTIONS


# Context around one match: raw slice, whitespace-collapsed, ellipsis where it was cut
def _snippet(text: str, start: int, length: int) -> str:
    begin = max(0, start - SNIPPET_RADIUS)
    end = min(len(text), start + length + SNIPPET_RADIUS)
    fragment = " ".join(text[begin:end].split())
    return ("…" if begin > 0 else "") + fragment + ("…" if end < len(text) else "")


# Find every block of the deduplicated timeline that contains term; returns the hit list.
#
# One hit per (turn, block) — the block is the unit because a hit reports a block label, and a
# block holding the term N times stays ONE hit carrying count=N. Deduplication is structural,
# not a post-filter: the searched payload is the single last request, which already embeds the
# whole conversation, so a term is never re-reported per request that resent it.
# An empty term matches nothing rather than every block (str.count("") counts positions).
def find_matches(payload: dict, term: str, case_sensitive: bool = False) -> list:
    needle = term if case_sensitive else term.lower()
    if not needle:
        return []
    hits = []
    for block in iter_block_texts(payload):
        text = block["text"]
        haystack = text if case_sensitive else text.lower()
        count = haystack.count(needle)
        if not count:
            continue
        hits.append({
            "turn": block["turn"],
            "role": block["role"],
            "block": block["block"],
            "label": block["label"],
            "count": count,
            "snippet": _snippet(text, haystack.find(needle), len(needle)),
        })
    return hits
