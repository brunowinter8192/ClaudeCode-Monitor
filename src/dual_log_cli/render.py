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


# Fixed columns of the `[idx] role type chars` msg line — reused to keep a block sub-line's chars
# figure right-aligned to the same column the parent line uses.
_MSG_PREFIX_WIDTH = 12  # "[idx] role  "
_MSG_LABEL_WIDTH = 20
_MSG_CHARS_WIDTH = 6
_BLOCK_INDENT = "        "  # 8 spaces — never matches `^[`, so `grep '^\['` keeps selecting msg lines only
_BLOCK_LABEL_WIDTH = _MSG_PREFIX_WIDTH + _MSG_LABEL_WIDTH - len(_BLOCK_INDENT)


# msgs: request groups — one REQ separator, then the msgs that request added. The msg line is
# `[idx] role type chars`, and a single-block msg gets nothing further. A multi-block msg shows its
# block COUNT in place of a type — the aggregated type would name just one of the blocks it stands
# for — and is followed by one indented sub-line per block: its label (already carrying the tool
# name or the `!err` marker via `timeline._block_label`) and its own char count, right-aligned to
# the same column the parent line's chars use. That is what makes the count legible: a 3,862c msg
# that is 2,451c thinking and 1,129c Bash input reads very differently from one that is mostly tool
# output. Pane grammar: role clipped to 4 chars. Chars carry the pane's `1,234c` spelling rather
# than fmt_chars' `1.2k`, since this view is for locating a msg by size, not for skimming
# magnitudes. The 6-wide chars column fits every value up to 99,999c; a wider one right-aligns past
# it and pushes its own line out by a character rather than truncating.
#
# A separator is emitted immediately before the first msg of its group that is actually PRINTED, so
# a group with no printed msgs (out of range, or trailing re-fires past the last msg) emits nothing.
# The FIRST printed msg is special: a FROM that lands mid-group would otherwise leave it with no
# separator at all, so it falls back to the group that GOVERNS it — the nearest one opening at or
# before it. A session whose _forwarded stream is missing or yields no boundaries prints no
# separators at all, which is exactly the pre-separator output.
#
# Directly under a separator, `_req_delta_lines` lists the system blocks and tools that request's
# `system_delta`/`tools_delta` named (`timeline.request_boundaries`, computed against the previous
# request of the same model family) — the prompt-cache prefix a rebuild most often traces back to.
# The family's first request lists every sys/tool block, no tag; a later request lists only what
# changed or is new, tagged accordingly, and prints no sys/tool lines at all when nothing did. The
# per-request billing header (system index 0) is excluded from that comparison on every request but
# the first — it changes on every request by construction and never invalidates the cache (see
# process-docs/cache/). A re-fire group shows only the OWNER boundary's lines, matching the
# timestamp and usage the separator itself carries.
#
# usage_by_flow is {flow_id: (cache_read, cache_creation)} from usage.build_usage_by_flow, keyed
# on the group owner's flow_id; a group whose flow_id is absent (usage unresolved, or no usage
# joined for the session at all) prints the separator without CR/CC — never a placeholder.
#
# overlay is {(msg_idx, blk_idx): {stripped, injected, req}} from overlay.build_overlay — the SAME
# dict `expand` uses, now also read here. A block with neither stripped nor injected text appends
# nothing, which is what keeps an untouched line byte-identical to the pre-overlay output; a
# transformed one appends "  −N +M → Wc" (chars stripped, chars injected, resulting wire size),
# plus " by REQ n" when the request that performed the transform differs from the group's own —
# the `expand` case where a msg arrives under one REQ and is overwritten by a later one.
def render_msgs(data: dict, start: int, end: int, usage_by_flow: dict = None,
                overlay: dict = None) -> str:
    markers = request_markers(data.get("boundaries") or [])
    lines = []
    group_req = None
    for offset, msg in enumerate(data["turns"][start:end + 1]):
        marker = markers.get(msg["index"])
        if marker is None and offset == 0:
            marker = _governing_marker(markers, msg["index"])
        if marker is not None:
            lines.append(_req_separator(marker, usage_by_flow))
            lines.extend(_req_delta_lines(marker))
            group_req = marker["number"]
        blocks = msg["blocks"]
        label = blocks[0]["type"] if len(blocks) == 1 else f"{len(blocks)} blocks"
        chars_value = msg["chars"]
        chars = f"{chars_value:,}c"
        tail = _msg_delta_tail(msg["index"], blocks, chars_value, overlay, group_req)
        lines.append(f"[{msg['index']:3d}] {msg['role'][:4]:<4}  {label:<{_MSG_LABEL_WIDTH}}{chars:>{_MSG_CHARS_WIDTH}}{tail}")
        if len(blocks) > 1:
            lines.extend(_block_sub_lines(msg["index"], blocks, overlay, group_req))
    return "\n".join(lines) + "\n"


