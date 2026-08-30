# The Writer Records a List-Shaped Strip Against Its Own Request, 2026-08-30

Closes the loop on this area's attribution-lag entry, which diagnosed the defect and fixed it
READ-side because the write path was out of scope then. This entry is the durable write-side repair:
`_ops_from_content_change` now produces ops for list-shaped content, so the request that performs a
trailing-message strip writes the span on its own delta line. Old logs are unaffected and keep the
lag forever, which is why the read-side correction stays.

## The gap was one missing shape transition

`_ops_from_content_change` dispatched over exactly two cases, `list`+`list` and `str`+`str`.
`_apply_role_system_strip` sets `content` to the literal string `"."` while the original content is
a list, so neither branch matched and it returned `{}`.

Measured by replaying real payloads through the actual pass pipeline, counting content-shape
transitions among messages the proxy changed:

| transition | occurrences | of which NO ops recorded |
|---|---|---|
| `str -> str` | 253 | 0 |
| `list -> list` | 45 | 0 |
| **`list -> str`** | **23** | **23** |
| `str -> list` | 0 | — |

So the mixed shape was the only broken transition, and every one of the 36 instances across two
sessions is the same thing: a single-block, `role='system'` message collapsed to `"."`. The trigger
is CC hanging the cache-control breakpoint on the LAST message, which makes an otherwise-plain
system message arrive list-shaped — which is why it was always the *trailing* message that lost its
span.

## Why the fix belongs in the op helper

The consuming end decides the shape of the fix. `_process_messages_section` does not use the diff's
`o_text`; it recomputes each block's before-text from the ORIGINAL content
(`_get_inner_text(o_content_raw[bidx])`). So the op has to be keyed at block 0 with
`(0, <inner text of original block 0>, ".")` — byte-for-byte the tuple the string path already
produces once CC re-sends the message as a string. That identity is what makes the fix
self-neutralising rather than double-counting: the line the fixed writer emits is the same line the
NEXT request used to emit, so the existing `loc_key`+hash dedup suppresses the repeat.

A consumption limit worth knowing: `diff_engine._diff_messages` emits a SINGLE block diff for a
mixed shape, so only block 0's ops are ever read. Ops for further blocks are recorded for
completeness and currently go nowhere. No multi-block `list -> str` collapse occurs in any recorded
session, so widening the diff engine was not part of this work.

## Verification (as of 2026-08-30)

**Replay, not unit tests.** 60 recorded requests per session driven through the real
`apply_modification_rules` → `_build_stripped_injected_deltas` chain, before and after:

| | monitor_cc | gh_cli |
|---|---|---|
| forwarded payload identical | 60/60 | 60/60 |
| requests recording their OWN trailing total_tokens strip | 0 → 45 | 0 → 49 |
| requests recording the PREVIOUS request's trailing strip (the lag) | 44 → 0 | 48 → 0 |

The forwarded identity is the load-bearing one: this is a logging-attribution change and the wire
must not move.

**Interplay with the read-side correction, end to end.** The replayed delta lines were written to a
synthetic fixed-writer stream and run through the REAL `accumulate_dual_log`: the read-side lag rule
finds **0** corrections to make (nothing left to correct), **0** coordinates are claimed by more
than one flow, and the performing flow claims its own trailing index. Rendering that stream through
`render_messages`, msg 179 shows olive+green in **exactly one** entry — flow `81039f6e`, REQ #62,
the request that performed the strip. Running the same accumulator over the RECORDED (old-format)
stream still yields its 158 lag corrections, so historical logs keep rendering correctly.

An intermediate check of mine reported 5 other entries rendering a span at 179, which was a bug in
the check rather than in the code: it tested whether a body contained both `[179]` and a
total_tokens string anywhere, and every request carries its own total_tokens message. Re-tested per
msg-179 segment, the count is 1.

**Suites.** `dev/proxy/test_strip_fix.py` 207/207, `dev/proxy_dual_log/test_composition_invariant.py`
12/12, `tt_delta_skip_replay --compare` PASS, `A_render_refactor_proof` 14/14 byte-identical, p6
probe all checks. `dev/proxy_dual_log/verify_strip_inject.py` raises `KeyError: 'spans'` — verified
byte-identical output before and after the change, so it is the pre-existing breakage recorded in
this area on 2026-08-29 and not a regression.

**NOT verified, and important:** the live proxy. The running mitmproxy addon holds the old code in
memory, so it keeps writing lagged lines until someone restarts it. No restart was performed as part
of this work. Until then, new log lines behave like old ones and the read-side correction covers
them — which it does correctly either way.

## What this does NOT change

Old recorded logs keep the lag permanently: the fix only affects lines written from now on. The
read-side correction in `src/proxy_display/parser.py` therefore stays exactly as it is, and its
self-neutralising design means it will simply stop finding anything to correct as new logs
accumulate, without any further change.

## Relevant Symbols / Paths

- `_ops_from_content_change()` (`src/proxy/rule_ops.py`) — the fix, one added branch
- `_apply_role_system_strip()` (`src/proxy/message_passes.py`) — the pass that hits it, unchanged
- `_process_messages_section()` (`src/proxy/strip_inject_delta.py`) — `if s_texts:`, the consumer
- `_diff_messages()` (`src/proxy/diff_engine.py`) — single block diff for mixed shapes
- `accumulate_dual_log()`, `_lag_msg_idx_by_flow_id` (`src/proxy_display/parser.py`) — read-side, untouched
- Ground truth: `src/logs/dual_log/api_requests_opus_monitor_cc_1788091735_*.jsonl`, flow `81039f6e`
