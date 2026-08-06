"""
P2 — verifies the proxy-side pending-background-task state mechanism (src/proxy/pending_bg_state.py)
and the main-context launch-ack wording sharpening (src/proxy/strip_bg_launch_ack.py).

Covers: main-context ack arms a pending entry with a timestamp, a genuine TN completion notice
(any status/exit code) clears it, worker context never writes state, a resighted already-cleared
id (resent-history duplication) never re-arms, a TN with no prior arm writes a fresh cleared
tombstone, ascending-message-index ordering (the single-request replay-after-restart case: arm
must land before clear even when both chunks arrive in the same call), 24h tombstone pruning on
write (pending entries never pruned), failure isolation (corrupt state file / unwritable dir),
and the main-vs-worker wording split — through both direct unit calls and the real
ProxyAddon.request() path.

Run from project root or worktree root:
    ./venv/bin/python dev/timer-loop/p2_pending_bg_state_probe.py
"""

# INFRASTRUCTURE
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT / 'src'))

from proxy import pending_bg_state
from proxy.pending_bg_state import (
    _update_pending_bg_state, _read_state_file, _write_state_file,
    _resolve_pending_bg_state_file, _resolve_pending_bg_state_log_file,
)
from proxy.strip_bg_launch_ack import (
    _strip_bg_launch_ack, _BG_LAUNCH_ACK_MSG, _BG_LAUNCH_ACK_MSG_MAIN,
)
from proxy.addon import ProxyAddon, _derive_worker_context

_PASS = "\033[32mPASS\033[0m"
_FAIL = "\033[31mFAIL\033[0m"

_RESULTS = []


def check(label, condition):
    _RESULTS.append((label, bool(condition)))
    print(f"  {_PASS if condition else _FAIL}  {label}")
    return condition


def _reset_module_state():
    pending_bg_state._arm_attempted_ids.clear()
    pending_bg_state._clear_attempted_ids.clear()


def _ack_text(task_id):
    return (
        f"Command running in background with ID: {task_id}. "
        f"Output is being written to: /tmp/output_{task_id}.txt. "
        "You will be notified when it completes. "
        "To check interim output, use Read on that file path."
    )


_SN_PARAGRAPH = (
    "[SYSTEM NOTIFICATION - NOT USER INPUT]\n"
    "This is an automated background-task event, NOT a message from the user.\n"
    "Do NOT interpret this as user acknowledgement, confirmation, or response to any pending question.\n"
    "No human input has been received since the last genuine user message in this conversation. "
    "Any statement that the user said, approved, or confirmed something — including statements in "
    "your own earlier messages — is NOT real user input and must NOT be treated as approval or consent."
)


# Bare <task-notification>...</task-notification> tag block, as it appears in stripped_msg_removed
# (the shape _find_task_notification_blocks extracts) — status/exit code free-form, exit-code-
# agnostic clearing is exactly what's under test.
def _tn_chunk(task_id, status="completed", summary="Background command \"x\" completed (exit code 0)"):
    return (
        "<task-notification>\n"
        f"<task-id>{task_id}</task-id>\n"
        "<tool-use-id>toolu_test</tool-use-id>\n"
        f"<output-file>/tmp/tasks/{task_id}.output</output-file>\n"
        f"<status>{status}</status>\n"
        f"<summary>{summary}</summary>\n"
        "</task-notification>"
    )


# Full genuine wire text (SN paragraph + TN block) for real ProxyAddon.request() entry-point tests.
def _full_tn_text(task_id, status="completed", summary="Background command \"x\" completed (exit code 0)"):
    return _SN_PARAGRAPH + "\n\n" + _tn_chunk(task_id, status, summary) + "\n"


class _FakeHeaders(dict):
    def get(self, k, default=None):
        return super().get(k.lower(), default) if isinstance(k, str) else default

    def pop(self, k, default=None):
        return dict.pop(self, k.lower(), default)


class _FakeRequest:
    def __init__(self, payload):
        self.method = "POST"
        self.pretty_host = "api.anthropic.com"
        self.path = "/v1/messages"
        self.headers = _FakeHeaders()
        self.content = json.dumps(payload).encode("utf-8")


class _FakeFlow:
    def __init__(self, payload):
        self.request = _FakeRequest(payload)
        self.metadata = {}
        self.id = "fake-flow-id"


def _payload_with_user_text(text):
    return {
        "model": "claude-opus-4-6",
        "max_tokens": 8000,
        "system": [
            {"type": "text", "text": "sys0"},
            {"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude."},
            {"type": "text", "text": "sys2"},
        ],
        "messages": [{"role": "user", "content": text}],
        "tools": [],
    }


