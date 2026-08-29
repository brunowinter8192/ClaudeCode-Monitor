# total_tokens Nuke Removed from the Badge Signal, 2026-08-29

Continues this area's badge line, which established that a strip/inject is badged ONLY when
something substantial happens, and catalogued the earlier phantom classes (field overrides,
`"."` placeholders, spurious newlines). This entry adds a new phantom class and, unlike the
earlier ones, fixes it on the READ side.

Related areas: `process-docs/proxy_instrumentation/` holds the badge's signal source (the move
off `fn_map` onto delta presence, and the per-flow span-scoping work);
`process-docs/message_strip_fp_nuke/` holds the anchored-match convention this detection follows.

## Symptom

Newer CC appends a fresh `role='system'` message `<total_tokens>N tokens left</total_tokens>` to
the END of the message history on EVERY request. `_apply_role_system_strip` nukes it to `"."`,
which is correct. The REQ-header badge nevertheless lit up on virtually every request, so the rare
real strip drowned in per-request noise.

## Root cause — why hash-dedup structurally cannot help

`_build_stripped_injected_deltas` suppresses a repeated change via a flat `loc_key → MD5[:10]`
hash chain, where a message's `loc_key` is `msg.<msg_idx>.<blk_idx>`. Historical total_tokens
messages keep their index, so their hash is stable and they ARE suppressed. The new one arrives at
a NEW index every request, so it gets a `loc_key` never seen before, and a `loc_key` with no
previous hash can never match one. The dedup is not merely ineffective here, it is structurally
incapable of firing.

Measured on `src/logs/dual_log/api_requests_opus_monitor_cc_1788011077`, replayed through the real
pass pipeline. That log was being appended to by the very session doing this work, so every absolute
count below belongs to ONE run of 88 requests on 2026-08-29; re-running the harness on the same stem
later yields larger counts, and the proportions rather than the totals are the point.

In that run 77 requests carried a non-empty `messages_delta`, of which 53 were PURE total_tokens
nukes, 10 mixed a total_tokens nuke with a real strip, and 14 were real strips alone. Under the old
rule 78 of 88 requests badged on each side — the extra one over the 77 is a request that badged via
a system-section change with no message delta at all. So roughly two thirds of all badge-lighting
requests carried nothing a reader wanted.

## Design — write-side skip was built first, then rejected

The first implementation skipped the class in `_process_messages_section`, so no delta entry was
written at all. It worked on the badge (measured at the time: entries with `messages_delta` fell
41 → 11, all pure-total_tokens requests went silent, all real-strip entries stayed byte-identical),
but it over-fulfilled: dropping the delta entry also dropped the expanded view's olive stripped
span and green `"."` at that message, because the overlay dicts are populated from the same
`messages_delta`. The requirement is that the spans keep rendering and only the header goes quiet.

So the suppression moved read-side, into `accumulate_dual_log`'s `has_content` computation ONLY.
The delta writer is untouched and its output is byte-identical to before, which is what keeps the
rendering intact.

```python
# src/proxy_display/parser.py — badge-only, nothing else in the accumulator sees this
def _msgs_delta_is_substantial(msgs_delta: dict, entry_type: str) -> bool: ...
```

Two classes stop counting toward the raw per-line signal:

- **stripped side:** a message whose blocks' stripped texts amount to exactly ONE text
  full-matching `^<total_tokens>\d+ tokens left</total_tokens>$`.
- **injected side:** a block whose injected spans are only `"."`.

The overlay section dicts and `_msg_idx_by_flow_id` are populated from the raw delta exactly as
before, so span rendering and per-flow scoping are unchanged.

### The injected-side rule alone was too broad — flow coordination fixes it

Suppressing every `"."`-only injection silences more than the target class. A task-tools-nag nuke
also injects the literal `"."`, and that `"."` DOES render as a green span, so its header must keep
saying `strip inject`. Observed live on a nag at message index 190, whose header showed `strip`
alone.

