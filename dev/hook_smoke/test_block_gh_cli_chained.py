# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/block_gh_cli_chained.py"

CASES = [
    # (description, command, expected_exit_code)
    # --- true positives: must block ---
    ("search_repos piped to grep BLOCK",
     "gh-cli search_repos \"foo\" | grep bar", 2),
    ("search_code piped to head BLOCK",
     "gh-cli search_code \"x\" owner/repo | head -10", 2),
    ("get_repo_tree piped to tail BLOCK",
     "gh-cli get_repo_tree owner/repo | tail -5", 2),
    ("get_file_content piped to sed BLOCK",
     "gh-cli get_file_content owner/repo path | sed 's/x/y/'", 2),
    ("index_issues piped to grep BLOCK",
     "gh-cli index_issues \"q\" o/r | grep open", 2),
    ("index_discussions piped to wc BLOCK",
     "gh-cli index_discussions \"q\" o/r | wc -l", 2),
    ("index_releases piped to awk BLOCK",
     "gh-cli index_releases o/r | awk '{print}'", 2),
    ("list_issues piped to grep BLOCK (2026-08: no longer exempt)",
     "gh-cli list_issues o/r | grep open", 2),
    ("get_issue piped to head BLOCK (2026-08: no longer exempt)",
     "gh-cli get_issue 123 o/r | head", 2),
    ("get_issue piped to grep BLOCK",
     "gh-cli get_issue owner repo 5 | grep foo", 2),
    ("get_issue redirect to file BLOCK (2026-08: replaces rewrite_gh_cli_read_noise.py)",
     "gh-cli get_issue 123 o/r > /tmp/out.txt", 2),
    ("list_issues 2>&1 BLOCK",
     "gh-cli list_issues o/r 2>&1", 2),
    ("for-loop body with foreign curl BLOCK",
     "for n in 1 2 3; do curl http://evil.com/$n; gh-cli get_issue o r $n; done", 2),
    # --- allowed: must pass ---
    ("two of the 7 chained with semicolon PASS",
     "gh-cli index_issues \"q\" o/r ; gh-cli index_discussions \"q\" o/r", 0),
    ("two of the 7 chained with && PASS",
     "gh-cli search_repos \"q\" && gh-cli search_code \"q\" owner/repo", 0),
    ("standalone with --limit --offset PASS",
     "gh-cli index_issues \"q\" o/r --limit 30 --offset 0", 0),
    ("standalone with --metadata-only PASS",
     "gh-cli get_file_content o/r path --metadata-only", 0),
    ("redirect to file PASS (the 7 search/research tools keep redirect-allowed)",
     "gh-cli get_file_content o/r path > /tmp/out.txt", 0),
    # --- get_issue/list_issues: standalone + combine (2026-08, absorbed from the deleted
    # rewrite_gh_cli_read_noise.py — now protected like the 7, not exempt) ---
    ("get_issue standalone PASS",
     "gh-cli get_issue 123 o/r", 0),
    ("list_issues standalone PASS",
     "gh-cli list_issues o/r", 0),
    ("get_issue + list_issues combined via && PASS",
     "gh-cli get_issue 123 o/r && gh-cli list_issues o/r", 0),
    ("get_issue combined with index_issues PASS (same-tool combine)",
     "gh-cli get_issue 123 o/r && gh-cli index_issues \"q\" o/r", 0),
    # --- cross-CLI combos (2026-08 relax: index_issues+rag-cli used to BLOCK) ---
    ("index_issues chained with rag-cli PASS (cross-CLI relax)",
     "gh-cli index_issues \"q\" o/r && rag-cli search \"q\" coll", 0),
    ("get_issue chained with worker-cli capture PASS (cross-CLI relax)",
     "gh-cli get_issue 123 o/r && worker-cli capture janitor", 0),
    ("cd guard before index_issues PASS",
     "cd /tmp && gh-cli index_issues \"q\" o/r", 0),
    # --- shell-strip: patterns inside quoted/heredoc regions must pass ---
    ("pattern inside single-quotes PASS shell-stripped",
     "echo 'gh-cli index_issues \"q\" o/r | grep foo'", 0),
    ("pattern inside heredoc body PASS shell-stripped",
     "cat <<'EOF'\ngh-cli search_code \"q\" | grep x\nEOF", 0),
    # --- repo_freshness as a legal chain segment (2026-08 websearch incident; 2026-08 cross-CLI
    # relax subsumes the old dedicated repo_freshness carve-out into the generic
    # is_known_cli_segment() check — same outcome, simpler mechanism) ---
    ("repo_freshness + two index_issues via && PASS (incident msg121)",
     "gh-cli repo_freshness unclecode crawl4ai && "
     "gh-cli index_issues \"Invalid IPv6 URL\" unclecode/crawl4ai --limit 30 && "
     "gh-cli index_issues \"raw markdown conversion\" unclecode/crawl4ai --limit 30", 0),
    ("repo_freshness + index_issues with echo segments PASS (incident msg118; 2026-08 loop "
     "relax: echo is a legal separator segment)",
     "gh-cli repo_freshness unclecode crawl4ai; echo \"=== PASS 1 ===\"; "
     "gh-cli index_issues \"Invalid IPv6 URL\" unclecode/crawl4ai --limit 30; "
     "echo \"=== PASS 2 ===\"; "
     "gh-cli index_issues \"raw markdown conversion\" unclecode/crawl4ai --limit 30", 0),
    ("repo_freshness chained with git (non-research) PASS — hook not triggered",
     "gh-cli repo_freshness unclecode crawl4ai && git log -1", 0),
    # --- 2026-08 loop relax: for/while scaffolding + echo separators alongside known-CLI
    # segments (real case: batch gh-cli get_issue over a list of issue numbers) ---
    ("real-world for-loop over get_issue with echo separator PASS",
     'for n in 62 61 59; do echo "===== #$n ====="; '
     'gh-cli get_issue brunowinter8192 wise2627 $n; done', 0),
    ("while-loop over get_issue with echo separator PASS",
     'while [ -f /tmp/flag ]; do echo "polling"; gh-cli get_issue o r 5; done', 0),
    ("bare echo segment chained with search_repos PASS (2026-08 loop relax)",
     "gh-cli search_repos \"q\" && echo done", 0),
    ("bare echo segment chained with get_issue PASS (2026-08 loop relax)",
     "gh-cli get_issue 123 o/r && echo done", 0),
]


# ORCHESTRATOR

def test_block_gh_cli_chained_workflow() -> None:
    failures = []
    for desc, cmd, expected in CASES:
        got = _run_hook(cmd)
        status = "OK  " if got == expected else "FAIL"
        print(f"  [{status}] {desc}: exit={got} (expected {expected})")
        if got != expected:
            failures.append(desc)
    print()
    if failures:
        print(f"FAILED: {len(failures)} case(s):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"All {len(CASES)} tests passed.")


# FUNCTIONS

# Run hook with given command string; return exit code
def _run_hook(command: str) -> int:
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
    })
    result = subprocess.run(
        ["python3", HOOK],
        input=payload.encode(),
        capture_output=True,
    )
    return result.returncode


if __name__ == "__main__":
    test_block_gh_cli_chained_workflow()
