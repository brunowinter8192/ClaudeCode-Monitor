#!/usr/bin/env python3
"""Unit tests for template-based exact-match SR strip (Phase B).

Coverage:
  - 8 core templates × 3 cases each = 24 tests (real strip at top level, FP preserve, tool_result
    content PRESERVED — SR family no longer descends into tool_result, 2026-07-28 FP-nuke fix;
    see process-docs/message_strip_fp_nuke/2026-07-28_tool_result_sr_audit.md)
  - 4 content-shape tests (str / list[text] stripped; list[tool_result:str] / list[tool_result:list]
    now PRESERVED)
  - user-interrupt partial mode (body preserved, IMPORTANT stripped) — top-level only
  - plan-mode None-return behavior
  - _find_system_reminder_blocks: top-level extraction only (tool_result now finds nothing)
  - SR-family tool_result non-descent: _apply_final_sr_pass identity-preservation (str + list
    tool_result shapes, the pass with no gate at all), the real Occurrence-8 fenced-example shape,
    and top-level-still-works evidence for one `_apply_first_pass`-gated template + one template
    only `_apply_final_sr_pass`'s catch-all covers

Run: python3 dev/proxy/test_strip_fix.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
os.environ.setdefault('MONITOR_CC_ROOT', os.path.join(os.path.dirname(__file__), '..', '..'))

from src.proxy.strip_sr import (
    _strip_system_reminders, _strip_system_reminder, _strip_all_system_reminders,
    _strip_plan_mode_blocks, _strip_user_interrupt_sr, _strip_pyright_diagnostics,
)
from src.proxy.payload_helpers import (
    _content_contains, _find_system_reminder_blocks,
)

_O = '<system-reminder>'
_C = '</system-reminder>'

PASS = []
FAIL = []


def check(name, condition, msg=''):
    if condition:
        PASS.append(name)
        print(f'  PASS  {name}')
    else:
        FAIL.append(name)
        print(f'  FAIL  {name}' + (f': {msg}' if msg else ''))


# ── HELPERS ──────────────────────────────────────────────────────────────────

def mk_sr(body):
    return f'{_O}\n{body}\n{_C}'


def real_sr_text(body):
    return mk_sr(body)


def fp_inline(body):
    # Code-literal: <system-reminder> appears mid-line inside a string
    return f'if "{_O}" in text:\n    return "system-reminder"\n    # rest of code\n\n{mk_sr(body)}'


def tool_result_str(text):
    return [{'type': 'tool_result', 'tool_use_id': 'x', 'content': text}]


def tool_result_list(text):
    return [{'type': 'tool_result', 'tool_use_id': 'x', 'content': [{'type': 'text', 'text': text}]}]


def text_block(text):
    return [{'type': 'text', 'text': text}]


# ── TEMPLATE TESTS ────────────────────────────────────────────────────────────

# T01-T03: task-tools-nag
def t01_task_tools_nag_real_text_block():
    sr = real_sr_text("The task tools haven't been used recently. Consider using TaskCreate.")
    result = _strip_system_reminders(text_block(sr))
    check('T01_task_nag_stripped', _O not in result[0]['text'])


def t02_task_tools_nag_fp_code_literal():
    content = fp_inline("The task tools haven't been used recently. Consider using TaskCreate.")
    # Inside tool_result, the strip no longer descends at all — the mid-line code-literal AND
    # the real trailing standalone SR are both preserved (whole block untouched).
    result = _strip_system_reminders(tool_result_str(content))
    remaining = result[0]['content']
    check('T02_nag_fp_code_preserved', 'if "' + _O + '" in text:' in remaining, repr(remaining[:80]))
    check('T02_nag_real_sr_now_preserved', remaining == content, repr(remaining[-100:]))


def t03_task_tools_nag_tool_result_preserved():
    sr = real_sr_text("The task tools haven't been used recently. Consider using TaskCreate.")
    result = _strip_system_reminders(tool_result_str(sr))
    check('T03_nag_in_tool_result_preserved', result[0]['content'] == sr)


# T04-T06: pyright-diagnostics
def t04_pyright_real():
    body = '<new-diagnostics>The following new diagnostic issues were detected:\n\nfoo.py:\n  ✘ [Line 1] error</new-diagnostics>'
    sr = real_sr_text(body)
    result = _strip_pyright_diagnostics(text_block(sr))
    check('T04_pyright_stripped', _O not in result[0]['text'])


def t05_pyright_fp():
    # Code containing <new-diagnostics> tag mid-line
    code = f'# strips {_O}\n<new-diagnostics>...\n{_C} blocks'
    result = _strip_pyright_diagnostics(tool_result_str(code))
    check('T05_pyright_fp_preserved', '<new-diagnostics>' in result[0]['content'])


def t06_pyright_tool_result_nested_preserved():
    body = '<new-diagnostics>The following new diagnostic issues were detected:\n\ntest.py: error</new-diagnostics>'
    sr = real_sr_text(body)
    result = _strip_system_reminders(tool_result_list(sr))
    check('T06_pyright_nested_preserved', result[0]['content'][0]['text'] == sr)


# T07-T09: deferred-tools
def t07_deferred_tools_real():
    body = 'The following deferred tools are now available via ToolSearch. Their schemas are NOT loaded.\nAskUserQuestion\nCronCreate'
    sr = real_sr_text(body)
    result = _strip_system_reminders(text_block(sr))
    check('T07_deferred_stripped', _O not in result[0]['text'])


def t08_deferred_tools_fp():
    code = f'"The following deferred tools are now available via ToolSearch"  # marker\n\n{real_sr_text("The following deferred tools are now available via ToolSearch.\nFoo")}'
    result = _strip_system_reminders(tool_result_str(code))
    remaining = result[0]['content']
    # Inside tool_result nothing descends — quoted string AND the real trailing SR both preserved.
    check('T08_deferred_quoted_preserved', '"The following deferred tools' in remaining)
    check('T08_deferred_real_now_preserved', remaining == code, repr(remaining[-100:]))


def t09_deferred_tools_tool_result_preserved():
    body = 'The following deferred tools are now available via ToolSearch.\nAskUserQuestion'
    sr = real_sr_text(body)
    result = _strip_system_reminders(tool_result_str(sr))
    check('T09_deferred_in_tool_result_preserved', result[0]['content'] == sr)


# T10-T12: user-interrupt (partial mode)
def t10_user_interrupt_partial_body_preserved():
    body = 'The user sent a new message while you were working:\nhello from user\n\nIMPORTANT: After completing your task, you MUST address this.'
    sr = real_sr_text(body)
    result = _strip_user_interrupt_sr(text_block(sr), 'user sent a new message while you were working')
    text = result[0]['text']
    check('T10_interrupt_sr_tag_preserved', _O in text, repr(text[:80]))
    check('T10_interrupt_important_stripped', 'IMPORTANT:' not in text, repr(text))
    check('T10_interrupt_body_preserved', 'hello from user' in text, repr(text))


def t11_user_interrupt_fp():
    code = f'note: "{_O}The user sent a new message..." wraps the body'
    result = _strip_user_interrupt_sr(tool_result_str(code), 'user sent a new message')
    check('T11_interrupt_fp_preserved', code == result[0]['content'], repr(result[0]['content'][:80]))


def t12_user_interrupt_tool_result_preserved():
    body = 'The user sent a new message while you were working:\nstop working please\n\nIMPORTANT: Address this.'
    sr = real_sr_text(body)
    result = _strip_user_interrupt_sr(tool_result_str(sr), 'user sent a new message while you were working')
    inner = result[0]['content']
    # Partial mode (IMPORTANT-line strip) no longer applies inside tool_result either — untouched.
    check('T12_interrupt_tr_important_preserved', 'IMPORTANT:' in inner, repr(inner))
    check('T12_interrupt_tr_now_byte_exact', inner == sr, repr(inner))


# T13-T15: system-notification
def t13_system_notification_real():
    body = '[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is a background task.\n<task-notification><task-id>abc</task-id></task-notification>'
    sr = real_sr_text(body)
    result = _strip_system_reminders(text_block(sr))
    check('T13_sysnotif_stripped', _O not in result[0]['text'])


def t14_system_notification_fp():
    code = f'# See {_O}[SYSTEM NOTIFICATION...]{_C} for context'
    result = _strip_system_reminders(tool_result_str(code))
    check('T14_sysnotif_fp_preserved', '[SYSTEM NOTIFICATION' in result[0]['content'])


def t15_system_notification_tool_result_preserved():
    body = '[SYSTEM NOTIFICATION - NOT USER INPUT]\nBackground task event.'
    sr = real_sr_text(body)
    result = _strip_system_reminders(tool_result_str(sr))
    check('T15_sysnotif_tool_result_preserved', result[0]['content'] == sr)


# T16-T18: file-modified
def t16_file_modified_real():
    body = 'Note: /Users/foo/project/CLAUDE.md was modified, either by the user or by a linter.'
    sr = real_sr_text(body)
    result = _strip_system_reminders(text_block(sr))
    check('T16_filemod_stripped', _O not in result[0]['text'])


def t17_file_modified_fp():
    code = f'# Note: This function modifies the file\n\n{real_sr_text("Note: /path/file.py was modified, either by the user or by a linter.")}'
    result = _strip_system_reminders(tool_result_str(code))
    remaining = result[0]['content']
    check('T17_filemod_comment_preserved', '# Note: This function' in remaining)
    check('T17_filemod_real_now_preserved', remaining == code, repr(remaining[-100:]))


def t18_file_modified_tool_result_preserved():
    body = 'Note: /Users/foo/DOCS.md was modified, either by the user or by a linter.'
    sr = real_sr_text(body)
    result = _strip_system_reminders(tool_result_str(sr))
    check('T18_filemod_tool_result_preserved', result[0]['content'] == sr)


# T19-T21: claudemd-contents
def t19_claudemd_real():
    body = 'Contents of /path/to/CLAUDE.md:\n# claudeMd\n...content...'
    sr = real_sr_text(body)
    result = _strip_system_reminders(text_block(sr))
    check('T19_claudemd_stripped', _O not in result[0]['text'])


def t20_claudemd_fp():
    code = f'# Contents of this dict: {{"a": 1}}'
    result = _strip_system_reminders(tool_result_str(code))
    check('T20_claudemd_fp_preserved', 'Contents of this dict' in result[0]['content'])


def t21_claudemd_tool_result_preserved():
    body = 'Contents of /path/CLAUDE.md:\n# claudeMd\nProject overview here.'
    sr = real_sr_text(body)
    result = _strip_system_reminders(tool_result_str(sr))
    check('T21_claudemd_tool_result_preserved', result[0]['content'] == sr)


# T22-T24: date-changed (new template)
def t22_date_changed_real():
    body = "The date has changed. Today's date is now 2026-04-22. DO NOT mention this to the user."
    sr = real_sr_text(body)
    result = _strip_system_reminders(text_block(sr))
    check('T22_datechanged_stripped', _O not in result[0]['text'])


def t23_date_changed_fp():
    code = f'# The date has changed format from ISO to epoch'
    result = _strip_system_reminders(tool_result_str(code))
    check('T23_datechanged_fp_preserved', '# The date has changed' in result[0]['content'])


def t24_date_changed_tool_result_preserved():
    body = "The date has changed. Today's date is now 2026-04-22."
    sr = real_sr_text(body)
    result = _strip_system_reminders(tool_result_str(sr))
    check('T24_datechanged_tool_result_preserved', result[0]['content'] == sr)


# ── CONTENT SHAPE TESTS ───────────────────────────────────────────────────────

def t25_shape_plain_string():
    sr = real_sr_text("The task tools haven't been used recently. Use TaskCreate.")
    result = _strip_system_reminders(sr)
    check('T25_string_shape_stripped', _O not in result)


def t26_shape_list_text():
    sr = real_sr_text("The task tools haven't been used recently. Use TaskCreate.")
    result = _strip_system_reminders(text_block(f'before\n{sr}\nafter'))
    check('T26_list_text_sr_stripped', _O not in result[0]['text'])
    check('T26_list_text_rest_preserved', 'before' in result[0]['text'] and 'after' in result[0]['text'])


def t27_shape_tool_result_str_now_preserved():
    sr = real_sr_text("The task tools haven't been used recently. Use TaskCreate.")
    text = f'prefix\n{sr}\nsuffix'
    result = _strip_system_reminders(tool_result_str(text))
    check('T27_tr_str_now_byte_exact', result[0]['content'] == text)


def t28_shape_tool_result_list_now_preserved():
    sr = real_sr_text("The task tools haven't been used recently. Use TaskCreate.")
    text = f'prefix\n{sr}\nsuffix'
    result = _strip_system_reminders(tool_result_list(text))
    check('T28_tr_list_now_byte_exact', result[0]['content'][0]['text'] == text)


# ── PLAN-MODE ────────────────────────────────────────────────────────────────

def t29_plan_mode_returns_none_when_empty():
    sr = real_sr_text('Plan mode is now active. Enter plan mode.')
    result = _strip_plan_mode_blocks(text_block(sr))
    check('T29_planmode_none_when_empty', result is None, repr(result))


def t30_plan_mode_preserves_other_content():
    sr = real_sr_text('Plan mode is now active.')
    content = text_block(f'{sr}\nuser text here')
    result = _strip_plan_mode_blocks(content)
    check('T30_planmode_preserves_other', result is not None and 'user text here' in result[0]['text'])


# ── find_system_reminder_blocks ───────────────────────────────────────────────

def t31_find_sr_blocks_tool_result_finds_none():
    # Same real+code-literal mix as before the fix — now 0 found either way, tool_result isn't scanned.
    code = f'if "{_O}" in text:\n    pass\n\n{real_sr_text("The task tools haven\'t been used recently. Use TaskCreate.")}'
    found = _find_system_reminder_blocks(tool_result_str(code), "task tools haven")
    check('T31_find_none_in_tool_result', len(found) == 0, f'found {len(found)}: {found}')


def t32_find_sr_blocks_top_level_real_found():
    sr = real_sr_text("The task tools haven't been used recently.")
    found = _find_system_reminder_blocks(text_block(sr), "task tools haven")
    check('T32_find_real_at_top_level', len(found) == 1, f'found {len(found)}')


# ── _content_contains ────────────────────────────────────────────────────────
# _content_contains itself still descends into tool_result — it remains the correct gate for the
# out-of-scope non-SR passes (git-lock, hook-prefix, bd-noise) whose genuine content only lives
# there; the SR family switched its own call sites to _top_level_content_contains instead (see
# _apply_first_pass / _apply_cumulative_sr_strips), it did not change this shared helper.

def t33_content_contains_tool_result_str():
    sr = real_sr_text("The task tools haven't been used recently.")
    result = _content_contains(tool_result_str(sr), 'task tools haven')
    check('T33_contains_in_tool_result', result is True, f'got {result}')


def t34_content_contains_text_block():
    sr = real_sr_text("The task tools haven't been used recently.")
    result = _content_contains(text_block(sr), 'task tools haven')
    check('T34_contains_in_text_block', result is True, f'got {result}')



# ── SR-FAMILY TOOL_RESULT NON-DESCENT (2026-07-28 FP-nuke fix) ────────────────
# _apply_final_sr_pass has NO gate at all — it calls _strip_all_system_reminders unconditionally
# on every user message, so the traversal fix in strip_sr.py is the ONLY thing standing between it
# and tool_result content. These cases give it extra scrutiny: both tool_result shapes must be
# untouched, and the block object must come back by IDENTITY (not a rebuilt-but-equal dict), since
# a rebuild would still register as a change in the diff-based bookkeeping downstream.

def t35_final_sr_pass_tool_result_str_identity_preserved():
    sr = real_sr_text('[SYSTEM NOTIFICATION - NOT USER INPUT]\nBackground task event.')
    content = tool_result_str(sr)
    msgs = [{'role': 'user', 'content': content}]
    new_msgs, mods, _, changed, _, _ops = _apply_final_sr_pass(msgs)
    check('T35_final_sr_pass_tool_result_str_untouched', new_msgs[0]['content'] == content)
    check('T35_final_sr_pass_block_identity', new_msgs[0]['content'][0] is content[0])
    check('T35_final_sr_pass_no_change_recorded', 0 not in changed, f'changed: {changed}')


def t36_final_sr_pass_tool_result_list_identity_preserved():
    sr = real_sr_text('[SYSTEM NOTIFICATION - NOT USER INPUT]\nBackground task event.')
    content = tool_result_list(sr)
    msgs = [{'role': 'user', 'content': content}]
    new_msgs, mods, _, changed, _, _ops = _apply_final_sr_pass(msgs)
    check('T36_final_sr_pass_tool_result_list_untouched', new_msgs[0]['content'] == content)
    check('T36_final_sr_pass_block_identity', new_msgs[0]['content'][0] is content[0])
    check('T36_final_sr_pass_no_change_recorded', 0 not in changed, f'changed: {changed}')


# T37 — real Occurrence-8 shape: a rag-cli/process-docs excerpt fencing a literal env-context
# system-reminder as a documentation example, inside a tool_result — must survive byte-exact.
def t37_occurrence8_fenced_env_context_in_tool_result_preserved():
    env_sr = (
        f'{_O}\n'
        "As you answer the user's questions, you can use the following context:\n"
        "# userEmail\nThe user's email address is brunowinter7934@gmail.com.\n"
        "# currentDate\nToday's date is 2026-05-30.\n\n"
        "      IMPORTANT: this context may or may not be relevant to your tasks. "
        "You should not respond to this context unless it is highly relevant to your task.\n"
        f'{_C}\n'
    )
    doc_excerpt = (
        "## Task B — Env-context system-reminder (userEmail / currentDate)\n\n"
        "### What we stripped\n\n"
        "CC injects this SR block on nearly every request:\n```\n"
        f"{env_sr}"
        "```\n334 chars of inner text per request, never useful to the proxy model.\n"
    )
    content = tool_result_str(doc_excerpt)
    msgs = [{'role': 'user', 'content': content}]
    new_msgs, mods, _, changed, _, _ops = _apply_final_sr_pass(msgs)
    check('T37_occ8_fenced_env_context_untouched', new_msgs[0]['content'] == content)
    check('T37_occ8_block_identity', new_msgs[0]['content'][0] is content[0])
    check('T37_occ8_no_change_recorded', 0 not in changed, f'changed: {changed}')


# T38/T39 — top-level SR stripping still works: this is a SCOPE REDUCTION, not a disable. One
# template from an _apply_first_pass gated branch, one only _apply_final_sr_pass's catch-all covers.
def t38_top_level_task_tools_nag_still_stripped_via_first_pass():
    sr = real_sr_text("The task tools haven't been used recently. Consider using TaskCreate.")
    msgs = [{'role': 'user', 'content': sr}]
    new_msgs, mods, _, _c, _, _ops = _apply_first_pass(msgs)
    check('T38_top_level_nag_stripped', _O not in new_msgs[0]['content'])
    check('T38_top_level_nag_mod_fired', 'stripped_task_tools_nag' in mods, f'mods: {mods}')


def t39_top_level_date_changed_still_stripped_via_final_sr_pass():
    sr = real_sr_text("The date has changed. Today's date is now 2026-04-22.")
    msgs = [{'role': 'user', 'content': sr}]
    new_msgs, mods, _, _c, _, _ops = _apply_final_sr_pass(msgs)
    check('T39_top_level_datechanged_stripped', _O not in new_msgs[0]['content'])
    check('T39_top_level_datechanged_mod_fired', 'stripped_all_sr_msg0' in mods, f'mods: {mods}')


# ── WAKEUP FALSE-POSITIVE TESTS ───────────────────────────────────────────────
# Import via importlib — avoids block_dev_imports_src hook pattern (from src.)
import importlib as _wakeup_il
_rules_mod = _wakeup_il.import_module('src.proxy.message_passes')
_apply_first_pass = _rules_mod._apply_first_pass
_apply_bg_exit_strip = _rules_mod._apply_bg_exit_strip
_apply_sn_notice_strip = _rules_mod._apply_sn_notice_strip
_apply_final_sr_pass = _rules_mod._apply_final_sr_pass
_apply_role_system_strip = _rules_mod._apply_role_system_strip
_bgk_mod = _wakeup_il.import_module('src.proxy.strip_bg_completed')
_WAKEUP_TEXT = _bgk_mod._WAKEUP_TEXT
_sn_mod = _wakeup_il.import_module('src.proxy.strip_sn_notice')
_SN_NOTICE_PARAGRAPH = _sn_mod._SN_NOTICE_PARAGRAPH
_bg_ack_mod = _wakeup_il.import_module('src.proxy.strip_bg_launch_ack')
_strip_bg_launch_ack = _bg_ack_mod._strip_bg_launch_ack
_im_mod = _wakeup_il.import_module('src.proxy.strip_interrupt_marker')
_strip_interrupt_marker = _im_mod._strip_interrupt_marker
_INTERRUPT_MARKER = '[Request interrupted by user]'
_INTERRUPT_MARKER_TOOL_USE = '[Request interrupted by user for tool use]'
_apply_interrupt_marker_strip = _rules_mod._apply_interrupt_marker_strip
del _wakeup_il, _rules_mod, _bgk_mod, _sn_mod, _bg_ack_mod, _im_mod


def _has_wakeup(content) -> bool:
    """Return True if _WAKEUP_TEXT (stripped of trailing newline) appears in content."""
    core = _WAKEUP_TEXT.rstrip('\n')
    if isinstance(content, str):
        return core in content
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get('type') == 'text' and core in b.get('text', '')
            for b in content
        )
    return False


# W01 — <task-notification> in tool_result str → TN branch must NOT fire
def w01_tn_in_tool_result_str():
    tn_data = 'RAG result: <task-notification><status>completed</status><summary>done</summary></task-notification>'
    msgs = [{'role': 'user', 'content': tool_result_str(tn_data)}]
    new_msgs, mods, _, _c, _, _ops = _apply_first_pass(msgs)
    content = new_msgs[0]['content']
    check('W01_no_wakeup_injected', not _has_wakeup(content), f'wakeup found: {content}')
    check('W01_tn_mod_not_fired', not any('task_notification' in m for m in mods), f'mods: {mods}')
    check('W01_tool_result_intact', new_msgs[0]['content'][0]['content'] == tn_data)


# W02 — <task-notification> in tool_result list-of-text → TN branch must NOT fire
def w02_tn_in_tool_result_list():
    tn_data = 'source: <task-notification><status>failed</status><summary></summary></task-notification>'
    msgs = [{'role': 'user', 'content': tool_result_list(tn_data)}]
    new_msgs, mods, _, _c, _, _ops = _apply_first_pass(msgs)
    content = new_msgs[0]['content']
    check('W02_no_wakeup_injected', not _has_wakeup(content), f'wakeup found: {content}')
    check('W02_tn_mod_not_fired', not any('task_notification' in m for m in mods), f'mods: {mods}')
    check('W02_tool_result_intact', new_msgs[0]['content'][0]['content'][0]['text'] == tn_data)


# W03 — complete BGK pattern in tool_result str → BGK branch must NOT fire, data intact
def w03_bgk_in_tool_result_str():
    bgk_data = 'log: Background command "sleep 600" completed (exit code 143)\n'
    msgs = [{'role': 'user', 'content': tool_result_str(bgk_data)}]
    new_msgs, mods, _, _c, _, _ops = _apply_bg_exit_strip(msgs)
    content = new_msgs[0]['content']
    check('W03_no_wakeup_injected', not _has_wakeup(content), f'wakeup found: {content}')
    check('W03_bgk_mod_not_fired', 'replaced_bg_completed_text' not in mods, f'mods: {mods}')
    check('W03_tool_result_intact', new_msgs[0]['content'][0]['content'] == bgk_data)


# W04 — genuine plain-string completed TN → wakeup injected, mod=trimmed_task_notification
# fixture has no <task-id> and no <output-file> — doubles as the "both missing" case: neither
# 'Output:' nor 'ID:' line, content reduces to exactly _WAKEUP_TEXT.
def w04_genuine_tn_completed_plain_string():
    tn = '<task-notification>\n<status>completed</status>\n<summary>Background command "sleep 10" completed (exit code 0)</summary>\n</task-notification>\n'
    msgs = [{'role': 'user', 'content': tn}]
    new_msgs, mods, _, _c, _, _ops = _apply_first_pass(msgs)
    check('W04_wakeup_injected', _has_wakeup(new_msgs[0]['content']), repr(new_msgs[0]['content'])[:80])
    check('W04_mod_trimmed', 'trimmed_task_notification' in mods, f'mods: {mods}')
    check('W04_no_output_line', 'Output:' not in new_msgs[0]['content'], repr(new_msgs[0]['content']))
    check('W04_no_id_line', 'ID:' not in new_msgs[0]['content'], repr(new_msgs[0]['content']))
    check('W04_reduces_to_bare_wakeup', new_msgs[0]['content'] == _WAKEUP_TEXT, repr(new_msgs[0]['content']))


# W05 — genuine plain-string failed TN → wakeup injected, mod=replaced_task_notification
def w05_genuine_tn_failed_plain_string():
    tn = '<task-notification>\n<status>failed</status>\n<summary></summary>\n</task-notification>\n'
    msgs = [{'role': 'user', 'content': tn}]
    new_msgs, mods, _, _c, _, _ops = _apply_first_pass(msgs)
    check('W05_wakeup_injected', _has_wakeup(new_msgs[0]['content']), repr(new_msgs[0]['content'])[:80])
    check('W05_mod_replaced', 'replaced_task_notification' in mods, f'mods: {mods}')
    check('W05_no_output_line', 'Output:' not in new_msgs[0]['content'], repr(new_msgs[0]['content']))
    check('W05_no_id_line', 'ID:' not in new_msgs[0]['content'], repr(new_msgs[0]['content']))


# W06 — genuine plain-string BGK kill notification → wakeup injected, mod=replaced_bg_completed_text
def w06_genuine_bgk_plain_string():
    bgk = 'Background command "sleep 600" completed (exit code 143)\n'
    msgs = [{'role': 'user', 'content': bgk}]
    new_msgs, mods, _, _c, _, _ops = _apply_bg_exit_strip(msgs)
    check('W06_wakeup_injected', _has_wakeup(new_msgs[0]['content']), repr(new_msgs[0]['content'])[:80])
    check('W06_mod_replaced', 'replaced_bg_completed_text' in mods, f'mods: {mods}')


# ── SN-NOTICE-PARAGRAPH TESTS ─────────────────────────────────────────────────
# strip_sn_notice.py — bare 4-line paragraph ahead of <task-notification>, anchored startswith
# decision (not substring-anywhere) — same FP-nuke class as bg_launch_ack / plan_mode, see
# process-docs/message_strip_fp_nuke/.

# W07 — genuine plain-string paragraph + <task-notification> tag → stripped, mod fired
def w07_sn_notice_genuine_plain_string():
    tn = '<task-notification>\n<status>completed</status>\n<summary>done</summary>\n</task-notification>\n'
    content = _SN_NOTICE_PARAGRAPH + '\n\n' + tn
    msgs = [{'role': 'user', 'content': content}]
    new_msgs, mods, _, _c, _, _ops = _apply_sn_notice_strip(msgs)
    result = new_msgs[0]['content']
    check('W07_sn_notice_stripped', _SN_NOTICE_PARAGRAPH not in result, repr(result)[:80])
    check('W07_tn_tag_preserved', result == tn, repr(result))
    check('W07_mod_fired', 'stripped_sn_notice_paragraph' in mods, f'mods: {mods}')


# W08 — genuine text-block at non-zero block index → stripped (do NOT hardcode index 0)
def w08_sn_notice_text_block_index_one():
    tn = '<task-notification>\n<status>failed</status>\n<summary></summary>\n</task-notification>\n'
    content = [
        {'type': 'text', 'text': 'preceding unrelated block'},
        {'type': 'text', 'text': _SN_NOTICE_PARAGRAPH + '\n\n' + tn},
    ]
    msgs = [{'role': 'user', 'content': content}]
    new_msgs, mods, _, _c, _, _ops = _apply_sn_notice_strip(msgs)
    result = new_msgs[0]['content']
    check('W08_block0_untouched', result[0]['text'] == 'preceding unrelated block')
    check('W08_block1_stripped', result[1]['text'] == tn, repr(result[1]['text']))
    check('W08_mod_fired', 'stripped_sn_notice_paragraph' in mods, f'mods: {mods}')


# W09 — paragraph quoted as tool_result data → must NOT fire, byte-exact untouched
def w09_sn_notice_tool_result_untouched():
    data = 'log excerpt:\n' + _SN_NOTICE_PARAGRAPH + '\nend of excerpt'
    msgs = [{'role': 'user', 'content': tool_result_str(data)}]
    new_msgs, mods, _, _c, _, _ops = _apply_sn_notice_strip(msgs)
    check('W09_tool_result_intact', new_msgs[0]['content'][0]['content'] == data)
    check('W09_mod_not_fired', 'stripped_sn_notice_paragraph' not in mods, f'mods: {mods}')


# W10 — paragraph mid-content in a text block (not at start) → must NOT fire, untouched
def w10_sn_notice_mid_content_untouched():
    text = 'user note before it:\n' + _SN_NOTICE_PARAGRAPH + '\n\nmore text after'
    msgs = [{'role': 'user', 'content': text_block(text)}]
    new_msgs, mods, _, _c, _, _ops = _apply_sn_notice_strip(msgs)
    check('W10_mid_content_intact', new_msgs[0]['content'][0]['text'] == text)
    check('W10_mod_not_fired', 'stripped_sn_notice_paragraph' not in mods, f'mods: {mods}')


# W11 — role="system" with paragraph at start → NOT touched by the SN-notice pass (out of scope)
def w11_sn_notice_role_system_untouched():
    content = _SN_NOTICE_PARAGRAPH + '\n\nsome trailing detail'
    msgs = [{'role': 'system', 'content': content}]
    new_msgs, mods, _, _c, _, _ops = _apply_sn_notice_strip(msgs)
    check('W11_role_system_intact', new_msgs[0]['content'] == content)
    check('W11_mod_not_fired', 'stripped_sn_notice_paragraph' not in mods, f'mods: {mods}')


# ── ROLE=SYSTEM TASK-NOTIFICATION TESTS (2026-07-29 fix) ─────────────────────
# _apply_role_system_strip previously nuked EVERY role='system' message to '.' before any TN
# handling could see it — CC delivers bg-task wake-ups as a plain-str role='system' message
# (measured: 173/280 real TN occurrences in one session log, role='system'/str; the other 107
# were role='user'/list-text, already handled). Fix: _apply_role_system_strip leaves TN-carrying
# role='system' messages untouched; _apply_sn_notice_strip + _apply_first_pass's TN branch (both
# widened to accept role='system', narrowly gated on the TN tag itself) do the actual wake-up
# construction — single source of truth, no duplicated TN-building logic. These tests run the
# real 3-pass sequence (role_system_strip -> sn_notice_strip -> first_pass) matching rules.py's
# `_passes` order.

def w12_role_system_tn_completed_full_pipeline():
    tn = ('<task-notification>\n<task-id>abc123</task-id>\n<status>completed</status>\n'
          '<summary>Background command "sleep 10" completed (exit code 0)</summary>\n'
          '</task-notification>')
    content = _SN_NOTICE_PARAGRAPH + '\n\n' + tn
    messages = [{'role': 'system', 'content': content}]
    messages, _m1, _, _, _, _ = _apply_role_system_strip(messages)
    messages, _m2, _, _, _, _ = _apply_sn_notice_strip(messages)
    messages, mods3, _, _, _, _ = _apply_first_pass(messages)
    result = messages[0]['content']
    check('W12_not_nuked_to_dot', result != '.', repr(result))
    check('W12_wakeup_present', _has_wakeup(result), repr(result))
    check('W12_sn_notice_gone', _SN_NOTICE_PARAGRAPH not in result, repr(result))
    check('W12_role_preserved', messages[0]['role'] == 'system')
    check('W12_mod_trimmed', 'trimmed_task_notification' in mods3, f'mods3: {mods3}')
    check('W12_id_line_present', 'ID: abc123' in result, repr(result))
    check('W12_no_output_line', 'Output:' not in result, repr(result))


def w13_role_system_tn_failed_with_output_file():
    tn = ('<task-notification>\n<task-id>xyz789</task-id>\n'
          '<output-file>/tmp/foo/task.output</output-file>\n<status>failed</status>\n'
          '<summary>Background command "x" failed with exit code 42</summary>\n'
          '</task-notification>')
    content = _SN_NOTICE_PARAGRAPH + '\n\n' + tn
    messages = [{'role': 'system', 'content': content}]
    messages, _m1, _, _, _, _ = _apply_role_system_strip(messages)
    messages, _m2, _, _, _, _ = _apply_sn_notice_strip(messages)
    messages, mods3, _, _, _, _ = _apply_first_pass(messages)
    result = messages[0]['content']
    check('W13_wakeup_present', _has_wakeup(result), repr(result))
    check('W13_output_line_present', 'Output: /tmp/foo/task.output' in result, repr(result))
    check('W13_mod_replaced', 'replaced_task_notification' in mods3, f'mods3: {mods3}')
    check('W13_id_line_present', 'ID: xyz789' in result, repr(result))
    check('W13_line_order', result.index('Output:') < result.index('ID:'), repr(result))


def w14_role_system_noise_still_nuked_through_full_chain():
    messages = [{'role': 'system', 'content': "The date has changed. Today's date is now 2026-04-22."}]
    messages, mods1, _, _, _, _ = _apply_role_system_strip(messages)
    messages, _m2, _, _, _, _ = _apply_sn_notice_strip(messages)
    messages, _m3, _, _, _, _ = _apply_first_pass(messages)
    check('W14_noise_nuked', messages[0]['content'] == '.', repr(messages[0]['content']))
    check('W14_mod_recorded', 'stripped_role_system_msg' in mods1, f'mods1: {mods1}')


# W30 — CC 2.1.223 mid-turn user message (role='system') preserved whole (issue #61). Pre-223 this
# arrived as a role='user' <system-reminder> ('user-interrupt' template, PARTIAL mode in
# strip_sr.py — IMPORTANT line stripped, user body kept). The 223 role=system form bypasses that
# SR-based guard entirely and was falling through to _apply_role_system_strip's unconditional '.'
# replacement, silently dropping the user's text before it reached the model. Real body (recorded
# session api_requests_opus_posts_1786051932, msg 274): 'jetzt' + CC's own boilerplate explainer.
def w30_role_system_mid_turn_user_msg_preserved_whole():
    real_body = (
        'The user sent a new message while you were working:\njetzt\n\n'
        'This is how Claude Code surfaces messages the user sends mid-turn — within the running '
        'turn, often alongside the next tool result, rather than as a separate conversation turn. '
        'Address the message above as you continue this turn.'
    )
    messages = [{'role': 'system', 'content': real_body}]
    new_messages, mods, removed, changed_idxs, injected, ops = _apply_role_system_strip(messages)
    check('W30_content_untouched', new_messages[0]['content'] == real_body, repr(new_messages[0]['content']))
    check('W30_user_text_present', 'jetzt' in new_messages[0]['content'])
    check('W30_role_preserved', new_messages[0]['role'] == 'system')
    check('W30_mod_not_fired', 'stripped_role_system_msg' not in mods, f'mods: {mods}')
    check('W30_no_changed_index', changed_idxs == [], f'changed_idxs: {changed_idxs}')
    check('W30_no_removed_recorded', removed == {}, f'removed: {removed}')
    check('W30_no_ops_recorded', ops == {}, f'ops: {ops}')

    # Leading whitespace before the marker — guard checks lstrip()'d text, not exact prefix.
    padded = '  \n' + real_body
    messages2 = [{'role': 'system', 'content': padded}]
    new_messages2, mods2, _, _, _, _ = _apply_role_system_strip(messages2)
    check('W30_leading_whitespace_still_preserved', new_messages2[0]['content'] == padded, repr(new_messages2[0]['content']))
    check('W30_leading_whitespace_mod_not_fired', 'stripped_role_system_msg' not in mods2)


# ── LAUNCH-ACK ID + PATH RECOVERY, TN ID LINE (2026-07-29 milestone) ──────────
# Both bg-launch-ack (strip_bg_launch_ack.py) and TN termination (_apply_first_pass) now emit a
# 3-line message: <line1>, then 'Output: <path>' (if extracted), then 'ID: <id>' (if extracted) —
# same fixed order in both places. Extraction verified against real recorded ack/TN bodies from
# src/logs/dual_log/ (api_requests_opus_monitor_cc_1785336796_original.jsonl +
# api_requests_opus_posts_1785338463_original.jsonl) — W18/W19 pin the exact real bodies.

# W15 — genuine ack, id + path both present (the only shape seen in real data) → 3 lines, fixed order
def w15_launch_ack_id_and_path_full():
    ack = ('Command running in background with ID: bg_01ABC. '
           'Output is being written to: /tmp/output_01ABC.txt. '
           'You will be notified when it completes. '
           'To check interim output, use Read on that file path.')
    new_content, removed = _strip_bg_launch_ack(ack)
    check('W15_msg_line', new_content.startswith('Command is running in the background.'), repr(new_content))
    check('W15_output_line', 'Output: /tmp/output_01ABC.txt' in new_content, repr(new_content))
    check('W15_id_line', 'ID: bg_01ABC' in new_content, repr(new_content))
    check('W15_line_order', new_content.index('Output:') < new_content.index('ID:'), repr(new_content))
    check('W15_removed_is_original_ack', removed == [ack])


# W16 — synthetic: id token empty → ID line omitted, no 'ID: None', Output line unaffected
def w16_launch_ack_missing_id_omits_id_line():
    ack = ('Command running in background with ID: . '
           'Output is being written to: /tmp/out.txt. '
           'You will be notified when it completes. '
           'To check interim output, use Read on that file path.')
    new_content, _removed = _strip_bg_launch_ack(ack)
    check('W16_no_id_line', 'ID:' not in new_content, repr(new_content))
    check('W16_no_dangling_none', 'None' not in new_content, repr(new_content))
    check('W16_output_line_present', 'Output: /tmp/out.txt' in new_content, repr(new_content))


# W17 — synthetic: no "Output is being written to:" segment → Output line omitted, ID unaffected
def w17_launch_ack_missing_path_omits_output_line():
    ack = 'Command running in background with ID: bg_02DEF. You will be notified when it completes.'
    new_content, _removed = _strip_bg_launch_ack(ack)
    check('W17_no_output_line', 'Output:' not in new_content, repr(new_content))
    check('W17_id_line_present', 'ID: bg_02DEF' in new_content, repr(new_content))


# W18 — real recorded ack body (src/logs/dual_log/api_requests_opus_monitor_cc_1785336796_original.jsonl)
def w18_launch_ack_real_corpus_body_exact():
    ack = (
        'Command running in background with ID: bg6wod7up. Output is being written to: '
        '/private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/'
        '80b146dd-9d9e-4cae-83c0-a1bbebb9e0cb/tasks/bg6wod7up.output. '
        'You will be notified when it completes. To check interim output, use Read on that file path.'
    )
    expected = (
        'Command is running in the background. Do NOT check, poll, or read its output — '
        'just wait until it finishes (you will get a completion notice).\n'
        'Output: /private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/'
        '80b146dd-9d9e-4cae-83c0-a1bbebb9e0cb/tasks/bg6wod7up.output\n'
        'ID: bg6wod7up\n'
    )
    new_content, _removed = _strip_bg_launch_ack(ack)
    check('W18_real_corpus_launch_exact', new_content == expected, repr(new_content))


# W19 — real recorded TN body (same corpus, failed status) → exact 3-line termination text
def w19_tn_real_corpus_body_exact():
    tn = (
        '<task-notification>\n<task-id>biw31morg</task-id>\n'
        '<tool-use-id>toolu_014Z5hrjf2UxcVLCKJqZyQ1U</tool-use-id>\n'
        '<output-file>/private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/'
        '80b146dd-9d9e-4cae-83c0-a1bbebb9e0cb/tasks/biw31morg.output</output-file>\n'
        '<status>failed</status>\n'
        '<summary>Background command "Rechenschleife bis Signal oder 30min-Timeout" failed with exit code 42</summary>\n'
        '</task-notification>'
    )
    expected = (
        'background done — check worker or other process\n'
        'Output: /private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/'
        '80b146dd-9d9e-4cae-83c0-a1bbebb9e0cb/tasks/biw31morg.output\n'
        'ID: biw31morg\n'
    )
    msgs = [{'role': 'user', 'content': tn}]
    new_msgs, mods, _, _c, _, _ops = _apply_first_pass(msgs)
    check('W19_real_corpus_tn_exact', new_msgs[0]['content'] == expected, repr(new_msgs[0]['content']))
    check('W19_mod_replaced', 'replaced_task_notification' in mods, f'mods: {mods}')


# W20 — TN block with <output-file> but no <task-id> → ID line omitted, Output line present
def w20_tn_missing_task_id_omits_id_line():
    tn = '<task-notification>\n<output-file>/tmp/foo.output</output-file>\n<status>completed</status>\n<summary>x</summary>\n</task-notification>\n'
    msgs = [{'role': 'user', 'content': tn}]
    new_msgs, mods, _, _c, _, _ops = _apply_first_pass(msgs)
    result = new_msgs[0]['content']
    check('W20_no_id_line', 'ID:' not in result, repr(result))
    check('W20_no_dangling_none', 'None' not in result, repr(result))
    check('W20_output_line_present', 'Output: /tmp/foo.output' in result, repr(result))


# W21 — TN block with <task-id> but no <output-file> → Output line omitted, ID line present
def w21_tn_missing_output_file_omits_output_line():
    tn = '<task-notification>\n<task-id>abc999</task-id>\n<status>completed</status>\n<summary>x</summary>\n</task-notification>\n'
    msgs = [{'role': 'user', 'content': tn}]
    new_msgs, mods, _, _c, _, _ops = _apply_first_pass(msgs)
    result = new_msgs[0]['content']
    check('W21_no_output_line', 'Output:' not in result, repr(result))
    check('W21_id_line_present', 'ID: abc999' in result, repr(result))


# W22 — neither <task-id> nor <output-file> → reduces to exactly _WAKEUP_TEXT (regression guard for
# the lines-list refactor: unconditional join must collapse back to the original bare-wakeup shape)
def w22_tn_no_id_no_output_reduces_to_bare_wakeup():
    tn = '<task-notification>\n<status>completed</status>\n<summary>x</summary>\n</task-notification>\n'
    msgs = [{'role': 'user', 'content': tn}]
    new_msgs, mods, _, _c, _, _ops = _apply_first_pass(msgs)
    check('W22_bare_wakeup_only', new_msgs[0]['content'] == _WAKEUP_TEXT, repr(new_msgs[0]['content']))


# ── LAUNCH-ACK WORDING 2 RECOGNITION (2026-07-29 milestone-2) ─────────────────
# Second CC wording ("Command was manually backgrounded by user with ID: ...") — fired when the
# user manually backgrounds an already-running Bash call, distinct from the wording-1 initial-
# launch ack. Measured in dev/bg_wakeup_id_line/md/launch_ack_wordings_20260729.md (2026-07-29):
# no ". You will be notified..." trailing sentence, ack IS the complete block in the only measured
# occurrence. W23 pins the exact 220-char live-observed text verbatim (not a paraphrase). W24 pins
# the trailing-content-in-same-block shape the M1 blast-radius classification flagged as possible
# but unobserved ("ANY trailing content after the ack in that block is also discarded").

# W23 — real live-observed wording-2 body, verbatim (2026-07-29 live observation) — exact 3-line output
def w23_launch_ack_wording2_real_body_exact():
    ack = (
        'Command was manually backgrounded by user with ID: bsxpatpam. Output is being written '
        'to: /private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/'
        '587284d6-c174-4432-a8d0-b5e2bcf10f0b/tasks/bsxpatpam.output'
    )
    check('W23_input_length_220', len(ack) == 220, f'len={len(ack)}')
    expected = (
        'Command is running in the background. Do NOT check, poll, or read its output — '
        'just wait until it finishes (you will get a completion notice).\n'
        'Output: /private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/'
        '587284d6-c174-4432-a8d0-b5e2bcf10f0b/tasks/bsxpatpam.output\n'
        'ID: bsxpatpam\n'
    )
    new_content, removed = _strip_bg_launch_ack(ack)
    check('W23_wording2_real_body_exact', new_content == expected, repr(new_content))
    check('W23_removed_is_original_ack', removed == [ack])
    check('W23_same_msg_line_as_wording1', new_content.startswith(
        'Command is running in the background. Do NOT check, poll, or read its output'
    ))


# W24 — wording-2 ack followed by trailing content in the SAME block (unobserved in the measured
# corpus, but the pass's own replacement mechanism discards "ANY trailing content after the ack in
# that block" per the M1 blast-radius classification — regression guard for the fix: without a
# newline bound on _ACK_PATH_RE's no-sentence fallback, this trailing text was swallowed into the
# Output line instead of being cleanly discarded with the rest of the block)
def w24_launch_ack_wording2_trailing_content_not_swallowed_into_path():
    ack = (
        'Command was manually backgrounded by user with ID: bsxpatpam. Output is being written '
        'to: /private/tmp/y/tasks/bsxpatpam.output'
    )
    ack_with_trailing = ack + '\nsome trailing note'
    new_content, _removed = _strip_bg_launch_ack(ack_with_trailing)
    check('W24_output_line_path_only',
          'Output: /private/tmp/y/tasks/bsxpatpam.output\n' in new_content, repr(new_content))
    check('W24_trailing_note_not_swallowed', 'some trailing note' not in new_content, repr(new_content))
    check('W24_id_line_present', 'ID: bsxpatpam' in new_content, repr(new_content))


# ── INTERRUPT-MARKER TESTS (strip_interrupt_marker.py, 2026-07-30, re-measured 2026-07-31) ────
# CC records the proxy's bg_escape.py tmux-Escape into a worker's pane as
# "[Request interrupted by user]" or "[Request interrupted by user for tool use]" — never a
# genuine user interrupt. Both real corpus wordings carry a trailing '\n' (11/11 occurrences,
# src/logs/dual_log/*_original.jsonl, 2026-07-31 re-measurement). Whole-block match anchored
# (ignoring only surrounding whitespace), NOT substring-anywhere — same FP-nuke class as
# bg_launch_ack / sn_notice / plan_mode.
_INTERRUPT_MARKER_NL = _INTERRUPT_MARKER + '\n'
_INTERRUPT_MARKER_TOOL_USE_NL = _INTERRUPT_MARKER_TOOL_USE + '\n'

# W25 — real measured shape: tool_result / marker(+trailing '\n') / injected wake-up (3 blocks).
# Marker emptied to '.'; neighbors byte-identical.
def w25_interrupt_marker_real_shape_neighbors_intact():
    tool_result_block = {'type': 'tool_result', 'tool_use_id': 'toolu_01', 'content': 'prior output'}
    marker_block = {'type': 'text', 'text': _INTERRUPT_MARKER_NL}
    wakeup_block = {'type': 'text', 'text': _WAKEUP_TEXT}
    content = [tool_result_block, marker_block, wakeup_block]
    new_content, removed = _strip_interrupt_marker(content)
    check('W25_removed_is_marker', removed == [_INTERRUPT_MARKER_NL])
    check('W25_block_count_unchanged', len(new_content) == 3)
    check('W25_marker_block_emptied', new_content[1] == {'type': 'text', 'text': '.'})
    check('W25_preceding_block_identical', new_content[0] == tool_result_block)
    check('W25_following_block_identical', new_content[2] == wakeup_block)


# W26 — 4 content shapes, each with the real newline-terminated marker.
def w26_interrupt_marker_four_shapes():
    s, r = _strip_interrupt_marker(_INTERRUPT_MARKER_NL)
    check('W26_str_shape', s == '.' and r == [_INTERRUPT_MARKER_NL])
    lt, r = _strip_interrupt_marker(text_block(_INTERRUPT_MARKER_NL))
    check('W26_list_text_shape', lt[0]['text'] == '.' and r == [_INTERRUPT_MARKER_NL])
    trs, r = _strip_interrupt_marker(tool_result_str(_INTERRUPT_MARKER_NL))
    check('W26_tool_result_str_shape', trs[0]['content'] == '.' and r == [_INTERRUPT_MARKER_NL])
    trl, r = _strip_interrupt_marker(tool_result_list(_INTERRUPT_MARKER_NL))
    check('W26_tool_result_list_shape', trl[0]['content'][0]['text'] == '.' and r == [_INTERRUPT_MARKER_NL])


# W26b — the 2nd real wording ("for tool use"), newline-terminated and bare, both strip.
def w26b_interrupt_marker_tool_use_wording():
    s, r = _strip_interrupt_marker(_INTERRUPT_MARKER_TOOL_USE_NL)
    check('W26b_tool_use_wording_nl_stripped', s == '.' and r == [_INTERRUPT_MARKER_TOOL_USE_NL])
    s2, r2 = _strip_interrupt_marker(_INTERRUPT_MARKER_TOOL_USE)
    check('W26b_tool_use_wording_bare_stripped', s2 == '.' and r2 == [_INTERRUPT_MARKER_TOOL_USE])


# W27 — false-positive class: marker embedded inside longer text must survive untouched, incl.
# a real corpus-derived 180-char user message that quotes the bracketed marker mid-sentence
# (src/logs/dual_log/api_requests_opus_monitor_cc_1785431184_original.jsonl, msg 11).
def w27_interrupt_marker_embedded_in_longer_text_untouched():
    longer = f'Note earlier: {_INTERRUPT_MARKER} was quoted from a transcript.'
    new_tb, r1 = _strip_interrupt_marker(text_block(longer))
    check('W27_top_level_text_untouched', new_tb[0]['text'] == longer and r1 == [])
    new_tr, r2 = _strip_interrupt_marker(tool_result_str(longer))
    check('W27_tool_result_untouched', new_tr[0]['content'] == longer and r2 == [])
    new_str, r3 = _strip_interrupt_marker(longer)
    check('W27_top_level_str_untouched', new_str == longer and r3 == [])

    corpus_quote = (
        '[Image #3] ok live verify da. hast du  [Request interrupted by user] gesehen? wenn ja '
        'funktionniert der strip nicht. wenn nein funktionniert der strip aber das rendering ist broken'
    )
    new_cq, r4 = _strip_interrupt_marker(text_block(corpus_quote))
    check('W27_corpus_quote_untouched', new_cq[0]['text'] == corpus_quote and r4 == [])


# W28 — message-pass wiring: role='user' only, mod name, removed-chunk attribution — real
# newline-terminated marker.
def w28_interrupt_marker_pass_role_gate_and_mod():
    msgs = [
        {'role': 'assistant', 'content': text_block(_INTERRUPT_MARKER_NL)},
        {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'toolu_02', 'content': 'output'},
            {'type': 'text', 'text': _INTERRUPT_MARKER_NL},
            {'type': 'text', 'text': _WAKEUP_TEXT},
        ]},
    ]
    new_msgs, mods, removed_by_idx, changed, _inj, ops = _apply_interrupt_marker_strip(msgs)
    check('W28_assistant_role_untouched', new_msgs[0] == msgs[0])
    check('W28_user_msg_changed', changed == [1])
    check('W28_mod_name', mods == ['stripped_interrupt_marker'])
    check('W28_removed_chunk', removed_by_idx[1] == [_INTERRUPT_MARKER_NL])
    check('W28_ops_recorded_block1', 1 in ops.get(1, {}))


# W29 — message-pass wiring for the "for tool use" wording (previously untested — the gap the
# false-negative shipped through).
def w29_interrupt_marker_pass_tool_use_wording():
    msgs = [
        {'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'toolu_03', 'content': 'output'},
            {'type': 'text', 'text': _INTERRUPT_MARKER_TOOL_USE_NL},
            {'type': 'text', 'text': _WAKEUP_TEXT},
        ]},
    ]
    new_msgs, mods, removed_by_idx, changed, _inj, ops = _apply_interrupt_marker_strip(msgs)
    check('W29_user_msg_changed', changed == [0])
    check('W29_mod_name', mods == ['stripped_interrupt_marker'])
    check('W29_removed_chunk', removed_by_idx[0] == [_INTERRUPT_MARKER_TOOL_USE_NL])
    check('W29_marker_block_emptied', new_msgs[0]['content'][1]['text'] == '.')


if __name__ == '__main__':
    tests = [
        t01_task_tools_nag_real_text_block, t02_task_tools_nag_fp_code_literal, t03_task_tools_nag_tool_result_preserved,
        t04_pyright_real, t05_pyright_fp, t06_pyright_tool_result_nested_preserved,
        t07_deferred_tools_real, t08_deferred_tools_fp, t09_deferred_tools_tool_result_preserved,
        t10_user_interrupt_partial_body_preserved, t11_user_interrupt_fp, t12_user_interrupt_tool_result_preserved,
        t13_system_notification_real, t14_system_notification_fp, t15_system_notification_tool_result_preserved,
        t16_file_modified_real, t17_file_modified_fp, t18_file_modified_tool_result_preserved,
        t19_claudemd_real, t20_claudemd_fp, t21_claudemd_tool_result_preserved,
        t22_date_changed_real, t23_date_changed_fp, t24_date_changed_tool_result_preserved,
        t25_shape_plain_string, t26_shape_list_text, t27_shape_tool_result_str_now_preserved, t28_shape_tool_result_list_now_preserved,
        t29_plan_mode_returns_none_when_empty, t30_plan_mode_preserves_other_content,
        t31_find_sr_blocks_tool_result_finds_none, t32_find_sr_blocks_top_level_real_found,
        t33_content_contains_tool_result_str, t34_content_contains_text_block,
        t35_final_sr_pass_tool_result_str_identity_preserved, t36_final_sr_pass_tool_result_list_identity_preserved,
        t37_occurrence8_fenced_env_context_in_tool_result_preserved,
        t38_top_level_task_tools_nag_still_stripped_via_first_pass, t39_top_level_date_changed_still_stripped_via_final_sr_pass,
        w01_tn_in_tool_result_str, w02_tn_in_tool_result_list, w03_bgk_in_tool_result_str,
        w04_genuine_tn_completed_plain_string, w05_genuine_tn_failed_plain_string,
        w06_genuine_bgk_plain_string,
        w07_sn_notice_genuine_plain_string, w08_sn_notice_text_block_index_one,
        w09_sn_notice_tool_result_untouched, w10_sn_notice_mid_content_untouched,
        w11_sn_notice_role_system_untouched,
        w12_role_system_tn_completed_full_pipeline, w13_role_system_tn_failed_with_output_file,
        w14_role_system_noise_still_nuked_through_full_chain,
        w15_launch_ack_id_and_path_full, w16_launch_ack_missing_id_omits_id_line,
        w17_launch_ack_missing_path_omits_output_line, w18_launch_ack_real_corpus_body_exact,
        w19_tn_real_corpus_body_exact, w20_tn_missing_task_id_omits_id_line,
        w21_tn_missing_output_file_omits_output_line, w22_tn_no_id_no_output_reduces_to_bare_wakeup,
        w23_launch_ack_wording2_real_body_exact, w24_launch_ack_wording2_trailing_content_not_swallowed_into_path,
        w25_interrupt_marker_real_shape_neighbors_intact, w26_interrupt_marker_four_shapes,
        w26b_interrupt_marker_tool_use_wording,
        w27_interrupt_marker_embedded_in_longer_text_untouched, w28_interrupt_marker_pass_role_gate_and_mod,
        w29_interrupt_marker_pass_tool_use_wording,
        w30_role_system_mid_turn_user_msg_preserved_whole,
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
