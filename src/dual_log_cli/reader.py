# INFRASTRUCTURE
import json
import re
from pathlib import Path

# Top-level key order written by addon.py is timestamp, flow_id, request_id, model, payload —
# so "model" always sits inside the first few hundred bytes of an _original line and can be
# sniffed without parsing the (up to 15 MB) line.
_MODEL_RE = re.compile(rb'"model"\s*:\s*"([^"]+)"')
_MODEL_SNIFF_BYTES = 512
_REVERSE_CHUNK_BYTES = 1 << 20

# FUNCTIONS


# Infer model family from a model id — mirrors addon.py / dev/proxy_dual_log/*.py
def infer_family(model: str) -> str:
    m = (model or "").lower()
    if "haiku" in m:
        return "haiku"
    if "sonnet" in m:
        return "sonnet"
    return "opus"


# Yield (offset, length) of every line in a file, from the LAST line backwards.
# Never loads more than one chunk plus the current partial line into memory.
def iter_line_offsets_reverse(path: Path, chunk_bytes: int = _REVERSE_CHUNK_BYTES):
    size = path.stat().st_size
    if size == 0:
        return
    line_end = size
    pos = size
    buf = b""
    with open(path, "rb") as fh:
        while pos > 0:
            read_len = min(chunk_bytes, pos)
            pos -= read_len
            fh.seek(pos)
            buf = fh.read(read_len) + buf
            while True:
                search_end = len(buf) - 1 if buf.endswith(b"\n") else len(buf)
                nl = buf.rfind(b"\n", 0, search_end)
                if nl == -1:
                    break
                line_start = pos + nl + 1
                if line_end > line_start:
                    yield line_start, line_end - line_start
                line_end = line_start
                buf = buf[:nl]
    if line_end > 0:
        yield 0, line_end


# Read the model id of the line starting at offset without parsing the whole line
def sniff_model(fh, offset: int) -> str:
    fh.seek(offset)
    match = _MODEL_RE.search(fh.read(_MODEL_SNIFF_BYTES))
    return match.group(1).decode("utf-8", "replace") if match else ""


# Load and parse one line by (offset, length)
def read_json_line(path: Path, offset: int, length: int) -> dict:
    with open(path, "rb") as fh:
        fh.seek(offset)
        raw = fh.read(length)
    return json.loads(raw)


# Locate the last _original line whose model family is NOT haiku — the conversation-carrying
# request. Haiku lines are CC's 1-message title/quota calls and are interleaved into every
# session file. Returns (entry, line_bytes, lines_skipped) or (None, 0, n) if none exists.
def load_last_request(original_path: Path) -> tuple:
    skipped = 0
    with open(original_path, "rb") as fh:
        for offset, length in iter_line_offsets_reverse(original_path):
            model = sniff_model(fh, offset)
            if model and infer_family(model) == "haiku":
                skipped += 1
                continue
            fh.seek(offset)
            raw = fh.read(length)
            try:
                return json.loads(raw), length, skipped
            except json.JSONDecodeError:
                skipped += 1
                continue
    return None, 0, skipped


# Iterate parsed entries of a small JSONL file (forwarded/stripped/injected/response/errors).
# Not for _original — those lines are megabytes each.
def iter_jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