An `injected_delta` line cannot tell the two apart: both carry exactly `"."`, and the
distinguishing marker text exists only on the stripped side. The sides are therefore coordinated by
`flow_id` at the badge CONSUMER, in `parser.badge_flags`, which the REQ header calls:

```python
show_inject = real (non-".") injection  OR  ("."-filler present AND the strip side is substantial)
```

`"."`-filler present is read as a non-empty `_inject_msgs_lookup` entry for the flow: the writer
only records a block that has an injected span, so once the real-injection case is excluded, a
touched message block means a `"."`. For a pure total_tokens flow the strip side is non-substantial,
so both words stay off; for the nag the strip side is substantial, so both come on; for a request
mixing total_tokens with a real strip both come on.

This is computed per render rather than stored at accumulation time on purpose. The two dual-log
files are tailed independently, so when one side's line is accumulated the peer line may not have
been read yet; a value frozen at that moment could be wrong and would never correct itself, since
each line is processed once. Deriving it at render is order-independent and retroactive for the
running session.

### Consequences worth knowing before touching this

**Header and expanded view diverge for exactly one class.** The badge's move onto delta presence
was originally motivated by closing that disagreement — a `"."`-filler injection rendered a green
span while the header showed no `inject`. That principle still holds everywhere except the
total_tokens nuke, which renders its spans while showing neither badge word. The narrow exception
is the point: the class occurs on nearly every request, so honoring one-to-one there would cost the
badge all of its meaning. Anyone reading the older rationale should know it was narrowed here, not
discarded.

**Exactly one class is silent, and every other nuke keeps the one-to-one behavior.** The
task-tools nag, deferred-tools, date-changed and mid-conversation nukes all still render
`strip inject`, because their `"."` renders green. A genuine content injection (bg-exit wake-up,
TN wake-up, system rules) badges `inject` regardless of the strip side.

**The read side has no role field.** The dual-log line carries `messages_delta` but not the
message's role, so the write side's second anchor (`role == 'system'`) is unavailable here. The
anti-FP property rests entirely on the text shape: exactly ONE stripped text, full-matching the
anchored pattern. This holds because no strip pass removes a bare, otherwise-empty total_tokens
marker from a non-system message — a quoted marker always sits inside surrounding content, which
yields either more than one text or a non-matching one. In the measured session the string appears
175 times as quoted content (82 in `tool_result`, 79 in `role='assistant'` text, 14 in
`role='user'` text) against 575 genuine `role='system'` nukes, and none of the quotes produce the
bare-marker shape.

**The stripped rule is per-message, the injected rule per-block.** Seven requests in the measured
session mixed a total_tokens nuke with a genuine strip; a per-request rule would have silenced
those too.

## Verification (as of 2026-08-29)

**Replay over the real pipeline.** `dev/proxy_dual_log/tt_delta_skip_replay.py --compare` drives
each recorded original payload through `apply_modification_rules` (the production source of
`all_ops`), then the real `_build_stripped_injected_deltas`, then the real `accumulate_dual_log`.
The old one-to-one rule is reproduced in the same process by patching `_msgs_delta_is_substantial`
to `bool(messages_delta)`, so both readings differ in nothing else; the new reading goes through the
real `badge_flags`. On the same 88-request run of the 1788011077 session: the write side kept all 77
stripped and 76 injected entries with `messages_delta`; the rendered badge fell from 78 to 25 for
`strip` and from 78 to 25 for `inject`; all 53 pure-total_tokens requests show NEITHER word while all
53 still carry their stripped spans; all 14 real-strip requests show `strip`, and all 13 of them that
have a green message span show `inject`; all 10 mixed requests show both.

The harness asserts these as invariants rather than as fixed counts — every pure-total_tokens
request silent on both words and still carrying its spans, every real-strip and mixed request loud,
every green message span forcing `inject` — so it keeps passing on the grown log as more requests
accumulate.

