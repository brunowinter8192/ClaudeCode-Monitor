#!/usr/bin/env python3
"""
Smoke test for the two-condition install gate in hook_setup.py (decide_entries()).
A script installs only if BOTH: committed on 'main' (git_query_fn) AND present in the current
working tree at the path that will be registered (tree_query_fn). Uses stub query functions —
no real git calls, no real filesystem checks, no real settings.json writes.

Usage: python3 dev/hook_smoke/test_hook_setup_main_branch_gate.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'src', 'hooks'))

from hook_setup import decide_entries


# Stub builders: maps map script filename -> verdict. Missing key -> default (present), so cases
# only need to name the interesting scripts.
def make_git_stub(name_to_verdict: dict):
    def stub(script: str):
        return name_to_verdict.get(script, True)
    return stub

def make_tree_stub(name_to_present: dict):
    def stub(script: str) -> bool:
        return name_to_present.get(script, True)
    return stub


CASES = [
    # (label, hook_scripts, git_verdict_map, tree_present_map, expect_installed, expect_skipped_scripts)
    (
        "all on main + all in tree -> all installed, none skipped",
        [("a.py", "Bash"), ("b.py", "Bash")],
        {}, {},
        [("a.py", "Bash"), ("b.py", "Bash")],
        [],
    ),
    (
        "one absent from main -> skipped, rest installed",
        [("a.py", "Bash"), ("feature_only.py", "Bash"), ("b.py", "Bash")],
        {"feature_only.py": False}, {},
        [("a.py", "Bash"), ("b.py", "Bash")],
        ["feature_only.py"],
    ),
    (
        "git query fails (None) -> fail-safe skip, rest installed",
        [("a.py", "Bash"), ("broken_query.py", "Bash")],
        {"broken_query.py": None}, {},
        [("a.py", "Bash")],
        ["broken_query.py"],
    ),
    (
        "mixed: present + absent + query-error in one set",
        [("a.py", "Bash"), ("absent.py", "Bash"), ("errored.py", "Bash"), ("b.py", "Bash")],
        {"absent.py": False, "errored.py": None}, {},
        [("a.py", "Bash"), ("b.py", "Bash")],
        ["absent.py", "errored.py"],
    ),
    (
        "same script, multiple matchers, absent from main -> ALL its entries skipped",
        [("multi.py", "Bash"), ("multi.py", "Read"), ("multi.py", "Write"), ("a.py", "Bash")],
        {"multi.py": False}, {},
        [("a.py", "Bash")],
        ["multi.py"],
    ),
    (
        "on main but missing from the working tree -> skipped, rest installed",
        [("a.py", "Bash"), ("renamed_away.py", "Bash"), ("b.py", "Bash")],
        {}, {"renamed_away.py": False},
        [("a.py", "Bash"), ("b.py", "Bash")],
        ["renamed_away.py"],
    ),
    (
        "on main AND present in tree -> installed (mirror-image positive)",
        [("healthy.py", "Bash")],
        {"healthy.py": True}, {"healthy.py": True},
        [("healthy.py", "Bash")],
        [],
    ),
    (
        "missing from BOTH main and the working tree -> skipped (main-branch reason primary)",
        [("a.py", "Bash"), ("gone_everywhere.py", "Bash")],
        {"gone_everywhere.py": False}, {"gone_everywhere.py": False},
        [("a.py", "Bash")],
        ["gone_everywhere.py"],
    ),
]

passed = failed = 0
for label, hook_scripts, git_map, tree_map, expect_installed, expect_skipped_scripts in CASES:
    installed, skipped = decide_entries(hook_scripts, make_git_stub(git_map), make_tree_stub(tree_map))
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
    make_git_stub({"multi.py": False}), make_tree_stub({}),
)
ok = len(skipped_multi) == 3 and all(s == "multi.py" for s, _m, _r in skipped_multi)
mark = "PASS" if ok else "FAIL"
print(f"[{mark}] absent script skips EVERY matcher entry, not just the first")
if ok:
    passed += 1
else:
    failed += 1
    print(f"       skipped_multi={skipped_multi}")

# reason text distinguishes the two conditions — a maintainer needs to know which one failed
_, skipped_main = decide_entries(
    [("not_on_main.py", "Bash")], make_git_stub({"not_on_main.py": False}), make_tree_stub({}))
_, skipped_tree = decide_entries(
    [("not_in_tree.py", "Bash")], make_git_stub({}), make_tree_stub({"not_in_tree.py": False}))
reason_main = skipped_main[0][2]
reason_tree = skipped_tree[0][2]
ok = ("not committed on" in reason_main) and ("missing from the current working tree" in reason_tree)
mark = "PASS" if ok else "FAIL"
print(f"[{mark}] skip reason text distinguishes not-on-main vs missing-from-tree")
if ok:
    passed += 1
else:
    failed += 1
    print(f"       reason_main={reason_main!r} reason_tree={reason_tree!r}")

print(f"\n{passed}/{passed + failed} passed")
sys.exit(0 if failed == 0 else 1)
