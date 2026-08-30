# INFRASTRUCTURE
from .timeline import request_markers

# FUNCTIONS


# Char count as a short human string
def fmt_chars(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k"
    return str(count)


# Trim the trailing "Z"/offset noise off an ISO timestamp for column output
def fmt_timestamp(timestamp: str) -> str:
    return timestamp[:19].replace("T", " ") if timestamp else "?"


# One line per session, newest first
def render_sessions(sessions: list) -> str:
    if not sessions:
        return "no sessions found\n"
    context_width = max(len(s["context"]) for s in sessions)
    # SESSION is the last column — left unpadded so no line carries trailing whitespace
    lines = [f"{'START':19}  {'CONTEXT':{context_width}}  SESSION"]
    for session in sessions:
        lines.append(
            f"{fmt_timestamp(session['start']):19}  "
            f"{session['context']:{context_width}}  "
            f"{session['stem']}"
        )
    lines.append("")
    lines.append(f"{len(sessions)} sessions")
    return "\n".join(lines) + "\n"


# The group covering a msg index — the nearest one opening at or before it. None when the msg sits
# below every boundary, which happens only if the _forwarded stream does not reach back that far.
def _governing_marker(markers: dict, index: int):
    starts = [s for s in markers if s <= index]
    return markers[max(starts)] if starts else None


# One REQ separator: the request that opened this msg index, and when it was sent
def _req_separator(marker: dict) -> str:
    refires = marker["refires"]
    extra = ""
    if refires:
        extra = f"  (+{refires} re-fire{'s' if refires != 1 else ''})"
    return f"── REQ {marker['number']}  {_clock(marker['timestamp'])} ──{extra}"


# msgs: request groups — one REQ separator, then the msgs that request added. The msg line is
# `[idx] role type chars` and nothing else: no count line, no block sub-rows, no previews. Pane
# grammar: role clipped to 4 chars, and a multi-block msg shows its block COUNT instead of a type,
# because the aggregated type would name just one of the blocks it stands for. Chars carry the
# pane's `1,234c` spelling rather than fmt_chars' `1.2k`, since this view is for locating a msg by
# size, not for skimming magnitudes. The 6-wide chars column fits every value up to 99,999c; a
# wider one right-aligns past it and pushes its own line out by a character rather than truncating.
#
# A separator is emitted immediately before the first msg of its group that is actually PRINTED, so
# a group with no printed msgs (out of range, or trailing re-fires past the last msg) emits nothing.
# The FIRST printed msg is special: a FROM that lands mid-group would otherwise leave it with no
# separator at all, so it falls back to the group that GOVERNS it — the nearest one opening at or
# before it. A session whose _forwarded stream is missing or yields no boundaries prints no
# separators at all, which is exactly the pre-separator output.
def render_msgs(data: dict, start: int, end: int) -> str:
    markers = request_markers(data.get("boundaries") or [])
    lines = []
    for offset, msg in enumerate(data["turns"][start:end + 1]):
        marker = markers.get(msg["index"])
        if marker is None and offset == 0:
            marker = _governing_marker(markers, msg["index"])
        if marker is not None:
            lines.append(_req_separator(marker))
        blocks = msg["blocks"]
        label = blocks[0]["type"] if len(blocks) == 1 else f"{len(blocks)} blocks"
        chars = f"{msg['chars']:,}c"
        lines.append(f"[{msg['index']:3d}] {msg['role'][:4]:<4}  {label:<20}{chars:>6}")
    return "\n".join(lines) + "\n"


# Search result: header plus one line per matching block
# Search results across one or more sessions. results is [(session, hits), …] in listing order,
# already filtered to sessions that HAVE hits. The term line is printed once overall; each session
# then contributes its own "session <stem>" line plus its hit lines. skipped counts sessions whose
# timeline could not be loaded — reported only when non-zero, so a clean run stays clean.
def render_search(term: str, case_sensitive: bool, results: list, skipped: int = 0) -> str:
    mode = "case-sensitive" if case_sensitive else "case-insensitive"
    lines = [f'term      "{term}"  ({mode})', ""]
    if not results:
        lines.append("no match")
        return "\n".join(lines + _skipped_lines(skipped)) + "\n"
    # one width across ALL sessions, so hit lines stay aligned when several sessions are shown
    label_width = max(len(hit["label"]) for _session, hits in results for hit in hits)
    for session, hits in results:
        lines.append(f"session   {session['stem']}")
        for hit in hits:
            lines.append(
                f"#{hit['turn']:<4} {hit['role']:9} {hit['label']:{label_width}}  "
                f"×{hit['count']:<3} {hit['snippet']}"
            )
        lines.append("")
    return "\n".join(lines[:-1] + _skipped_lines(skipped)) + "\n"


# Trailing note about unreadable sessions; empty when nothing was skipped
def _skipped_lines(skipped: int) -> list:
    if not skipped:
        return []
    return ["", f"({skipped} session{'s' if skipped != 1 else ''} skipped — timeline could not be loaded)"]


# expand: the complete content of each selected msg in the window
def render_expand_full(data: dict, anchor: int, start: int, end: int,
                       only: str, dumped: list) -> str:
    msgs = data["turns"]
    times = data.get("turn_times", {})
    scope = (f"msgs {start}-{end} of 0-{len(msgs) - 1}, anchor #{anchor}, "
             f"{_window_date(data, anchor)}")
    lines = [
        f"session   {data['session']['stem']}",
        f"context   {data['session']['context']}",
        f"window    {scope}" + (f", only {only}" if only else ""),
        "",
    ]
    if not dumped:
        lines.append(f"no msg in the window matches --only {only}" if only else "window is empty")
        return "\n".join(lines) + "\n"
    for msg, blocks in dumped:
        marker = "▶" if msg["index"] == anchor else " "
        lines.append(
            f"{marker} ═══ msg #{msg['index']} {_clock(times.get(msg['index']))} "
            f"{msg['role']} {fmt_chars(msg['chars'])} chars, {len(blocks)} block(s) ═══"
        )
        for position, (label, chars, text) in enumerate(blocks):
            lines.append(f"── block {position}  {label}  {fmt_chars(chars)} chars ──")
            lines.append(text)
        lines.append("")
    return "\n".join(lines) + "\n"


# HH:MM:SS of the request that first carried a msg; "?" when it has no reliable time
def _clock(timestamp) -> str:
    return timestamp[11:19] if timestamp else "?"


# Calendar day for the window header — the anchor's own day, else the session's start day
def _window_date(data: dict, anchor: int) -> str:
    stamp = data.get("turn_times", {}).get(anchor) or data["session"].get("start", "")
    return stamp[:10] if stamp else "?"