One request initially tripped the replay's inject criterion and turned out to be a criterion bug,
not a code bug: it injects the proxy's own rules into `system[2]` and touches no message block at
all, so it legitimately shows `inject` with an empty injected `messages_delta`. The check was an
equality between "shows inject" and "has injected messages"; it is now the implication that only a
green message span must force `inject`, which is the property actually wanted.

**Synthetic guards.** `dev/proxy/test_strip_fix.py` went from 159 to 207 passing checks, the 48 new
ones in TT01-TT09: the writer still emits full entries with spans and keeps its `'RS'` attribution;
both badge words are off for the class while the overlay dicts and `_msg_idx_by_flow_id` still carry
it; nag, deferred-tools, date-changed and mid-conversation nukes show BOTH words; a real bg-exit
injection shows both; the marker quoted with surrounding content in a `tool_result` or inline still
shows both; prefixed, suffixed, digit-less and reworded near-misses still show both while a
whitespace-padded exact marker shows neither; a mixed request shows both and keeps both message
indices in scope; system-only and tools-only deltas still badge and a fields-only delta still does
not. TT09 drives the REAL `_build_req_header_line` and asserts the rendered words themselves —
`strip inject` for the nag, nothing for total_tokens, `strip inject` for a real injection.
`dev/proxy_dual_log/test_composition_invariant.py` stayed at 12/12.

**Three named verification consumers could not contribute, all for reasons predating this work.**
`dev/proxy_dual_log/verify_strip_inject.py` raises `KeyError: 'spans'` on any log pair with a
changed message block, because `_diff_messages` stopped emitting a `spans` key when the ops /
`compose_block` architecture replaced it, while the script still reads it in its span-reconstruction
check; independently it calls the delta builder WITHOUT `all_ops`, so its message section produces
no spans at all. `dev/proxy_instrumentation/p2_badge_words_probe.py` and `p3_badge_inline_probe.py`
reference recorded sessions (1785364138, 1785347492, 1786052022) that no longer exist on disk and
abort while loading. All three were confirmed failing on an unmodified tree and left untouched; the
replay above was written to replace their coverage for this change. On the fixture expectations: p3's three span cases name their content in the probe source
(deferred-tools notice, task-tools nag, SN/bg notification), and all three still render
`strip inject` under the final rule, so its expectations stay valid. p2's `msg84_dot_filler_injection`
case expects `strip inject` too, but what msg 84 actually contained cannot be checked any more since
that log is gone — if it was a total_tokens nuke the expectation would now be wrong, and if it was
any other role=system nuke it is still right. Reviving either probe needs the recorded logs back
first.

**Not verified:** a live proxy restart against a real CC session, and the pane as a whole. The
badge words themselves ARE verified through the real `_build_req_header_line` (TT09), but the span
rendering was verified through the accumulator's overlay dicts rather than by inspecting rendered
expanded-view output.

## Relevant Symbols / Paths

- `_msgs_delta_is_substantial()`, `_TOTAL_TOKENS_NUKE_RE`, `accumulate_dual_log()`
  (`src/proxy_display/parser.py`) — the per-line badge filter
- `badge_flags()` (`src/proxy_display/parser.py`) — the flow coordination that decides the two words
- `_process_messages_section()` (`src/proxy/strip_inject_delta.py`) — the writer, deliberately unchanged
- `_apply_role_system_strip()` (`src/proxy/message_passes.py`) — the nuke itself, deliberately unchanged
- `_build_req_header_line()` (`src/proxy_display/render_turn.py`) — badge consumer, now delegating
  the two booleans to `badge_flags`
- `dev/proxy_dual_log/tt_delta_skip_replay.py` — replay harness
- Ground-truth log: `src/logs/dual_log/api_requests_opus_monitor_cc_1788011077_*.jsonl`
