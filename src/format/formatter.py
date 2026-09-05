# INFRASTRUCTURE
import re

# From constants.py: Colors and config values
from ..constants import GREEN, BLUE, YELLOW, CYAN, RED, RESET

INDENT = '  '

SCORE_PATTERN = re.compile(r'^-+ Result \d+ \(score: [\d.]+\) -+$')

# ORCHESTRATOR
# `req_num` (2026-09, main-pane redesign — tool-calls-only, req-numbered like the tokens pane):
# the same ordinal the tokens pane shows as REQ #N for this tool_use's requestId (int), or '?'
# when unresolved (see jsonl_parser.update_request_numbers / core/monitor_session.py). Replaces
# the old per-monitor `call_number` in the header; no timestamp, no char counts, no →/← arrows.
def format_tool_call(tool_name: str, input_data: dict, output_data: str, req_num, is_subagent: bool = False, is_error: bool = False) -> str:
    request = format_request(tool_name, input_data, req_num, is_subagent)
    response = format_response(output_data, is_error)
    return combine_request_response(request, response)

# FUNCTIONS

# Combine the header+params block and the result block with one blank-line separator
def combine_request_response(request: str, response: str) -> str:
    return f"{request}\n\n{response}"

# Format the "req N: ToolName" header (color by agent type) plus params
def format_request(tool_name: str, input_data: dict, req_num, is_subagent: bool = False) -> str:
    color = BLUE if is_subagent else GREEN
    header = f"{color}req {req_num}: {tool_name}{RESET}"

    if tool_name == 'TodoWrite' and 'todos' in input_data:
        params = format_todo_list(input_data['todos'])
    elif tool_name == 'Task' and 'subagent_type' in input_data:
        params = format_task_parameters(input_data)
    else:
        params = format_parameters(input_data)

    return f"{header}\n{params}" if params else header

# Format the result body — red when the tool call errored, plain otherwise. No header: the
# single "req N: ToolName" header above already identifies the call.
def format_response(output_data: str, is_error: bool = False) -> str:
    if is_error:
        return format_error_output(output_data)
    return format_output(output_data)

# Format todo list with colored status and icons
def format_todo_list(todos: list) -> str:
    if not todos:
        return f"{INDENT}(no todos)"

    lines = []
    for idx, todo in enumerate(todos, 1):
        status = todo.get('status', 'pending')
        content = todo.get('content', '(no content)')

        icon = get_status_icon(status)
        color = get_status_color(status)
        status_label = status.upper().replace('_', ' ')

        lines.append(f"\n{INDENT}TODO #{idx} - {status_label} {icon}")
        lines.append(f"{INDENT}{INDENT}{color}{content}{RESET}")

    return '\n'.join(lines)

# Format input parameters with 2-space indentation
def format_parameters(params: dict) -> str:
    lines = []
    for key, value in params.items():
        formatted_value = format_value(value)
        lines.append(f"{INDENT}{key}: {formatted_value}")
    return '\n'.join(lines)

# Format Task parameters with highlighted subagent_type
def format_task_parameters(params: dict) -> str:
    lines = []
    for key, value in params.items():
        if key == 'subagent_type':
            lines.append(f"{INDENT}{key}: {CYAN}{value}{RESET}")
        else:
            formatted_value = format_value(value)
            lines.append(f"{INDENT}{key}: {formatted_value}")
    return '\n'.join(lines)

# Format output content with 2-space indentation
def format_output(content: str) -> str:
    if not content:
        return f"{INDENT}(empty)"

    lines = content.split('\n')
    formatted_lines = []
    for line in lines:
        line = line.expandtabs(8)
        if SCORE_PATTERN.match(line.strip()):
            formatted_lines.append(f"{INDENT}{GREEN}{line}{RESET}")
        else:
            formatted_lines.append(f"{INDENT}{line}")
    return '\n'.join(formatted_lines)

# Format error output content in red — the visible error marker (no separate [ERROR] header)
def format_error_output(content: str) -> str:
    if not content:
        return f"{INDENT}{RED}(empty){RESET}"

    lines = content.split('\n')
    formatted_lines = '\n'.join(f"{INDENT}{RED}{line.expandtabs(8)}{RESET}" for line in lines)
    return formatted_lines

# Format a parameter value: multi-line strings render as-is under the key (indented, unchanged
# from before); dict/list values flatten to indented key:value / bullet lines rather than
# Python-repr braces+quotes — unobserved in real tool usage (measured 2026-09: 840 real tool_use
# blocks across 6 sessions in 2 projects, 0 dict/list-valued params — see process-docs/main_pane/)
# but still avoided since a future tool call could carry one. `depth` only affects nested
# dict/list indentation; every existing single-level caller passes no depth (default 1), so a
# plain multi-line string renders byte-identical to before.
def format_value(value, depth: int = 1) -> str:
    pad = INDENT * depth
    if isinstance(value, str):
        if '\n' in value:
            lines = value.split('\n')
            return '\n' + '\n'.join(f"{pad}{line.expandtabs(8)}" for line in lines)
        return value
    if isinstance(value, dict):
        if not value:
            return '(empty)'
        lines = [f"{pad}{k}: {format_value(v, depth + 1)}" for k, v in value.items()]
        return '\n' + '\n'.join(lines)
    if isinstance(value, list):
        if not value:
            return '(empty)'
        lines = [f"{pad}- {format_value(v, depth + 1)}" for v in value]
        return '\n' + '\n'.join(lines)
    return str(value)

# Get status icon for todo item
def get_status_icon(status: str) -> str:
    icons = {
        'completed': '[X]',
        'in_progress': '[>]',
        'pending': '[-]'
    }
    return icons.get(status, '[-]')

# Get status color for todo item
def get_status_color(status: str) -> str:
    colors = {
        'completed': GREEN,
        'in_progress': YELLOW,
        'pending': RESET
    }
    return colors.get(status, RESET)

# Shorten MCP tool names for display (mcp__plugin_xxx_yyy__tool_name → tool_name)
def shorten_tool_name(name: str) -> str:
    if name.startswith('mcp__'):
        parts = name.split('__')
        if len(parts) >= 3:
            return parts[-1]
    return name
