# INFRASTRUCTURE
import json
import subprocess
import sys

HOOK = "src/hooks/block_rag_cli_index_isolated.py"

CASES = [
    # (description, command, expected_exit_code)
    # --- must block: the observed failure (tail + echo + cd + index in one call) ---
    ("observed tail+echo+cd+index BLOCK",
     'tail -20 /tmp/linkedin-reference_batch2_index.log\n'
     'echo "--- is rag-cli still holding lock? ---"\n'
     'cd ~/Documents/ai/Meta/ClaudeCode/cli/rag-cli && '
     'rag-cli index --collection linkedin-reference > /tmp/lock_check4.log 2>&1', 2),
    ("tail before index && BLOCK",
     "tail -20 /tmp/x.log && rag-cli index --collection x", 2),
    ("index then echo && BLOCK",
     "rag-cli index --collection x && echo done", 2),
    ("index then tail ; BLOCK",
     "rag-cli index --collection x ; tail /tmp/x.log", 2),
    ("second rag-cli command alongside index BLOCK",
     "rag-cli delete --collection x && rag-cli index --collection x", 2),
    ("index piped to tee BLOCK",
     "rag-cli index --collection x | tee /tmp/log", 2),
    # --- must block: HOLE 1 — env-var prefix must not defeat the anchor ---
    ("tail before env-prefixed index BLOCK",
     "tail -20 /tmp/x.log && PYTHONUNBUFFERED=1 rag-cli index --collection x", 2),
    ("env-prefixed index then echo BLOCK",
     "PYTHONUNBUFFERED=1 rag-cli index --collection x && echo done", 2),
    ("multi-env-prefixed index piped to tee BLOCK",
     "FOO=1 BAR=2 rag-cli index --collection x | tee /tmp/log", 2),
    # --- must block: HOLE 2 — standalone assignment line does not exempt a tail before it ---
    ("assignment line + tail + cd + env-prefixed index BLOCK",
     'RAG_ROOT=/x\ntail /tmp/y.log\ncd "$RAG_ROOT" && PYTHONUNBUFFERED=1 rag-cli index --collection x', 2),
    # --- must allow: bare index ---
    ("bare index ALLOW",
     "rag-cli index --collection linkedin-reference", 0),
    # --- must allow: index with redirect (not a separator) ---
    ("index redirected to log ALLOW",
     "rag-cli index --collection x > /tmp/out.log 2>&1", 0),
    # --- must allow: leading cd before index ---
    ("cd before index ALLOW",
     "cd /some/path && rag-cli index --collection x", 0),
    # --- must allow: leading cd before index with redirect ---
    ("cd before index with redirect ALLOW",
     "cd /path && rag-cli index --collection x > /tmp/out.log 2>&1", 0),
    # --- must allow: env-var prefix on the index call itself ---
    ("env-prefixed bare index ALLOW",
     "PYTHONUNBUFFERED=1 rag-cli index --collection x", 0),
    # --- must allow: the real HOLE 2 command — assignment line, cd, env-prefixed index,
    #     backslash line-continuation before the redirect ---
    ("assignment line + cd + env-prefixed index + line-continued redirect ALLOW",
     'RAG_ROOT=~/Documents/ai/Meta/ClaudeCode/cli/rag-cli\n'
     'cd "$RAG_ROOT" && PYTHONUNBUFFERED=1 rag-cli index --collection linkedin-reference \\\n'
     '    > /tmp/linkedin-reference_batch3_index.log 2>&1', 0),
    ("assignment line + cd + bare index + redirect ALLOW",
     'RAG_ROOT=/x\ncd "$RAG_ROOT" && rag-cli index --collection x > /tmp/o.log 2>&1', 0),
    ("bare index with backslash line-continued redirect ALLOW",
     "rag-cli index --collection x \\\n    > /tmp/x.log 2>&1", 0),
    # --- out of scope: rag-cli without index ---
    ("rag-cli search out of scope ALLOW",
     'rag-cli search_hybrid "q" coll', 0),
    ("rag-cli list_documents out of scope ALLOW",
     "rag-cli list_documents coll | head", 0),
    ("rag-cli delete out of scope ALLOW",
     "rag-cli delete --collection x", 0),
    # --- no rag-cli at all ---
    ("no rag-cli ALLOW",
     "echo hello world", 0),
    # --- shell-strip: rag-cli index inside single-quoted string must be blanked ---
    ("rag-cli index inside single-quotes ALLOW",
     "echo 'tail /tmp/x.log && rag-cli index --collection x'", 0),
    # --- shell-strip: rag-cli index inside heredoc body must be blanked ---
    ("rag-cli index inside heredoc body ALLOW",
     "cat <<'EOF'\ntail /tmp/x.log && rag-cli index --collection x\nEOF", 0),
]


# ORCHESTRATOR

def test_block_rag_cli_index_isolated_workflow() -> None:
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
    test_block_rag_cli_index_isolated_workflow()
