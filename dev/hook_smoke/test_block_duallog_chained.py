# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/block_duallog_chained.py"

CASES = [
    # (description, command, expected_exit_code)
    # --- true positives: must block (redirect/pipe on the protected segment) ---
    ("expand piped to head BLOCK (the trigger incident, first form)",
     "duallog expand s 1 --before 0 --after 0 | head -60", 2),
    ("expand piped to tail BLOCK (the trigger incident, second form)",
     "duallog expand s 1 --before 0 --after 0 | tail -25", 2),
    ("expand redirect to file BLOCK",
     "duallog expand s 1 > /tmp/out.txt", 2),
    # --- allowed: multi-call and cross-CLI chains, standalone ---
    ("two duallog calls chained PASS (same-tool combine)",
     "duallog sessions && duallog msgs x", 0),
    ("cd guard before search PASS",
     "cd /x && duallog search foo", 0),
    ("plain expand standalone PASS",
     "duallog expand s 5", 0),
]


# ORCHESTRATOR

def test_block_duallog_chained_workflow() -> None:
    failures = []
    for desc, cmd, expected in CASES:
        got = _run_hook(cmd)
        status = "OK  " if got == expected else "FAIL"
        print(f"  [{status}] {desc}: exit={got} (expected {expected})")
        if got != expected:
            failures.append(desc)

    malformed_got = _run_hook_raw(b"not valid json at all")
    status = "OK  " if malformed_got == 0 else "FAIL"
    print(f"  [{status}] malformed stdin payload fails open: exit={malformed_got} (expected 0)")
    if malformed_got != 0:
        failures.append("malformed stdin payload fails open")

    print()
    if failures:
        print(f"FAILED: {len(failures)} case(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"All {len(CASES) + 1} tests passed.")


# FUNCTIONS

# Run hook with given command string wrapped in a valid PreToolUse payload; return exit code
def _run_hook(command: str) -> int:
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
    })
    return _run_hook_raw(payload.encode())


# Run hook with raw bytes on stdin (used for the malformed-payload fail-open case); return exit code
def _run_hook_raw(stdin_bytes: bytes) -> int:
    result = subprocess.run(
        ["python3", HOOK],
        input=stdin_bytes,
        capture_output=True,
    )
    return result.returncode


if __name__ == "__main__":
    test_block_duallog_chained_workflow()
