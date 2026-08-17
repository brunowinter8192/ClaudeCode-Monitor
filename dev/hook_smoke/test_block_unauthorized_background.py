# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/block_unauthorized_background.py"

# (description, command, run_in_background, expected_rewritten_bg)
# expected_rewritten_bg:
#   None  = hook emits no output (pass-through, command stays background or already foreground)
#   False = hook emits rewrite flipping run_in_background to false (foreground-forced)
CASES = [
    # --- ALLOW: sleep-only forms — must NOT be foreground-forced (order-independence vs rewrite hook) ---
    ("sleep N && echo done — sleep-only form ALLOW",
     "sleep 300 && echo done", True, None),
    ("sleep N bare — sleep-only form ALLOW",
     "sleep 300", True, None),
    ("sleep N with custom echo text (fire-log actual) ALLOW",
     'sleep 45 && echo "bg-ack-probe done"', True, None),

    # --- ALLOW: worker-cli wait forms — canonical pull-based wake-up command ---
    ("worker-cli wait bare ALLOW",
     "worker-cli wait", True, None),
    ("worker-cli wait with project_path ALLOW",
     "worker-cli wait /path/to/project", True, None),
    ("worker-cli wait with --timeout ALLOW",
     "worker-cli wait --timeout 600", True, None),
    ("worker-cli wait with project_path + --timeout ALLOW",
     "worker-cli wait /path/to/project --timeout 600", True, None),

    # --- FORCE: former pipeline whitelists — no whitelist, must be foreground-forced ---
    ("reddit-cli index_subreddits — foreground-forced FORCE",
     "reddit-cli index_subreddits", True, False),
    ("workflow.py index-dir — foreground-forced FORCE",
     "workflow.py index-dir", True, False),

    # --- FORCE: genuine non-canonical background commands — must be foreground-forced ---
    ("./venv/bin/python script.py — non-canonical background FORCE",
     "./venv/bin/python script.py", True, False),
    ("rag-cli update_docs — original triggering incident FORCE",
     "rag-cli update_docs .", True, False),
    ("worker-cli wait && rag-cli index — chained, tail-guard rejects it FORCE",
     "worker-cli wait && rag-cli index docs", True, False),
    ("worker-cli waitfoo — not a word-boundary match on 'wait' FORCE",
     "worker-cli waitfoo", True, False),

    # --- PASS: already foreground — hook is no-op ---
    ("./venv/bin/python script.py foreground — no output PASS",
     "./venv/bin/python script.py", False, None),
]


# ORCHESTRATOR

def test_block_unauthorized_background_workflow() -> None:
    failures = []
    for desc, cmd, rb, expected_bg in CASES:
        got_bg = _run_hook(cmd, rb)
        ok = got_bg == expected_bg
        status = "OK  " if ok else "FAIL"
        print(f"  [{status}] {desc}: rewritten_bg={got_bg!r} (expected {expected_bg!r})")
        if not ok:
            failures.append(desc)
    print()
    if failures:
        print(f"FAILED: {len(failures)} case(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"All {len(CASES)} tests passed.")


# FUNCTIONS

# Run hook; return run_in_background value from rewrite output, or None if hook emits no output
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
    if result.returncode == 0 and result.stdout.strip():
        try:
            data = json.loads(result.stdout)
            return data["hookSpecificOutput"]["updatedInput"]["run_in_background"]
        except (KeyError, json.JSONDecodeError):
            pass
    return None


if __name__ == "__main__":
    test_block_unauthorized_background_workflow()
