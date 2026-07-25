# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/rewrite_websearch_scrape_noise.py"

# (description, command, expected_rewrite_or_None)
# None = no rewrite expected (hook should emit nothing and exit 0)
CASES = [
    # --- positive: noise inside the scrape_url segment is stripped ---
    (
        "> /tmp/file 2>&1 redirect — strip (the actual real-world culprit)",
        'websearch scrape_url "https://x.com/a" > /tmp/scrape.md 2>&1',
        'websearch scrape_url "https://x.com/a"',
    ),
    (
        "| head -45 — strip",
        'websearch scrape_url "https://x.com/a" | head -45',
        'websearch scrape_url "https://x.com/a"',
    ),
    (
        "2>&1 | head — strip both",
        'websearch scrape_url "https://x.com/a" 2>&1 | head -45',
        'websearch scrape_url "https://x.com/a"',
    ),
    (
        "| tail -50 — strip",
        'websearch scrape_url "https://x.com/a" | tail -50',
        'websearch scrape_url "https://x.com/a"',
    ),
    (
        "| sed -n 1,40p — strip",
        'websearch scrape_url "https://x.com/a" | sed -n "1,40p"',
        'websearch scrape_url "https://x.com/a"',
    ),
    (
        "> /tmp/out redirect alone — strip",
        'websearch scrape_url "https://x.com/a" > /tmp/out.txt',
        'websearch scrape_url "https://x.com/a"',
    ),
    (
        "cd /path && scrape_url ... | head — strip pipe, keep cd chain",
        'cd /path && websearch scrape_url "https://x.com/a" | head',
        'cd /path && websearch scrape_url "https://x.com/a"',
    ),
    (
        "scrape_url ... > f ; echo done — strip redirect, keep trailing chain",
        'websearch scrape_url "https://x.com/a" > /tmp/o.md ; echo done',
        'websearch scrape_url "https://x.com/a" ; echo done',
    ),
    (
        "scrape_url ... | head || echo fail — strip pipe, keep || chain",
        'websearch scrape_url "https://x.com/a" | head || echo fail',
        'websearch scrape_url "https://x.com/a" || echo fail',
    ),
    # --- negative: nothing to strip, hook is no-op ---
    (
        "bare scrape_url — no-op",
        'websearch scrape_url "https://x.com/a"',
        None,
    ),
    (
        "cd /path && scrape_url ... bare — no-op (chain preserved)",
        'cd /path && websearch scrape_url "https://x.com/a"',
        None,
    ),
    (
        "scrape_url ... ; bd list — no-op (trailing chain, no pipe in segment)",
        'websearch scrape_url "https://x.com/a" ; bd list',
        None,
    ),
    (
        "search_web | head — out of scope, no-op",
        'websearch search_web "rag chunking" | head -40',
        None,
    ),
    (
        "search_engine_drilldown | head — out of scope, no-op",
        'websearch search_engine_drilldown "x" --engine duckduckgo | head',
        None,
    ),
    (
        "download_pdf > file — out of scope, no-op",
        'websearch download_pdf "https://x.com/a.pdf" > /tmp/log.txt',
        None,
    ),
    (
        "scrape_url inside quoted echo — no-op (token in string, not active)",
        'echo "websearch scrape_url foo | head"',
        None,
    ),
]


# ORCHESTRATOR

# Run all cases and print results; exit 1 if any fail
def test_rewrite_websearch_scrape_noise_workflow() -> None:
    failures = []
    for desc, cmd, expected_rewrite in CASES:
        exit_code, rewrite = _run_hook(cmd)
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

# Invoke the hook script as subprocess; feed payload via stdin; return (exit_code, rewritten_command_or_None)
def _run_hook(command: str):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    proc = subprocess.run(
        ["python3", HOOK],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
    )
    rewrite = None
    if proc.stdout.strip():
        try:
            out = json.loads(proc.stdout)
            rewrite = out.get("hookSpecificOutput", {}).get("updatedInput", {}).get("command")
        except json.JSONDecodeError:
            pass
    return proc.returncode, rewrite


if __name__ == "__main__":
    test_rewrite_websearch_scrape_noise_workflow()
