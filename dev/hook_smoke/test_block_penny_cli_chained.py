# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/block_penny_cli_chained.py"

CASES = [
    # (description, command, expected_exit_code)
    # --- true positives: must block ---
    ("real-world chained incident BLOCK",
     'gcommit "..." && penny-cli --klasse "X" 2>&1 | sed -n \'/^Klasse/,$p\'', 2),
    ("piped to head BLOCK",
     'penny-cli --klasse "X" | head', 2),
    ("redirect to file BLOCK",
     'penny-cli --klasse "X" > out.txt', 2),
    ("leading cd guard still BLOCK (no relaxation here)",
     'cd /x && penny-cli --klasse "X"', 2),
    ("cross-CLI chain still BLOCK (no known-CLI relaxation here)",
     'rag-cli search q c && penny-cli --klasse "X"', 2),
    ("command substitution wrapping penny-cli BLOCK",
     'OUT=$(penny-cli --klasse "X")', 2),
    ("substitution as an argument to penny-cli itself BLOCK",
     'penny-cli --klasse "$(echo X)"', 2),
    # --- allowed: must pass ---
    ("standalone PASS",
     'penny-cli --klasse "X"', 0),
    ("env-prefixed standalone PASS",
     'FOO=1 penny-cli --klasse "X"', 0),
    ("path substring in ls PASS",
     'ls ~/Documents/ai/haendler/penny/bin/penny-cli', 0),
    ("path substring in ln -sf PASS",
     'ln -sf ~/Documents/ai/haendler/penny/bin/penny-cli ~/.local/bin/penny-cli', 0),
    ("no penny-cli at all PASS",
     'ls -la', 0),
]


# ORCHESTRATOR

def test_block_penny_cli_chained_workflow() -> None:
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
    test_block_penny_cli_chained_workflow()
