#!/usr/bin/env python3
"""
Smoke test for block_timer_pending_bg.py (Milestone 3 — src/proxy/pending_bg_state.py's
enforcement hook).

Three layers: (1) decide() unit cases with an injected state_fn stub — no real file I/O; (2) real
stdin entry-point via subprocess, driving a genuine pending_bg_tasks.json under a scoped
MONITOR_CC_ROOT tempdir, cwd deliberately OUTSIDE any .claude/worktrees/ path (this worktree's own
path contains that fragment — running the subprocess from here would always hit the hook's own
worktree exemption and mask every block/allow case under test); (3) a dedicated worktree-exemption
test with cwd INSIDE a .claude/worktrees/ path and a state file that WOULD block if not exempted;
(4) a static hook_setup._HOOK_SCRIPTS registration check (position + count), same verification
method used to confirm the 2026-07-21 block_concurrent_timer.py removal.

Usage: python3 dev/hook_smoke/test_block_timer_pending_bg.py
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src', 'hooks'))
from block_timer_pending_bg import decide

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = str(WORKTREE_ROOT / "src" / "hooks" / "block_timer_pending_bg.py")

_TARGET = "sleep 3300 && echo done"

_results = []


def check(label, condition):
    _results.append((label, bool(condition)))
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}")
    return condition


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def _stub(state):
    def fn():
        return state
    return fn


def _stub_raises():
    def fn():
        raise RuntimeError("simulated read failure")
    return fn


# FUNCTIONS

# Layer 1 — decide() unit cases, no real file I/O.
def test_decide_unit_cases():
    print("\n[Layer 1] decide() unit cases")
    now = datetime.now(timezone.utc)
    fresh_ts = _iso(now - timedelta(minutes=4))
    stale_ts = _iso(now - timedelta(hours=2))
    boundary_exact_ts = _iso(now - timedelta(seconds=3600))
    boundary_under_ts = _iso(now - timedelta(seconds=3599))

    check("fresh pending -> block (id returned)",
          decide(_TARGET, True, _stub({"a1": {"status": "pending", "armed_at": fresh_ts}})) == ["a1"])
    check("cleared-only -> allow",
          decide(_TARGET, True, _stub({"a1": {"status": "cleared", "armed_at": fresh_ts, "cleared_at": fresh_ts}})) == [])
    check("stale pending (2h) -> allow",
          decide(_TARGET, True, _stub({"a1": {"status": "pending", "armed_at": stale_ts}})) == [])
    check("boundary: armed EXACTLY at 3600s -> allow (strictly-younger-than semantics)",
          decide(_TARGET, True, _stub({"a1": {"status": "pending", "armed_at": boundary_exact_ts}})) == [])
    check("boundary: armed 3599s (1s under threshold) -> block",
          decide(_TARGET, True, _stub({"a1": {"status": "pending", "armed_at": boundary_under_ts}})) == ["a1"])
    check("state_fn raises (missing/corrupt file) -> allow",
          decide(_TARGET, True, _stub_raises()) == [])
    check("non-dict state -> allow",
          decide(_TARGET, True, _stub(None)) == [])
    check("non-timer command -> allow",
          decide("rag-cli update_docs .", True, _stub({"a1": {"status": "pending", "armed_at": fresh_ts}})) == [])
    check("run_in_background=False -> allow",
          decide(_TARGET, False, _stub({"a1": {"status": "pending", "armed_at": fresh_ts}})) == [])
    check("bare 'sleep N' (no echo) -> block same as canonical form",
          decide("sleep 300", True, _stub({"a1": {"status": "pending", "armed_at": fresh_ts}})) == ["a1"])
    check("unparseable armed_at -> allow (per-entry fail-open)",
          decide(_TARGET, True, _stub({"a1": {"status": "pending", "armed_at": "not-a-timestamp"}})) == [])
    multi = decide(_TARGET, True, _stub({
        "a1": {"status": "pending", "armed_at": fresh_ts},
        "a2": {"status": "pending", "armed_at": stale_ts},
        "a3": {"status": "cleared", "armed_at": fresh_ts, "cleared_at": fresh_ts},
        "a4": {"status": "pending", "armed_at": fresh_ts},
    }))
    check("multiple entries -> only fresh-pending ones returned, sorted", multi == ["a1", "a4"])

    # --- project scoping (2026-08, cross-project false-block incident) ---
    check("foreign-project pending -> allow (task b4z5fzzao class)",
          decide(_TARGET, True,
                 _stub({"posts1": {"status": "pending", "armed_at": fresh_ts, "project": "posts"}}),
                 "websearch") == [])
    check("same-project pending -> block",
          decide(_TARGET, True,
                 _stub({"ws1": {"status": "pending", "armed_at": fresh_ts, "project": "websearch"}}),
                 "websearch") == ["ws1"])
    check("legacy entry with no 'project' field -> blocks every project (backward compat)",
          decide(_TARGET, True,
                 _stub({"legacy1": {"status": "pending", "armed_at": fresh_ts}}),
                 "some_other_project") == ["legacy1"])
    check("foreign-project pending, but expired -> allow (expiry checked before project)",
          decide(_TARGET, True,
                 _stub({"posts2": {"status": "pending", "armed_at": stale_ts, "project": "posts"}}),
                 "websearch") == [])
    check("same-project pending, but expired -> allow",
          decide(_TARGET, True,
                 _stub({"ws2": {"status": "pending", "armed_at": stale_ts, "project": "websearch"}}),
                 "websearch") == [])
    mixed = decide(_TARGET, True, _stub({
        "own1": {"status": "pending", "armed_at": fresh_ts, "project": "websearch"},
        "foreign1": {"status": "pending", "armed_at": fresh_ts, "project": "posts"},
        "legacy2": {"status": "pending", "armed_at": fresh_ts},
    }), "websearch")
    check("mixed own/foreign/legacy -> only own + legacy block", mixed == ["legacy2", "own1"])


# Run the real hook via stdin; env scopes MONITOR_CC_ROOT to tmp_root; cwd is caller-controlled
# (outside a worktree unless the test explicitly wants the exemption to fire).
def _run_hook(command, run_in_background, tmp_root, cwd):
    payload = json.dumps({
        "tool_name": "Bash",
        "session_id": "probe-session",
        "tool_input": {"command": command, "run_in_background": run_in_background},
    })
    env = dict(os.environ)
    env["MONITOR_CC_ROOT"] = tmp_root
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload.encode(), capture_output=True, cwd=cwd, env=env,
    )
    return result.returncode, result.stderr.decode()


def _seed_state(tmp_root, state):
    state_path = Path(tmp_root) / "src" / "logs" / "pending_bg_tasks.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return state_path


# Layer 2 — real stdin entry-point, cwd deliberately OUTSIDE any .claude/worktrees/ path.
def test_real_entrypoint():
    print("\n[Layer 2] Real stdin entry-point (subprocess), cwd outside any worktree")
    now = datetime.now(timezone.utc)
    fresh_ts = _iso(now - timedelta(minutes=4))
    stale_ts = _iso(now - timedelta(hours=2))

    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as cwd:
        _seed_state(tmp_root, {"real1": {"status": "pending", "armed_at": fresh_ts}})
        code, stderr = _run_hook(_TARGET, True, tmp_root, cwd)
        check("fresh pending -> exit 2", code == 2)
        check("block message names the id", "real1" in stderr)
        check("block message states an age ('ago')", "ago" in stderr)
        check("block message instructs going idle", "idle" in stderr.lower())

    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as cwd:
        _seed_state(tmp_root, {"real1": {"status": "cleared", "armed_at": fresh_ts, "cleared_at": fresh_ts}})
        code, stderr = _run_hook(_TARGET, True, tmp_root, cwd)
        check("cleared-only -> exit 0, no stderr", code == 0 and stderr == "")

    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as cwd:
        _seed_state(tmp_root, {"real1": {"status": "pending", "armed_at": stale_ts}})
        code, stderr = _run_hook(_TARGET, True, tmp_root, cwd)
        check("stale pending (>3600s) -> exit 0", code == 0 and stderr == "")

    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as cwd:
        # no state file written at all
        code, stderr = _run_hook(_TARGET, True, tmp_root, cwd)
        check("missing state file -> exit 0 (fail-open)", code == 0 and stderr == "")

    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as cwd:
        state_path = Path(tmp_root) / "src" / "logs" / "pending_bg_tasks.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{not valid json", encoding="utf-8")
        code, stderr = _run_hook(_TARGET, True, tmp_root, cwd)
        check("corrupt state file -> exit 0 (fail-open)", code == 0 and stderr == "")

    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as cwd:
        _seed_state(tmp_root, {"real1": {"status": "pending", "armed_at": fresh_ts}})
        code, stderr = _run_hook("rag-cli update_docs .", True, tmp_root, cwd)
        check("non-timer command, fresh pending present -> exit 0 (not gated by pending state)",
              code == 0 and stderr == "")

    # --- project scoping (2026-08) via real cwd-basename derivation, subprocess entry-point ---
    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as outer:
        ws_cwd = Path(outer) / "Websearch"
        ws_cwd.mkdir()
        _seed_state(tmp_root, {"posts_task": {"status": "pending", "armed_at": fresh_ts, "project": "posts"}})
        code, stderr = _run_hook(_TARGET, True, tmp_root, str(ws_cwd))
        check("real entry-point: foreign-project (posts) pending, cwd=Websearch -> exit 0 (allow)",
              code == 0 and stderr == "")

    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as outer:
        ws_cwd = Path(outer) / "Websearch"
        ws_cwd.mkdir()
        _seed_state(tmp_root, {"ws_task": {"status": "pending", "armed_at": fresh_ts, "project": "websearch"}})
        code, stderr = _run_hook(_TARGET, True, tmp_root, str(ws_cwd))
        check("real entry-point: same-project pending, cwd=Websearch normalizes to 'websearch' -> exit 2 (block)",
              code == 2 and "ws_task" in stderr)

    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as outer:
        ws_cwd = Path(outer) / "Websearch"
        ws_cwd.mkdir()
        _seed_state(tmp_root, {"legacy_task": {"status": "pending", "armed_at": fresh_ts}})
        code, stderr = _run_hook(_TARGET, True, tmp_root, str(ws_cwd))
        check("real entry-point: legacy no-project entry -> exit 2 (blocks regardless of cwd)",
              code == 2 and "legacy_task" in stderr)

    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as cwd:
        _seed_state(tmp_root, {"real1": {"status": "pending", "armed_at": fresh_ts}})
        code, stderr = _run_hook(_TARGET, False, tmp_root, cwd)
        check("run_in_background=False, fresh pending present -> exit 0", code == 0 and stderr == "")


# Layer 3 — worktree exemption: cwd contains '.claude/worktrees/' AND a fresh pending entry exists
# (would block if not exempted) -> must still allow.
def test_worktree_exemption():
    print("\n[Layer 3] Worktree-cwd exemption (would otherwise block)")
    now = datetime.now(timezone.utc)
    fresh_ts = _iso(now - timedelta(minutes=1))
    with tempfile.TemporaryDirectory() as tmp_root, tempfile.TemporaryDirectory() as outer:
        fake_worktree_cwd = Path(outer) / ".claude" / "worktrees" / "fake-worker"
        fake_worktree_cwd.mkdir(parents=True)
        _seed_state(tmp_root, {"real1": {"status": "pending", "armed_at": fresh_ts}})
        code, stderr = _run_hook(_TARGET, True, tmp_root, str(fake_worktree_cwd))
        check("worktree cwd + fresh pending -> exit 0 (exemption fires)", code == 0 and stderr == "")


# Layer 4 — static hook_setup._HOOK_SCRIPTS registration check.
def test_hook_setup_registration():
    print("\n[Layer 4] hook_setup._HOOK_SCRIPTS registration")
    import importlib
    sys.path.insert(0, str(WORKTREE_ROOT / "src" / "hooks"))
    hook_setup = importlib.import_module("hook_setup")
    importlib.reload(hook_setup)
    names = [n for n, _ in hook_setup._HOOK_SCRIPTS]
    check("block_timer_pending_bg.py present exactly once", names.count("block_timer_pending_bg.py") == 1)
    idx = names.index("block_timer_pending_bg.py")
    check("immediately after block_timer_no_worker_working.py",
          idx > 0 and names[idx - 1] == "block_timer_no_worker_working.py")
    check("immediately before rewrite_background_sleep.py",
          idx + 1 < len(names) and names[idx + 1] == "rewrite_background_sleep.py")
    check("registered under Bash matcher",
          hook_setup._HOOK_SCRIPTS[idx][1] == "Bash")


# ORCHESTRATOR

def run_smoke_workflow() -> None:
    print("=" * 70)
    print("block_timer_pending_bg.py smoke suite — Milestone 3 enforcement hook")
    print("=" * 70)
    test_decide_unit_cases()
    test_real_entrypoint()
    test_worktree_exemption()
    test_hook_setup_registration()

    total = len(_results)
    passed = sum(1 for _, ok in _results if ok)
    print(f"\n{passed}/{total} passed")
    if passed != total:
        print("FAILED:")
        for label, ok in _results:
            if not ok:
                print(f"  - {label}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    run_smoke_workflow()
