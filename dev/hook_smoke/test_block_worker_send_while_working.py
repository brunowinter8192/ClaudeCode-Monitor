#!/usr/bin/env python3
"""
Smoke test for block_worker_send_while_working.py.
Uses real _strip_non_shell_active (called inside decide()) and a stub status_fn for the
pure-decision cases, plus one subprocess invocation of the real script for the malformed-stdin
fail-open case (decide() never touches stdin, so that path needs the actual entrypoint).
No real workers required — all status responses are injected via the stub.

Usage: python3 dev/hook_smoke/test_block_worker_send_while_working.py
"""
import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src', 'hooks'))

from block_worker_send_while_working import decide

HOOK = "src/hooks/block_worker_send_while_working.py"


# Stub builder: name_to_status maps name → return value.
# Raises RuntimeError for the special sentinel name 'raises'.
def make_stub(name_to_status: dict):
    def stub(name: str) -> str:
        if name == 'raises':
            raise RuntimeError("simulated status_fn error")
        return name_to_status.get(name, '')
    return stub


# Worker statuses are exactly working / idle / dead — nothing else.
CASES = [
    # (label, command, stub_map, expect_block)
    (
        "send working → block",
        "worker-cli send foo hello",
        {"foo": "working 88%"},
        True,
    ),
    (
        "send idle → allow",
        "worker-cli send foo hello",
        {"foo": "idle 59%"},
        False,
    ),
    (
        "send dead → allow",
        "worker-cli send foo hello",
        {"foo": "dead"},
        False,
    ),
    (
        "send unknown worker name (empty status) → allow",
        "worker-cli send foo hello",
        {"foo": ""},
        False,
    ),
    (
        "quoted send inside another send-message → allow (double-quoted region stripped)",
        'worker-cli send bar "worker-cli send foo hello"',
        {"foo": "working"},
        False,
    ),
    (
        "heredoc send inside send-message → allow (heredoc body stripped)",
        "worker-cli send bar <<EOF\nworker-cli send foo hello\nEOF",
        {"foo": "working"},
        False,
    ),
    (
        "non-send command → allow",
        "git status",
        {},
        False,
    ),
    (
        "multi-send one working → block (bar)",
        "worker-cli send foo hi && worker-cli send bar hi",
        {"foo": "idle 72%", "bar": "working 44%"},
        True,
    ),
    (
        "status_fn raises → allow (exception treated as empty status)",
        "worker-cli send raises hi",
        {},
        False,
    ),
    (
        "send working 100% → block",
        "worker-cli send foo hello",
        {"foo": "working 100%"},
        True,
    ),
]

passed = failed = 0
for label, cmd, stub_map, expect in CASES:
    block, name = decide(cmd, make_stub(stub_map))
    ok = (block == expect)
    mark = "PASS" if ok else "FAIL"
    blocking_info = f" (blocking: {name})" if block else ""
    print(f"[{mark}] {label}{blocking_info}")
    if ok:
        passed += 1
    else:
        failed += 1

# Malformed stdin fail-open — decide() never touches stdin, so this exercises the real entrypoint.
malformed_result = subprocess.run(
    ["python3", HOOK], input=b"not valid json at all", capture_output=True,
)
ok = malformed_result.returncode == 0
mark = "PASS" if ok else "FAIL"
print(f"[{mark}] malformed stdin payload fails open: exit={malformed_result.returncode} (expected 0)")
if ok:
    passed += 1
else:
    failed += 1

# A working worker via the real entrypoint, stub-free but status_fn unreachable in this sandbox
# (no real worker-cli / worker named 'foo') — must still exit 0, proving the fail-open path holds
# when _live_worker_status cannot resolve a real status at all.
no_worker_result = subprocess.run(
    ["python3", HOOK],
    input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "worker-cli send foo hi"}}).encode(),
    capture_output=True,
)
ok = no_worker_result.returncode == 0
mark = "PASS" if ok else "FAIL"
print(f"[{mark}] real entrypoint, no resolvable worker status: exit={no_worker_result.returncode} (expected 0)")
if ok:
    passed += 1
else:
    failed += 1

print(f"\n{passed}/{passed + failed} passed")
sys.exit(0 if failed == 0 else 1)
