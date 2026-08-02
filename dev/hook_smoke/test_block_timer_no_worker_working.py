#!/usr/bin/env python3
"""
Smoke test for block_timer_no_worker_working.py.
Uses the real decide() + regex, with a stub status_fn (injected raw 'worker-cli status --all'
stdout text). No real workers required.

Usage: python3 dev/hook_smoke/test_block_timer_no_worker_working.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src', 'hooks'))

from block_timer_no_worker_working import decide


# Stub builder: raw is the literal 'worker-cli status --all' stdout to return.
# raw=None → status_fn raises (simulated probe failure).
def make_stub(raw):
    def stub(project_path: str) -> str:
        if raw is None:
            raise RuntimeError("simulated status_fn error")
        return raw
    return stub


_TARGET = "sleep 3300 && echo done"

CASES = [
    # (label, command, run_in_background, raw_status_output, expect_block)
    (
        "empty worker set → block",
        _TARGET, True,
        "(no active workers)",
        True,
    ),
    (
        "all idle → block",
        _TARGET, True,
        "alpha: idle\nbeta: idle 59%",
        True,
    ),
    (
        "one working among idle → allow",
        _TARGET, True,
        "alpha: idle\nbeta: working 88%",
        False,
    ),
    (
        "single unknown → allow",
        _TARGET, True,
        "alpha: unknown",
        False,
    ),
    (
        "unknown mixed with idle → allow",
        _TARGET, True,
        "alpha: unknown\nbeta: idle",
        False,
    ),
    (
        "limit reached → allow",
        _TARGET, True,
        "alpha: limit reached",
        False,
    ),
    (
        "foreground call → no-op (allow)",
        _TARGET, False,
        "(no active workers)",
        False,
    ),
    (
        "non-sleep background command → no-op (allow)",
        "npm run dev", True,
        "(no active workers)",
        False,
    ),
    (
        "bare 'sleep N' background, no worker works → block",
        "sleep 300", True,
        "alpha: idle",
        True,
    ),
    (
        "status probe raises → allow (fail-open)",
        _TARGET, True,
        None,
        False,
    ),
]

passed = failed = 0
for label, cmd, bg, raw, expect in CASES:
    block = decide(cmd, bg, "/fake/project", make_stub(raw))
    ok = (block == expect)
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}")
    if ok:
        passed += 1
    else:
        failed += 1

print(f"\n{passed}/{passed + failed} passed")
sys.exit(0 if failed == 0 else 1)
