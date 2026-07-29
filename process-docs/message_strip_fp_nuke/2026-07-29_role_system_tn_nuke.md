# role=system Task-Notification Nuked to "." Instead of Wake-Up, 2026-07-29

Same class as the rest of this folder (content-blind strip destroys content it shouldn't), same root
mechanism as `rs_pass_truncation_notice.md` — `_apply_role_system_strip`'s unconditional `.`-nuke —
but a different content class hitting the same blind spot: task-notification (TN) delivery, not a
Read-truncation notice.

## Symptom

Live in the proxy pane, 2026-07-29: a background task terminated; the forwarded message content was
a single `.` instead of the canonical two-line wake-up (`background done — check worker or other
process` + `Output: <path>`). The message carried `role: 'system'`.

## Root cause — confirmed via dual-log replay

Measured against `src/logs/dual_log/api_requests_opus_monitor_cc_1785336796_original.jsonl` (112
requests, the session containing the observed live symptom): TN arrives in **two disjoint delivery
shapes**.

| Shape | Role | Content | Occurrences (this log) | Handled before fix |
|---|---|---|---|---|
| A | `system` | plain `str` — SN-notice paragraph + `<task-notification>` block concatenated in one string | 173 (102 unique requests) | NO — nuked to `.` |
| B | `user` | `list[{type:text}]` — same content, block-shaped | 107 | YES — `_apply_first_pass`'s TN branch |

Traced 3 unique shape-A bodies (task-ids `biw31morg`/`baky5k8lf`/`bmd5vxwdx`) end-to-end into
`_forwarded.jsonl`: `msg[18]` content is literally `"."` in the payload actually sent to Anthropic —
byte-for-byte the reported symptom. `_apply_role_system_strip` runs first in `rules.py`'s `_passes`
list and gates only on `role == "system"`, with no content inspection beyond the pre-existing
truncation-notice guard — it consumes shape-A messages before `_apply_first_pass` (which gated
`role == "user"` only) ever sees them. Pass ORDER isn't even the deciding factor here — the role gate
alone is sufficient to explain the loss, since `_apply_first_pass`'s TN branch would have rejected a
`role='system'` message regardless of order.

Cross-checked shape B in a second log (`api_requests_opus_posts_1785338463_original.jsonl`): traced
into `_forwarded.jsonl`, content is exactly `background done — check worker or other process\nOutput:
<path>\n` — confirms shape B was never broken, only shape A.

## Fix — two candidate designs weighed

**Design 1 (rejected): self-contained fix inside `_apply_role_system_strip`.** Detect the TN tag, run
`_strip_sn_notice` + `_extract_task_notification_output_file` + `_replace_task_notification_tags`
locally, replacing the `.`-nuke branch for TN-carrying content. Pro: `strip_inject_delta.py`'s
`role=='system' → code='RS'` attribution shortcut stays literally true (the function IS still the one
touching role=system content). Con: duplicates the exact wake-up-construction sequence
(SN-strip → output-path extract → inject-text build → tag-replace) that `_apply_first_pass` already
owns — a second copy of fragile, marker-anchored text-construction logic that can drift from the
original on a future edit to either copy.

**Design 2 (applied): widen the role gate on the passes that already own TN handling.**
`_apply_role_system_strip` gets ONE new carve-out (`_top_level_content_contains(old_content,
"<task-notification>")`, checked before the unconditional nuke, mirroring the existing
`[Truncated:` carve-out) that leaves TN-carrying `role='system'` messages untouched.
`_apply_sn_notice_strip` and `_apply_first_pass`'s TN branch (only that branch, not the
nag/deferred/user-interrupt/rejection branches) widen their role check from `role == 'user'` to
accept `role='system'` too — narrowly, since `_apply_role_system_strip` still nukes every OTHER
`role='system'` message to `.`, so only TN-carrying ones can ever reach the widened gates. TN
wake-up construction now exists exactly once.

Chose design 2 for the single-source-of-truth property — verified it doesn't just move the bug
elsewhere by checking three things concretely (not by assumption):

1. **`_apply_first_pass`'s elif-chain behaves correctly for a plain-str `role='system'` TN message.**
   `is_failed_bg`, `_extract_task_notification_output_file`, `_replace_task_notification_tags` all
   already operate generically on `str` content — no shape assumption tied to role. Confirmed by
   replaying the two failed/completed real corpus bodies above through the actual 3-pass sequence:
   both produced the exact canonical wake-up text, role stayed `'system'`.