# The separator's sys/tool lines — one indented line per system block / tool the OWNING request's
# system_delta/tools_delta named (timeline.request_boundaries computes these per boundary; a
# marker carries its owner's copy). Empty for a request with no such delta at all — the billing
# header (sys[0]) excluded on every request but the first is what makes that the common case. Same
# indent/column layout as a block sub-line, tagged "  changed"/"  new" for anything but the
# family's first request, which carries no tag at all. A tool item can also carry `chars is None`
# ("removed" — the name-based tool comparison's tag for a tool no longer present at all): that item
# skips the chars column entirely rather than printing a size for content that no longer exists.
def _req_delta_lines(marker: dict) -> list:
    lines = []
    for item in (marker.get("sys_lines") or []) + (marker.get("tool_lines") or []):
        label = f"{item['label']:<{_BLOCK_LABEL_WIDTH}}"
        if item.get("chars") is None:
            lines.append(f"{_BLOCK_INDENT}{label}  {item['tag']}")
            continue
        chars = f"{item['chars']:,}c"
        tail = f"  {item['tag']}" if item.get("tag") else ""
        lines.append(f"{_BLOCK_INDENT}{label}{chars:>{_MSG_CHARS_WIDTH}}{tail}")
    return lines


# One indented sub-line per block of a multi-block msg — label and chars, plus the block's own
# strip/inject delta when the overlay touched it, no previews
def _block_sub_lines(msg_index: int, blocks: list, overlay: dict, group_req) -> list:
    lines = []
    for blk_index, block in enumerate(blocks):
        chars_value = block["chars"]
        chars = f"{chars_value:,}c"
        totals = _block_overlay_totals(overlay, msg_index, blk_index)
        if totals:
            stripped_chars, injected_chars, req = totals
            tail = _delta_tail(stripped_chars, injected_chars, chars_value, req, group_req)
        else:
            tail = ""
        lines.append(f"{_BLOCK_INDENT}{block['label']:<{_BLOCK_LABEL_WIDTH}}{chars:>{_MSG_CHARS_WIDTH}}{tail}")
    return lines


# The msg-level delta tail: the SUM of stripped/injected chars over every block the overlay
# touched, measured against the msg's own printed chars value (so the arithmetic on that one line
# is self-consistent regardless of how msg-level chars relate to the sum of block chars
# elsewhere). "" when no block of this msg was touched at all.
#
# "by REQ" is added only when every touched block shares the SAME request — a msg split across
# two transforming requests has never been observed in the corpus (measured: 0 of 1949 transformed
# msgs), and summarizing an ambiguous case with one REQ number would be a guess, so it is omitted
# instead; the per-block sub-lines still carry it individually.
def _msg_delta_tail(msg_index: int, blocks: list, chars_value: int, overlay: dict, group_req) -> str:
    total_stripped = 0
    total_injected = 0
    reqs = set()
    touched = False
    for blk_index in range(len(blocks)):
        totals = _block_overlay_totals(overlay, msg_index, blk_index)
        if totals is None:
            continue
        touched = True
        stripped_chars, injected_chars, req = totals
        total_stripped += stripped_chars
        total_injected += injected_chars
        if req is not None:
            reqs.add(req)
    if not touched:
        return ""
    req = next(iter(reqs)) if len(reqs) == 1 else None
    return _delta_tail(total_stripped, total_injected, chars_value, req, group_req)


