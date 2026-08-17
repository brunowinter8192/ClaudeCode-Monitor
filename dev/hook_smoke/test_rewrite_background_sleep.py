# INFRASTRUCTURE
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# Absolute path — required so the subprocess's cwd (deliberately forced per-case below, incl. a
# worktree-shaped cwd) never affects where the hook script itself is found.
WORKTREE_ROOT = Path(__file__).resolve().parents[2]
HOOK = str(WORKTREE_ROOT / "src" / "hooks" / "rewrite_background_sleep.py")

# (description, command, run_in_background, expected_rewrite_or_None, cwd_kind)
# expected_rewrite_or_None: None = no rewrite expected (hook should emit nothing and exit 0)
# cwd_kind: "orchestrator" = plain non-worktree cwd (no .claude/worktrees/ fragment anywhere in
#           it — required so this suite's own on-disk worktree path can never leak in and mask
#           a case, see _ORCHESTRATOR_CWD below); "worktree" = cwd inside a .claude/worktrees/
#           path, proving the 2026-08 orchestrator-only guard actually fires.
CASES = [
    # --- positive (orchestrator cwd): any sleep-only background command → rewrite to worker-cli wait ---
    (
        "sleep 300 background timer → rewrite to worker-cli wait",
        "sleep 300 && echo done",
        True,
        "worker-cli wait",
        "orchestrator",
    ),
    (
        "sleep 5 background timer → rewrite to worker-cli wait",
        "sleep 5 && echo done",
        True,
        "worker-cli wait",
        "orchestrator",
    ),
    (
        "sleep 1200 background timer → rewrite to worker-cli wait",
        "sleep 1200 && echo done",
        True,
        "worker-cli wait",
        "orchestrator",
    ),
    (
        "old canonical sleep 3300 && echo done — also a stale habit now, rewrite",
        "sleep 3300 && echo done",
        True,
        "worker-cli wait",
        "orchestrator",
    ),
    (
        "bare sleep 300 — bare sleep, rewrite to worker-cli wait",
        "sleep 300",
        True,
        "worker-cli wait",
        "orchestrator",
    ),
    (
        "sleep 45 with custom echo text (fire-log actual incident) → rewrite",
        'sleep 45 && echo "bg-ack-probe done"',
        True,
        "worker-cli wait",
        "orchestrator",
    ),
    # --- negative A: foreground (run_in_background=false) → no rewrite ---
    (
        "foreground sleep 300 — no background flag, no rewrite",
        "sleep 300 && echo done",
        False,
        None,
        "orchestrator",
    ),
    # --- negative B: already the canonical worker-cli wait — no rewrite (not a sleep pattern) ---
    (
        "worker-cli wait bare — already canonical, no rewrite",
        "worker-cli wait",
        True,
        None,
        "orchestrator",
    ),
    (
        "worker-cli wait with project_path + --timeout — already canonical, no rewrite",
        "worker-cli wait /path/to/project --timeout 600",
        True,
        None,
        "orchestrator",
    ),
    # --- negative C: non-canonical command (not sleep N && echo done form) → no rewrite ---
    (
        "rag-cli background — not canonical form, no rewrite",
        "rag-cli update_docs .",
        True,
        None,
        "orchestrator",
    ),
    # --- negative D: sleep but wrong chain target (not echo done) → no rewrite ---
    (
        "sleep 300 && rag-cli — not echo done form, no rewrite",
        "sleep 300 && rag-cli server list",
        True,
        None,
        "orchestrator",
    ),
    # --- negative E (2026-08 live incident fix): worktree cwd → NEVER rewrite, worker sleeps stay sleeps ---
    (
        "bare sleep 300 from a WORKTREE cwd — orchestrator-only guard, no rewrite",
        "sleep 300",
        True,
        None,
        "worktree",
    ),
    (
        "sleep 3300 && echo done from a WORKTREE cwd — old canonical form, still no rewrite",
        "sleep 3300 && echo done",
        True,
        None,
        "worktree",
    ),
    (
        "foreground sleep from a WORKTREE cwd — no rewrite (already a no-op via the bg-flag gate)",
        "sleep 300 && echo done",
        False,
        None,
        "worktree",
    ),
]


# ORCHESTRATOR

# Run all cases and print results; exit 1 if any fail
def test_rewrite_background_sleep_workflow() -> None:
    with tempfile.TemporaryDirectory() as orchestrator_cwd, tempfile.TemporaryDirectory() as outer:
        # Plain tempdir — guaranteed no ".claude/worktrees/" fragment anywhere in the path.
        worktree_cwd = Path(outer) / ".claude" / "worktrees" / "fake-worker"
        worktree_cwd.mkdir(parents=True)
        cwd_by_kind = {"orchestrator": orchestrator_cwd, "worktree": str(worktree_cwd)}

        failures = []
        for desc, cmd, rb, expected_rewrite, cwd_kind in CASES:
            exit_code, rewrite = _run_hook(cmd, rb, cwd_by_kind[cwd_kind])
            ok = exit_code == 0 and rewrite == expected_rewrite
            status = "OK  " if ok else "FAIL"
            want = repr(expected_rewrite) if expected_rewrite is not None else "None (no output)"
            got  = repr(rewrite) if rewrite is not None else "None (no output)"
            print(f"  [{status}] {desc}")
            if not ok:
                print(f"           want: {want}")
                print(f"           got:  {got} (exit={exit_code})")
                failures.append(desc)
        print()
        if failures:
            print(f"FAILED: {len(failures)} case(s):")
            for f in failures:
                print(f"  - {f}")
            sys.exit(1)
        print(f"All {len(CASES)} tests passed.")


# FUNCTIONS

# Run hook with given command, run_in_background flag, and explicit cwd (never inherited — see
# module docstring on why); return (exit_code, rewritten_command_or_None)
def _run_hook(command: str, run_in_background: bool, cwd: str):
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command, "run_in_background": run_in_background},
    })
    result = subprocess.run(
        ["python3", HOOK],
        input=payload.encode(),
        capture_output=True,
        cwd=cwd,
    )
    rewrite = None
    if result.returncode == 0 and result.stdout.strip():
        try:
            data   = json.loads(result.stdout)
            rewrite = data["hookSpecificOutput"]["updatedInput"]["command"]
        except (KeyError, json.JSONDecodeError):
            rewrite = None
    return result.returncode, rewrite


if __name__ == "__main__":
    test_rewrite_background_sleep_workflow()
