# total_tokens role=system Nuke Excluded from Strip/Inject Delta Accounting, 2026-08-29

Continues this area's badge line: the badge signal was moved off `fn_map` onto delta presence
(`has_content` in `parser.py::accumulate_dual_log`), which made the badge agree with what the
expanded view renders. That coupling is exactly what this entry exploits — and what forced the
fix, because a per-request delta entry now means a per-request badge.

Related areas: `process-docs/proxy_tool_stripping/` established the "badge only for substantial
events" principle and the earlier phantom-badge classes (field overrides, `"."` placeholders,
spurious newlines); `process-docs/message_strip_fp_nuke/` established the anchored-match
convention (never substring-anywhere) that the detection here follows.

## Symptom

Newer CC appends a fresh `role='system'` message `<total_tokens>N tokens left</total_tokens>` to
the END of the message history on EVERY request. `_apply_role_system_strip` nukes it to `"."`,
which is correct. The REQ-header badge nevertheless showed `strip inject` on virtually every
request, and the expanded view rendered an olive stripped span plus a green `"."` span for it.
The rare real strip drowned in per-request noise.

## Root cause — why hash-dedup structurally cannot help

`_build_stripped_injected_deltas` suppresses a repeated change via a flat `loc_key → MD5[:10]`
hash chain. For messages the `loc_key` is `msg.<msg_idx>.<blk_idx>`. Historical total_tokens
messages keep their index, so their hash is stable and they ARE suppressed. The NEW one arrives
at a new index every request, so it gets a NEW `loc_key` every request, and a `loc_key` that has
never been seen before can never match a previous hash. The dedup is therefore not merely
ineffective here, it is structurally incapable of firing.

Measured on `src/logs/dual_log/api_requests_opus_monitor_cc_1788011077` (46 requests replayed
through the real pass pipeline, 2026-08-29): 41 requests carried a non-empty `messages_delta`,
of which 30 were PURE total_tokens nukes, 3 mixed a total_tokens nuke with a real strip, and 8
were real strips alone. So roughly three quarters of all badge-lighting requests carried no
information a reader wanted.

## Fix — suppress the accounting, never the strip

The strip stays untouched: the forwarded payload and the `_forwarded` log are byte-identical to
before. Only `_process_messages_section` in `src/proxy/strip_inject_delta.py` changed — a block
matching the class is skipped with a `continue` placed BEFORE the hash writes:

```python
_TOTAL_TOKENS_NUKE_RE = re.compile(r"^<total_tokens>\d+ tokens left</total_tokens>$")

if (om_norm.get("role") == "system"
        and len(s_texts) == 1
        and _TOTAL_TOKENS_NUKE_RE.match(s_texts[0].strip())):
    continue
```

No read-side change was needed, and none was made. Because `has_content` is pure delta presence,
removing the write silences the badge, the msg-index overlay lookup and the span rendering in one
move. That is the practical payoff of having moved the badge onto delta presence earlier in this
area — the write side became the single lever for all three surfaces.

### Three design points that carry the fix

**Doubly anchored detection.** The condition requires `role == 'system'` AND exactly ONE stripped
span that FULL-matches the anchored pattern. In the same session the identical string appears 175
times as quoted content — 82 in `tool_result`, 79 in `role='assistant'` text, 14 in `role='user'`
text — against 575 genuine `role='system'` nukes. A substring-anywhere check would have swallowed
real strips of messages that merely discuss the marker, which is precisely the FP-nuke failure
mode this codebase has hit repeatedly.

**Per-block, not per-message.** Three requests in the measured session mixed a total_tokens nuke
with a genuine strip. A message-level skip would have discarded the genuine one. The block-level
skip drops only the marker block and leaves the real strip at its own index.

**Hash entries omitted rather than written.** The `loc_key` is left out of the returned hash state
entirely. The hash exists only to suppress a REPEAT of identical content at the same `loc_key`,
and this class is skipped unconditionally, so its hash would be dead state that also grows the
chain on every request. Omitting it cannot swallow a later emission: if different content ever
lands on that `loc_key`, the lookup yields `None`, and `None` differs from the new hash exactly as
a stored total_tokens hash would have. Both variants are behaviourally identical on the emitted
deltas, so the one without dead state was chosen.

## Verification (as of 2026-08-29)

**Before/after replay over the real pipeline.** `dev/proxy_dual_log/tt_delta_skip_replay.py
--compare` drives each recorded original payload through `apply_modification_rules` (the
production source of `all_ops`), then through the real `_build_stripped_injected_deltas`, then
through the real `accumulate_dual_log`. Baseline is reproduced in the same process by patching the
class regex to one that matches nothing, so both sides differ in nothing else. Result on the
1788011077 session: entries with `messages_delta` fell 41 → 11 on the stripped side and 40 → 10 on
the injected side; `has_content` True fell 42 → 12 per side; all 30 pure total_tokens requests
compute `has_content` False on BOTH sides; all 8 real-strip requests are byte-identical before and
after; the 3 mixed requests keep their entries, which is what leaves 11.

**Synthetic guards.** `dev/proxy/test_strip_fix.py` went from 159 to 192 passing checks, the 33 new
ones in TT01-TT08: the class produces no entry and computes `has_content` False; a `role='user'`
message and a `tool_result` quoting the same string keep their entries; nag, deferred-tools,
date-changed and mid-conversation `role='system'` nukes keep their entries and their `'RS'`
attribution; prefixed, suffixed, digit-less and reworded near-misses keep their entries while a
whitespace-padded exact marker is skipped; a mixed request keeps its real strip; the skipped
`loc_key` is absent from the hash state and a later real strip at that same `loc_key` still emits.
`dev/proxy_dual_log/test_composition_invariant.py` stayed at 12/12.

**Three named verification consumers could not contribute, all for reasons predating this work.**
`dev/proxy_dual_log/verify_strip_inject.py` raises `KeyError: 'spans'` on any log pair with a
changed message block, because `_diff_messages` stopped emitting a `spans` key when the ops /
`compose_block` architecture replaced it, while the script still reads it in its span-reconstruction
check. Independently, that script calls the delta builder WITHOUT `all_ops`, so its message section
produces no spans at all and it is structurally blind to this change — verified directly, both
`messages_delta` sides come back empty in that mode. `dev/proxy_instrumentation/p2_badge_words_probe.py`
and `p3_badge_inline_probe.py` reference recorded sessions (1785364138, 1785347492, 1786052022) that
no longer exist on disk and abort while loading. All three were confirmed failing on an unmodified
tree and were deliberately left untouched; the replay above was written to replace their coverage
for this change.

**Not verified:** a live proxy restart against a real CC session. The running proxy uses a frozen
source copy and only picks up the change after a restart.

## Relevant Symbols / Paths

- `_process_messages_section()`, `_TOTAL_TOKENS_NUKE_RE` (`src/proxy/strip_inject_delta.py`) — the skip
- `_apply_role_system_strip()` (`src/proxy/message_passes.py`) — the nuke itself, deliberately unchanged
- `accumulate_dual_log()` (`src/proxy_display/parser.py`) — `has_content` as pure delta presence, unchanged
- `dev/proxy_dual_log/tt_delta_skip_replay.py` — before/after replay harness
- Ground-truth log: `src/logs/dual_log/api_requests_opus_monitor_cc_1788011077_*.jsonl`
