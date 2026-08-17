# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/rewrite_background_sleep.py"

# (description, command, run_in_background, expected_rewrite_or_None)
# None = no rewrite expected (hook should emit nothing and exit 0)
CASES = [
    # --- positive: any sleep-only background command → rewrite to worker-cli wait ---
    (
        "sleep 300 background timer → rewrite to worker-cli wait",
        "sleep 300 && echo done",
        True,
        "worker-cli wait",
    ),
    (
        "sleep 5 background timer → rewrite to worker-cli wait",
        "sleep 5 && echo done",
        True,
        "worker-cli wait",
    ),
    (
        "sleep 1200 background timer → rewrite to worker-cli wait",
        "sleep 1200 && echo done",
        True,
        "worker-cli wait",
    ),
    (
        "old canonical sleep 3300 && echo done — also a stale habit now, rewrite",
        "sleep 3300 && echo done",
        True,
        "worker-cli wait",
    ),
    (
        "bare sleep 300 — bare sleep, rewrite to worker-cli wait",
        "sleep 300",
        True,
        "worker-cli wait",
    ),
    (
        "sleep 45 with custom echo text (fire-log actual incident) → rewrite",
        'sleep 45 && echo "bg-ack-probe done"',
        True,
        "worker-cli wait",
    ),
    # --- negative A: foreground (run_in_background=false) → no rewrite ---
    (
        "foreground sleep 300 — no background flag, no rewrite",
        "sleep 300 && echo done",
        False,
        None,
    ),
    # --- negative B: already the canonical worker-cli wait — no rewrite (not a sleep pattern) ---
    (
        "worker-cli wait bare — already canonical, no rewrite",
        "worker-cli wait",
        True,
        None,
    ),
    (
        "worker-cli wait with project_path + --timeout — already canonical, no rewrite",
        "worker-cli wait /path/to/project --timeout 600",
        True,
        None,
    ),
    # --- negative C: non-canonical command (not sleep N && echo done form) → no rewrite ---
    (
        "rag-cli background — not canonical form, no rewrite",
        "rag-cli update_docs .",
        True,
        None,
    ),
    # --- negative D: sleep but wrong chain target (not echo done) → no rewrite ---
    (
        "sleep 300 && rag-cli — not echo done form, no rewrite",
        "sleep 300 && rag-cli server list",
        True,
        None,
    ),
]


# ORCHESTRATOR

# Run all cases and print results; exit 1 if any fail
def test_rewrite_background_sleep_workflow() -> None:
    failures = []
    for desc, cmd, rb, expected_rewrite in CASES:
        exit_code, rewrite = _run_hook(cmd, rb)
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

# Run hook with given command and run_in_background flag; return (exit_code, rewritten_command_or_None)
def _run_hook(command: str, run_in_background: bool):
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command, "run_in_background": run_in_background},
    })
    result = subprocess.run(
        ["python3", HOOK],
        input=payload.encode(),
        capture_output=True,
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