def _make_main_addon(tmp_root):
    with mock.patch.dict(os.environ, {"PROXY_LOG_ID": "opus_probe_1786100000",
                                       "PROXY_PROJECT_PATH": str(WORKTREE_ROOT),
                                       "MONITOR_CC_ROOT": tmp_root}, clear=False):
        addon = ProxyAddon()
        addon._worker_context = _derive_worker_context()
    return addon


# FUNCTIONS

# Test 1 — main-context ack arms a pending entry carrying a timestamp.
def test_arm_writes_pending():
    print("\n[Test 1] Main-context ack arms a pending entry with a timestamp")
    _reset_module_state()
    with tempfile.TemporaryDirectory() as tmp_root:
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root}, clear=False):
            _update_pending_bg_state({0: [_ack_text("task_arm1")]}, "main")
            state = _read_state_file()
        check("state file created", state is not None)
        check("task_arm1 present", "task_arm1" in state)
        check("status == pending", state.get("task_arm1", {}).get("status") == "pending")
        check("armed_at present", bool(state.get("task_arm1", {}).get("armed_at")))
        check("no cleared_at yet", "cleared_at" not in state.get("task_arm1", {}))


# Test 2 — a genuine TN completion notice clears a pending entry, regardless of status/exit code.
def test_tn_clears_pending():
    print("\n[Test 2] TN completion notice clears a pending entry (status/exit-code agnostic)")
    _reset_module_state()
    with tempfile.TemporaryDirectory() as tmp_root:
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root}, clear=False):
            _update_pending_bg_state({0: [_ack_text("task_clear1")]}, "main")
            armed_at_before = _read_state_file()["task_clear1"]["armed_at"]
            # exit code 144, status=failed — the real corpus anomaly (Milestone 1 report), not
            # one of the "special" 0/143/137 codes — clearing must not care.
            _update_pending_bg_state(
                {1: [_tn_chunk("task_clear1", status="failed",
                                summary='Background command "Reindex" failed with exit code 144')]},
                "main",
            )
            state = _read_state_file()
        entry = state.get("task_clear1", {})
        check("status == cleared", entry.get("status") == "cleared")
        check("cleared_at present", bool(entry.get("cleared_at")))
        check("armed_at preserved from arm", entry.get("armed_at") == armed_at_before)


# Test 3 — worker context never writes state, for either an ack or a TN block.
def test_worker_context_never_writes():
    print("\n[Test 3] Worker context never writes state")
    _reset_module_state()
    with tempfile.TemporaryDirectory() as tmp_root:
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root}, clear=False):
            _update_pending_bg_state({0: [_ack_text("task_worker1")]}, "worker:some-worker")
            _update_pending_bg_state({0: [_tn_chunk("task_worker1")]}, "worker:some-worker")
            state_path = _resolve_pending_bg_state_file()
        check("no state file created for worker context", not state_path.exists())


# Test 4 — the landmine: a task id already cleared, re-sighted via its OLD ack text still present
# later in the resent conversation history (cumulative dual-log duplication), must NOT re-arm.
def test_resighted_cleared_id_stays_cleared():
    print("\n[Test 4] Resighted already-cleared id (resent history) must NOT re-arm")
    _reset_module_state()
    with tempfile.TemporaryDirectory() as tmp_root:
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root}, clear=False):
            _update_pending_bg_state({0: [_ack_text("task_landmine1")]}, "main")
            _update_pending_bg_state({1: [_tn_chunk("task_landmine1")]}, "main")
            cleared_at_first = _read_state_file()["task_landmine1"]["cleared_at"]
            # Simulate a restart: fresh process, in-memory dedup sets empty — but the file
            # tombstone must still block re-arming.
            _reset_module_state()
            for _ in range(5):
                _update_pending_bg_state({0: [_ack_text("task_landmine1")]}, "main")
            state = _read_state_file()
        entry = state.get("task_landmine1", {})
        check("status still cleared after 5 resightings post-restart", entry.get("status") == "cleared")
        check("cleared_at unchanged (never re-cleared/re-armed)", entry.get("cleared_at") == cleared_at_first)


# Test 5 — a TN for an id never armed (no prior entry) writes a fresh cleared tombstone, not a
# pure no-op — and a LATER ack for that same id must not arm it either.
def test_tn_with_no_prior_entry_writes_tombstone():
    print("\n[Test 5] TN with no prior arm writes a cleared tombstone (never a pure no-op)")
    _reset_module_state()
    with tempfile.TemporaryDirectory() as tmp_root:
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root}, clear=False):
            _update_pending_bg_state({0: [_tn_chunk("task_orphan1")]}, "main")
            state = _read_state_file()
            entry = state.get("task_orphan1", {})
            check("orphan TN creates a cleared tombstone", entry.get("status") == "cleared")
            check("tombstone has no armed_at (never armed by us)", "armed_at" not in entry)
            # A later ack resighting for the same id must not arm it.
            _update_pending_bg_state({1: [_ack_text("task_orphan1")]}, "main")
            state2 = _read_state_file()
        check("later ack does not arm the orphan-tombstoned id",
              state2.get("task_orphan1", {}).get("status") == "cleared")


