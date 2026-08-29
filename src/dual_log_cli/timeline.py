# INFRASTRUCTURE
from pathlib import Path

from ..proxy.message_summary import _summarize_message
from .reader import infer_family, iter_jsonl, load_last_request

PREVIEW_CHARS = 100

# FUNCTIONS


# One-line preview: first non-empty line of the text, whitespace-collapsed and truncated
def _preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    if not text:
        return ""
    line = ""
    for candidate in text.split("\n"):
        if candidate.strip():
            line = " ".join(candidate.split())
            break
    if not line:
        line = " ".join(text.split())
    return line[:limit] + ("…" if len(line) > limit else "")


# Display label for one content block
def _block_label(block: dict) -> str:
    btype = block.get("type", "text")
    if btype == "tool_use":
        return f"tool_use[{block.get('preview', '') or '?'}]"
    if btype == "tool_result" and block.get("is_error"):
        return "tool_result!err"
    return btype


# Preview text for one content block — tool_use shows its input, not just the tool name
def _block_preview(block: dict) -> str:
    full = block.get("full_text", "") or ""
    if block.get("type") == "tool_use":
        _, _, input_json = full.partition("\n")
        return _preview(input_json or full)
    return _preview(full)


# Compact rows for every message of a payload. full_text is dropped here — only the requested
# turn is re-summarized for --full, so peak memory stays near the parsed payload.
def build_turns(payload: dict) -> list:
    turns = []
    for index, message in enumerate(payload.get("messages", []) or []):
        summary = _summarize_message(message)
        blocks = [
            {
                "label": _block_label(block),
                "type": block.get("type", "text"),
                "chars": block.get("chars", 0),
                "sig_chars": block.get("sig_chars", 0),
                "preview": _block_preview(block),
            }
            for block in summary.get("blocks", [])
        ]
        if not blocks:
            # str content (CC delivers role='system' messages that way) — no block list exists
            blocks = [{
                "label": summary.get("type", "text"),
                "type": summary.get("type", "text"),
                "chars": summary.get("chars", 0),
                "sig_chars": 0,
                "preview": _preview(summary.get("content_preview", "")),
            }]
        turns.append({
            "index": index,
            "role": summary.get("role", "?"),
            "type": summary.get("type", "text"),
            "chars": summary.get("chars", 0),
            "blocks": blocks,
        })
    return turns


# Stream every block of every turn as {turn, role, block, label, text}. A generator, so a
# 14 MB payload is never doubled by holding all full_text values at once — build_turns drops
# them for exactly the same reason.
def iter_block_texts(payload: dict):
    for index, message in enumerate(payload.get("messages", []) or []):
        summary = _summarize_message(message)
        role = summary.get("role", "?")
        blocks = summary.get("blocks", [])
        if blocks:
            for position, block in enumerate(blocks):
                yield {
                    "turn": index,
                    "role": role,
                    "block": position,
                    "label": _block_label(block),
                    "text": block.get("full_text", "") or "",
                }
        else:
            yield {
                "turn": index,
                "role": role,
                "block": 0,
                "label": summary.get("type", "text"),
                "text": summary.get("content_preview", "") or "",
            }


# Full content of one turn: [(label, chars, full_text), ...]
def full_turn(payload: dict, turn_index: int) -> list:
    messages = payload.get("messages", []) or []
    if turn_index < 0 or turn_index >= len(messages):
        return []
    summary = _summarize_message(messages[turn_index])
    blocks = summary.get("blocks", [])
    if not blocks:
        return [(summary.get("type", "text"), summary.get("chars", 0), summary.get("content_preview", ""))]
    return [(_block_label(b), b.get("chars", 0), b.get("full_text", "") or "") for b in blocks]


# Request boundaries for the conversation family, read from the _forwarded delta log
# (counts.messages per request). Each boundary marks the message index at which that request's
# new messages start. A restart flag is set when the message count regressed — CC was restarted
# mid-log-id, so boundaries before that point do not align with the final message list.
def request_boundaries(forwarded_path: Path, family: str) -> list:
    boundaries = []
    request_no = 0
    prev_count = 0
    for entry in iter_jsonl(forwarded_path):
        if entry.get("type") != "forwarded_delta":
            continue
        if infer_family(entry.get("model", "")) != family:
            continue
        request_no += 1
        count = entry.get("counts", {}).get("messages", 0)
        restart = count < prev_count
        boundaries.append({
            "request_no": request_no,
            "timestamp": entry.get("timestamp", ""),
            "model": entry.get("model", ""),
            "start_index": 0 if restart else prev_count,
            "message_count": count,
            "restart": restart,
        })
        prev_count = count
    return boundaries


# Group boundaries by the message index they open, collapsing consecutive re-fires that added
# no messages into one marker
def boundaries_by_index(boundaries: list) -> dict:
    grouped: dict = {}
    for boundary in boundaries:
        grouped.setdefault(boundary["start_index"], []).append(boundary)
    return grouped


# Load everything the timeline renderer needs for one session
def load_timeline(session: dict) -> dict:
    original = session["streams"].get("original")
    if original is None:
        raise FileNotFoundError(f"no _original stream for {session['stem']}")
    entry, line_bytes, skipped = load_last_request(original)
    if entry is None:
        raise ValueError(f"no non-haiku request line in {original.name}")
    payload = entry.get("payload", {}) or {}
    family = infer_family(entry.get("model", ""))
    forwarded = session["streams"].get("forwarded")
    boundaries = request_boundaries(forwarded, family) if forwarded else []
    return {
        "session": session,
        "entry": entry,
        "payload": payload,
        "family": family,
        "line_bytes": line_bytes,
        "haiku_lines_skipped": skipped,
        "turns": build_turns(payload),
        "boundaries": boundaries,
    }
