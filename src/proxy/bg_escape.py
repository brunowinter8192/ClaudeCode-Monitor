# INFRASTRUCTURE
import os
import subprocess

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
def _trigger_bg_escape(stripped_msg_removed: dict, worker_context: str, project_path: str) -> None:
    tmux_session = None
    for chunks in stripped_msg_removed.values():
        for chunk in chunks:
            if not isinstance(chunk, str) or not _is_bg_launch_ack(chunk):
                continue
            task_id = _extract_task_id(chunk)
            if not task_id or task_id in _escaped_task_ids:
                continue
            if tmux_session is None:
                tmux_session = _derive_tmux_session_name(worker_context, project_path) or ""
            if not tmux_session:
                continue
            _escaped_task_ids.add(task_id)
            _send_escape_key(tmux_session)


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