2. **`_apply_cumulative_sr_strips` / `_apply_final_sr_pass` need nothing.** By the time a
   `role='system'` TN message would reach them (it doesn't — `_apply_first_pass` already turned it
   into wake-up text with no SR markers in it) their `role == 'user'`-only gates are harmless to leave
   untouched.
3. **`strip_inject_delta.py`'s RS/TN attribution does NOT stay coherent under a blind gate widen.**
   `_process_messages_section` hardcoded `role=='system' → code='RS'` unconditionally — under design 2
   that mislabels the reused TN/SNP strip as the blanket nuke, since `_apply_role_system_strip` no
   longer actually touches TN-carrying content. Fixed with a one-line narrowing: the `'RS'` shortcut
   fires only when the original content does NOT top-level-contain `<task-notification>`; TN-carrying
   `role='system'` messages fall through to the normal `_attribute_chunk` content-based path, same as
   the pre-existing `role='user'` TN path already did (this is not a new pattern, just extending an
   existing one to a second role).

**Widening `_apply_sn_notice_strip` had a narrower-than-expected correct scope.** A first attempt
widened its role gate unconditionally (`role in ('user', 'system')`) — this broke an existing test
(`dev/proxy/test_strip_fix.py::w11_sn_notice_role_system_untouched`) asserting a `role='system'`
SN-paragraph-without-TN message stays out of scope for this pass EVEN WHEN CALLED IN ISOLATION (a
defensive boundary, not merely a fact about pipeline order — the test constructs the message directly
and calls the function without going through `_apply_role_system_strip` first). Corrected to
`role == 'system' AND top-level-contains "<task-notification>"` — narrows the widening to exactly the
messages `_apply_role_system_strip`'s new carve-out lets through, preserving the isolated-call safety
net the existing test encodes.

## Verification

**Regression guards** (`dev/proxy/test_strip_fix.py`, pure-function): 91/91 passing — 3 new (W12
completed-TN role=system full pipeline, W13 failed-TN + Output-file, W14 genuine role=system noise
still nuked through the full 3-pass chain), run via `_apply_role_system_strip → _apply_sn_notice_strip
→ _apply_first_pass` in sequence, matching `rules.py`'s `_passes` order.

**Existing suites, no regressions:** `proxy_176_strip_tests.py` (incl. the pre-existing RS
attribution tests — `_SYSTEM_CONTENT` fixture there has no TN tag, so the narrowed attribution
shortcut still resolves to `'RS'`), `proxy_176_agent_types_tests.py`, `test_composition_invariant.py`
(12/12), `proxy_bgcomplete_tests.py` — all green. `proxy_176_bg_launch_ack_tests.py` has 4 FAILs
confirmed via `git stash` to predate this change (unrelated `_apply_bg_launch_ack_strip` area).

**Integration-level, real recorded data:** replayed the two actual `role='system'` TN bodies traced
from the corpus above (previously proven to forward as `.`) through the real 3-pass sequence — both
now produce the exact canonical wake-up text, role stays `'system'`.

**NOT verified:** live proxy restart / a genuine CC session hitting a real background-task
completion — the running proxy uses a frozen source copy and only picks up a fix after restart.

## Relevant Symbols / Paths

- `_apply_role_system_strip()` (`src/proxy/message_passes.py`) — TN carve-out added alongside the
  existing `[Truncated:` carve-out, both checked before the unconditional `.`-nuke
- `_apply_sn_notice_strip()` (`src/proxy/message_passes.py`) — role gate widened, narrowly TN-scoped
  for `role='system'`
- `_apply_first_pass()` (`src/proxy/message_passes.py`) — TN branch's role check widened to
  `('user', 'system')`; all other elif branches unchanged
- `_process_messages_section()` (`src/proxy/strip_inject_delta.py`) — `'RS'` attribution shortcut
  narrowed to exclude TN-carrying `role='system'` content
- Ground-truth logs: `src/logs/dual_log/api_requests_opus_monitor_cc_1785336796_original.jsonl`
  (shape A, the bug), `src/logs/dual_log/api_requests_opus_posts_1785338463_original.jsonl` (shape B,
  confirms user-role path was always correct)