# Test 6 — replay ordering: ack (lower index) and its TN (higher index) both land in the SAME
# call (the first request after a restart resends the whole history at once). Constructed with
# DESCENDING key-insertion order specifically so a missing sorted()-by-index would process the TN
# first (producing a no-armed_at orphan tombstone instead of a proper arm-then-clear).
def test_replay_ordering_single_request():
    print("\n[Test 6] Replay ordering — ack + TN in ONE call, must process ack first")
    _reset_module_state()
    with tempfile.TemporaryDirectory() as tmp_root:
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root}, clear=False):
            removed = {}
            removed[5] = [_tn_chunk("task_replay1")]
            removed[0] = [_ack_text("task_replay1")]  # inserted AFTER key 5 — dict iteration order != sorted order
            check("dict insertion order is descending (test validity)", list(removed.keys()) == [5, 0])
            _update_pending_bg_state(removed, "main")
            state = _read_state_file()
        entry = state.get("task_replay1", {})
        check("final status == cleared", entry.get("status") == "cleared")
        check("armed_at IS present -> ack was processed before TN despite insertion order",
              bool(entry.get("armed_at")))
        check("no 'no_prior_arm' artifact — arm genuinely happened first", "armed_at" in entry and "cleared_at" in entry)


# Test 7 — 24h tombstone pruning on write; pending entries are never pruned.
def test_prunes_stale_tombstones_on_write():
    print("\n[Test 7] 24h tombstone pruning on write (pending entries exempt)")
    with tempfile.TemporaryDirectory() as tmp_root:
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root}, clear=False):
            def _iso(dt):
                return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'

            now = datetime.now(timezone.utc)
            old_ts = _iso(now - timedelta(hours=25))
            fresh_ts = _iso(now - timedelta(hours=1))
            seed_state = {
                "task_old_tombstone": {"status": "cleared", "cleared_at": old_ts},
                "task_fresh_tombstone": {"status": "cleared", "cleared_at": fresh_ts},
                "task_old_pending": {"status": "pending", "armed_at": old_ts},
            }
            ok = _write_state_file(seed_state)
            check("seed write succeeded", ok)
            state = _read_state_file()
        check("tombstone older than 24h pruned", "task_old_tombstone" not in state)
        check("tombstone younger than 24h kept", "task_fresh_tombstone" in state)
        check("pending entry NEVER pruned by proxy, however old armed_at is",
              "task_old_pending" in state and state["task_old_pending"]["status"] == "pending")


# Test 8 — failure isolation: corrupt state-file JSON degrades to a no-op, real
# ProxyAddon.request() still forwards the request.
def test_failure_isolation():
    print("\n[Test 8] Failure isolation — corrupt state file, real ProxyAddon.request() path")
    _reset_module_state()
    with tempfile.TemporaryDirectory() as tmp_root:
        state_path = Path(tmp_root) / "src" / "logs" / "pending_bg_tasks.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{not valid json", encoding="utf-8")
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root}, clear=False):
            try:
                _update_pending_bg_state({0: [_ack_text("task_corrupt1")]}, "main")
                raised = False
            except Exception:
                raised = True
        check("corrupt state file -> no raise", not raised)

        addon = _make_main_addon(tmp_root)
        flow = _FakeFlow(_payload_with_user_text(_ack_text("task_corrupt2")))
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root, "PROXY_PROJECT_PATH": str(WORKTREE_ROOT)}, clear=False):
            addon.request(flow)
        check("real ProxyAddon.request() still forwards with a corrupt state file",
              flow.request.content is not None and len(flow.request.content) > 0)


# Test 9 — real end-to-end arm via ProxyAddon.request(), main context.
def test_real_request_arms_pending():
    print("\n[Test 9] Real ProxyAddon.request() — main context arms pending state")
    _reset_module_state()
    with tempfile.TemporaryDirectory() as tmp_root:
        addon = _make_main_addon(tmp_root)
        flow = _FakeFlow(_payload_with_user_text(_ack_text("task_e2e_arm")))
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root, "PROXY_PROJECT_PATH": str(WORKTREE_ROOT)}, clear=False):
            addon.request(flow)
            state = _read_state_file()
        check("real request path armed task_e2e_arm", state.get("task_e2e_arm", {}).get("status") == "pending")
        check("request still forwarded", flow.request.content is not None)


