# INFRASTRUCTURE

# Exact tmux-Escape interruption marker CC records when the proxy sends an Escape keystroke into
# a worker's pane mid-tool-call (bg_escape.py) — CC logs this identically to a genuine user
# Ctrl-C/Escape interrupt, though no user pressed anything. Measured (full dual-log corpus scan,
# 2026-07-30): 1791 occurrences across 4 log files, EVERY occurrence role='user', block
# type='text', text EXACTLY this string, block index 1 of 3 (preceded by a tool_result or text
# block, followed by the proxy's injected wake-up text) — never embedded inside longer text.
_INTERRUPT_MARKER = '[Request interrupted by user]'


# True only for an exact match — the marker is its own whole block in every measured occurrence.
# Exact-equality, NOT substring-anywhere: a genuine user paste/transcript that happens to CONTAIN
# this phrase inside longer text must never be nuked (the FP-nuke class every other strip_*.py
# anchors against).
def _is_interrupt_marker(text):
    return text == _INTERRUPT_MARKER


# ORCHESTRATOR

# Replace the text of any block that IS the interrupt marker with '.'. The marker occupies its
# own block among others (measured shape: tool_result / marker / injected-wakeup) — content is
# emptied in place rather than spliced out of the list: keeps block count/indices stable for
# downstream index-keyed diffing (rule_ops._ops_from_content_change walks old/new content by
# index), and matches the emptied-block convention ('.') the other strip_*.py passes use for a
# block reduced to nothing (the API rejects an empty text block).
# Covers all 4 content shapes: str, list[text], list[tool_result+str], list[tool_result+list].
# Returns (new_content, removed_chunks) — removed_chunks: original marker text per match.
def _strip_interrupt_marker(content):
    removed = []
    if isinstance(content, str):
        if _is_interrupt_marker(content):
            removed.append(content)
            return '.', removed
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
                if _is_interrupt_marker(text):
                    removed.append(text)
                    result.append({**block, 'text': '.'})
                else:
                    result.append(block)
            elif btype == 'tool_result':
                inner = block.get('content', '')
                if isinstance(inner, str):
                    if _is_interrupt_marker(inner):
                        removed.append(inner)
                        result.append({**block, 'content': '.'})
                    else:
                        result.append(block)
                elif isinstance(inner, list):
                    new_sub = []
                    sub_changed = False
                    for sub in inner:
                        if isinstance(sub, dict) and sub.get('type') == 'text':
                            text = sub.get('text', '')
                            if _is_interrupt_marker(text):
                                removed.append(text)
                                new_sub.append({**sub, 'text': '.'})
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
