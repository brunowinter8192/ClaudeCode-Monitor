# INFRASTRUCTURE
import json
import subprocess
from pathlib import Path

from .reader import iter_jsonl

_PROJECTS_ROOT = Path("~/.claude/projects").expanduser()
_GREP_TIMEOUT_SECONDS = 30

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


# The one transcript file carrying this request id, found by a literal-fragment search across
# CC's whole transcript store. The fragment includes the `"requestId":` key, never a bare id —
# a bare id can also match a tool_result that merely quotes one (measured: happens in a live
# session), which would silently resolve to the wrong transcript. None on zero or MULTIPLE
# matches (a split transcript is not safely resolvable either) and on any read failure.
def _find_transcript(request_id: str, projects_root: Path = None) -> Path:
    root = Path(projects_root) if projects_root else _PROJECTS_ROOT
    fragment = f'"requestId":"{request_id}"'
    try:
        result = subprocess.run(
            ["grep", "-rlF", "--include=*.jsonl", fragment, str(root)],
            capture_output=True, text=True, timeout=_GREP_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    matches = [line for line in result.stdout.splitlines() if line]
    if len(matches) != 1:
        return None
    return Path(matches[0])


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
# stream is missing, no boundary's flow_id resolves to a request id, the transcript store has no
# single matching file, or the transcript yields no usable usage lines. A flow whose _response
# status is not 200 is dropped even when its request id would otherwise resolve — an errored
# request carries no meaningful cache figures.
def build_usage_by_flow(session: dict, boundaries: list) -> dict:
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
    transcript_path = _find_transcript(anchor_request_id)
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
