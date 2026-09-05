# INFRASTRUCTURE
import json
import os
import subprocess
import sys

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__)).replace("dev/hook_smoke", "src/hooks")
_NEW_HOOK = os.path.join(_HOOKS_DIR, "block_cli_chained.py")
_WORKTREE_FRAGMENT = ".claude/worktrees/"
_REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "md",
                            "block_cli_chained_replay_report.md")

# The seven hooks block_cli_chained.py replaces — every decision="block" fire of these,
# from the MAIN checkout's log (not the worktree's — the worktree has no fire history of
# its own), gets replayed through the new hook.
_OLD_HOOKS = [
    "block_gh_cli_chained",
    "block_rag_cli_chained",
    "block_worker_cli_read_chained",
    "block_websearch_scrape_chained",
    "block_duallog_chained",
    "block_linkedin_cli_isolated",
    "block_penny_cli_chained",
]


# ORCHESTRATOR

# Replay every historical block fire of the 7 old hooks through the new block_cli_chained.py;
# print per-hook blocks-kept/now-passing counts, write the passing commands to a report.
def probe_replay_cli_chained_workflow() -> None:
    log_path = _resolve_main_log_path()
    records = _load_block_records(log_path, _OLD_HOOKS)
    results = {hook: {"block": [], "pass": []} for hook in _OLD_HOOKS}
    for hook, command in records:
        exit_code = _replay(command)
        bucket = "block" if exit_code == 2 else "pass"
        results[hook][bucket].append(command)

    total_block = sum(len(r["block"]) for r in results.values())
    total_pass = sum(len(r["pass"]) for r in results.values())
    print(f"Replayed {len(records)} historical block fires from {log_path}")
    for hook in _OLD_HOOKS:
        r = results[hook]
        print(f"  {hook}: {len(r['block'])} still block, {len(r['pass'])} now pass")
    print(f"TOTAL: {total_block} still block, {total_pass} now pass")

    _write_report(log_path, results, total_block, total_pass)
    print(f"Report: {_REPORT_PATH}")


# FUNCTIONS

# Resolve the MAIN checkout's hook_firing.jsonl — this worktree's own log has no fire
# history; strip the `.claude/worktrees/<name>` suffix off this script's own path to
# find the main repo root, mirroring worker-cli's resolve_project_path convention.
def _resolve_main_log_path() -> str:
    here = os.path.abspath(__file__)
    idx = here.find(_WORKTREE_FRAGMENT)
    if idx == -1:
        main_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    else:
        main_root = here[:idx].rstrip("/")
    return os.path.join(main_root, "src", "logs", "hook_firing.jsonl")

# Read every decision="block" record whose hook is one of `old_hooks`; return list of
# (hook_name, command) tuples in file order. Fails loudly (this is a probe, not a
# fail-open hook) if the log is missing or malformed.
def _load_block_records(log_path: str, old_hooks: list) -> list:
    records = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("decision") == "block" and entry.get("hook") in old_hooks:
                records.append((entry["hook"], entry.get("command", "")))
    return records

# Feed one historical command through the new hook via a real subprocess call with a
# real PreToolUse JSON payload; return its exit code (2 = still blocks, 0 = now passes).
def _replay(command: str) -> int:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    result = subprocess.run(
        ["python3", _NEW_HOOK],
        input=payload.encode("utf-8"),
        capture_output=True,
    )
    return result.returncode

# Write the per-old-hook block/pass counts and the full text of every now-passing
# command (for manual review — these are the previously-blocked-but-non-truncating
# chains the milestone measured) to the markdown report.
def _write_report(log_path: str, results: dict, total_block: int, total_pass: int) -> None:
    os.makedirs(os.path.dirname(_REPORT_PATH), exist_ok=True)
    lines = [
        "# block_cli_chained.py replay report",
        "",
        f"Source log: `{log_path}`",
        "",
        f"Total: {total_block} still block, {total_pass} now pass "
        f"(of {total_block + total_pass} historical block fires from the 7 replaced hooks).",
        "",
        "## Per-hook counts",
        "",
        "| old hook | still block | now pass |",
        "|---|---|---|",
    ]
    for hook in _OLD_HOOKS:
        r = results[hook]
        lines.append(f"| {hook} | {len(r['block'])} | {len(r['pass'])} |")
    lines.append("")
    lines.append("## Now-passing commands (previously blocked, non-truncating)")
    lines.append("")
    for hook in _OLD_HOOKS:
        passing = results[hook]["pass"]
        if not passing:
            continue
        lines.append(f"### {hook} ({len(passing)})")
        lines.append("")
        for cmd in passing:
            lines.append("```")
            lines.append(cmd)
            lines.append("```")
            lines.append("")
    with open(_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    probe_replay_cli_chained_workflow()
