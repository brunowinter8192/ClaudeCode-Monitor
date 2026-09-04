# INFRASTRUCTURE
import json
from pathlib import Path

from .discovery import stem_identity
from .project_map import build_project_index, project_label
from .reader import iter_jsonl, local_datetime

_PROJECTS_ROOT = Path("~/.claude/projects").expanduser()

# FUNCTIONS


# {flow_id: (request_id, status_code)} for every line of one session's _response stream
def _flow_status_ids(response_path: Path) -> dict:
    result = {}
    for entry in iter_jsonl(response_path):
        flow_id = entry.get("flow_id")
        if not flow_id:
            continue
        result[flow_id] = (entry.get("request_id", ""), entry.get("status_code"))
    return result


# Epoch seconds of an ISO timestamp, tolerant of the dual log's two shapes ("...998Z" and
# "...998+00:00Z" — the latter from addon.py appending "Z" to an isoformat() that already carries
# an offset). None on anything unparseable, which the caller reads as "don't filter by time".
# 2026-09-04: delegates to `reader.local_datetime` (the one shared UTC-aware parse this package
# now uses everywhere) rather than its own inline parsing — `.timestamp()` on an AWARE datetime is
# timezone-independent (correct regardless of which zone the datetime is expressed in), so this
# still returns the exact same epoch value as before; only the duplicate parsing logic is gone.
# Audited for a UTC-vs-local bug during that same-day work and found already correct: the ORIGINAL
# inline version explicitly appended "+00:00" whenever the cleaned string carried no offset of its
# own, so the "...998Z"-only case (the common one) was already parsed as AWARE UTC, never as a
# naive-assumed-local datetime.
def _epoch_from_iso(timestamp: str):
    dt = local_datetime(timestamp)
    return dt.timestamp() if dt else None


# The project directories a session's stem could possibly have a transcript in — derived from the
# stem alone, never a store-wide scan. A worker stem's sid8 resolves to its project's cwd (the
# same md5(project_path)[:8] hash build_project_map uses), and the worker's OWN cwd is that
# project's cwd plus the worktree layout every worker runs under
# (".claude/worktrees/<name>"). A main stem's label is matched against every known cwd's label —
# plural on purpose, since two different projects can share a basename. Empty when the stem does
# not parse or its cwd/label matches no known directory.
def _candidate_dirs(stem: str, index: dict) -> list:
    identity = stem_identity(stem)
    if identity is None:
        return []
    cwd_to_dir = index["cwd_to_dir"]
    if identity[0] == "worker":
        _, sid, name = identity
        cwd = index["sid_to_cwd"].get(sid)
        if not cwd:
            return []
        worktree_cwd = f"{cwd.rstrip('/')}/.claude/worktrees/{name}"
        directory = cwd_to_dir.get(worktree_cwd)
        return [directory] if directory else []
    _, _head, label = identity
    return [directory for cwd, directory in cwd_to_dir.items() if project_label(cwd) == label]


# The first file (name order) under `directories`, with mtime at or after `since_epoch`, whose
# content contains the literal fragment `"requestId":"<id>"` — WITH the key, never a bare id (a
# tool_result can quote one, which a bare-id search would wrongly treat as that record's own).
# Stops at the first match rather than hunting for or rejecting a second one: a full-store sweep
# of the corpus on disk found zero sessions where the same request id appears in two transcripts.
# None when no candidate file matches or a candidate cannot be read.
def _find_transcript(request_id: str, directories: list, since_epoch=None) -> Path:
    fragment = f'"requestId":"{request_id}"'
    candidates = []
    for directory in directories:
        try:
            entries = sorted(directory.iterdir())
        except Exception:
            continue
        for path in entries:
            if path.suffix != ".jsonl":
                continue
            if since_epoch is not None:
                try:
                    if path.stat().st_mtime < since_epoch:
                        continue
                except OSError:
                    continue
            candidates.append(path)
    for path in candidates:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if fragment in content:
            return path
    return None


# {request_id: (cache_read_input_tokens, cache_creation_input_tokens)} from one transcript's
# assistant records. One API request produces several streaming assistant records with identical
# input-side usage, so only the first record per requestId is kept.
def _transcript_usage(transcript_path: Path) -> dict:
    usage = {}
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "assistant":
                    continue
                request_id = entry.get("requestId")
                if not request_id or request_id in usage:
                    continue
                message_usage = entry.get("message", {}).get("usage", {}) or {}
                cache_read = message_usage.get("cache_read_input_tokens")
                cache_creation = message_usage.get("cache_creation_input_tokens")
                if cache_read is None or cache_creation is None:
                    continue
                usage[request_id] = (cache_read, cache_creation)
    except Exception:
        return {}
    return usage


# {flow_id: (cache_read_input_tokens, cache_creation_input_tokens)} for one session — what
# render._req_separator looks its CR/CC figures up by, keyed on the group owner's flow_id from
# timeline.request_markers.
#
# Degrades to {} (every separator renders value-less, never a placeholder) when the _response
# stream is missing, no boundary's flow_id resolves to a request id, the stem does not resolve to
# a known project directory, no candidate file in it matches, or the matched transcript yields no
# usable usage lines. A flow whose _response status is not 200 is dropped even when its request id
# would otherwise resolve — an errored request carries no meaningful cache figures.
def build_usage_by_flow(session: dict, boundaries: list, projects_root: Path = None) -> dict:
    if not boundaries:
        return {}
    response_path = session.get("streams", {}).get("response")
    if response_path is None:
        return {}
    try:
        flow_status = _flow_status_ids(response_path)
    except Exception:
        return {}
    anchor_request_id = None
    for boundary in boundaries:
        request_id, _status = flow_status.get(boundary.get("flow_id", ""), ("", None))
        if request_id:
            anchor_request_id = request_id
            break
    if not anchor_request_id:
        return {}
    root = Path(projects_root) if projects_root else _PROJECTS_ROOT
    index = build_project_index(root)
    directories = _candidate_dirs(session.get("stem", ""), index)
    if not directories:
        return {}
    since_epoch = _epoch_from_iso(boundaries[0].get("timestamp", ""))
    transcript_path = _find_transcript(anchor_request_id, directories, since_epoch)
    if transcript_path is None:
        return {}
    usage_by_request_id = _transcript_usage(transcript_path)
    if not usage_by_request_id:
        return {}
    usage_by_flow = {}
    for flow_id, (request_id, status) in flow_status.items():
        if status != 200 or not request_id:
            continue
        usage = usage_by_request_id.get(request_id)
        if usage is not None:
            usage_by_flow[flow_id] = usage
    return usage_by_flow
