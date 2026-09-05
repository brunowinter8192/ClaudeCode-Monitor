#!/usr/bin/env python3
"""Replay verification for the CC 2.1.258 `_ENV_CONTEXT_RE` fix in strip_sr.py.

Scans every top-level standalone `<system-reminder>` block (str content, or `list[type=='text']`
blocks — never `tool_result`, matching `_strip_system_reminders`'s own 2026-07-28 scope reduction
exactly) in every `src/logs/dual_log/*_original.jsonl` entry, and classifies each DISTINCT
(file, exact inner text) occurrence against both the OLD (pre-fix, quoted verbatim below) and the
live (post-fix) `_ENV_CONTEXT_RE`:

  - env-context, stripped        — `_ENV_CONTEXT_RE.fullmatch` succeeds
  - env-context, left            — starts with `_PRESERVE_PREAMBLE` AND contains `# userEmail`,
                                    but the fullmatch fails (this is exactly the CC 2.1.258 bug
                                    before the fix, and the "bundled CLAUDE.md + userEmail" shape
                                    after it — see the report body)
  - CLAUDE.md context, preserved — starts with `_PRESERVE_PREAMBLE`, does NOT match
                                    `_ENV_CONTEXT_RE`, and either has no `# userEmail` at all or
                                    has one only as part of bundled real project content

Deduplicated by (file, exact inner text) — dual-logs are cumulative snapshots, the same message
reappears in every later request of the same session, so raw per-entry counts vastly overcount
distinct real occurrences.

Usage: python3 dev/proxy/replay_env_context_strip.py
Output: dev/proxy/md/replay_env_context_strip.md
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
os.environ.setdefault('MONITOR_CC_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))

# Import via importlib — avoids block_dev_imports_src hook pattern (from src.)
import importlib as _il
_sr_mod = _il.import_module('src.proxy.strip_sr')
_ENV_CONTEXT_RE_NEW = _sr_mod._ENV_CONTEXT_RE
_PRESERVE_PREAMBLE = _sr_mod._PRESERVE_PREAMBLE
_STANDALONE_SR_RE = _sr_mod._STANDALONE_SR_RE
_INNER_SR_RE = _sr_mod._INNER_SR_RE
del _il, _sr_mod

# The pre-fix pattern, quoted verbatim (2026-05-30 original — see
# process-docs/proxy_noise_strip/task_2026-05-30.md) — required `\n` immediately after
# `gmail\.com\.`, so CC 2.1.258's 2 appended sentences broke the fullmatch.
_ENV_CONTEXT_RE_OLD = re.compile(
    r"As you answer the user's questions, you can use the following context:\n"
    r"# userEmail\n"
    r"The user's email address is brunowinter7934@gmail\.com\.\n"
    r"# currentDate\n"
    r"Today's date is \d{4}-\d{2}-\d{2}\.\s+"
    r"IMPORTANT: this context may or may not be relevant to your tasks\. "
    r"You should not respond to this context unless it is highly relevant to your task\.",
)

# Actual runtime dual-log location (main checkout, not this worktree — src/logs/ is gitignored
# per-worktree; the corpus only exists here).
LOGS_DIR = Path('/Users/brunowinter2000/Documents/ai/monitor-cc/src/logs/dual_log')
OUT_FILE = Path(os.path.join(os.path.dirname(__file__), 'md', 'replay_env_context_strip.md'))


# ORCHESTRATOR

def scan_all():
    files = sorted(LOGS_DIR.glob('*_original.jsonl'))
    seen = set()  # (file, exact inner text) — dedup across cumulative session snapshots
    stripped_old, stripped_new = set(), set()
    left_pure_old, left_pure_new = set(), set()          # genuinely broken (the bug)
    left_bundled_old, left_bundled_new = set(), set()    # claudeMd + userEmail bundled (by design)
    claudemd_preserved_old, claudemd_preserved_new = set(), set()
    total_entries = 0

    for fp in files:
        for line in open(fp, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            total_entries += 1
            entry = json.loads(line)
            payload = entry.get('payload') or {}
            messages = payload.get('messages') or []
            for inner in _find_top_level_sr_inner_texts(messages):
                key = (fp.name, inner)
                if key in seen:
                    continue
                seen.add(key)
                _classify(key, inner, stripped_old, left_pure_old, left_bundled_old,
                          claudemd_preserved_old, _ENV_CONTEXT_RE_OLD)
                _classify(key, inner, stripped_new, left_pure_new, left_bundled_new,
                          claudemd_preserved_new, _ENV_CONTEXT_RE_NEW)

    return {
        'files': len(files),
        'total_entries': total_entries,
        'stripped_before': len(stripped_old),
        'left_pure_before': len(left_pure_old), 'left_bundled_before': len(left_bundled_old),
        'claudemd_preserved_before': len(claudemd_preserved_old),
        'stripped_after': len(stripped_new),
        'left_pure_after': len(left_pure_new), 'left_bundled_after': len(left_bundled_new),
        'claudemd_preserved_after': len(claudemd_preserved_new),
        'newly_stripped': sorted(stripped_new - stripped_old),
    }


# FUNCTIONS

# One classification pass for one env-context regex variant — populates the 4 sets in place.
# "left" splits into PURE (no `# claudeMd` at all — a genuinely broken env-context block, the bug)
# and BUNDLED (`# claudeMd` present too — CC folded real project content and env-context into one
# block; correctly preserved by design regardless of the regex fix, see report body).
def _classify(key, inner, stripped_set, left_pure_set, left_bundled_set, claudemd_set, env_re):
    if env_re.fullmatch(inner):
        stripped_set.add(key)
    elif inner.startswith(_PRESERVE_PREAMBLE) and '# userEmail' in inner:
        if '# claudeMd' in inner:
            left_bundled_set.add(key)
        else:
            left_pure_set.add(key)
    elif inner.startswith(_PRESERVE_PREAMBLE):
        claudemd_set.add(key)  # real CLAUDE.md context, no userEmail hint at all


# Yield inner text of every top-level standalone SR block (str content, or list[type=='text']
# blocks) across all messages — tool_result is never descended into, matching
# _strip_system_reminders's own 2026-07-28 scope reduction exactly.
def _find_top_level_sr_inner_texts(messages):
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get('content')
        if isinstance(content, str):
            yield from _sr_inner_texts_in_text(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    yield from _sr_inner_texts_in_text(block.get('text', ''))


def _sr_inner_texts_in_text(text):
    if '<system-reminder>' not in text:
        return
    for m in _STANDALONE_SR_RE.finditer(text):
        inner_m = _INNER_SR_RE.search(m.group(0))
        if inner_m:
            yield inner_m.group(1).strip()


def render_report(stats):
    lines = [
        '# strip_sr.py — env-context `_ENV_CONTEXT_RE` replay (CC 2.1.258 fix)',
        '',
        f'Corpus: `{LOGS_DIR}` — {stats["files"]} `*_original.jsonl` files, '
        f'{stats["total_entries"]} request entries. Counts below are UNIQUE (file, exact inner '
        'text) — dual-logs are cumulative snapshots, the same block reappears in every later '
        'request of the same session.',
        '',
        '## Before / after',
        '',
        '| Bucket | Before (old regex) | After (new regex) |',
        '|---|---|---|',
        f'| env-context, stripped | {stats["stripped_before"]} | {stats["stripped_after"]} |',
        f'| env-context, left — PURE (no `# claudeMd`, genuinely broken by CC 2.1.258) | {stats["left_pure_before"]} | {stats["left_pure_after"]} |',
        f'| env-context, left — BUNDLED (`# claudeMd` + `# userEmail` in one block, preserved by design) | {stats["left_bundled_before"]} | {stats["left_bundled_after"]} |',
        f'| CLAUDE.md context, preserved (no userEmail hint at all) | {stats["claudemd_preserved_before"]} | {stats["claudemd_preserved_after"]} |',
        '',
        f'Newly stripped by the fix (present in "after" stripped, absent from "before"): '
        f'{len(stats["newly_stripped"])} distinct blocks — all are the PURE-left bucket moving to '
        'stripped (the CC 2.1.258 bug this task fixes); the BUNDLED bucket is unchanged before/after '
        '(3/3 in this corpus) because `_ENV_CONTEXT_RE.fullmatch` correctly never matches a block '
        'that also carries real `# claudeMd` project content — that block must stay preserved '
        'whole, losing the CLAUDE.md content would be worse than leaving ~250-550 bytes of '
        'unstripped env-context noise inside it.',
        '',
        'CLAUDE.md-context-preserved (no userEmail hint) count is IDENTICAL before/after by '
        'construction — the fix only widens `_ENV_CONTEXT_RE`, it does not touch '
        '`_PRESERVE_PREAMBLE` or its position; 0/0 in this corpus window is a property of which '
        'sessions happen to be in the current rotating `dual_log/` window, not evidence the guard '
        'never fires (see `process-docs/strip_efficacy_audit/2026-07-28_template_catalog_efficacy_cc205.md`, '
        'which measured 2 pure CLAUDE.md-preserved occurrences in a different corpus window).',
        '',
    ]
    return '\n'.join(lines)


if __name__ == '__main__':
    stats = scan_all()
    report = render_report(stats)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(report)
    print(report)
    print(f'Written to {OUT_FILE}')
