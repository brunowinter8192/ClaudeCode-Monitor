# INFRASTRUCTURE
import json
import logging
import os
import time
from pathlib import Path
from typing import List, Tuple, Optional

from ..constants import EXCLUDED_TOOLS
from .jsonl_extractors import (
    extract_user_media, extract_user_prompts, extract_thinking_blocks,
    extract_skill_activations, extract_usage_data, extract_system_messages,
)

# Top-level subprocess worker (must be importable by name for multiprocessing 'spawn').
# Parses session JSONL in a child process, returns 9-tuple + cache + request_numbers via Queue.
# SUBPROCESS_PARSE_FAIL=1 / SUBPROCESS_PARSE_SLOW=1 env vars activate test hooks.
def _subprocess_worker(filepath_str: str, root_dir: str, q) -> None:
    import sys
    if root_dir and root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    try:
        if os.environ.get('SUBPROCESS_PARSE_FAIL') == '1':
            raise RuntimeError('forced failure for testing')
        if os.environ.get('SUBPROCESS_PARSE_SLOW') == '1':
            time.sleep(10)
        from pathlib import Path as _Path
        from src.jsonl.jsonl_parser import parse_new_tool_calls as _parse
        cache: dict = {}
        request_numbers: dict = {}
        result = _parse(_Path(filepath_str), 0, cache, request_numbers)
        q.put(('ok', result, dict(cache), dict(request_numbers)))
    except Exception as exc:
        q.put(('error', str(exc)))

# parse_new_tool_calls variant that offloads initial parse (last_position==0) to a subprocess.
# Subprocess peak allocation (large session JSONL) is discarded when child exits;
# parent receives only extracted scalar fields.  Cache state is transmitted explicitly
# via Queue since pending entries are not present in the returned tuple.
# Falls back to in-parent parse on subprocess failure, timeout, or IPC error.
# Test hooks: SUBPROCESS_PARSE_TIMEOUT env (override 60s default), SUBPROCESS_PARSE_FAIL=1,
# SUBPROCESS_PARSE_SLOW=1 (child sleeps 10s to exercise timeout path).
# `request_numbers` (2026-09, main-pane req-numbering milestone): optional, additive — None
# (every pre-existing caller) skips it entirely, byte-identical to before. When given, it is
# updated in place with {requestId: ordinal} the same way tool_use_cache is, including across
# the subprocess boundary (the subprocess always builds its OWN request_numbers dict — cheap,
# same messages already being walked — and returns it via the Queue; the caller's dict is only
# touched here if it actually asked for one).
def parse_new_tool_calls_isolated(filepath: Path, last_position: int, tool_use_cache: dict, request_numbers: dict = None) -> Tuple[List[dict], int, List[dict], List[dict], List[dict], List[dict], List[dict], List[dict], List[dict]]:
    if last_position != 0:
        return parse_new_tool_calls(filepath, last_position, tool_use_cache, request_numbers)
    import multiprocessing as _mp
    import queue as _queue
    root = os.environ.get('MONITOR_CC_ROOT', '') or str(Path(__file__).parent.parent.parent)
    timeout = int(os.environ.get('SUBPROCESS_PARSE_TIMEOUT', '60'))
    ctx = _mp.get_context('spawn')
    q = ctx.Queue()
    p = ctx.Process(target=_subprocess_worker, args=(str(filepath), root, q), daemon=True)
    result = None
    try:
        p.start()
        result = q.get(timeout=timeout)
    except _queue.Empty:
        logging.warning('subprocess jsonl parse timed out after %ss — falling back to in-parent', timeout)
    except Exception as exc:
        logging.warning('subprocess jsonl parse IPC error: %s — falling back to in-parent', exc)
    finally:
        if p.is_alive():
            p.terminate()
        if p.pid is not None:
            p.join(timeout=5)
    if result is None or result[0] == 'error':
        if result is not None:
            logging.warning('subprocess jsonl parse worker error: %s — falling back to in-parent', result[1])
        return parse_new_tool_calls(filepath, last_position, tool_use_cache, request_numbers)
    _, result_tuple, cache_state, request_numbers_state = result
    tool_use_cache.clear()
    tool_use_cache.update(cache_state)
    if request_numbers is not None:
        request_numbers.clear()
        request_numbers.update(request_numbers_state)
    return result_tuple

