# INFRASTRUCTURE
from typing import Dict, List, Optional
import os
import time

from ..constants import (
    GREEN, RED, YELLOW, WHITE, CYAN,
    DIM, PASTEL_PURPLE, SOFT_RESET,
    SEARCH_MATCH_BG, SEARCH_CURRENT_BG,
)
from ..format.token_format import _format_k, format_cache_tracker
from ..jsonl import read_new_lines, parse_jsonl_lines, get_message_content, is_tool_use
# From utils.py: right-align a ⎘/✓ copy symbol at the pane edge, width-guarded
from ..utils import append_copy_symbol
# From search_bar.py: shared BG-restore sentinel (2026-08-18, rollout sub-milestone 5) — this
# module doesn't know a row's eventual chosen_bg (zebra/hover) at embed time, only
# worker_pane.py's own render loop does, once computed; same pattern as format/token_format.py
from ..search_bar import _BG_RESTORE_SENTINEL

INDENT = '  '

# Worker fleet is all 1M-context models (opus-4-8, sonnet-5, fable-5); haiku-4-5 (200k) is never a worker.
_WORKER_CONTEXT_WINDOW = 1000000

# FUNCTIONS

# Derive worker project name from project path (worktree-aware, matches tmux_spawn.sh logic)
def get_worker_project_name(project_path: str) -> str:
    if '/.claude/worktrees/' in project_path:
        base = project_path.split('/.claude/worktrees/')[0]
        return os.path.basename(base)
    return os.path.basename(os.path.normpath(project_path))

# Extract all tool_use entries from a worker's JSONL file
def extract_worker_tokens(jsonl_path) -> dict:
    lines = read_new_lines(jsonl_path, 0)
    messages, _ = parse_jsonl_lines(lines)
    total_output = 0
    for message in messages:
        if message.get('type') != 'assistant':
            continue
        usage = message.get('message', {}).get('usage', {})
        total_output += usage.get('output_tokens', 0)
    return {'output': total_output}

# Extract remaining context percentage from a worker's JSONL (mirrors worker-cli context_pct formula)
def extract_worker_context_pct(jsonl_path) -> Optional[int]:
    lines = read_new_lines(jsonl_path, 0)
    messages, _ = parse_jsonl_lines(lines)
    cr = None
    for message in messages:
        if message.get('type') != 'assistant':
            continue
        val = message.get('message', {}).get('usage', {}).get('cache_read_input_tokens')
        if val is not None:
            cr = val
    if cr is None:
        return None
    return (100 * (_WORKER_CONTEXT_WINDOW - cr)) // _WORKER_CONTEXT_WINDOW

# Extract tool call list from a worker's JSONL file
def extract_worker_tool_calls(jsonl_path) -> List[dict]:
    lines = read_new_lines(jsonl_path, 0)
    messages, _ = parse_jsonl_lines(lines)
    calls = []
    call_number = 0
    for message in messages:
        content_blocks = get_message_content(message)
        timestamp = message.get('timestamp', '')
        for block in content_blocks:
            if is_tool_use(block):
                call_number += 1
                calls.append({
                    'tool_name': block.get('name', 'Unknown'),
                    'input': block.get('input', {}),
                    'timestamp': timestamp,
                    'call_number': call_number,
                })
    return calls

# Filter a flat copy-feedback dict (str name keys + (name,turn_idx,call_idx) tuple keys) down to
# this worker's (turn_idx, call_idx)→expiry sub-dict, for format_cache_tracker's own key format
def _worker_cache_copy_feedback(copy_feedback: Optional[dict], name: str) -> Optional[dict]:
    if copy_feedback is None:
        return None
    return {(k[1], k[2]): exp for k, exp in copy_feedback.items()
            if isinstance(k, tuple) and len(k) == 3 and k[0] == name}

# Scope a flat search-match set (worker-tagged keys: str name / (name,'turn',turn_idx) /
# (name,turn_idx,call_idx)) down to THIS worker's own token_format-shape keys
# (('turn',turn_idx) / (turn_idx,call_idx)) — a match belonging to a DIFFERENT worker must never
# highlight in this worker's own nested cache-tracker view.
def _scope_matches_to_worker(matches, name: str) -> set:
    scoped = set()
    for k in matches or ():
        if isinstance(k, tuple) and len(k) == 3 and k[0] == name:
            scoped.add(('turn', k[2]) if k[1] == 'turn' else (k[1], k[2]))
    return scoped

# Scope the current match key to THIS worker's own token_format-shape key, or None when the
# current match belongs to a different worker (or is the bare worker-level key itself, which
# format_cache_tracker has no concept of).
def _scope_current_key_to_worker(current_key, name: str):
    if isinstance(current_key, tuple) and len(current_key) == 3 and current_key[0] == name:
        return ('turn', current_key[2]) if current_key[1] == 'turn' else (current_key[1], current_key[2])
    return None

