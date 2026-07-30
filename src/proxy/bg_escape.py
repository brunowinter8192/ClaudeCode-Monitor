# INFRASTRUCTURE
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .strip_bg_launch_ack import _is_bg_launch_ack, _ACK_ID_RE

_TMUX_TIMEOUT_SECS = 2
_WORKER_PREFIX = "worker:"

# Task ids already escaped by this proxy process. Module-global, in-memory only — same lifetime
# class as tool_injection.py's schema caches: lives for the mitmproxy process's lifetime, wiped on
# hot-reload (file edit under src/proxy/) or process restart. A restart can re-fire an Escape for a
# task id whose launch-ack text is still present in conversation history (measured 142/169 requests
# carry the raw ack) — bounded to at most one extra Escape per still-referenced task id, never a
# repeat storm, since the freshly-restarted process re-populates this set on its own first sighting
# of each id.
_escaped_task_ids: set = set()


# ORCHESTRATOR

# Scan one request's removed chunks for a genuine bg-launch ack and fire Escape at most once per
# task id. No-op for a non-worker context, an ack with no extractable task id, or an id already
# escaped this process. Every failure mode (dead tmux session, missing tmux binary, subprocess
# error) degrades to a no-op — never raises, so a caller needs no try/except of its own, though
# addon.py wraps the call anyway per its per-concern defensive convention.
# Logging is scoped to genuine-ack sightings only — a request carrying no bg-launch-ack chunk at
# all never touches the log sink, so the per-request hot path stays log-free.
def _trigger_bg_escape(stripped_msg_removed: dict, worker_context: str, project_path: str) -> None:
    tmux_session = None
    for chunks in stripped_msg_removed.values():
        for chunk in chunks:
            if not isinstance(chunk, str) or not _is_bg_launch_ack(chunk):
                continue
            task_id = _extract_task_id(chunk)
            if not task_id:
                _log_bg_escape_event("skipped", worker_context, "", "", reason="no_task_id")
                continue
            if task_id in _escaped_task_ids:
                _log_bg_escape_event("skipped", worker_context, task_id, "", reason="already_escaped")
                continue
            if tmux_session is None:
                tmux_session = _derive_tmux_session_name(worker_context, project_path) or ""
            if not tmux_session:
                reason = "main_context" if not worker_context.startswith(_WORKER_PREFIX) else "no_tmux_session"
                _log_bg_escape_event("skipped", worker_context, task_id, "", reason=reason)
                continue
            _escaped_task_ids.add(task_id)
            sent = _send_escape_key(tmux_session)
            _log_bg_escape_event("fired", worker_context, task_id, tmux_session, send_result=sent)


# FUNCTIONS

# Recover the task id from a genuine ack's raw text (already-detected — see _is_bg_launch_ack in
# strip_bg_launch_ack.py, reused unchanged here, not re-implemented).
def _extract_task_id(ack_text: str) -> str:
    match = _ACK_ID_RE.search(ack_text)
    return match.group(1).strip() if match else ''


# Build the iterative-dev tmux session name for a worker context — worker-{basename(project_path)}-
# {worker_name}. Empty string for "main" or any incomplete input — the caller treats empty as no-op.
def _derive_tmux_session_name(worker_context: str, project_path: str) -> str:
    if not worker_context.startswith(_WORKER_PREFIX):
        return ''
    worker_name = worker_context[len(_WORKER_PREFIX):]
    if not worker_name or not project_path:
        return ''
    basename = os.path.basename(project_path.rstrip('/'))
    if not basename:
        return ''
    return f'worker-{basename}-{worker_name}'


# Send one Escape keystroke into a tmux pane by session name — tmux interprets "Escape" as a key
# name (no -l flag), not literal characters. Gated on a liveness check first: a dead/missing
# session must not attempt the send. Any exception (missing tmux binary, timeout, subprocess
# error) is swallowed and reported as a plain no-op — this function must never raise.
def _send_escape_key(tmux_session: str) -> bool:
    try:
        alive = subprocess.run(
            ["tmux", "has-session", "-t", tmux_session],
            capture_output=True, timeout=_TMUX_TIMEOUT_SECS,
        )
        if alive.returncode != 0:
            return False
        sent = subprocess.run(
            ["tmux", "send-keys", "-t", tmux_session, "Escape"],
            capture_output=True, timeout=_TMUX_TIMEOUT_SECS,
        )
        return sent.returncode == 0
    except Exception:
        return False


# Append one JSONL trace line for a fire or a meaningful skip (main context, already-escaped id,
# no extractable task id, no derivable tmux session) — the same append-only-JSONL-file convention
# every other proxy diagnostic sink uses (addon.py's api_errors.jsonl), not stderr: mitmdump runs
# production with stderr routed to /dev/null (src/claude_proxy_start.sh), so a print-only trace
# would be invisible in exactly the situation this exists to make visible. Never raises — a logging
# failure (disk full, permission) degrades to a stderr print, same as addon.py's own _log_* helpers.
def _log_bg_escape_event(event: str, worker_context: str, task_id: str, tmux_session: str, reason: str = "", send_result: bool = None) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat() + "Z",
        "event": event,
        "worker_context": worker_context,
        "task_id": task_id,
        "tmux_session": tmux_session,
    }
    if reason:
        entry["reason"] = reason
    if send_result is not None:
        entry["send_result"] = send_result
    try:
        log_file = _resolve_bg_escape_log_file()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[bg_escape] event log write failed: {e}", file=sys.stderr)


# Resolve the flat bg_escape_events.jsonl path — same MONITOR_CC_ROOT/tmp-fallback convention as
# addon.py's api_errors.jsonl (a top-level file in src/logs/, not the per-session dual_log/ pairs).
def _resolve_bg_escape_log_file() -> Path:
    root = os.environ.get("MONITOR_CC_ROOT")
    if root:
        return Path(root) / "src" / "logs" / "bg_escape_events.jsonl"
    return Path("/tmp") / "bg_escape_events.jsonl"