# ORCHESTRATOR
# `request_numbers` (2026-09): optional, additive dict mutated in place — see
# parse_new_tool_calls_isolated's docstring-comment above for the full rationale.
def parse_new_tool_calls(filepath: Path, last_position: int, tool_use_cache: dict, request_numbers: dict = None) -> Tuple[List[dict], int, List[dict], List[dict], List[dict], List[dict], List[dict], List[dict], List[dict]]:
    new_lines = read_new_lines(filepath, last_position)
    new_position = get_current_position(filepath)
    messages, malformed_lines = parse_jsonl_lines(new_lines)
    tool_calls = extract_tool_calls(messages, tool_use_cache)
    if request_numbers is not None:
        update_request_numbers(messages, request_numbers)
    user_prompts = extract_user_prompts(messages)
    user_media = extract_user_media(messages)
    thinking_blocks = extract_thinking_blocks(messages)
    skill_activations = extract_skill_activations(messages)
    usage_data = extract_usage_data(messages)
    system_messages = extract_system_messages(messages)
    malformed_warnings = build_malformed_warnings(filepath, malformed_lines)
    return tool_calls, new_position, malformed_warnings, user_media, thinking_blocks, user_prompts, skill_activations, usage_data, system_messages

# FUNCTIONS

# Build warning dictionaries from malformed line data
def build_malformed_warnings(filepath: Path, malformed_lines: List[dict]) -> List[dict]:
    warnings = []
    for malformed in malformed_lines:
        warning = {
            'file_path': filepath.name,
            'line_number': malformed['line_number'],
            'error_message': malformed['error_message'],
            'raw_line': malformed['raw_line']
        }
        warnings.append(warning)
    return warnings

# Read new lines from file since last position
def read_new_lines(filepath: Path, last_position: int) -> List[str]:
    if not filepath.exists():
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        f.seek(last_position)
        content = f.read()
        if not content:
            return []
        lines = content.split('\n')
        if lines and not lines[-1]:
            lines = lines[:-1]
        return lines

# Get current file position for next read
def get_current_position(filepath: Path) -> int:
    return filepath.stat().st_size

# Parse JSONL lines into message objects
def parse_jsonl_lines(lines: List[str]) -> Tuple[List[dict], List[dict]]:
    messages = []
    malformed_lines = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            messages.append(message)
        except json.JSONDecodeError as e:
            malformed_lines.append({
                'line_number': line_number,
                'error_message': str(e),
                'raw_line': line
            })
    return messages, malformed_lines

# Assign the next ordinal to each newly-seen requestId among qualifying assistant messages —
# mutates `request_numbers` in place, same qualifying condition (non-zero cache_read/
# cache_creation/input_tokens) jsonl_cache_turns.extract_cache_turns uses to build an api_call,
# so the ordinal assigned here for a given requestId is the SAME number the tokens pane shows as
# `REQ #N` for that request (verified 2026-09 against 840 real tool_use blocks across 6 sessions
# in 2 projects: 0 disagreements — see process-docs/main_pane/). Keys are inserted in first-seen
# order, so `len(request_numbers) + 1` IS the next ordinal — no separate counter needed. A single
# GLOBAL counter across the whole file, not per-turn: a pure-text/thinking response with no tool
# call still advances the count, exactly like format_cache_tracker's own request_num loop does.
def update_request_numbers(messages: List[dict], request_numbers: dict) -> None:
    for message in messages:
        if message.get('type') != 'assistant':
            continue
        usage = message.get('message', {}).get('usage', {})
        if not isinstance(usage, dict):
            continue
        if (usage.get('cache_read_input_tokens', 0) == 0
                and usage.get('cache_creation_input_tokens', 0) == 0
                and usage.get('input_tokens', 0) == 0):
            continue
        rid = message.get('requestId', '')
        if rid and rid not in request_numbers:
            request_numbers[rid] = len(request_numbers) + 1

