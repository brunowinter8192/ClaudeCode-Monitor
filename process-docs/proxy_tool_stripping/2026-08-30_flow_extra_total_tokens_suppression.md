# The total_tokens Nuke Stops Prepending an Out-of-Window Message, 2026-08-30

Continues this area's total_tokens line. The 2026-08-29 work took that class out of the REQ-header
badge and deliberately left the expanded view alone, accepting a one-class divergence between
header and body. This entry closes half of that divergence from the other side: the class no longer
prepends an out-of-window message either. Related areas: `process-docs/proxy_instrumentation/`
holds the out-of-window prepend mechanism this modifies and the per-flow span-scoping it rests on.

## Symptom

`render_messages()` prepends `_render_flow_extra_messages()` output to every expanded request whose
own flow touched a message index below the rendered delta window. The mechanism exists for CC's
mid-conversation system messages, where the strip lands at an index the forwarded reconstruction
sees no delta for.

The per-request total_tokens nuke satisfies that condition on nearly every request, and it does so
at index `covered_from - 1` — the PREVIOUS request's trailing system message. So an expanded view
typically opened like this, with the real delta only starting on line 5:

```
[  4] syst  system
  [0] text              1c [CC]
    .
    <total_tokens>14979500 tokens left</total_tokens>
[  5] assi  3 blocks                 274c      <- the actual delta starts here
```

The view therefore showed a `syst` message twice per request and stopped mirroring the payload's
own delta shape (assistant, user, system — system exactly once, at the end).

## Measurement before the fix

Driving the real `_parse_forwarded_log` → `accumulate_dual_log` → `render_messages` path over two
recorded sessions, with each prepended index classified against the raw dual-log delta lines:

| session | entries rendered | entries prepending | prepends ALL pure total_tokens |
|---|---|---|---|
| `api_requests_opus_monitor_cc_1788091735` | 60 | 52 | 43 |
| `api_requests_opus_gh_cli_1787995963` | 487 | 449 | 382 |

Across both, 428 prepended indices were pure nukes against 76 real out-of-window strips. Every
single prepended index fell into one of exactly two shapes: stripped side a lone total_tokens
marker with a `"."` injected (the nuke), or stripped side real content with a `"."` injected (nag /
deferred-tools / mid-conversation). **Zero** indices had a substantial injected side without a
substantial stripped side, and zero had no stripped side at all.

## Root cause

The badge path filters, the prepend path does not. `accumulate_dual_log` records
`_msg_idx_by_flow_id[fid] = set(msgs_delta.keys())` — the RAW delta keys, no substantiality filter —
and `_render_flow_extra_messages` prepends every one of them below `covered_from`. The
`_msgs_delta_is_substantial` filter that took this class off the badge produced only an aggregate
per-LINE bool, so the per-INDEX verdict it computed internally was discarded.

## Design

The per-index verdict was extracted rather than re-derived:

- `parser._msg_delta_entry_is_substantial(blks, is_injected)` is the loop body of
  `_msgs_delta_is_substantial`, lifted into its own function. `_msgs_delta_is_substantial` becomes
  an `any()` over it, so the badge cannot move.
- `accumulate_dual_log` records `_msg_idx_sub_by_flow_id[fid]` — the substantial subset of the same
  indices — alongside the untouched raw set, cleared on `is_first` with everything else.
- The panes attach it as `_strip_msgs_sub_lookup` / `_inject_msgs_sub_lookup`, mirroring the four
  existing per-flow attachments.
- `_render_flow_extra_messages` reads the sub-lookups through `_own_msgs`, which falls back to the
  raw lookups when an entry does not carry them — the same feature-detection convention
  `_lookup_spans` already uses, so synthetic fixtures keep the old behavior.

Three properties this shape buys, each a deliberate choice:

**The raw set stays untouched, so in-window rendering is unaffected.** `_lookup_spans` still reads
it, which means wherever the delta window already covers the nuke it keeps rendering its olive
marker and green `"."`. The delta window is the payload's own structure; filtering it by badge
reasoning would hide real content. Only the PREPEND — a display convenience the renderer invents —
is filtered.

**Union-of-both-sides is kept.** Suppression is not "drop indices whose stripped text is the
marker" but "keep indices either side calls substantial", so a real out-of-window content injection
still prepends even when nothing was stripped there. The measurement found no such index today; the
rule costs nothing and does not depend on that staying true.

