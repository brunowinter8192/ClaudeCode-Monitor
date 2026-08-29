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


# Find every block of the deduplicated timeline that contains term.
#
# One hit per (turn, block) — the block is the unit because a hit reports a block label, and a
# block holding the term N times stays ONE hit carrying count=N. Deduplication is structural,
# not a post-filter: the searched payload is the single last request, which already embeds the
# whole conversation, so a term is never re-reported per request that resent it.
def find_matches(payload: dict, term: str, case_sensitive: bool = False) -> tuple:
    needle = term if case_sensitive else term.lower()
    hits = []
    turns = set()
    hit_turns = set()
    blocks_searched = 0
    chars_searched = 0
    occurrences = 0

    for block in iter_block_texts(payload):
        text = block["text"]
        turns.add(block["turn"])
        blocks_searched += 1
        chars_searched += len(text)
        if not needle:
            continue
        haystack = text if case_sensitive else text.lower()
        count = haystack.count(needle)
        if not count:
            continue
        occurrences += count
        hit_turns.add(block["turn"])
        hits.append({
            "turn": block["turn"],
            "role": block["role"],
            "block": block["block"],
            "label": block["label"],
            "count": count,
            "snippet": _snippet(text, haystack.find(needle), len(needle)),
        })

    stats = {
        "turns": len(turns),
        "blocks": blocks_searched,
        "chars": chars_searched,
        "occurrences": occurrences,
        "hit_turns": len(hit_turns),
    }
    return hits, stats
