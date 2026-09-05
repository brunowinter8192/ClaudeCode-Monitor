# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/block_cli_chained.py"

CASES = [
    # (description, command, expected_exit_code)

    # --- rule 1: pipe after a known-CLI segment (any of the 8 CLIs, any subcommand) ---
    ("rag-cli search piped to head BLOCK",
     'rag-cli search "x" coll | head -40', 2),
    ("gh-cli get_file_content (unprotected subcommand) piped BLOCK — rule 1 is universal",
     "gh-cli get_file_content owner repo path.py | head -80", 2),
    ("worker-cli kill (unprotected subcommand) piped BLOCK",
     "worker-cli kill chore-fridge 2>&1 | tail -5", 2),
    ("linkedin piped to head BLOCK",
     "linkedin --help 2>&1 | head -40", 2),
    ("penny-cli piped BLOCK",
     'penny-cli --klasse "X" | head', 2),
    ("duallog expand piped to head BLOCK",
     "duallog expand s 1 --before 0 --after 0 | head -60", 2),
    ("reddit-cli search_subreddits piped BLOCK",
     'reddit-cli search_subreddits "q" | head', 2),
    ("for-loop over get_issue, one iteration piped BLOCK",
     "for n in 5 62; do echo \"#$n\"; gh-cli get_issue o r $n | sed -n '/^---/,$p'; done", 2),

    # --- rule 2: redirect on a PROTECTED subcommand ---
    ("rag-cli search redirect to file BLOCK",
     'rag-cli search "x" coll > /tmp/out.txt', 2),
    ("gh-cli get_issue redirect BLOCK",
     "gh-cli get_issue owner repo 5 > /tmp/out.txt", 2),
    ("gh-cli list_issues 2>&1 alone (no pipe) BLOCK",
     "gh-cli list_issues owner repo 2>&1", 2),
    ("worker-cli capture redirect BLOCK",
     "worker-cli capture janitor > /tmp/out.txt", 2),
    ("websearch scrape_url redirect BLOCK",
     "websearch scrape_url URL > /tmp/f.md 2>&1", 2),
    ("duallog sessions redirect BLOCK (every subcommand protected)",
     "duallog sessions > /tmp/out.txt", 2),
    ("linkedin get_messages redirect BLOCK (every subcommand protected)",
     "linkedin get_messages --days 3 > /tmp/out.txt", 2),
    ("penny-cli redirect BLOCK (no subcommand, whole invocation protected)",
     'penny-cli --klasse "X" > out.txt', 2),
    ("reddit-cli search_subreddits redirect BLOCK",
     'reddit-cli search_subreddits "q" > /tmp/out.txt', 2),
    ("bare 2> on protected subcommand does NOT count as a redirect PASS",
     "gh-cli list_issues owner repo 2>/dev/null || true", 0),
    ("unprotected rag-cli index redirect stays allowed PASS (no readback)",
     "rag-cli index --collection x > /tmp/log 2>&1", 0),
    ("unprotected worker-cli status redirect stays allowed PASS",
     "worker-cli status janitor > /tmp/status.txt", 0),
    ("unprotected reddit-cli index_subreddits redirect stays allowed PASS",
     "reddit-cli index_subreddits q sub1 sub2 > /tmp/x.log", 0),

    # --- rule 3: same-call readback of a CLI's own redirected file ---
    ("the milestone's canonical incident BLOCK",
     "rag-cli update_docs . > /tmp/ragsync.txt 2>&1; tail -12 /tmp/ragsync.txt", 2),
    ("readback via head BLOCK",
     "gh-cli download_files o r a.py > /tmp/dl.log 2>&1; head -20 /tmp/dl.log", 2),
    ("readback via cat BLOCK",
     "worker-cli status janitor > /tmp/s.txt; cat /tmp/s.txt", 2),
    ("readback of a DIFFERENT file PASS (no target match)",
     "rag-cli index --collection x > /tmp/a.log 2>&1; tail -5 /tmp/b.log", 0),
    ("redirect with no same-call readback stays allowed PASS",
     "rag-cli index --collection x > /tmp/a.log 2>&1; git status --short", 0),

    # --- allowed: chaining with ; or && is fine, for any CLI, with any other command ---
    ("mkdir before rag-cli index PASS (no allowlist of chain segments)",
     "mkdir -p x && rag-cli index --collection x", 0),
    ("ls/echo before gh-cli get_issue PASS",
     'ls ~/foo ; echo "=== issue ==="; gh-cli get_issue owner repo 9', 0),
    ("penny-cli chained with && PASS (isolation retired)",
     'echo test && penny-cli --klasse "Basis Trockenware"', 0),
    ("cd guard before rag-cli search PASS (no redirect, no pipe)",
     'cd /tmp && rag-cli search "x" coll', 0),
    ("cross-CLI chain, both protected, no pipe/redirect PASS",
     "gh-cli get_issue o r 5 && worker-cli capture janitor", 0),
    ("for-loop over get_issue with no pipe/redirect PASS",
     'for n in 62 61 59; do echo "=== #$n ==="; gh-cli get_issue o r $n; done', 0),
    ("duallog path-substring FP PASS (not a real duallog invocation)",
     "cat ~/Meta/iterative-dev/skills/iterative-dev-duallog/SKILL.md | grep -n msgs", 0),
    ("worker-cli status/name substring PASS (not a real duallog invocation)",
     "worker-cli status duallog-search-chars; git -C .claude/worktrees/duallog-search-chars log integration..HEAD", 0),
    ("no known CLI at all PASS",
     "ls -la && git status --short", 0),
]


# ORCHESTRATOR

def test_block_cli_chained_workflow() -> None:
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
    test_block_cli_chained_workflow()
