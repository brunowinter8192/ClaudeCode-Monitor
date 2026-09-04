# SR-Wrapped TN Wake-Up Loss — Root Cause + Fix, 2026-09-04

CC started delivering some background-task wake-ups as a `role='user'` message whose single text
block is an entire `<system-reminder>` block wrapping BOTH the `[SYSTEM NOTIFICATION - NOT USER
INPUT]` paragraph AND the `<task-notification>` tag — previously the paragraph and the tag always
arrived unwrapped (bare paragraph + bare tag, back to back, no `<system-reminder>` around either).
Net effect measured in one real session (`api_requests_opus_monitor_cc_1788464543`, 2026-09-03/04):
20 of 22 wake-ups arrived in the new wrapped shape and were silently reduced to `"."` — the
orchestrator never saw `worker-cli wait` completions; only the 2 wake-ups that happened to arrive as
a bare `role='system'` string survived.

## Trigger: CC 2.1.258 (2026-09-02)

The wrapped shape's onset was verified against the CC version history: the machine generating the
`api_requests_opus_monitor_cc_1788464543` session was updated to CC 2.1.258 on 2026-09-02. Every
wrapped-TN occurrence in the corpus post-dates that update; every TN occurrence recorded before it
arrived unwrapped (bare paragraph + bare tag, the shape every existing pass was already built for).
2.1.258 is the verified trigger for the wrapper's introduction, not a coincidental correlation.

## Root cause: three passes, each individually correct, compose into data loss

Traced the wrapped fixture through `rules.py`'s `_passes` chain in order:

1. `_apply_sn_notice_strip` — no-op. Its decision function is `text.lstrip().startswith
   (_SN_NOTICE_PARAGRAPH)` (anchored, not substring-anywhere — the FP-nuke-class guard shared with
   `strip_bg_launch_ack.py`). In the wrapped shape the text starts with `<system-reminder>\n`, not
   the paragraph, so the anchor never matches. Working as designed for the shape it was built for;
   simply blind to the new wrapped shape.
2. `_apply_first_pass`'s TN branch — fires correctly (`_top_level_content_contains` doesn't care
   about the wrapper) and replaces the `<task-notification>...</task-notification>` tag with the
   wake-up text via `_replace_task_notification_tags`, whose regex is anchored to start-of-line
   (`(?m)^<task-notification>`), not start-of-message — it matches fine INSIDE the wrapper. The
   substitution is correct in isolation; it just leaves the `<system-reminder>` open tag, the SN
   paragraph, and the close tag all still standing around the new wake-up text.
3. `_apply_final_sr_pass` — strips ALL remaining `<system-reminder>` blocks unconditionally (it has
   no gate of its own; `strip_sr.py`'s tool_result non-descent is its only protection). The inner
   text, after step 2, is `[SYSTEM NOTIFICATION - NOT USER INPUT]\n...\n\nbackground done...` — this
   STARTS WITH the paragraph, so it matches `strip_sr.py`'s `'system-notification'` template
   (mode `'full'`) and the entire block — wrapper AND the wake-up text injected one pass earlier —
   gets removed, leaving `"."`.

None of the three passes has a bug in isolation. The bug is compositional: pass 1 doesn't recognize
this shape, pass 2 doesn't need to (its job is the tag, not the wrapper), and pass 3 correctly
recognizes the now-exposed paragraph as a genuine SR template and does its job. The wake-up text
becomes collateral damage of pass 3 doing exactly what it's supposed to do to a block it has no way
of knowing was just partially rewritten by pass 2.

Confirmed via `fn_map`: the dual-log's own attribution pinned the loss on `_apply_bg_exit_strip`
(last-writer attribution — whichever pass's output happened to be the final content before the
dead-end), not `_apply_final_sr_pass` — a reminder that `fn_map`'s attribution is last-touch, not
causal, and shouldn't be read as a root-cause pointer without re-tracing the actual pass chain.

## Fix: unwrap inside `_apply_first_pass`, not a fourth special case in the final pass

Rejected: adding a wrapper check to `_apply_final_sr_pass` (or widening its SR-template matching) —
that pass's whole design point is "strip anything that still looks like a genuine SR block, no
per-shape exceptions"; carving out an exception there for one upstream pass's leftover artifact
would start eroding the reason it has no gate at all.

Rejected: widening `_apply_sn_notice_strip`'s anchor to also match `<system-reminder>\n` + paragraph
— this would conflate two different jobs (paragraph removal vs. wrapper removal) in one pass, and
the wrapper only ever needs removing in the narrow case where the TN branch is about to build a
wake-up inside it; a general-purpose wrapper-strip pass would be reaching for content it doesn't own.

Fix: `_apply_first_pass`'s TN branch calls a new local helper, `_unwrap_full_sr_wrapper`, right after
`_replace_task_notification_tags` (and after the pre-existing task-tools-nag sub-strip). The helper
is anchored — `\A<system-reminder>\n(.*)</system-reminder>\s*\Z` (DOTALL) against the ENTIRE string,
or a single `list[text]` block's own full text — never substring-anywhere, same FP-nuke-class
discipline as every other anchored decision in this pass family. It reuses `_strip_sn_notice`
(already imported into `message_passes.py`) to remove the paragraph from the unwrapped inner text,
so the paragraph-removal logic isn't duplicated. For the unwrapped shape (content doesn't start with
`<system-reminder>`) the regex never matches — no-op, byte-identical to before the fix. This closes
the gap exactly where it opens: the TN branch is the only place that both knows a wake-up was just
built AND can see whether it landed inside a wrapper that needs peeling off before the message ever
reaches `_apply_final_sr_pass`.

## Fixture and verification

Real fixture reconstructed verbatim from `src/logs/dual_log/
api_requests_opus_wise2627_1788533758_stripped.jsonl`, request_id
`65c964d6-90c6-46ec-81de-190487d92e55`, `messages_delta["411"]["0"]` (3-string list, concatenation
is the exact original text); cross-checked against the matching `_original.jsonl` entry (flow_id
`13fca4a5-45f6-40be-bdaf-f8f0d10e765e`) to confirm the real shape is `role='user'`,
`content=[{'type':'text','text': <wrapped text>}]`, one block, `<status>completed</status>`,
`<task-id>bhf5x6b5r</task-id>`, `<output-file>` present.

Pinned as `dev/proxy/test_strip_fix.py` W31 (full `apply_modification_rules` chain on the wrapped
fixture → wire content is exactly the wake-up text) plus W32/W33 (bare `role='system'` str and
pre-existing unwrapped `role='user'` list-text shapes stay byte-identical through the same chain).

One-shot before/after replay against the full real session (`api_requests_opus_monitor_cc_
1788464543_original.jsonl`, 19 wrapped-TN occurrences across its request history) confirmed the
mechanism directly: replaying every request's `payload` through `apply_modification_rules` with the
fix reverted (`_unwrap_full_sr_wrapper` call site short-circuited) reproduced the failure — 19/19
wrapped-TN messages reduced to `"."` at the exact by-index location in the modified message list, 0
surviving; replaying the same session with the fix in place — 0/19 lost, all 19 reconstructed to the
clean wake-up text with no `<system-reminder>` residue. This before/after pair, not just the unit
fixture, is what ties the fix to the originally observed symptom (20/22 lost wake-ups in the
`_1788464543` session).
