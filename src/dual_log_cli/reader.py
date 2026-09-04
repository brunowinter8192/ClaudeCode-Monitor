# INFRASTRUCTURE
import json
import re
from datetime import datetime, timezone
from pathlib import Path

# Top-level key order written by addon.py is timestamp, flow_id, request_id, model, payload —
# so "model" always sits inside the first few hundred bytes of an _original line and can be
# sniffed without parsing the (up to 15 MB) line.
_MODEL_RE = re.compile(rb'"model"\s*:\s*"([^"]+)"')
_MODEL_SNIFF_BYTES = 512
_REVERSE_CHUNK_BYTES = 1 << 20

# FUNCTIONS


# Parse a dual-log ISO timestamp ("...998Z", always UTC — see src/proxy/logging.py's write side —
# or the rarer "...998+00:00Z" shape, an offset with "Z" appended, still always UTC in practice)
# into a LOCAL, DST-correct datetime. This is the ONE place every UTC timestamp this package reads
# gets converted, so every render/filter that shows or compares a time or a day agrees with each
# other and with the proxy pane / menubar log (both already local) — see 2026-09-04's
# process-docs entry in this area for why this exists (verified: the same instant showed 18:16:02
# in `reqs`, UTC, against 20:16:02 in the proxy pane, local, before this fix).
# `.astimezone()` with no explicit `tz=` resolves to the SYSTEM's configured local zone via the
# OS's own tzdata, correct for whichever specific date is being converted — DST included — never a
# fixed offset baked in. Returns None for an empty/unparseable string (never raises); callers
# render "?" or drop the session from a date filter, exactly as they did before local conversion
# existed.
def local_datetime(timestamp: str):
    if not timestamp:
        return None
    try:
        aware_utc = datetime.fromisoformat(timestamp.rstrip("Z")).replace(tzinfo=timezone.utc)
        return aware_utc.astimezone()
    except ValueError:
        return None


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


# Locate the last _original line whose model family is NOT haiku AND that carries at least one
# tool — the conversation-carrying request. Haiku lines are CC's 1-message title/quota calls,
# skipped cheaply from the model sniff alone. A zero-tool non-haiku line is the OTHER sidecar shape
# `timeline._is_sidecar` excludes from request boundaries (measured: a recurring "security
# monitor" review call, own system prompt, no tools) — a real conversation request always carries
# tools, so this line is never "the conversation" either, but telling the two apart needs the
# parsed payload (tools can sit well past the cheap model-sniff window behind a large system
# block), so it is checked right after the parse this function already does for its return value,
# not via a second cheap sniff. Returns (entry, line_bytes, lines_skipped) or (None, 0, n) if none
# exists. `lines_skipped` now counts both shapes — see `load_timeline`'s Gotcha.
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
                entry = json.loads(raw)
            except json.JSONDecodeError:
                skipped += 1
                continue
            tools = (entry.get("payload") or {}).get("tools") or []
            if not tools:
                skipped += 1
                continue
            return entry, length, skipped
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
