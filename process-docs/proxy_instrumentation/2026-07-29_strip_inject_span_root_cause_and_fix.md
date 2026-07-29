# 2026-07-29 — Strip/inject span rendering: root cause, fix, and a corrected line reference

## Root cause: content SHAPE, not span lookup or per-request association

Both previously-recorded candidate hypotheses were wrong.

**Not a span lookup key mismatch.** The accumulator built by `accumulate_dual_log`
(`proxy_display/parser.py`) is cumulative and attached to every entry BY REFERENCE — every
proxy entry of a given model family shares the same `_stripped_spans`/`_injected_spans` dict
object, which keeps growing as more dual-log lines are read. The coordinate `msg.276.0` is
present and reachable in that dict at render time regardless of which specific request is being
rendered; a direct lookup at `entry['_injected_spans']['messages']['276']['0']` returns the
recorded span correctly when actually attempted.

**Not a per-request association error.** Confirmed by inspecting the raw dual-log lines directly:
`..._stripped.jsonl` and `..._injected.jsonl` line 132 both carry `request_id
b6e4f411-74b2-4b56-8940-bf5ce51e7380` and the same `flow_id`. The rendering path doesn't even
correlate by `request_id` at runtime (the `_forwarded` dual-log's own `request_id` field is
always blank — correlation happens purely by cumulative accumulator content, keyed by
message/block index, never by request identity), so a request-association bug was never a live
possibility here.

**The actual discriminator is message content SHAPE.** `render_messages.py` only consults
`_stripped_spans`/`_injected_spans` inside `_render_block_spans`, reached exclusively when
`msg.get('blocks')` is non-empty (`message_summary._summarize_message` only populates `blocks`
when `content` is a `list`). Message 276's forwarded content at this point is a plain `str` —
`blocks` is empty — so the render loop took the block-less branch (`content_preview` in the
new-message path, `content_tail` in the modified-message path), which printed the text in flat
`DIM` and never looked at the span accumulator at all. Message 274 rendered correctly only
because its forwarded content was still a block-list (`[{"type": "text", "text": ".", ...}]`) at
that point in the session.

**The precondition, not a defect:** the bg-exit / task-notification replacement pass collapses a
single-block `list` content into a plain `str` replacement (`_apply_first_pass` sets
`new_msg["content"]` to a plain string via `_replace_task_notification_tags`). That collapse is
intentional proxy behavior, unrelated to this rendering bug — it is simply the condition under
which the block-less branch fires and the missing span lookup became visible.

## Fix

Extracted the span-emitting logic (new-format inline tuples vs. legacy stacked yellow/green) out
of `_render_block_spans` into a shared `_render_span_content(full_text, i_blk, s_blk, indent,
highlight_suspect=True)` + `_lookup_spans(entry, msg_idx, bidx, use_dual)`. Both block-less
branches (`_render_new_messages`, `_render_modified_messages`) now call these at block index
`"0"` — confirmed against the recorded payload that block-less messages are always logged at
coordinate `"0"`, not assumed. `highlight_suspect=False` is passed from the block-less callers
specifically so the fix does not retroactively add suspect-tag highlighting to plain content that
never had it before — the bug was missing span color, not missing tag highlighting, and scope
was kept to exactly that.

## Line-number correction

The prior observation recorded the reproduction at dual-log line 133. The data is actually at
line 132 (0-based) — resolved by matching `request_id b6e4f411-74b2-4b56-8940-bf5ce51e7380`
directly in `..._stripped.jsonl`, not by trusting the previously-noted line number. Also: message
274 does not render inside request b6e4f411's own diff — `render_messages` only renders
`msg_idx` in `[prev_msg_count, message_count)` for that request, which is `[275, 278)`; message
274 was introduced one request earlier (dual-log line 131, range `[272, 275)`) and is unchanged
(hence correctly omitted) by line 132's own render. The true "known-good, block-path" control is
the line-131 request's own render, not line 132's.

## Secondary finding: `fn_map` attribution imprecision (not fixed — reported only)

`fn_map` attributes `msg.276.0` to `_apply_bg_exit_strip`, but `strip_bg_completed.py:_BG_EXIT_RE`
matches only a bare `Background command "..." (failed with exit code 143|137 / completed (exit
code 143|137))` line and explicitly excludes exit code 0. Message 276's removed original is a
`<task-notification>` block with `<summary>...completed (exit code 0)</summary>`, preceded by a
`[SYSTEM NOTIFICATION - NOT USER INPUT]` paragraph — a different shape than `_BG_EXIT_RE` matches,
and exit code 0 is excluded by the regex regardless. The actual acting function is
`_apply_first_pass`'s task-notification branch in `message_passes.py` (records mod_name
`replaced_task_notification` / `trimmed_task_notification`).

The mislabel traces to a post-hoc heuristic in `strip_inject_delta.py:176-178`:
```python
elif "background done" in i_text:
    i_fn[lk] = "_apply_bg_exit_strip"
```
This keys on the shared `_WAKEUP_TEXT` sentence (`'background done — check worker or other
process\n'`, defined in `strip_bg_completed.py`, imported and reused by `message_passes.py`
specifically so both the BGK-kill path and the TN-tag path emit the same wake-up text) rather
than tracing which pass actually ran. Any injected span containing that shared sentence gets
attributed to `_apply_bg_exit_strip` regardless of origin. This is a standing imprecision in
`fn_map` attribution — it was not changed; only reported with evidence from the recorded payload.

## Verification status

Verified at integration level: the real render path (`_parse_forwarded_log` →
`_lazy_load_messages_forwarded` → `accumulate_dual_log` → `render_messages`) run against the
recorded dual-log for this exact session, through a harness reconstructing the pane render
without a live proxy. Asserted on presence of the ANSI background escape codes
(`\x1b[48;2;38;74;46m` green, `\x1b[48;2;94;81;47m` yellow) around the expected text, not on a
screenshot. Byte-identical output confirmed for the two previously-correct control messages
(15/15 lines each) between the pre-fix and post-fix render implementations. NOT verified visually
in a live terminal — that gate is still open and belongs to the user.
