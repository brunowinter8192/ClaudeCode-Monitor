#!/usr/bin/env python3
"""
Smoke test for the main-branch presence gate in hook_setup.py (decide_entries()).
Uses a stub git_query_fn (script name -> True/False/None) — no real git calls, no real
settings.json writes.

Usage: python3 dev/hook_smoke/test_hook_setup_main_branch_gate.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src', 'hooks'))

from hook_setup import decide_entries


# Stub builder: name_to_verdict maps script filename -> True/False/None.
# Missing key -> True (defaults present, so cases only need to name the interesting scripts).
def make_stub(name_to_verdict: dict):
    def stub(script: str):
        return name_to_verdict.get(script, True)
    return stub


CASES = [
    # (label, hook_scripts, verdict_map, expect_installed, expect_skipped_scripts)
    (
        "all on main -> all installed, none skipped",
        [("a.py", "Bash"), ("b.py", "Bash")],
        {},
        [("a.py", "Bash"), ("b.py", "Bash")],
        [],
    ),
    (
        "one absent from main -> skipped, rest installed",
        [("a.py", "Bash"), ("feature_only.py", "Bash"), ("b.py", "Bash")],
        {"feature_only.py": False},
        [("a.py", "Bash"), ("b.py", "Bash")],
        ["feature_only.py"],
    ),
    (
        "git query fails (None) -> fail-safe skip, rest installed",
        [("a.py", "Bash"), ("broken_query.py", "Bash")],
        {"broken_query.py": None},
        [("a.py", "Bash")],
        ["broken_query.py"],
    ),
    (
        "mixed: present + absent + query-error in one set",
        [("a.py", "Bash"), ("absent.py", "Bash"), ("errored.py", "Bash"), ("b.py", "Bash")],
        {"absent.py": False, "errored.py": None},
        [("a.py", "Bash"), ("b.py", "Bash")],
        ["absent.py", "errored.py"],
    ),
    (
        "same script, multiple matchers, absent from main -> ALL its entries skipped",
        [("multi.py", "Bash"), ("multi.py", "Read"), ("multi.py", "Write"), ("a.py", "Bash")],
        {"multi.py": False},
        [("a.py", "Bash")],
        ["multi.py"],
    ),
]

passed = failed = 0
for label, hook_scripts, verdict_map, expect_installed, expect_skipped_scripts in CASES:
    installed, skipped = decide_entries(hook_scripts, make_stub(verdict_map))
    skipped_scripts = sorted({s for s, _m, _r in skipped})
    ok = (installed == expect_installed) and (skipped_scripts == sorted(expect_skipped_scripts))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {label}")
    if not ok:
        print(f"       installed={installed} skipped_scripts={skipped_scripts}")
    if ok:
        passed += 1
    else:
        failed += 1

# multi-matcher case: confirm all 3 matcher entries for 'multi.py' produced a skip reason each
_, skipped_multi = decide_entries(
    [("multi.py", "Bash"), ("multi.py", "Read"), ("multi.py", "Write")],
    make_stub({"multi.py": False}),
)
ok = len(skipped_multi) == 3 and all(s == "multi.py" for s, _m, _r in skipped_multi)
mark = "PASS" if ok else "FAIL"
print(f"[{mark}] absent script skips EVERY matcher entry, not just the first")
if ok:
    passed += 1
else:
    failed += 1
    print(f"       skipped_multi={skipped_multi}")

print(f"\n{passed}/{passed + failed} passed")
sys.exit(0 if failed == 0 else 1)