# Build flat (all_lines, line_keys) for workers pane; keys: str=worker name, 3-tuple=cache entry,
# None=non-clickable. (2026-08-18, rollout sub-milestone 5) search_match_set/search_current_key
# hold worker-TAGGED keys (str name / (name,'turn',turn_idx) / (name,turn_idx,call_idx) — same
# shape state.matches in worker_pane.py holds). A worker-level match (bare name) container-marks
# the header_line unconditionally (marker+line+sentinel, mirrors token_format's turn-header
# treatment) — BEFORE append_copy_symbol, so the copy button stays outside the marked span. A
# turn/call-level match is scoped down (_scope_matches_to_worker/_scope_current_key_to_worker)
# to THIS worker's own token_format-shape keys and threaded into format_cache_tracker, which
# does ALL the collapsed-container-mark / expanded-substring-highlight work internally — zero
# new highlighting logic needed for the nested view.
def format_workers_block(workers: list, expand_states: dict = None, worker_turns: dict = None, scroll_offsets: dict = None, cache_expand_states: dict = None, frozen: bool = False, selected_name: Optional[str] = None, copy_feedback: Optional[dict] = None, regions_out: Optional[dict] = None, search_match_set: Optional[set] = None, search_current_key=None, search_query: str = '') -> tuple:
    freeze_indicator = f" {YELLOW}[FROZEN]{SOFT_RESET}" if frozen else f" {CYAN}[LIVE]{SOFT_RESET}"

    try:
        pane_width = os.get_terminal_size().columns
    except OSError:
        pane_width = 80

    # Freeze badge always sits on the FIRST line ("Workers [LIVE]"/"[FROZEN]") — the pane has no
    # separate fixed header, this line is part of the scrollable content (see worker_pane.py's
    # DOCS gotcha); the caller resolves whether it survived viewport clipping and, if so, which
    # phys_row it landed on. Column span only, no row — width-guarded, same as append_copy_symbol.
    if regions_out is not None:
        regions_out.clear()
        badge = "[FROZEN]" if frozen else "[LIVE]"
        start_col = len("Workers") + 1
        end_col = start_col + len(badge) - 1
        if end_col < pane_width:
            regions_out['freeze'] = (start_col + 1, end_col + 1)

    all_lines: List[str] = []
    line_keys: List = []

    if not workers:
        all_lines.append(f"{WHITE}Workers{SOFT_RESET}{freeze_indicator}")
        line_keys.append(None)
        all_lines.append('')
        line_keys.append(None)
        all_lines.append(f"{YELLOW}No active workers{SOFT_RESET}")
        line_keys.append(None)
        return all_lines, line_keys

    if expand_states is None:
        expand_states = {}
    if worker_turns is None:
        worker_turns = {}

    status_colors = {
        'working': GREEN,
        'idle': YELLOW,
        'exited': RED,
        'unknown': WHITE,
    }

    all_lines.append(f"{WHITE}Workers{SOFT_RESET}{freeze_indicator}")
    line_keys.append(None)
    all_lines.append('')
    line_keys.append(None)

    for idx, w in enumerate(workers, 1):
        status = w.get('status', 'unknown')
        sc = status_colors.get(status, WHITE)
        name = w.get('name', '?')
        spawned = w.get('spawned', '')
        purpose = w.get('purpose', '')
        is_expanded = expand_states.get(name, False)
        toggle_symbol = "[-]" if is_expanded else "[+]"

        spawned_str = f"  {WHITE}{spawned}{SOFT_RESET}" if spawned else ''
        model = w.get('model', '')
        model_str = f"  {PASTEL_PURPLE}{model}{SOFT_RESET}" if model else ''
        tokens = w.get('tokens', {})
        tok_out = tokens.get('output', 0)
        tokens_str = f"  {WHITE}{_format_k(tok_out)}out{SOFT_RESET}" if tok_out else ''
        pct = w.get('context_pct')
        if pct is None:
            pct_str = f"  {DIM}—%{SOFT_RESET}"
        else:
            pct_color = GREEN if pct >= 60 else (YELLOW if pct >= 40 else RED)
            pct_str = f"  {pct_color}{pct:3d}%{SOFT_RESET}"
        is_selected = selected_name is not None and name == selected_name
        sel_prefix = f"{GREEN}>>{SOFT_RESET} " if is_selected else "   "
        header_line = f"{sel_prefix}{toggle_symbol} {CYAN}[{idx}] {name}{SOFT_RESET}  {sc}{status.upper()}{SOFT_RESET}{pct_str}{spawned_str}{model_str}{tokens_str}"
        if search_match_set and name in search_match_set:
            marker = SEARCH_CURRENT_BG if name == search_current_key else SEARCH_MATCH_BG
            header_line = f"{marker}{header_line}{_BG_RESTORE_SENTINEL}"
        if copy_feedback is not None:
            is_flash = copy_feedback.get(name, 0) > time.time()
            header_line = append_copy_symbol(header_line, '✓' if is_flash else '⎘', pane_width)
        all_lines.append(header_line)
        line_keys.append(name)

        if purpose:
            if is_expanded:
                purpose_line = f"{INDENT}{WHITE}{purpose}{SOFT_RESET}"
            else:
                truncated = purpose[:60] + ('...' if len(purpose) > 60 else '')
                purpose_line = f"{INDENT}{WHITE}{truncated}{SOFT_RESET}"
            all_lines.append(purpose_line)
            line_keys.append(name)

        if is_expanded:
            turns = worker_turns.get(name, [])
            if not turns:
                all_lines.append(f"{INDENT}{YELLOW}(no token data yet){SOFT_RESET}")
                line_keys.append(name)
            else:
                scroll_offset = (scroll_offsets or {}).get(name, 0)
                per_worker_expand = (cache_expand_states or {}).get(name, {})
                visible_lines, visible_keys, _, _, _ = format_cache_tracker(
                    turns, per_worker_expand, 15, pane_width - 4, scroll_offset,
                    copy_feedback=_worker_cache_copy_feedback(copy_feedback, name),
                    search_match_set=_scope_matches_to_worker(search_match_set, name),
                    search_current_key=_scope_current_key_to_worker(search_current_key, name),
                    search_query=search_query,
                )
                for cl, ck in zip(visible_lines, visible_keys):
                    all_lines.append(f"  {cl}")
                    if ck is not None:
                        line_keys.append((name, ck[0], ck[1]))
                    else:
                        line_keys.append(None)

        all_lines.append('')
        line_keys.append(None)

    while all_lines and all_lines[-1] == '':
        all_lines.pop()
        line_keys.pop()

    return all_lines, line_keys
