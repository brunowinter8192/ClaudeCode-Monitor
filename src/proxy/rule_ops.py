# INFRASTRUCTURE
import json

# FUNCTIONS

# Minimal (offset, removed, injected) op from (before, after) text pair via common-prefix/suffix
# — UNLESS full_replace=True, in which case the pair is recorded as ONE contiguous op spanning
# the entire before/after text, with NO prefix/suffix trimming. full_replace is an explicit
# signal from the CALLER, never inferred here: this function only ever sees two strings, and a
# ratio/size heuristic cannot discriminate "whole-content replacement that happens to share a
# leading/trailing substring with the original" from "a genuine small edit inside much larger
# surrounding text" (measured: their size-ratio ranges overlap — see
# process-docs/proxy_instrumentation/2026-07-29_full_replacement_blast_radius_measurement.md).
# The caller is the one place that actually knows which case it is — whether it constructs new
# content independently of the old (full_replace=True) or excises a chunk from within text it
# otherwise preserves (full_replace=False, the default, unchanged from before this parameter
# existed).
def _extract_block_op(before: str, after: str, full_replace: bool = False) -> list:
    if before == after:
        return []
    if full_replace:
        return [(0, before, after)]
    p = 0
    while p < len(before) and p < len(after) and before[p] == after[p]:
        p += 1
    s = 0
    max_s = min(len(before) - p, len(after) - p)
    while s < max_s and before[-(s + 1)] == after[-(s + 1)]:
        s += 1
    removed  = before[p: (len(before) - s) if s else len(before)]
    injected = after[p:  (len(after)  - s) if s else len(after)]
    return [(p, removed, injected)]


# Extract plain text from a single content block for op recording
def _block_inner_text(block) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        if "text" in block:
            return str(block["text"])
        if block.get("type") == "tool_result":
            c = block.get("content", "")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and "text" in b)
        return json.dumps(block, ensure_ascii=False)
    return json.dumps(block, ensure_ascii=False)


# Per-block ops {blk_idx: [(offset, removed, injected)]} from a content change — used by op-recording passes.
# full_replace threads straight through to _extract_block_op for every block/string pair — see
# that function's docstring for why this can only be a caller-supplied signal, never inferred.
#
# Three shape transitions, not two. The MIXED list->str case (2026-08-30) is what a pass produces
# when it collapses block content to a bare string — `_apply_role_system_strip` setting content to
# "." is the live instance, and it fires whenever CC hangs the cache-control breakpoint on the
# message, which makes a plain-string message arrive list-shaped. Without this branch the pass
# still rewrote the payload correctly but recorded NO op, so `_process_messages_section`'s
# `if s_texts:` wrote no stripped span and the strip surfaced only one request later, attributed to
# whichever request re-sent the message as a string (measured before the fix: 0 of 510 trailing
# total_tokens strips recorded against the request that performed them).
# The new string is the "after" text of block 0 — matching `_process_messages_section`, which
# recomputes each block's before-text from the ORIGINAL content and reads only block 0 in this case
# (`_diff_messages` emits a single block diff for a mixed shape). Further blocks are recorded as
# removed for completeness; nothing consumes them today, and no multi-block list->str collapse
# occurs in any recorded session.
def _ops_from_content_change(old_content, new_content, full_replace: bool = False) -> dict:
    ops: dict = {}
    if isinstance(old_content, list) and isinstance(new_content, list):
        for bi in range(max(len(old_content), len(new_content))):
            bt = _block_inner_text(old_content[bi]) if bi < len(old_content) else ""
            at = _block_inner_text(new_content[bi]) if bi < len(new_content) else ""
            for op in _extract_block_op(bt, at, full_replace):
                ops.setdefault(bi, []).append(op)
    elif isinstance(old_content, list) and isinstance(new_content, str):
        for bi in range(len(old_content)):
            bt = _block_inner_text(old_content[bi])
            at = new_content if bi == 0 else ""
            for op in _extract_block_op(bt, at, full_replace):
                ops.setdefault(bi, []).append(op)
    elif isinstance(old_content, str) and isinstance(new_content, str):
        for op in _extract_block_op(old_content, new_content, full_replace):
            ops.setdefault(0, []).append(op)
    return ops


# Merge per-block ops from one pass into the accumulated ops dict
def _merge_ops(dst: dict, src: dict) -> None:
    for msg_idx, blk_map in src.items():
        for blk_idx, op_list in blk_map.items():
            dst.setdefault(msg_idx, {}).setdefault(blk_idx, []).extend(op_list)
