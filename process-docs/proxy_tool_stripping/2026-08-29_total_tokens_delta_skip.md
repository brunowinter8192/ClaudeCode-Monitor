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

Measured on `src/logs/dual_log/api_requests_opus_monitor_cc_1788011077` (67 requests replayed
through the real pass pipeline, 2026-08-29): 60 requests carried a non-empty `messages_delta`, of
which 42 were PURE total_tokens nukes, 7 mixed a total_tokens nuke with a real strip, and 11 were
real strips alone. Under the old rule 61 of 67 requests badged on each side.

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

Two classes stop counting toward the badge:

- **stripped side:** a message whose blocks' stripped texts amount to exactly ONE text
  full-matching `^<total_tokens>\d+ tokens left</total_tokens>$`.
- **injected side:** a block whose injected spans are only `"."` — the API-required empty-block
  filler, not a real injection.

The overlay section dicts and `_msg_idx_by_flow_id` are populated from the raw delta exactly as
before, so span rendering and per-flow scoping are unchanged.

### Consequences worth knowing before touching this

**Header and expanded view are now deliberately not one-to-one.** The badge's move onto delta
presence was originally motivated by closing exactly that disagreement — a `"."`-filler injection
rendered a green span while the header showed no `inject`. This change re-opens that gap on
purpose, because the two surfaces answer different questions: the header answers "is there
anything here worth opening", the expanded view answers "what exactly changed". Anyone who reads
the older rationale should know it was superseded here, not forgotten.

**Every `"."`-nuke now badges `strip` alone, never `strip inject`.** That covers the task-tools
nag, deferred-tools, date-changed and mid-conversation notices, not just total_tokens. It is
intended: their strip is real signal, their `"."` is not an injection. A genuine content injection
(bg-exit wake-up, TN wake-up, system rules) still badges `inject`.

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
The old badge rule is reproduced in the same process by patching `_msgs_delta_is_substantial` to
`bool(messages_delta)`, so both readings differ in nothing else. On the 1788011077 session:
the write side kept all 60 stripped and 59 injected entries with `messages_delta`; the badge
signal fell from 61 to 19 on the stripped side and from 61 to 9 on the injected side; all 42
pure-total_tokens requests went badge-silent on both sides while all 42 still carry their stripped
spans; all 11 real-strip and all 7 mixed requests still badge `strip`.

**Synthetic guards.** `dev/proxy/test_strip_fix.py` went from 159 to 193 passing checks, the 34 new
ones in TT01-TT08: the writer still emits full entries with spans and keeps its `'RS'` attribution;
the badge is False on both sides for the class while the overlay dicts and `_msg_idx_by_flow_id`
still carry it; nag, deferred-tools, date-changed and mid-conversation nukes badge `strip` True and
`inject` False; a real bg-exit injection badges both; the marker quoted with surrounding content in
a `tool_result` or inline still badges; prefixed, suffixed, digit-less and reworded near-misses
still badge while a whitespace-padded exact marker does not; a mixed request still badges and keeps
both message indices in scope; system-only and tools-only deltas still badge and a fields-only
delta still does not. `dev/proxy_dual_log/test_composition_invariant.py` stayed at 12/12.

**Three named verification consumers could not contribute, all for reasons predating this work.**
`dev/proxy_dual_log/verify_strip_inject.py` raises `KeyError: 'spans'` on any log pair with a
changed message block, because `_diff_messages` stopped emitting a `spans` key when the ops /
`compose_block` architecture replaced it, while the script still reads it in its span-reconstruction
check; independently it calls the delta builder WITHOUT `all_ops`, so its message section produces
no spans at all. `dev/proxy_instrumentation/p2_badge_words_probe.py` and `p3_badge_inline_probe.py`
reference recorded sessions (1785364138, 1785347492, 1786052022) that no longer exist on disk and
abort while loading. All three were confirmed failing on an unmodified tree and left untouched; the
replay above was written to replace their coverage for this change. Note that p2's and p3's fixture
expectations encode the superseded one-to-one rule (`"."`-filler cases expected `strip inject`), so
reviving them would require updating those expectations, not just restoring the logs.

**Not verified:** a live proxy restart against a real CC session, and the rendered pane itself. The
running proxy uses a frozen source copy and only picks up the change after a restart; the span
rendering was verified through the accumulator's overlay dicts, not by inspecting rendered output.

## Relevant Symbols / Paths

- `_msgs_delta_is_substantial()`, `_TOTAL_TOKENS_NUKE_RE`, `accumulate_dual_log()`
  (`src/proxy_display/parser.py`) — the badge filter, the only behavior change
- `_process_messages_section()` (`src/proxy/strip_inject_delta.py`) — the writer, deliberately unchanged
- `_apply_role_system_strip()` (`src/proxy/message_passes.py`) — the nuke itself, deliberately unchanged
- `_build_req_header_line()` (`src/proxy_display/render_turn.py`) — badge consumer, unchanged
- `dev/proxy_dual_log/tt_delta_skip_replay.py` — replay harness
- Ground-truth log: `src/logs/dual_log/api_requests_opus_monitor_cc_1788011077_*.jsonl`
