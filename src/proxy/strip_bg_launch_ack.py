import re

# INFRASTRUCTURE

# Fast-path marker — cheap contains check before block walk
_BG_LAUNCH_ACK_MARKER = 'running in background with ID'
# Anchored ack prefix: a genuine CC bg-launch ack ALWAYS starts with this exact prefix. The strip
# decision uses startswith() on the lstripped text (NOT substring-anywhere), so a large tool_result
# or user message that merely CONTAINS the phrase as data is never destroyed (was the FP-nuke bug).
_BG_LAUNCH_ACK_PREFIX = 'Command running in background with ID:'

_BG_LAUNCH_ACK_MSG = (
    'Command is running in the background. Do NOT check, poll, or read its output — '
    'just wait until it finishes (you will get a completion notice).'
)

# Recover id/path FROM the ack text being replaced — real recorded shape (verified against
# src/logs/dual_log/): "Command running in background with ID: <id>. Output is being written to:
# <path>. You will be notified when it completes. To check interim output, use Read on that file
# path." Id group excludes '.' (ids are alnum tokens in every measured occurrence); path group is
# non-greedy up to the literal ". You will be notified" so an internal dot in the path (e.g. the
# ".output" extension) doesn't truncate it early.
_ACK_ID_RE = re.compile(r'Command running in background with ID:\s*([^.]*)\.')
_ACK_PATH_RE = re.compile(r'Output is being written to:\s*(.*?)\.\s*You will be notified', re.DOTALL)


# True only for a genuine bg-launch ack: the marker phrase anchored at the start of the text.
def _is_bg_launch_ack(text):
    return text.lstrip().startswith(_BG_LAUNCH_ACK_PREFIX)


# ORCHESTRATOR

# Replace entire content of any block whose text STARTS WITH the bg-launch-ack prefix with the
# 3-line hold message (msg + optional Output: + optional ID:, recovered from the ack itself).
# Anchored (not substring-anywhere): legitimate content that merely contains the phrase is kept.
# Covers all 4 content shapes: str, list[text], list[tool_result+str], list[tool_result+list].
# Returns (new_content, removed_chunks) — removed_chunks: original texts of replaced blocks.
def _strip_bg_launch_ack(content):
    removed = []
    if isinstance(content, str):
        if _is_bg_launch_ack(content):
            removed.append(content)
            return _build_launch_ack_replacement(content), removed
        return content, removed
    if isinstance(content, list):
        result = []
        for block in content:
            if not isinstance(block, dict):
                result.append(block)
                continue
            btype = block.get('type')
            if btype == 'text':
                text = block.get('text', '')
                if _is_bg_launch_ack(text):
                    removed.append(text)
                    result.append({**block, 'text': _build_launch_ack_replacement(text)})
                else:
                    result.append(block)
            elif btype == 'tool_result':
                inner = block.get('content', '')
                if isinstance(inner, str):
                    if _is_bg_launch_ack(inner):
                        removed.append(inner)
                        result.append({**block, 'content': _build_launch_ack_replacement(inner)})
                    else:
                        result.append(block)
                elif isinstance(inner, list):
                    new_sub = []
                    sub_changed = False
                    for sub in inner:
                        if isinstance(sub, dict) and sub.get('type') == 'text':
                            text = sub.get('text', '')
                            if _is_bg_launch_ack(text):
                                removed.append(text)
                                new_sub.append({**sub, 'text': _build_launch_ack_replacement(text)})
                                sub_changed = True
                            else:
                                new_sub.append(sub)
                        else:
                            new_sub.append(sub)
                    result.append({**block, 'content': new_sub} if sub_changed else block)
                else:
                    result.append(block)
            else:
                result.append(block)
        return result, removed
    return content, removed


# FUNCTIONS

# Build the 3-line hold message from a genuine ack's text: msg, then Output: <path> (if the ack's
# path was recovered), then ID: <id> (if the ack's id was recovered). A value that fails to extract
# is OMITTED — never "ID: None", never a dangling "ID:" with nothing after it. Not observed in real
# data (id+path present in every measured ack), defensive only.
def _build_launch_ack_replacement(ack_text):
    id_match = _ACK_ID_RE.search(ack_text)
    path_match = _ACK_PATH_RE.search(ack_text)
    task_id = id_match.group(1).strip() if id_match else ''
    path = path_match.group(1).strip() if path_match else ''
    lines = [_BG_LAUNCH_ACK_MSG]
    if path:
        lines.append('Output: ' + path)
    if task_id:
        lines.append('ID: ' + task_id)
    return '\n'.join(lines) + '\n'
