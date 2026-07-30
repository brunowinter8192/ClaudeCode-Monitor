# 2026-07-30 — `full_replace` stays opt-in: the latent span-split was scoped, costed, and dropped

## What was on the table

`rule_ops.py::_extract_block_op` walks off the common prefix/suffix of `before`/`after`, so a
whole-content replacement sharing its leading word with the original is recorded as a partial span;
`render_messages.py::_render_span_content` then emits the shared fragment unhighlighted on its own
line with the replacement green below — a 2-line split instead of one contiguous green block.

The 2026-07-29 milestone already closed this for the sites that hit it, via a `full_replace: bool =
False` parameter the calling pass sets when it replaced content wholesale. As of 2026-07-30 three
sites pass it (`_apply_role_system_strip`, `_apply_bg_launch_ack_strip`, `_apply_first_pass`'s
rejection branch); a fourth (`_apply_interrupt_marker_strip`, added 2026-07-30) sets it too, copied
from the neighbouring passes' shape.

The open question this session weighed: make the guarantee **structural** rather than opt-in, so a
future pass that replaces content wholesale cannot silently omit the flag and reintroduce the split.

## Why it was dropped

Scoped against the alternatives and judged not worth a worker run:

- **No live defect.** Six live bg wake-ups measured 2026-07-30 (same area's live-verify entry)
  rendered as one contiguous green block. The reworked replacement texts share no leading word with
  their originals, so nothing is trimmed. The split does not reproduce today.
- **Cosmetic blast radius.** The failure mode is a mis-coloured render in the proxy pane. No data
  loss, no wrong forwarding behaviour, no wrong dual-log content — the op data itself is a faithful
  record of the change either way.
- **Latency of harm is unbounded but its cost is bounded.** The trigger is a future replacement text
  that happens to start with the original's first word. When that lands, the symptom is visible
  immediately in the pane and the fix is one keyword at one call site.

Weighed against two issues with user-facing payoff (a CotEditor drag-selection defect the user hits
daily, and a news-pane multi-platform extension), the structural-guarantee work lost on value per
worker run.

## Design constraint that survives this decision

If the structural version is ever picked up: inferring "whole-content replacement" from the two
strings alone is closed off, not merely unattractive. The 2026-07-29 blast-radius measurement found
FULL-class ops spanning a `len(removed)/len(before)` ratio of `[0.973, 1.000]` and PARTIAL-class ops
spanning `[0.015, 1.000]` — overlapping ranges, so no threshold separates the classes without
misclassifying real cases in both directions. Only the calling pass knows which case it is; any
structural approach has to make the caller state it, not guess it.