**The regex stays in the parser.** The render layer asks a question, it does not know what a
total_tokens marker looks like.

### Rejected: reading the accumulator internals from the renderer

`entry['_stripped_spans']` IS the family accumulator dict, so `render_messages` could have read
`entry['_stripped_spans']['_msg_idx_sub_by_flow_id']` with no pane changes at all. Rejected: it
introduces a second access path for data whose four siblings all reach the renderer as explicit
per-entry attachments, and it points the render layer at accumulator internals.

### Rejected: classifying from the cumulative span dicts

`_stripped_spans['messages'][idx]` already holds the stripped texts, so the renderer could have
matched the marker there without any new state. Rejected as unsound: that dict is cumulative and
last-writer-wins per coordinate, so for an index several flows touched it does not describe THIS
flow's touch. It would likely have worked on today's data and broken silently on data where it
matters.

## Verification (as of 2026-08-30)

**Double-render comparison on real sessions.** `dev/proxy_instrumentation/p6_flow_extra_suppress_probe.py`
renders every entry of a recorded session twice in one process — once as the panes assemble it,
once with the sub-lookups removed, which drops the renderer onto its pre-suppression fallback — so
the two runs differ in the suppression and nothing else. Five invariants pass on both sessions
(counts reported, never asserted, so log growth cannot break it): an entry with suppressed indices
drops exactly those blocks with the rest of its body byte-verbatim; an entry prepending only
substantial indices is byte-identical; an entry that never prepended is byte-identical;
`badge_flags` is identical for all 547 entries across both sessions; and the suppressed/kept split
matches `_msg_delta_entry_is_substantial` read straight off the raw delta lines.

The first invariant initially failed on 3 of 547 entries. All three were MIXED requests — one nuke
plus one real out-of-window strip — where the body legitimately differs by the dropped nuke block.
The check had demanded byte-identity for any entry with a kept index; it now demands that the
dropped prefix carry precisely the suppressed indices' `[N]` headers and that the tail survive
verbatim, which is the property actually wanted and which those three satisfy.

**Badge equivalence of the refactor, directly.** The pre-refactor inline body was re-implemented in
a throwaway harness and run against every `messages_delta` in all recorded dual-logs — 3184
payloads plus 12 adversarial shapes (non-dict values, empty blocks, whitespace-padded markers,
multi-text messages, `"."`-plus-real injections) — with zero divergence from the refactored
function.

**Regression.** `dev/proxy/test_strip_fix.py` 207/207, `dev/proxy_dual_log/test_composition_invariant.py`
12/12, `dev/display/test_hover_map.py` 45/45, `dev/proxy_dual_log/tt_delta_skip_replay.py --compare`
PASS on a current session. `dev/proxy_dual_log/A_render_refactor_proof.py`: a baseline captured on
the pre-change tree verifies 14/14 byte-identical against the post-change tree, which is the direct
proof that the fixture fallback path did not move. That script's stored `baseline_20260818.json`
fails 2 of 14 cases, but it fails them identically on the unmodified tree — pre-existing drift,
confirmed by stashing the change and re-running, and left alone.

**Not verified:** the live TUI. Everything above is the real render path driven over recorded logs;
no running proxy pane was observed, and neither pane's event loop was exercised.

## Relevant Symbols / Paths

- `_msg_delta_entry_is_substantial()`, `_msgs_delta_is_substantial()`, `accumulate_dual_log()`
  (`src/proxy_display/parser.py`) — the per-index verdict and the new `_msg_idx_sub_by_flow_id`
- `_own_msgs()`, `_render_flow_extra_messages()` (`src/proxy_display/render_messages.py`) — the prepend gate
- `_lookup_spans()` (`src/proxy_display/render_messages.py`) — in-window path, deliberately still on the raw set
- `pane.py` / `worker_proxy_pane.py` — the `_strip_msgs_sub_lookup` / `_inject_msgs_sub_lookup` attachments
- `dev/proxy_instrumentation/p6_flow_extra_suppress_probe.py` — the double-render probe
- Ground-truth logs: `src/logs/dual_log/api_requests_opus_monitor_cc_1788091735_*.jsonl`,
  `src/logs/dual_log/api_requests_opus_gh_cli_1787995963_*.jsonl`