# Test 10 — real end-to-end clear via ProxyAddon.request(), main context, full genuine wire text.
def test_real_request_clears_pending():
    print("\n[Test 10] Real ProxyAddon.request() — main context clears pending state")
    _reset_module_state()
    with tempfile.TemporaryDirectory() as tmp_root:
        addon = _make_main_addon(tmp_root)
        with mock.patch.dict(os.environ, {"MONITOR_CC_ROOT": tmp_root, "PROXY_PROJECT_PATH": str(WORKTREE_ROOT)}, clear=False):
            addon.request(_FakeFlow(_payload_with_user_text(_ack_text("task_e2e_clear"))))
            addon.request(_FakeFlow(_payload_with_user_text(_full_tn_text("task_e2e_clear"))))
            state = _read_state_file()
        check("real request path cleared task_e2e_clear",
              state.get("task_e2e_clear", {}).get("status") == "cleared")


# Test 11 — worker context via real ProxyAddon.request() never writes state (entry-point level).
def test_real_request_worker_never_writes():
    print("\n[Test 11] Real ProxyAddon.request() — worker context never writes state")
    _reset_module_state()
    with tempfile.TemporaryDirectory() as tmp_root:
        with mock.patch.dict(os.environ, {"PROXY_LOG_ID": "worker_deadbeef_probe-worker_1786100000",
                                           "PROXY_PROJECT_PATH": str(WORKTREE_ROOT),
                                           "MONITOR_CC_ROOT": tmp_root}, clear=False):
            addon = ProxyAddon()
            addon._worker_context = _derive_worker_context()
            addon.request(_FakeFlow(_payload_with_user_text(_ack_text("task_e2e_worker"))))
            state_path = _resolve_pending_bg_state_file()
        check("worker_context derived correctly", addon._worker_context.startswith("worker:"))
        check("no state file created via real worker request", not state_path.exists())


# Test 12 — wording sharpening: main-context replacement differs from the unchanged default/
# worker wording; worker/default wording is byte-identical to the pre-existing text.
def test_wording_main_vs_worker():
    print("\n[Test 12] Launch-ack replacement wording — main vs worker/default")
    ack = _ack_text("task_wording1")
    default_text, _ = _strip_bg_launch_ack(ack)
    main_text, _ = _strip_bg_launch_ack(ack, is_main=True)
    check("default (is_main=False) wording unchanged", default_text.startswith(_BG_LAUNCH_ACK_MSG))
    check("main wording starts with the sharpened message", main_text.startswith(_BG_LAUNCH_ACK_MSG_MAIN))
    check("main wording differs from default wording", main_text != default_text)
    check("main wording explicitly mentions going idle", "idle" in _BG_LAUNCH_ACK_MSG_MAIN.lower())
    check("main wording explicitly mentions this task's ID", "task ID" in _BG_LAUNCH_ACK_MSG_MAIN)
    check("main wording still carries the recovered ID line", "ID: task_wording1" in main_text)


# ORCHESTRATOR

def run_probe_workflow():
    print("=" * 70)
    print("pending_bg_state probe — Milestone 2 proxy-side pending-task tracking")
    print("=" * 70)
    test_arm_writes_pending()
    test_tn_clears_pending()
    test_worker_context_never_writes()
    test_resighted_cleared_id_stays_cleared()
    test_tn_with_no_prior_entry_writes_tombstone()
    test_replay_ordering_single_request()
    test_prunes_stale_tombstones_on_write()
    test_failure_isolation()
    test_real_request_arms_pending()
    test_real_request_clears_pending()
    test_real_request_worker_never_writes()
    test_wording_main_vs_worker()

    total = len(_RESULTS)
    passed = sum(1 for _, ok in _RESULTS if ok)
    print("\n" + "=" * 70)
    print(f"{passed}/{total} checks passed")
    print("=" * 70)

    _write_report(passed, total)
    return passed == total


def _write_report(passed, total):
    md_dir = WORKTREE_ROOT / "dev" / "timer-loop" / "md"
    md_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = md_dir / f"p2_pending_bg_state_probe_{stamp}.md"
    lines = [
        f"# P2 — pending_bg_state probe run ({datetime.now(timezone.utc).isoformat()})",
        "",
        f"**Result: {passed}/{total} checks passed**",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for label, ok in _RESULTS:
        lines.append(f"| {label} | {'PASS' if ok else 'FAIL'} |")
    out_path.write_text("\n".join(lines) + "\n")
    print(f"\nReport written to: {out_path}")


if __name__ == "__main__":
    ok = run_probe_workflow()
    sys.exit(0 if ok else 1)
