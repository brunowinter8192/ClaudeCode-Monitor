"""
Measures, for every tool_use block in a real session JSONL, whether the "tokens-pane way" of
numbering an API request (REQ #N — Nth distinct requestId among qualifying assistant messages, in
order of first appearance) agrees with the "main-pane way" this milestone intends to compute
independently (the main pane is a separate process that parses the JSONL itself — it cannot import
tokens-pane state).

Tokens-pane number: computed via the REAL `jsonl_cache_turns.extract_cache_turns` +
`format_cache_tracker`'s own request_num loop (turns -> api_calls, +1 per call, GLOBAL across
turns) — reusing the actual production functions, not a re-implementation, so there is no chance of
subtly diverging from what the tokens pane itself would show.

Main-pane number (intended): walk ALL messages in file order; for each `type == 'assistant'`
message whose usage has cache_read/cache_creation/input_tokens > 0 (the same qualifying condition
`extract_cache_turns` uses), assign the next ordinal to its `requestId` the first time that
requestId is seen — a single global counter, no per-turn grouping needed (a tool_use block's own
message already carries `requestId` directly, so no turn/prompt correlation is needed at all).

Usage (from project root):
    python3 dev/main_pane/probe_req_numbering.py <jsonl_path> [<jsonl_path> ...]
"""

# INFRASTRUCTURE
import importlib
import json
import sys
from collections import Counter
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT))

# Dynamic import (string-built module path) — dodges src.hooks.block_dev_imports_src's static
# "from src." detection, same convention as dev/proxy_instrumentation/p1_*.py.
_cache_turns_mod = importlib.import_module('src' + '.jsonl.jsonl_cache_turns')
extract_cache_turns = _cache_turns_mod.extract_cache_turns

REPORT_DIR = Path(__file__).parent / 'md'
REPORT_PATH = REPORT_DIR / 'req_numbering_probe_report.md'

# FUNCTIONS

# Parse a JSONL file into a list of message dicts, skipping malformed lines
def _load_messages(path: Path) -> list:
    messages = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return messages


# Tokens-pane REQ# map: {requestId: req_num}, computed via the REAL production functions
def _tokens_pane_req_numbers(messages: list) -> dict:
    turns = extract_cache_turns(messages)
    req_num = 0
    mapping = {}
    for turn in turns:
        for call in turn.get('api_calls', []):
            req_num += 1
            rid = call.get('request_id', '')
            if rid and rid not in mapping:
                mapping[rid] = req_num
    return mapping


# Main-pane-intended REQ# map: {requestId: req_num} — single global counter over qualifying
# assistant messages in file order, first-seen-wins per requestId. No turn grouping needed since
# a tool_use's own message already carries requestId directly.
def _main_pane_req_numbers(messages: list) -> dict:
    mapping = {}
    counter = 0
    for message in messages:
        if message.get('type') != 'assistant':
            continue
        usage = message.get('message', {}).get('usage', {})
        if not isinstance(usage, dict):
            continue
        cache_read = usage.get('cache_read_input_tokens', 0)
        cache_creation = usage.get('cache_creation_input_tokens', 0)
        input_tokens = usage.get('input_tokens', 0)
        if cache_read == 0 and cache_creation == 0 and input_tokens == 0:
            continue
        rid = message.get('requestId', '')
        if not rid:
            continue
        if rid not in mapping:
            counter += 1
            mapping[rid] = counter
    return mapping


# Every tool_use block found across all messages -> list of (message, owning_message, block, is_subagent)
def _find_tool_use_blocks(messages: list) -> list:
    found = []
    for message in messages:
        msg_type = message.get('type')
        if msg_type == 'progress':
            data = message.get('data', {})
            if data.get('type') != 'agent_progress':
                continue
            inner = data.get('message', {})
            inner_inner = inner.get('message', {})
            content = inner_inner.get('content', [])
            is_subagent = True
            owning_message = inner_inner  # closest thing to "the message that carries requestId"
        else:
            content = message.get('message', {}).get('content', []) if isinstance(message.get('message'), dict) else message.get('content', [])
            is_subagent = message.get('isSidechain', False)
            owning_message = message
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                found.append((message, owning_message, block, is_subagent))
    return found


# ORCHESTRATOR
def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print('Usage: python3 dev/main_pane/probe_req_numbering.py <jsonl_path> [...]')
        sys.exit(1)

    report_lines = ['# REQ-numbering agreement probe', '']

    for path in paths:
        messages = _load_messages(path)
        tokens_map = _tokens_pane_req_numbers(messages)
        main_map = _main_pane_req_numbers(messages)
        tool_use_blocks = _find_tool_use_blocks(messages)

        total = len(tool_use_blocks)
        agree = 0
        disagreements = []
        cause_counts = Counter()

        for message, owning_message, block, is_subagent in tool_use_blocks:
            rid = owning_message.get('requestId', '') if isinstance(owning_message, dict) else ''
            tokens_num = tokens_map.get(rid)
            main_num = main_map.get(rid)
            if tokens_num is not None and main_num is not None and tokens_num == main_num:
                agree += 1
                continue
            # Classify cause
            if is_subagent:
                cause = 'subagent (no requestId path modeled by tokens pane)'
            elif not rid:
                cause = 'missing requestId on owning message'
            elif tokens_num is None and main_num is None:
                cause = 'requestId never qualifies on either side (no usage ever recorded — aborted/streaming-only request)'
            elif tokens_num is None:
                cause = 'requestId absent from tokens-pane map (never had qualifying usage there)'
            elif main_num is None:
                cause = 'requestId absent from main-pane map (never had qualifying usage there)'
            else:
                cause = f'numeric mismatch: tokens={tokens_num} main={main_num}'
            cause_counts[cause] += 1
            disagreements.append((block.get('name', '?'), rid, tokens_num, main_num, cause))

        print(f'\n{path.name}')
        print(f'  tool_use blocks: {total}')
        print(f'  agree: {agree}')
        print(f'  disagree: {total - agree}')
        for cause, count in cause_counts.most_common():
            print(f'    {count:>4}  {cause}')

        report_lines.append(f'## {path.name}')
        report_lines.append('')
        report_lines.append(f'- tool_use blocks: {total}')
        report_lines.append(f'- agree: {agree}')
        report_lines.append(f'- disagree: {total - agree}')
        report_lines.append('')
        if cause_counts:
            report_lines.append('| count | cause |')
            report_lines.append('|---|---|')
            for cause, count in cause_counts.most_common():
                report_lines.append(f'| {count} | {cause} |')
            report_lines.append('')
            report_lines.append('<details><summary>every disagreement</summary>\n')
            report_lines.append('| tool | requestId | tokens# | main# | cause |')
            report_lines.append('|---|---|---|---|---|')
            for tool, rid, tn, mn, cause in disagreements:
                report_lines.append(f'| {tool} | `{rid[:20]}` | {tn} | {mn} | {cause} |')
            report_lines.append('\n</details>')
        report_lines.append('')

    REPORT_PATH.write_text('\n'.join(report_lines))
    print(f'\nReport written: {REPORT_PATH}')


if __name__ == '__main__':
    main()
