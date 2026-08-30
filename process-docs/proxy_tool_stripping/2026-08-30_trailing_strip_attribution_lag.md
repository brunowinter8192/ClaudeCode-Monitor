# The Trailing-Message Strip Is Attributed One Request Too Late, 2026-08-30

Continues this area's total_tokens line. The two same-day entries before this one changed WHERE
the expanded view draws spans (badge suppression, then removing the out-of-window prepend). This
entry is about a defect that predates both: the span for a request's own trailing system message
was never recorded against that request at all, so the in-window rendering this area's docs
promised had in fact never worked.

## Symptom

REQ #62 of `api_requests_opus_monitor_cc_1788091735`, expanded, showed its trailing system message
as a bare dot:

```
[179] syst  system   1c
  [0] text  1c [CC]
    .
```

No olive stripped-original, no green filler — although `_original` carries
`<total_tokens>14990609 tokens left</total_tokens>` at msg 179 and the forwarded payload carries
`"."`, so the strip demonstrably happened in that request.

## Root cause — a shape-dependent gap in op registration

Each step measured, not inferred:

1. CC hangs the cache-control breakpoint on the LAST message, so a fresh trailing `role='system'`
   total_tokens message arrives **list-shaped**: `[{type:text, text:'<total_tokens>…',
   cache_control:{…}}]`. Confirmed in the `_original` line for that flow.
2. `_apply_role_system_strip` nukes it regardless of shape (`{**msg, "content": "."}`), which is
   why the forwarded payload is correct.
3. Its op registration is NOT shape-independent. Direct call:

   ```
   _ops_from_content_change(<string>, '.', full_replace=True) -> {0: [(0, '<total_tokens>…', '.')]}
   _ops_from_content_change(<list>,   '.', full_replace=True) -> {}
   ```

4. So `all_ops` has no entry for that index — replaying REQ #62 through the real pass pipeline:
   `179 in all_ops` is False while the replayed forward output still nukes 179 to `"."`.
5. `_process_messages_section` writes a stripped span only when the ops yield `s_texts`
   (`if s_texts:`), so that request's delta line omits the strip. REQ #62's `fn_map` is
   `['msg.176.0']` alone.
6. On the NEXT request CC re-sends the same message as a plain STRING (the breakpoint has moved to
   the new trailing message), the op is produced, and the strip is recorded — against the wrong
   request, which no longer renders that index.

At scale, over `opus_monitor_cc_1788091735` and `opus_gh_cli_1787995963`: **0 of 510 total_tokens
strips recorded against the request that performed them, 510 of 510 against the following request,
0 anywhere else.** The lag is total, not occasional.

Three of the four investigation candidates were checked and cleared: the block-index coordinate
matches (recorded block `'0'`, reconstructed single text block at bidx 0); cumulative
last-writer-wins is not the trigger; and the lazy-load path is not implicated, since the lookups
are references attached at parse time and only `messages` is rebuilt. The fourth was the answer —
the flow's own strip is not in `_strip_msgs_lookup` because it is not in the stream for that flow.

## Fix — read-side re-attribution, because the recorded logs are already wrong

The durable repair is write-side: make `_ops_from_content_change` produce ops for list content.
That is out of this milestone's scope, and on its own it would be insufficient anyway — it would
only help logs recorded AFTER the fix, while every existing log keeps the lag permanently. So the
correction lives on the read side, where it also serves historical logs.

`parser.accumulate_dual_log` now tracks the previous line's `(flow_id, counts.messages)` per family
(in `_last_line_meta`, inside the acc dict so it survives incremental calls) and maps a delta index
back onto the previous flow when three conditions hold together:

- the index is that flow's trailing message (`prev_count - 1`),
- the count did not regress (no restart), and
- the delta at that index is a **total_tokens nuke** (`_is_total_tokens_nuke`, reusing the existing
  marker regex).

The result is `_lag_msg_idx_by_flow_id`, attached by both panes as `_lag_msgs_lookup` and consulted
by `_lookup_spans` for both sides. One set governs both because the class is a stripped
total_tokens plus its injected `"."` at the same coordinate, and — the same reason `badge_flags`
coordinates at the consumer — an injected line cannot identify the class alone.

### Why the marker guard is load-bearing, not decoration

CC overwrites mid-conversation indices **in place**. The task-tools nag in this session lands on
msg 176 — which was an earlier request's trailing message. Without the marker check, that nag's
text would be attributed to a request that stripped total_tokens at that index, and the pane would
render the wrong original content under it. That is precisely the neighbour bleed the 2026-08-07
flow scoping exists to prevent. Verified after implementation: of 512 corrected coordinates, 0
carry non-marker text and 0 land on a nag coordinate.

### Self-neutralising

If the writer is later fixed, the request records its own strip and the following line's repeat is
suppressed by the existing `loc_key`+hash dedup, so the lag rule finds nothing to correct. No
double attribution, no cleanup needed.

## Verification (as of 2026-08-30)

**Target case, both render paths.** REQ #62's msg 179 now renders the green `"."` and the olive
`<total_tokens>14990609 tokens left</total_tokens>` — through the live-parse path AND through
`_lazy_load_messages_forwarded`, the path the live pane uses for entries outside the keep-last
window.

**Before/after over every entry of both sessions.** 512 bodies changed, each gaining exactly a
total_tokens olive line plus a green filler at a lag-corrected coordinate; 149 unchanged;
**0 changed in any other way**; **0 badge changes**. In-window span coverage rose from 37 to 150
entries on one session and 73 to 425 on the other.

**Soundness of the correction set.** 512 coordinates re-attributed, at most one per flow (a request
has exactly one trailing message), every one carrying the marker text, none on a nag coordinate.

**Regression.** `dev/proxy/test_strip_fix.py` 207/207, `dev/proxy_dual_log/test_composition_invariant.py`
12/12, `dev/display/test_hover_map.py` 45/45, `tt_delta_skip_replay --compare` PASS,
`A_render_refactor_proof` 14/14 byte-identical. The p6 probe passes all five checks per session,
the fifth being a new permanent guard for this defect (folded into the existing probe rather than
added as a new file).

**Not verified:** the live TUI. Everything above drives the real render path over recorded logs.

## Relevant Symbols / Paths

- `_ops_from_content_change()` (`src/proxy/rule_ops.py`) — returns `{}` for list content; the
  write-side defect, deliberately untouched here
- `_apply_role_system_strip()` (`src/proxy/message_passes.py`) — nukes correctly, registers no op
- `_process_messages_section()` (`src/proxy/strip_inject_delta.py`) — `if s_texts:` is where the
  span is dropped
- `_is_total_tokens_nuke()`, `accumulate_dual_log()` (`src/proxy_display/parser.py`) — the correction
- `_lookup_spans()` (`src/proxy_display/render_messages.py`) — consults `_lag_msgs_lookup`
- `dev/proxy_instrumentation/p6_no_flow_extra_prepend_probe.py` — check 5 guards this
- Ground truth: `src/logs/dual_log/api_requests_opus_monitor_cc_1788091735_*.jsonl`, flow
  `81039f6e` (REQ #62) and `123e4847` (REQ #63, which recorded #62's strip)