# Extract tool_use and tool_result pairs from messages
def extract_tool_calls(messages: List[dict], tool_use_cache: dict) -> List[dict]:
    tool_calls = []
    tool_use_count = 0
    tool_result_count = 0
    orphaned_results = 0
    total_blocks = 0
    progress_count = 0

    for message in messages:
        msg_type = message.get('type')

        if msg_type == 'progress':
            data = message.get('data', {})
            if data.get('type') != 'agent_progress':
                continue
            progress_count += 1
            agent_id = data.get('agentId')
            if not agent_id:
                continue
            inner_message = data.get('message', {})
            content_blocks = get_progress_content(inner_message)
            is_subagent = True
        else:
            content_blocks = get_message_content(message)
            is_subagent = False
            agent_id = None

        total_blocks += len(content_blocks)
        if not content_blocks:
            continue

        for block in content_blocks:
            if is_tool_use(block):
                tool_use_count += 1
                tool_data = create_tool_use_entry(block, message, is_subagent, agent_id)
                tool_use_cache[tool_data['tool_use_id']] = tool_data
            elif is_tool_result(block):
                tool_result_count += 1
                tool_use_id = block.get('tool_use_id')
                if tool_use_id in tool_use_cache:
                    tool_data = tool_use_cache[tool_use_id]
                    raw_content = extract_result_content(block)
                    tool_data['output'] = raw_content
                    tool_data['spawned_agent_id'] = extract_spawned_agent_id(message)
                    tool_data['is_error'] = block.get('is_error', False)
                    tool_calls.append(tool_data)
                    del tool_use_cache[tool_use_id]
                else:
                    orphaned_results += 1

    filtered_calls = filter_excluded_tools(tool_calls)
    sorted_calls = sort_by_timestamp(filtered_calls)
    return sorted_calls

# Get message content blocks
def get_message_content(message: dict) -> List[dict]:
    if 'message' in message and isinstance(message['message'], dict):
        content = message['message'].get('content', [])
    else:
        content = message.get('content', [])
    if isinstance(content, list):
        return content
    return []

# Get content blocks from progress message (nested structure: data.message.message.content)
def get_progress_content(inner_message: dict) -> List[dict]:
    inner_inner = inner_message.get('message', {})
    content = inner_inner.get('content', [])
    if isinstance(content, list):
        return content
    return []

# Check if content block is tool_use
def is_tool_use(block: dict) -> bool:
    return block.get('type') == 'tool_use'

# Check if content block is tool_result
def is_tool_result(block: dict) -> bool:
    return block.get('type') == 'tool_result'

# Create tool call entry from tool_use block
# `request_id` (2026-09, main-pane req-numbering milestone): additive — the owning message's own
# `requestId`, used together with `request_numbers` (update_request_numbers) to look up the same
# ordinal number the tokens pane shows as `REQ #N` for the same API request. Empty string for a
# subagent/progress-derived entry whose outer message never carries the field directly (measured:
# 0 occurrences of subagent tool_use in the real corpus this was verified against — see
# process-docs/main_pane/ — so this path is a graceful, untested-in-practice fallback, not a
# confirmed-correct extraction).
def create_tool_use_entry(block: dict, message: dict, is_subagent: bool = False, agent_id: str = None) -> dict:
    return {
        'tool_name': block.get('name', 'Unknown'),
        'input': block.get('input', {}),
        'output': None,
        'tool_use_id': block.get('id', ''),
        'timestamp': message.get('timestamp', ''),
        'call_number': message.get('call_number', 0),
        'is_subagent': is_subagent or message.get('isSidechain', False),
        'agent_id': agent_id or message.get('agentId', None),
        'request_id': message.get('requestId', ''),
    }

# Extract spawned agent ID from toolUseResult in message
def extract_spawned_agent_id(message: dict) -> Optional[str]:
    tool_use_result = message.get('toolUseResult', {})
    if isinstance(tool_use_result, dict):
        return tool_use_result.get('agentId')
    return None

# Extract result content from tool_result block
def extract_result_content(block: dict) -> str:
    content = block.get('content', '')
    if isinstance(content, list) and len(content) > 0:
        if isinstance(content[0], dict):
            return content[0].get('text', '')
        return str(content[0])
    return str(content)

# Filter out excluded tools
def filter_excluded_tools(tool_calls: List[dict]) -> List[dict]:
    return [call for call in tool_calls if call['tool_name'] not in EXCLUDED_TOOLS]

# Sort tool calls by timestamp
def sort_by_timestamp(tool_calls: List[dict]) -> List[dict]:
    return sorted(tool_calls, key=lambda x: x.get('timestamp', ''))
