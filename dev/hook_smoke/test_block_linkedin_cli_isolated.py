# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/block_linkedin_cli_isolated.py"

CASES = [
    # (description, command, expected_exit_code)
    # --- true positives: must block ---
    ("piped to grep BLOCK",
     "linkedin get_notifications | grep NEW", 2),
    ("piped to head BLOCK",
     "linkedin get_notifications | head -5", 2),
    ("piped to tail BLOCK",
     "linkedin get_messages --count 3 | tail -5", 2),
    ("piped to sed BLOCK",
     "linkedin get_messages | sed 's/x/y/'", 2),
    ("piped to awk BLOCK",
     "linkedin get_notifications | awk '{print}'", 2),
    ("piped to wc BLOCK",
     "linkedin get_messages | wc -l", 2),
    ("two linkedin calls chained with && BLOCK",
     "linkedin get_messages --count 3 && linkedin get_notifications", 2),
    ("two linkedin calls chained with ; BLOCK",
     "linkedin get_messages ; linkedin get_notifications", 2),
    ("chained with unrelated echo BLOCK",
     "linkedin get_messages && echo done", 2),
    ("chained after unrelated command BLOCK",
     "echo start && linkedin get_messages", 2),
    ("env-prefixed then piped BLOCK",
     "LINKEDIN_HEADED=1 linkedin get_messages | grep NEW", 2),
    # --- allowed: must pass ---
    ("standalone with --count PASS",
     "linkedin get_notifications --count 15", 0),
    ("standalone with --days PASS",
     "linkedin get_messages --days 3", 0),
    ("redirect to file, not a separator PASS",
     "linkedin get_messages > /tmp/out.txt", 0),
    ("env-prefixed standalone PASS (LINKEDIN_HEADED real usage, src/linkedin/browser.py)",
     "LINKEDIN_HEADED=1 linkedin get_messages", 0),
    # Pinned decision (explicitly requested): a bare `linkedin` with no subcommand is a
    # single standalone segment like any other — ALLOWED, not a special case to block.
    ("bare `linkedin` with no subcommand PASS (pinned decision)",
     "linkedin", 0),
    ("non-linkedin command untouched PASS",
     "ls -la", 0),
    # --- false-positive avoidance: must NOT be mistaken for a linkedin invocation ---
    ("repo dir named linkedin in a cd, unrelated cmd follows PASS",
     "cd /Users/brunowinter2000/Documents/ai/Meta/ClaudeCode/cli/linkedin && git status", 0),
    ("path segment cli/linkedin/cli.py PASS",
     "python3 cli/linkedin/cli.py get_messages", 0),
    ("word 'linkedin' as a grep argument PASS",
     "grep linkedin file.txt", 0),
    ("linkedin-prefixed different tool name PASS",
     "linkedin-web scrape", 0),
    ("quoted mention alone PASS shell-stripped",
     'echo "call linkedin later"', 0),
    ("quoted mention chained with unrelated cmd PASS shell-stripped",
     'echo "call linkedin later" && ls', 0),
    ("linkedin invocation text inside single quotes PASS shell-stripped",
     "echo 'linkedin get_messages | grep NEW'", 0),
]


# ORCHESTRATOR

def test_block_linkedin_cli_isolated_workflow() -> None:
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
    test_block_linkedin_cli_isolated_workflow()
