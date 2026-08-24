# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/block_websearch_scrape_chained.py"

CASES = [
    # (description, command, expected_exit_code)
    # --- true positives: must block (redirect on the protected segment) ---
    ("proven incident: redirect + dependent wc/head chain BLOCK",
     "websearch scrape_url https://x.com > /tmp/f.md 2>&1; wc -l /tmp/f.md; head -120 /tmp/f.md", 2),
    ("redirect to file BLOCK",
     "websearch scrape_url https://x.com > /tmp/out.md", 2),
    ("append redirect BLOCK",
     "websearch scrape_url https://x.com >> /tmp/out.md", 2),
    ("2>&1 redirect BLOCK",
     "websearch scrape_url https://x.com 2>&1", 2),
    # --- true positives: must block (foreign, non-CLI segment) ---
    ("piped to head BLOCK",
     "websearch scrape_url https://x.com | head -50", 2),
    ("piped to grep BLOCK",
     "websearch scrape_url https://x.com | grep foo", 2),
    ("chained with echo BLOCK",
     "websearch scrape_url https://x.com && echo done", 2),
    ("chained after unrelated command BLOCK",
     "echo start && websearch scrape_url https://x.com", 2),
    ("chained with tail via semicolon BLOCK",
     "websearch scrape_url https://x.com ; tail -5 /tmp/x.md", 2),
    # --- allowed: standalone ---
    ("standalone PASS",
     "websearch scrape_url https://x.com", 0),
    ("search_web untouched (different subcommand) PASS",
     'websearch search_web "query"', 0),
    # --- allowed: cross-CLI and same-tool combos (2026-08 relax) ---
    ("two scrape_url calls chained PASS (cross-CLI relax)",
     "websearch scrape_url https://a.com && websearch scrape_url https://b.com", 0),
    ("scrape_url + rag-cli search chained PASS (cross-CLI relax)",
     'websearch scrape_url https://x.com && rag-cli search "q" coll', 0),
    ("scrape_url + gh-cli get_issue chained PASS (cross-CLI relax)",
     "websearch scrape_url https://x.com && gh-cli get_issue owner/repo 5", 0),
    ("cd guard before scrape_url PASS",
     "cd /tmp && websearch scrape_url https://x.com", 0),
    # --- false-positive avoidance ---
    ("non-websearch command untouched PASS",
     "ls -la", 0),
    ("quoted mention shell-stripped PASS",
     'echo "websearch scrape_url https://x.com | grep foo"', 0),
]


# ORCHESTRATOR

def test_block_websearch_scrape_chained_workflow() -> None:
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
    test_block_websearch_scrape_chained_workflow()
