# INFRASTRUCTURE
from .timeline import boundaries_by_index

# FUNCTIONS


# Byte count as a short human string
def fmt_bytes(size: int) -> str:
    for unit, factor in (("G", 1 << 30), ("M", 1 << 20), ("K", 1 << 10)):
        if size >= factor:
            return f"{size / factor:.1f}{unit}"
    return f"{size}B"


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


# Header block for a timeline
def _timeline_header(data: dict) -> list:
    session = data["session"]
    entry = data["entry"]
    boundaries = data["boundaries"]
    restarts = [b for b in boundaries if b["restart"]]
    lines = [
        f"session   {session['stem']}",
        f"context   {session['context']}   family {data['family']}   model {entry.get('model', '?')}",
        f"requests  {session['requests']} total, {len(boundaries)} on {data['family']} "
        f"({data['haiku_lines_skipped']} trailing non-conversation lines skipped)",
        f"source    last {data['family']} request of _original, {fmt_bytes(data['line_bytes'])}, "
        f"{fmt_timestamp(entry.get('timestamp', ''))}",
        f"turns     {len(data['turns'])} messages, {fmt_chars(sum(t['chars'] for t in data['turns']))} chars",
    ]
    if restarts:
        first = restarts[0]["request_no"]
        lines.append(
            f"WARNING   message count regressed at request {first} (CC restart within this log id) — "
            "request markers before it do not align with the final message list"
        )
    lines.append("")
    return lines


# Marker line for the requests that open at one message index. Several requests share an index
# when a request added no message (re-fire) or when a restart reset the index to 0 — a range is
# only printed when the request numbers really are consecutive.
def _boundary_line(group: list) -> str:
    first, last = group[0], group[-1]
    stamp = fmt_timestamp(first["timestamp"])
    if len(group) == 1:
        return f"── REQ {first['request_no']}  {stamp}  msgs {first['message_count']} ──"
    numbers = [b["request_no"] for b in group]
    consecutive = last["request_no"] - first["request_no"] == len(group) - 1
    label = f"{first['request_no']}-{last['request_no']}" if consecutive else ",".join(str(n) for n in numbers[:6])
    if not consecutive and len(numbers) > 6:
        label += f",+{len(numbers) - 6}"
    return (
        f"── REQ {label}  {stamp}  msgs {last['message_count']}  "
        f"({len(group)} requests, no new messages) ──"
    )


# Deduplicated turn timeline: request markers plus one line per turn and per block
def render_timeline(data: dict) -> str:
    lines = _timeline_header(data)
    grouped = boundaries_by_index(data["boundaries"])
    turn_count = len(data["turns"])
    for turn in data["turns"]:
        opening = grouped.get(turn["index"])
        if opening:
            lines.append(_boundary_line(opening))
        lines.append(
            f"#{turn['index']:<4} {turn['role']:9} {turn['type']:16} "
            f"{fmt_chars(turn['chars']):>7}  {len(turn['blocks'])} block(s)"
        )
        for block in turn["blocks"]:
            size = fmt_chars(block["chars"])
            if block["type"] == "thinking" and block.get("sig_chars"):
                size = f"{size}+sig{fmt_chars(block['sig_chars'])}"
            lines.append(f"      {block['label']:16} {size:>10}  {block['preview']}")
    for index in sorted(k for k in grouped if k >= turn_count):
        lines.append(_boundary_line(grouped[index]))
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


# Full content of one turn, block by block
def render_turn_full(data: dict, turn_index: int, blocks: list) -> str:
    if not blocks:
        return f"turn {turn_index} out of range (0..{len(data['turns']) - 1})\n"
    turn = data["turns"][turn_index]
    lines = [
        f"session   {data['session']['stem']}",
        f"turn      #{turn_index}  {turn['role']}  {turn['type']}  {fmt_chars(turn['chars'])} chars, "
        f"{len(blocks)} block(s)",
        "",
    ]
    for position, (label, chars, text) in enumerate(blocks):
        lines.append(f"── block {position}  {label}  {fmt_chars(chars)} chars ──")
        lines.append(text)
        lines.append("")
    return "\n".join(lines) + "\n"