# One block's overlay totals as (stripped_chars, injected_chars, req), or None when the overlay
# has nothing for this coordinate or recorded zero chars on both sides (a strip/inject slot with
# only empty strings, which build_overlay's own _texts already filters out, but zero is treated as
# untouched here too rather than trusted blindly).
def _block_overlay_totals(overlay: dict, msg_index: int, blk_index: int):
    slot = (overlay or {}).get((msg_index, blk_index))
    if not slot:
        return None
    stripped_chars = sum(len(t) for t in slot.get("stripped") or [])
    injected_chars = sum(len(t) for t in slot.get("injected") or [])
    if not stripped_chars and not injected_chars:
        return None
    return stripped_chars, injected_chars, slot.get("req")


# "  −N +M → Wc" appended after a chars column — N/M/W digit-grouped like every other chars figure
# in `msgs`, the real minus sign (U+2212) rather than a hyphen, and W computed as
# chars − stripped + injected. " by REQ n" only when that request differs from the group's own.
def _delta_tail(stripped_chars: int, injected_chars: int, chars_value: int, req, group_req) -> str:
    wire_chars = chars_value - stripped_chars + injected_chars
    tail = f"  −{stripped_chars:,} +{injected_chars:,} → {wire_chars:,}c"
    if req is not None and req != group_req:
        tail += f" by REQ {req}"
    return tail


# The group covering a msg index — the nearest one opening at or before it. None when the msg sits
# below every boundary, which happens only if the _forwarded stream does not reach back that far.
def _governing_marker(markers: dict, index: int):
    starts = [s for s in markers if s <= index]
    return markers[max(starts)] if starts else None


# One REQ separator: the request that opened this msg index, when it was sent, and — when
# resolved — its prompt-cache usage. The re-fire suffix stays OUTSIDE the closing "──", exactly
# where it sat before usage was added; CR/CC sits inside, between the clock and the "──".
def _req_separator(marker: dict, usage_by_flow: dict = None) -> str:
    refires = marker["refires"]
    extra = ""
    if refires:
        extra = f"  (+{refires} re-fire{'s' if refires != 1 else ''})"
    usage = (usage_by_flow or {}).get(marker.get("flow_id"))
    usage_part = f"  {_fmt_usage(*usage)}" if usage else ""
    return f"── REQ {marker['number']}  {_clock(marker['timestamp'])}{usage_part} ──{extra}"


# "CR 9,096  CC 1,928" — cache_read_input_tokens / cache_creation_input_tokens of the response
# that owns the group, same 1,234 digit-grouping the msg lines use for chars
def _fmt_usage(cache_read: int, cache_creation: int) -> str:
    return f"CR {cache_read:,}  CC {cache_creation:,}"


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


# expand: the complete content of each selected msg in the window, plus the proxy's own
# transformations of it when an overlay is supplied. `overlay` is {(msg, blk): {stripped, injected,
# req}} from overlay.py; an empty/absent one renders exactly the pre-overlay output, which is what
# keeps an untouched msg byte-identical.
def render_expand_full(data: dict, anchor: int, start: int, end: int,
                       only: str, dumped: list, overlay: dict = None) -> str:
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
            lines.extend(_overlay_lines((overlay or {}).get((msg["index"], position))))
        lines.append("")
    return "\n".join(lines) + "\n"


# The proxy's transformations of one block: what it removed from the text above, and what it put
# there instead. Labels carry the meaning — this output is read by agents through pipes, so there
# is no colour anywhere in it. Empty for a block the proxy never touched.
def _overlay_lines(slot) -> list:
    if not slot:
        return []
    req = slot.get("req")
    tag = f"REQ {req}" if req else "REQ ?"
    lines = []
    for text in slot.get("stripped") or []:
        lines.append(f"── stripped by {tag} ──")
        lines.append(text)
    for text in slot.get("injected") or []:
        lines.append(f"── injected by {tag} ──")
        lines.append(text)
    return lines


# HH:MM:SS of the request that first carried a msg; "?" when it has no reliable time
def _clock(timestamp) -> str:
    return timestamp[11:19] if timestamp else "?"


# Calendar day for the window header — the anchor's own day, else the session's start day
def _window_date(data: dict, anchor: int) -> str:
    stamp = data.get("turn_times", {}).get(anchor) or data["session"].get("start", "")
    return stamp[:10] if stamp else "?"
