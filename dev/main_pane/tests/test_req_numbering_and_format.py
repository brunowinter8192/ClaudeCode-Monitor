#!/usr/bin/env python3
"""
Regression suite for the main-pane tool-calls-only redesign (2026-09, process-docs/main_pane/):
req-numbering (jsonl_parser.update_request_numbers / create_tool_use_entry's request_id),
the new single-block format_tool_call output, and monitor_session.process_session_file's
"only tool calls" buffering.

Placed under tests/ (pytest-shaped filename) so src.hooks.block_dev_imports_src's regression-
suite exemption applies — this file needs literal `from src....` imports.

Run: python3 dev/main_pane/tests/test_req_numbering_and_format.py
"""
# INFRASTRUCTURE
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
os.environ.setdefault('MONITOR_CC_ROOT', os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from src.jsonl.jsonl_parser import (
    update_request_numbers, create_tool_use_entry, parse_new_tool_calls,
    parse_new_tool_calls_isolated,
)
from src.format.formatter import format_tool_call
from src.core import monitor as _monitor
from src.core import monitor_display as _md
from src.core.monitor_session import process_session_file

PASS = []
FAIL = []


def check(name, condition, msg=''):
    if condition:
        PASS.append(name)
        print(f'  PASS  {name}')
    else:
        FAIL.append(name)
        print(f'  FAIL  {name}' + (f': {msg}' if msg else ''))


# ── fixture builders ──────────────────────────────────────────────────────────

# One "split" assistant line — real CC shape: one content block per top-level JSONL line, all
# lines for the same logical response share requestId + usage (measured 2026-09, see
# process-docs/main_pane/).
def _assistant_line(request_id, block, usage=None, is_sidechain=False):
    usage = usage or {'cache_read_input_tokens': 100, 'cache_creation_input_tokens': 0, 'input_tokens': 5, 'output_tokens': 20}
    return {
        'type': 'assistant', 'requestId': request_id, 'isSidechain': is_sidechain,
        'message': {'role': 'assistant', 'content': [block], 'usage': usage},
    }


def _tool_result_line(tool_use_id, content, is_error=False):
    return {
        'type': 'user', 'userType': 'external',
        'message': {'content': [{'type': 'tool_result', 'tool_use_id': tool_use_id, 'content': content, 'is_error': is_error}]},
    }


# A realistic mini-session: 2 requests, each with a tool_use + matching tool_result, plus a
# pure-text (no tool_use) request in between — mirrors the real "not every request has a tool
# call" shape and proves the ordinal counter is GLOBAL, not tool_use-gated.
def _mini_session_lines():
    return [
        _assistant_line('req_1', {'type': 'tool_use', 'id': 'tu1', 'name': 'Bash', 'input': {'command': 'ls'}}),
        _tool_result_line('tu1', 'file1\nfile2'),
        _assistant_line('req_2', {'type': 'text', 'text': 'no tool call here'}),
        _assistant_line('req_3', {'type': 'tool_use', 'id': 'tu2', 'name': 'Read', 'input': {'file_path': '/tmp/x'}}),
        _tool_result_line('tu2', 'contents'),
    ]


# ── update_request_numbers / create_tool_use_entry ──────────────────────────────

def t01_update_request_numbers_first_seen_order():
    messages = _mini_session_lines()
    request_numbers = {}
    update_request_numbers(messages, request_numbers)
    check('T01_three_distinct_requests', request_numbers == {'req_1': 1, 'req_2': 2, 'req_3': 3},
          repr(request_numbers))


def t02_update_request_numbers_ignores_non_qualifying_and_dupes():
    messages = [
        _assistant_line('req_1', {'type': 'tool_use', 'id': 'tu1', 'name': 'Bash', 'input': {}}),
        _assistant_line('req_1', {'type': 'text', 'text': 'same request, second block'}),  # dup requestId
        {'type': 'assistant', 'requestId': 'req_no_usage',
         'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'x'}],
                     'usage': {'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0, 'input_tokens': 0}}},
        _assistant_line('req_2', {'type': 'tool_use', 'id': 'tu2', 'name': 'Read', 'input': {}}),
    ]
    request_numbers = {}
    update_request_numbers(messages, request_numbers)
    check('T02_dup_and_nonqualifying_skipped', request_numbers == {'req_1': 1, 'req_2': 2}, repr(request_numbers))


def t03_update_request_numbers_incremental_continues_counter():
    request_numbers = {}
    update_request_numbers([_assistant_line('req_1', {'type': 'text', 'text': 'x'})], request_numbers)
    update_request_numbers([_assistant_line('req_2', {'type': 'text', 'text': 'y'})], request_numbers)
    check('T03_incremental_ordinals', request_numbers == {'req_1': 1, 'req_2': 2}, repr(request_numbers))


def t04_create_tool_use_entry_carries_request_id():
    message = _assistant_line('req_42', {'type': 'tool_use', 'id': 'tu1', 'name': 'Bash', 'input': {'command': 'ls'}})
    entry = create_tool_use_entry(message['message']['content'][0], message)
    check('T04_request_id_present', entry.get('request_id') == 'req_42', repr(entry.get('request_id')))


def t05_create_tool_use_entry_empty_request_id_when_absent():
    message = {'message': {}}  # no requestId at all — subagent/progress-derived shape, untested in practice
    entry = create_tool_use_entry({'type': 'tool_use', 'id': 'tu', 'name': 'X', 'input': {}}, message)
    check('T05_empty_request_id_fallback', entry.get('request_id') == '', repr(entry.get('request_id')))


# ── parse_new_tool_calls / parse_new_tool_calls_isolated threading ──────────────

def _write_jsonl(lines):
    f = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False)
    for line in lines:
        f.write(json.dumps(line) + '\n')
    f.close()
    return Path(f.name)


def t06_parse_new_tool_calls_optional_param_is_additive():
    path = _write_jsonl(_mini_session_lines())
    try:
        cache = {}
        result_without = parse_new_tool_calls(path, 0, cache)
        cache2 = {}
        result_with = parse_new_tool_calls(path, 0, cache2, {})
        check('T06_return_shape_unaffected', result_without[0] == result_with[0], 'tool_calls differ')
        check('T06_nine_tuple', len(result_without) == 9, len(result_without))
    finally:
        path.unlink()


def t07_parse_new_tool_calls_populates_request_numbers():
    path = _write_jsonl(_mini_session_lines())
    try:
        cache = {}
        request_numbers = {}
        tool_calls, *_ = parse_new_tool_calls(path, 0, cache, request_numbers)
        check('T07_request_numbers_populated', request_numbers == {'req_1': 1, 'req_2': 2, 'req_3': 3}, repr(request_numbers))
        check('T07_two_tool_calls_extracted', len(tool_calls) == 2, len(tool_calls))
        by_name = {tc['tool_name']: tc for tc in tool_calls}
        check('T07_bash_request_id', by_name['Bash']['request_id'] == 'req_1')
        check('T07_read_request_id', by_name['Read']['request_id'] == 'req_3')
    finally:
        path.unlink()


def t08_parse_new_tool_calls_isolated_subprocess_path_threads_request_numbers():
    # last_position == 0 forces the subprocess path — the critical new plumbing (Queue payload
    # gained a 4th element). A real subprocess is spawned; no monkeypatching.
    path = _write_jsonl(_mini_session_lines())
    try:
        cache = {}
        request_numbers = {}
        tool_calls, new_position, *_ = parse_new_tool_calls_isolated(path, 0, cache, request_numbers)
        check('T08_subprocess_path_populates_request_numbers',
              request_numbers == {'req_1': 1, 'req_2': 2, 'req_3': 3}, repr(request_numbers))
        check('T08_subprocess_path_extracts_tool_calls', len(tool_calls) == 2, len(tool_calls))
        check('T08_position_advanced', new_position > 0, new_position)
    finally:
        path.unlink()


def t09_parse_new_tool_calls_isolated_none_request_numbers_unaffected():
    # Every pre-existing caller passes no request_numbers at all — must still work byte-identical.
    path = _write_jsonl(_mini_session_lines())
    try:
        cache = {}
        tool_calls, new_position, *_ = parse_new_tool_calls_isolated(path, 0, cache)
        check('T09_none_request_numbers_no_crash', len(tool_calls) == 2, len(tool_calls))
    finally:
        path.unlink()


# ── format_tool_call ─────────────────────────────────────────────────────────

import re as _re
_ANSI = _re.compile(r'\x1b\[[0-9;]*m')


def t10_format_tool_call_basic_shape():
    out = _ANSI.sub('', format_tool_call('Bash', {'command': 'ls -la', 'run_in_background': True}, 'file1\nfile2', 93))
    lines = out.split('\n')
    check('T10_header_line', lines[0] == 'req 93: Bash', repr(lines[0]))
    check('T10_param_lines', lines[1] == '  command: ls -la' and lines[2] == '  run_in_background: True', repr(lines[1:3]))
    check('T10_blank_separator', lines[3] == '', repr(lines[3]))
    check('T10_result_lines', lines[4] == '  file1' and lines[5] == '  file2', repr(lines[4:6]))
    check('T10_no_timestamp', ':' not in lines[0] or 'req' in lines[0], repr(lines[0]))
    check('T10_no_arrows', '→' not in out and '←' not in out, out)
    check('T10_no_hash', '#' not in lines[0], repr(lines[0]))


def t11_format_tool_call_error_marked_red():
    out = format_tool_call('Bash', {'command': 'false'}, 'boom', 5, is_error=True)
    check('T11_result_is_red', '\033[38;2;243;139;168m' in out and 'boom' in out, repr(out))
    header_line = out.split('\n')[0]
    check('T11_header_not_red', '\033[38;2;243;139;168m' not in header_line, repr(header_line))


def t12_format_tool_call_subagent_color():
    out_main = format_tool_call('Read', {'file_path': '/x'}, 'y', 1, is_subagent=False)
    out_sub = format_tool_call('Read', {'file_path': '/x'}, 'y', 1, is_subagent=True)
    check('T12_main_is_green', out_main.split('\n')[0].startswith('\033[38;2;166;227;161m'), repr(out_main.split(chr(10))[0]))
    check('T12_subagent_is_blue', out_sub.split('\n')[0].startswith('\033[38;2;137;180;250m'), repr(out_sub.split(chr(10))[0]))


def t13_format_tool_call_no_params():
    out = _ANSI.sub('', format_tool_call('Bar', {}, 'ok', 10))
    check('T13_header_then_blank_then_result',
          out.split('\n')[0] == 'req 10: Bar' and 'ok' in out, repr(out))


def t14_format_tool_call_multiline_value_indented_as_is():
    out = _ANSI.sub('', format_tool_call('Write', {'file_path': '/tmp/x', 'content': 'line1\nline2\nline3'}, '', 8))
    check('T14_multiline_value_lines_present',
          '  line1' in out.split('\n') and '  line2' in out.split('\n') and '  line3' in out.split('\n'), out)


def t15_format_tool_call_dict_list_no_json_braces_or_quotes():
    out = _ANSI.sub('', format_tool_call('Foo', {'nested': {'a': 1, 'b': [1, 2, 3]}}, '', 9))
    check('T15_no_curly_braces', '{' not in out and '}' not in out, out)
    check('T15_no_square_brackets', '[' not in out and ']' not in out, out)
    check("T15_no_python_quotes", "'" not in out, out)
    check('T15_sub_values_present', 'a: 1' in out and '- 1' in out and '- 2' in out and '- 3' in out, out)


def t16_format_tool_call_todo_write_special_case_kept():
    out = format_tool_call('TodoWrite', {'todos': [{'status': 'completed', 'content': 'do the thing'}]}, '', 3)
    check('T16_todo_special_case_still_used', 'TODO #1' in out and 'do the thing' in out, out)


# ── process_session_file: only tool calls, malformed warnings, session banner ───

def _reset_monitor_state(filepath):
    _monitor.file_positions[filepath] = 0
    _monitor.tool_use_caches[filepath] = {}
    _monitor.request_numbers_by_file[filepath] = {}
    _monitor.active_mode = 'all'
    _md.main_event_buffer.clear()


def t17_process_session_file_buffers_only_tool_calls_and_warnings():
    lines = _mini_session_lines() + [
        {'type': 'user', 'userType': 'external', 'message': {'content': 'a real user prompt, not a tool result'}},
        {'type': 'system', 'content': 'a system-level message'},
    ]
    path = _write_jsonl(lines)
    # Append a malformed line by hand (parse_jsonl_lines skips bad JSON as a warning)
    with open(path, 'a') as f:
        f.write('{not valid json\n')
    try:
        _reset_monitor_state(path)
        process_session_file(path)
        types_seen = {e['type'] for e in _md.main_event_buffer}
        check('T17_only_tool_call_warning_session_banner_types',
              types_seen <= {'tool_call', 'warning'}, repr(types_seen))
        check('T17_no_user_prompt_event', 'user_prompt' not in types_seen)
        check('T17_no_system_message_event', 'system_message' not in types_seen)
        check('T17_no_thinking_event', 'thinking' not in types_seen)
        check('T17_no_skill_activation_event', 'skill_activation' not in types_seen)
        check('T17_no_user_media_event', 'user_media' not in types_seen)
        check('T17_malformed_line_still_warns', 'warning' in types_seen, repr(types_seen))
        tool_call_events = [e for e in _md.main_event_buffer if e['type'] == 'tool_call']
        check('T17_two_tool_calls_buffered', len(tool_call_events) == 2, len(tool_call_events))
    finally:
        path.unlink()
        _monitor.file_positions.pop(path, None)
        _monitor.tool_use_caches.pop(path, None)
        _monitor.request_numbers_by_file.pop(path, None)


def t18_process_session_file_attaches_correct_req_num():
    path = _write_jsonl(_mini_session_lines())
    try:
        _reset_monitor_state(path)
        process_session_file(path)
        tool_call_events = [e for e in _md.main_event_buffer if e['type'] == 'tool_call']
        by_name = {e['data']['tool_name']: e['data']['req_num'] for e in tool_call_events}
        # req_1 -> Bash (ordinal 1), req_3 -> Read (ordinal 3) — req_2 (the tool-less request)
        # still advances the counter, exactly like the tokens pane's own request_num loop does.
        check('T18_bash_req_num', by_name.get('Bash') == 1, repr(by_name))
        check('T18_read_req_num', by_name.get('Read') == 3, repr(by_name))
    finally:
        path.unlink()
        _monitor.file_positions.pop(path, None)
        _monitor.tool_use_caches.pop(path, None)
        _monitor.request_numbers_by_file.pop(path, None)


if __name__ == '__main__':
    tests = [
        t01_update_request_numbers_first_seen_order,
        t02_update_request_numbers_ignores_non_qualifying_and_dupes,
        t03_update_request_numbers_incremental_continues_counter,
        t04_create_tool_use_entry_carries_request_id,
        t05_create_tool_use_entry_empty_request_id_when_absent,
        t06_parse_new_tool_calls_optional_param_is_additive,
        t07_parse_new_tool_calls_populates_request_numbers,
        t08_parse_new_tool_calls_isolated_subprocess_path_threads_request_numbers,
        t09_parse_new_tool_calls_isolated_none_request_numbers_unaffected,
        t10_format_tool_call_basic_shape,
        t11_format_tool_call_error_marked_red,
        t12_format_tool_call_subagent_color,
        t13_format_tool_call_no_params,
        t14_format_tool_call_multiline_value_indented_as_is,
        t15_format_tool_call_dict_list_no_json_braces_or_quotes,
        t16_format_tool_call_todo_write_special_case_kept,
        t17_process_session_file_buffers_only_tool_calls_and_warnings,
        t18_process_session_file_attaches_correct_req_num,
    ]

    print(f'Running {len(tests)} tests...\n')
    for fn in tests:
        fn()

    total = len(PASS) + len(FAIL)
    print(f'\n{len(PASS)}/{total} passed')
    if FAIL:
        print('FAILED:', FAIL)
        sys.exit(1)
    print('ALL PASS')
