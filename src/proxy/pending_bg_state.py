# INFRASTRUCTURE
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .strip_bg_launch_ack import _is_bg_launch_ack, _ACK_ID_RE
from .payload_helpers import _extract_task_notification_task_id

_TN_BLOCK_PREFIX = '<task-notification>'
_TOMBSTONE_TTL_SECS = 24 * 3600


# UTC timestamp with a genuine single 'Z' designator, millisecond precision — same convention as
# addon.py's mc_timestamp. NOT datetime.now(timezone.utc).isoformat() + "Z": isoformat() on a
# tz-aware datetime already appends "+00:00", so plain string-concatenating "Z" after it produces
# an unparseable "...+00:00Z" double-suffix — armed_at/cleared_at must round-trip through
# _prune_stale_tombstones (and, later, Milestone 3's expiry check), so they need to actually parse.
def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.') + f'{now.microsecond // 1000:03d}Z'

# Task ids already arm-attempted / clear-attempted by this proxy process. Same lifetime class as
# bg_escape.py's _escaped_task_ids: lives for the mitmproxy process's lifetime, wiped on
# hot-reload or restart. Purely an I/O-avoidance shortcut — correctness across restarts lives in
# the state FILE's tombstone design (see _update_pending_bg_state docstring), not these sets; a
# fresh process re-touches the file at most once per id per direction on its first sighting.
_arm_attempted_ids: set = set()
_clear_attempted_ids: set = set()


# ORCHESTRATOR

# Scan one request's removed chunks for genuine bg-launch acks (arm) and genuine TN completion
# blocks (clear), updating the on-disk pending-state file. No-op entirely for any worker_context
# other than "main" — workers never write state. Every failure mode (unwritable file, corrupt/
# unparseable existing state) degrades to a no-op for that one update — never raises; addon.py
# wraps the call in its own try/except anyway, matching bg_escape.py's call-site convention.
#
# Ordering: chunks are processed in ASCENDING message-index order (stripped_msg_removed is keyed
# by message index) — an ack always sits at a lower index than its own completion notice in real
# conversation history, so this guarantees arm-before-clear even when both land in the SAME
# request (the replay case: the first request after a proxy restart resends the whole history at
# once, ack and TN both freshly "removed" together).
#
# Restart / resent-history dedup: a dual-log request resends the FULL cumulative conversation
# every time, so the SAME genuine ack or TN block reappears in stripped_msg_removed on every
# subsequent request for as long as it stays in the conversation window (measured: 25219 raw TN
# occurrences deduping to 110 real events in one session, dev/timer-loop/md/
# bg_completion_wordings_20260806.md). The state file entry is never DELETED on clear — only
# status-flipped pending -> cleared with a cleared_at timestamp (a tombstone), and a TN sighted
# with NO prior entry at all writes a fresh cleared tombstone rather than a pure no-op. Either way
# the arm path's "does ANY entry already exist for this id" check (not "is it currently pending")
# means a stale re-sighting of an already-resolved id's ORIGINAL ack text — still sitting later in
# the same growing history — can never re-arm it, regardless of restart timing or processing gaps.
#
# Project scoping (2026-08): project_path (addon.py's PROXY_PROJECT_PATH, already in scope at the
# call site) is normalized to a "project" slug and stamped on freshly-armed entries only — clear
# stays id-based (ids are globally unique across projects, no scoping needed there).
def _update_pending_bg_state(stripped_msg_removed: dict, worker_context: str, project_path: str = "") -> None:
    if worker_context != "main":
        return
    project_slug = _project_slug_from_path(project_path)
    for idx in sorted(stripped_msg_removed.keys()):
        for chunk in stripped_msg_removed[idx]:
            if not isinstance(chunk, str):
                continue
            if _is_bg_launch_ack(chunk):
                _handle_launch_ack_chunk(chunk, worker_context, project_slug)
            elif chunk.startswith(_TN_BLOCK_PREFIX):
                _handle_tn_chunk(chunk, worker_context)


# FUNCTIONS

# Normalize a project name/basename to the same canonical slug claude_proxy_start.sh derives for
# dual-log stems (PROJECT_BASENAME): lower-case, any run of non-[a-z0-9] chars (including existing
# underscores/hyphens) collapsed to a single "_", leading/trailing "_" stripped. Duplicated in
# block_timer_pending_bg.py (same convention as this module's other small helpers, e.g.
# _resolve_pending_bg_state_file — the hook and the writer stay structurally independent).
def _normalize_project_slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


# Derive the armed-entry "project" slug from PROXY_PROJECT_PATH (basename, normalized). Empty
# string when project_path is falsy — callers must treat "" as "no project recorded" (omit the
# field), never write it as a literal empty-string project.
def _project_slug_from_path(project_path: str) -> str:
    if not project_path:
        return ""
    return _normalize_project_slug(os.path.basename(project_path.rstrip('/')))


# Recover the task id from a genuine ack chunk and attempt to arm it (once per id per process).
def _handle_launch_ack_chunk(chunk: str, worker_context: str, project_slug: str) -> None:
    match = _ACK_ID_RE.search(chunk)
    task_id = match.group(1).strip() if match else ''
    if not task_id:
        _log_pending_state_event("skipped", worker_context, "", reason="no_task_id")
        return
    if task_id in _arm_attempted_ids:
        return
    _arm_attempted_ids.add(task_id)
    _arm_pending(task_id, worker_context, project_slug)


# Recover the task id from a genuine TN chunk and attempt to clear it (once per id per process).
def _handle_tn_chunk(chunk: str, worker_context: str) -> None:
    task_id = _extract_task_notification_task_id(chunk)
    if not task_id:
        _log_pending_state_event("skipped", worker_context, "", reason="no_task_id")
        return
    if task_id in _clear_attempted_ids:
        return
    _clear_attempted_ids.add(task_id)
    _clear_pending(task_id, worker_context)


# Record task_id as pending iff it has no existing state-file entry at all (any status) — an
# existing entry (pending OR cleared) means this exact task id has already been through arm once
# and must never be re-armed by a resighting of its ack text later in the same growing history.
# project_slug ("" when PROXY_PROJECT_PATH was absent/unresolvable) is stored as the "project"
# field so block_timer_pending_bg.py can scope blocking to the arming project — omitted entirely
# when empty, which keeps the entry in the pre-migration "blocks every project" shape rather than
# writing a literal "" that would match nothing.
def _arm_pending(task_id: str, worker_context: str, project_slug: str = "") -> None:
    try:
        state = _read_state_file()
        if state is None:
            _log_pending_state_event("skipped", worker_context, task_id, reason="state_read_failed")
            return
        if task_id in state:
            _log_pending_state_event("skipped", worker_context, task_id, reason="already_recorded")
            return
        entry = {
            "status": "pending",
            "armed_at": _now_iso(),
        }
        if project_slug:
            entry["project"] = project_slug
        state[task_id] = entry
        if _write_state_file(state):
            _log_pending_state_event("armed", worker_context, task_id)
        else:
            _log_pending_state_event("skipped", worker_context, task_id, reason="state_write_failed")
    except Exception as e:
        print(f"[pending_bg_state] arm failed: {e}", file=sys.stderr)


# Flip a recorded pending entry to cleared. A missing entry (never armed by this mechanism — e.g.
# proxy started mid-session, or the launch ack's id failed to extract) still gets a FRESH cleared
# tombstone written (not a pure no-op) — costs nothing and structurally guarantees this task id
# can never later be mistaken for a fresh arm target, regardless of processing-order gaps. An
# already-cleared entry (duplicate TN resighting, the dominant real-world case) is a pure no-op.
def _clear_pending(task_id: str, worker_context: str) -> None:
    try:
        state = _read_state_file()
        if state is None:
            _log_pending_state_event("skipped", worker_context, task_id, reason="state_read_failed")
            return
        now_iso = _now_iso()
        entry = state.get(task_id)
        if entry is None:
            state[task_id] = {"status": "cleared", "cleared_at": now_iso}
            if _write_state_file(state):
                _log_pending_state_event("cleared", worker_context, task_id, reason="no_prior_arm")
            else:
                _log_pending_state_event("skipped", worker_context, task_id, reason="state_write_failed")
            return
        if entry.get("status") != "pending":
            _log_pending_state_event("skipped", worker_context, task_id, reason="already_cleared")
            return
        entry["status"] = "cleared"
        entry["cleared_at"] = now_iso
        if _write_state_file(state):
            _log_pending_state_event("cleared", worker_context, task_id)
        else:
            _log_pending_state_event("skipped", worker_context, task_id, reason="state_write_failed")
    except Exception as e:
        print(f"[pending_bg_state] clear failed: {e}", file=sys.stderr)


# Read + parse the state file; {} if absent, None on any read/parse failure. Callers treat None
# as "cannot safely proceed this call" — never invent or overwrite unreadable state blindly.
def _read_state_file() -> dict:
    path = _resolve_pending_bg_state_file()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# Drop cleared tombstones older than 24h (mirrors the removed block_concurrent_timer.py hook's
# timer_state.jsonl 24h-prune-by-write-ts convention, process-docs/tool_use_safety/
# 2026-07-20_timer_guard_concurrent_redesign.md). Pending entries are NEVER pruned here — a
# pending entry's staleness/expiry is Milestone 3's hook's job (armed_at is the signal it reads),
# not this proxy's; pruning a pending entry itself would defeat the tombstone dedup guarantee for
# an id whose completion notice simply hasn't passed through the proxy yet.
def _prune_stale_tombstones(state: dict) -> dict:
    now = datetime.now(timezone.utc)
    pruned = {}
    for task_id, entry in state.items():
        if entry.get("status") == "cleared":
            cleared_at = entry.get("cleared_at", "")
            try:
                ts = datetime.fromisoformat(cleared_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pruned[task_id] = entry  # unparseable timestamp — keep, never destroy on a surprise format
                continue
            if (now - ts).total_seconds() > _TOMBSTONE_TTL_SECS:
                continue  # pruned
        pruned[task_id] = entry
    return pruned


# Prune stale tombstones, then write the state dict; returns True on success, False on any
# failure (never raises).
def _write_state_file(state: dict) -> bool:
    path = _resolve_pending_bg_state_file()
    try:
        pruned = _prune_stale_tombstones(state)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pruned, f)
        return True
    except Exception:
        return False


# Resolve the pending-bg-tasks state file path — same MONITOR_CC_ROOT/tmp-fallback convention as
# bg_escape.py's event log (a top-level file in src/logs/, not per-session dual_log/ pairs).
def _resolve_pending_bg_state_file() -> Path:
    root = os.environ.get("MONITOR_CC_ROOT")
    if root:
        return Path(root) / "src" / "logs" / "pending_bg_tasks.json"
    return Path("/tmp") / "pending_bg_tasks.json"


# Append one JSONL trace line — same append-only-JSONL-file convention as bg_escape.py's
# _log_bg_escape_event. Never raises — a logging failure degrades to a stderr print.
def _log_pending_state_event(event: str, worker_context: str, task_id: str, reason: str = "") -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat() + "Z",
        "event": event,
        "worker_context": worker_context,
        "task_id": task_id,
    }
    if reason:
        entry["reason"] = reason
    try:
        log_file = _resolve_pending_bg_state_log_file()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[pending_bg_state] event log write failed: {e}", file=sys.stderr)


# Resolve the flat pending_bg_state_events.jsonl trace path — same convention as
# bg_escape.py's _resolve_bg_escape_log_file.
def _resolve_pending_bg_state_log_file() -> Path:
    root = os.environ.get("MONITOR_CC_ROOT")
    if root:
        return Path(root) / "src" / "logs" / "pending_bg_state_events.jsonl"
    return Path("/tmp") / "pending_bg_state_events.jsonl"
