# SN-Notice Bare-Paragraph Strip — Design + Attribution Collision + Count Discrepancy, 2026-07-27

CC injects a 4-line `[SYSTEM NOTIFICATION - NOT USER INPUT]` paragraph ahead of `<task-notification>`
tags in background-task wake-up messages — pure noise for the agent, actively confusing (it reads like
the model should distrust its own recent turns). Task: strip the paragraph, leave the tag + wake-up
injection untouched.

## Design — anchored decision, no tool_result descent

Followed the pattern from the two prior FP-nuke incidents in this codebase (substring-anywhere match
replacing whole block content — `strip_bg_launch_ack.py`'s `Command running in background with ID`
fix, and `_apply_first_pass`'s plan-mode branch removal): the decision function is
`text.lstrip().startswith(_SN_NOTICE_PARAGRAPH)`, never `substring in text`. `strip_sn_notice.py`
additionally does NOT descend into `tool_result` content at all (mirrors `strip_bg_completed.py`'s
top-level-only traversal) — measured over the dual-log corpus, the paragraph never genuinely
originates there, only as quoted data (RAG output, pasted transcripts, bash output echoing it back).

Pass position: `_apply_sn_notice_strip` runs as message-pass #2, immediately after
`_apply_role_system_strip` and BEFORE `_apply_first_pass` (the TN-tag consumer). Verified functionally
order-independent (the TN regex only touches the `<task-notification>...</task-notification>` span,
leaving the paragraph text before it untouched regardless of pass order) — chosen anyway for
separation of concerns: the TN-consumption pass's `_top_level_content_contains` guard and
`_replace_task_notification_tags` substitution operate on an already-cleaned prefix.

## Attribution collision: SN vs SNP

`strip_vocab.py` already had an `'SN'` rule code for `stripped_system_notification_sr` —
`strip_sr.py`'s `system-notification` template, which strips the SAME 4-line paragraph text when it
arrives WRAPPED in `<system-reminder>` tags (a structurally distinct occurrence, out of scope for this
task). Both the old `SN` chunk and the new bare-paragraph chunk contain `'[SYSTEM NOTIFICATION'` as a
substring — `attribute_chunk`'s generic marker loop (`for code, (_, markers) in RULES.items(): if
marker in chunk: return code`) would attribute EVERY bare-paragraph chunk to `SN` first, since `SN`
precedes any newly-appended code in dict-iteration order and its marker is a true substring of the new
chunk too.

Rejected: extending the `'SN'` entry to also mean "either wrapped or bare" — the two are genuinely
different code paths (different strip module, different pass) and collapsing them loses the
distinction the whole attribution system exists to preserve.

Fix: new distinct code `'SNP'`, disambiguated via a `startswith` special-case in `attribute_chunk`
placed BEFORE the generic loop — exactly mirroring the pre-existing `<task-notification>` → `'TN'`
special-case at the top of the same function. `SNP` chunks (bare, no `<system-reminder>` wrapper) are
structurally distinguishable from `SN` chunks (always start with the `<system-reminder>` tag literal)
by prefix alone, so `startswith` is sufficient and precise — no ambiguity remains. `SNP` also excluded
from `_SR_STRIP_RULES` (alongside `TN`, `PP`) since it never strips an actual `<system-reminder>` tag.

## Replay-count discrepancy — investigated, not tuned away

Task-stated expectation (measured over 52 dual-logs in a prior session): 269 unique genuine messages
stripped, 120 data occurrences left untouched (45 tool_result + 75 mid-content).

Measured this session over the current 53-file corpus at `src/logs/dual_log/*_original.jsonl`
(`dev/proxy/replay_sn_notice_strip.py`): 534 unique genuine, 9 untouched-data (0 tool_result + 9
mid-content). Investigation into the gap:

- Dual-log `_original.jsonl` entries are FULL cumulative payload snapshots — the same message
  reappears verbatim in every later request of the same session, so a naive per-entry scan wildly
  overcounts (raw genuine-fire count was 32230 before any dedup).
- Tried delta-scoping (only scan `messages[prev_len:]` per entry, mirroring
  `strip_vocab.classify_tags`'s `prev_message_count` approach) — produced numbers close to a
  per-fragment dedup (265) but undercounted whole-message dedup, because a message can grow new
  blocks across requests without its start index changing.
- Settled on "unique = deduplicated by (file, exact full message content)" as the metric — matches the
  task's own framing ("269 UNIQUE GENUINE MESSAGES") better than per-fragment or per-entry counting.
- Even with this methodology, 534 vs. 269 and 9 vs. 120 do not reconcile to a simple factor (not 2x,
  not the +1-file ratio). Most likely cause: the dual-log directory is a rolling/pruned window — this
  session's 53 files are NOT the same 52 files (plus one) the original measurement ran over; session
  content differs, not just file count.
- Per this project's explicit instruction ("if your numbers differ, report the discrepancy — do NOT
  tune the rule to hit my numbers"), the numbers are reported as-is in
  `dev/proxy/md/replay_sn_notice_strip.md` rather than adjusted to match.

The property that DOES hold, independent of the count discrepancy: 0 byte-exact reconstruction
failures across all 5860 scanned request entries — every genuine strip's removed span, spliced back
into the new content, reproduces the original byte-for-byte, and every message NOT reported as changed
(including every tool_result and mid-content occurrence found) is asserted identical before/after.
