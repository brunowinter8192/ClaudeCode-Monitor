"""
Replays the exact commands from the websearch-session repo_freshness incident
(src/logs/dual_log/api_requests_opus_websearch_1786052022_original.jsonl, messages [118]-[129])
through the real block_gh_cli_chained.py hook via subprocess, verifying:

  - repo_freshness is now a legal segment in a combined research chain (the [121] retry passes)
  - the [118] echo-variant still blocks (echo is not a legal segment)
  - piping a research call to `head` still blocks
  - the [129] double-index_issues chain (already legal pre-fix) still passes
  - repo_freshness chained with a non-research command (git) still never triggers the hook
  - a plain non-gh-cli command is untouched

Also asserts stderr shape: BLOCK cases carry the new _BLOCK_MESSAGE (combine-example +
output-always-full-context + cross-CLI-allowed wording); PASS cases emit no stderr.

Usage (from project root):
    python3 dev/hook_smoke/probe_gh_cli_repo_freshness_incident.py
"""

# INFRASTRUCTURE
import json
import subprocess
import sys
from pathlib import Path

HOOK = "src/hooks/block_gh_cli_chained.py"
REPORT_DIR = Path(__file__).parent / 'md'
REPORT_PATH = REPORT_DIR / 'gh_cli_repo_freshness_incident_probe_report.md'

# Verbatim commands from the recorded incident
_MSG118_ECHO_VARIANT = (
    'gh-cli repo_freshness unclecode crawl4ai; echo "=== PASS 1 ==="; '
    'gh-cli index_issues "Invalid IPv6 URL" unclecode/crawl4ai --limit 30; '
    'echo "=== PASS 2 ==="; '
    'gh-cli index_issues "raw markdown conversion" unclecode/crawl4ai --limit 30'
)
_MSG121_FIXED_RETRY = (
    'gh-cli repo_freshness unclecode crawl4ai && '
    'gh-cli index_issues "Invalid IPv6 URL" unclecode/crawl4ai --limit 30 && '
    'gh-cli index_issues "raw markdown conversion" unclecode/crawl4ai --limit 30'
)
_MSG129_DOUBLE_INDEX = (
    'gh-cli index_issues "Invalid IPv6 URL" unclecode/crawl4ai --limit 30 && '
    'gh-cli index_issues "raw markdown conversion" unclecode/crawl4ai --limit 30'
)

CASES = [
    # (label, command, expected_exit, expect_stderr, source)
    ('msg121_fixed_retry_now_passes', _MSG121_FIXED_RETRY, 0, False, 'incident msg [121]'),
    ('msg118_echo_variant_still_blocked', _MSG118_ECHO_VARIANT, 2, True, 'incident msg [118]'),
    ('index_issues_piped_to_head_still_blocked',
     'gh-cli index_issues "Invalid IPv6 URL" unclecode/crawl4ai --limit 30 | head -20', 2, True,
     'generalization of the piping restriction'),
    ('msg129_double_index_issues_still_passes', _MSG129_DOUBLE_INDEX, 0, False, 'incident msg [129]'),
    ('repo_freshness_chained_with_git_still_passes',
     'gh-cli repo_freshness unclecode crawl4ai && git log -1', 0, False,
     'hook must not trigger — repo_freshness alone never matches _GH_TRIGGER_RE'),
    ('plain_non_gh_cli_command_untouched', 'git status', 0, False, 'baseline no-op'),
]

# FUNCTIONS

# Run hook with given command string; return (exit_code, stderr_text)
def _run_hook(command: str) -> tuple:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    result = subprocess.run(
        ["python3", HOOK], input=payload.encode(), capture_output=True,
    )
    return result.returncode, result.stderr.decode()


# ORCHESTRATOR
def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    lines = ['# gh-cli repo_freshness incident probe — block_gh_cli_chained.py', '']
    lines.append('Replays the exact commands from the websearch-session incident '
                  '(`api_requests_opus_websearch_1786052022_original.jsonl`, messages [118]-[129]) '
                  'through the real hook via subprocess.')
    lines.append('')
    lines.append('| case | source | expected exit | actual exit | stderr shape | pass |')
    lines.append('|---|---|---|---|---|---|')
    all_pass = True
    for label, cmd, expected_exit, expect_stderr, source in CASES:
        exit_code, stderr = _run_hook(cmd)
        has_stderr = bool(stderr.strip())
        ok = (exit_code == expected_exit) and (has_stderr == expect_stderr)
        all_pass = all_pass and ok
        stderr_shape = f'{len(stderr)} chars' if has_stderr else '(empty)'
        lines.append(f"| {label} | {source} | {expected_exit} | {exit_code} | {stderr_shape} | {'PASS' if ok else 'FAIL'} |")
        if has_stderr:
            lines.append('')
            lines.append(f'  stderr: `{stderr.strip()[:200]}...`' if len(stderr.strip()) > 200 else f'  stderr: `{stderr.strip()}`')
            lines.append('')
    # Message-content assertions on one representative BLOCK case
    _, block_stderr = _run_hook(_MSG118_ECHO_VARIANT)
    msg_checks = [
        ('combine example present',
         'gh-cli index_issues "q1" owner/repo && gh-cli get_issue owner/repo 5' in block_stderr),
        ('output-always-full-context stated',
         'ALWAYS returns IN FULL' in block_stderr),
        ('cross-CLI-allowed stated (2026-08: subsumes the old repo_freshness-may-join wording)',
         'Cross-CLI and multi-call chains ARE allowed' in block_stderr),
    ]
    lines.append('')
    lines.append('## _BLOCK_MESSAGE content checks (against msg118 echo-variant stderr)')
    lines.append('')
    lines.append('| check | pass |')
    lines.append('|---|---|')
    for label, ok in msg_checks:
        all_pass = all_pass and ok
        lines.append(f"| {label} | {'PASS' if ok else 'FAIL'} |")
    lines.append('')
    lines.append(f"## Overall: {'ALL PASS' if all_pass else 'FAILURES PRESENT'}")
    REPORT_PATH.write_text('\n'.join(lines))
    print(f'Report written: {REPORT_PATH}')
    print('ALL PASS' if all_pass else 'FAILURES PRESENT')
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
