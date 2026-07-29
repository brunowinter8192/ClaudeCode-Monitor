# Full-replacement-aware `_extract_block_op`, 2026-07-29

Milestone-3 fix: the M1 blast-radius measurement (same area, 2026-07-29) established that
`_extract_block_op`'s common-prefix/suffix trim mis-renders 17 (of 97 measured) FULL-class ops as
a 2-piece split when the replacement happens to share leading/trailing text with the original —
live-observed as a background-launch ack rendering with the shared word `"Command"` unhighlighted
on its own line, the rest green below. This entry records the fix and the design reasoning behind
each choice, not just the diff.

## Why the signal must come from the caller, not inferred from the two strings

`_extract_block_op(before, after)` only ever receives two strings — it has no way to know which
pass produced them or what that pass intended. The obvious alternative, inferring "whole-content
replacement" from some ratio/size property of the two strings, was already ruled out by the M1
measurement itself: FULL-class ops measured a `len(removed)/len(bt)` ratio range of
`[0.973, 1.000]`, PARTIAL-class ops measured `[0.015, 1.000]` — the ranges overlap, so no
threshold could separate the two classes without misclassifying real cases in both directions (a
large SR block excised from a mostly-empty surrounding message legitimately scores near 1.0; a
whole-block replacement whose text happens to share a long accidental prefix/suffix with the
original would score below any reasonable cut). The only place that genuinely knows which case it
is is the calling pass function itself — it either constructs new content independently of the
old, or it excises a known chunk and keeps everything else. That knowledge has to be threaded in
explicitly.

## Why a default argument keeps 14 of 17 sites byte-identical

`_extract_block_op` and `_ops_from_content_change` both gained a `full_replace: bool = False`
parameter. Every one of the 17 real call sites in `message_passes.py`, plus 3 direct test-file
callers found by grep, calls these functions with 2 positional arguments — none of them pass a
third. Only 3 call sites were edited to add `full_replace=True` explicitly; the other 14 are
textually and behaviorally untouched. This is why the PARTIAL-ops regression argument is
"byte-identical by construction," not just "byte-identical because I tested it": the code path
those 14 sites execute is the exact pre-milestone code, unreachable-different by construction, not
merely observed-to-be-unchanged.

## Why the rendering layer needed no change at all

Hand-traced `apply_edit_to_spans`/`compose_block` (`diff_engine.py`) against the op
`(0, before, after)` before writing any code: starting from `spans = [('equal', c0_text)]`, one
full-block edit op at offset 0 covering the whole text splits that single equal span into exactly
`[('stripped', before), ('injected', after)]` — one contiguous stripped span, one contiguous
injected span, no `equal` fragment left over. `_render_span_content`
(`proxy_display/render_messages.py`) already renders a single injected `(tag, text)` tuple as one
contiguous colored block in its existing new-format branch. Nothing in either file needed to
change; both were exercised, unmodified, by the regression guard and by re-running the M1 render
harness against real corpus data post-fix, and produced the desired one-block render directly.

## Per-site justification for the 3 flagged sites

- `_apply_role_system_strip` — unambiguous: content is set to the literal `"."` unconditionally,
  regardless of shape (`message_passes.py:66`). No caveat needed.
- `_apply_bg_launch_ack_strip` — `_strip_bg_launch_ack` sets a matched block's whole text/content
  field wholesale to `_build_launch_ack_replacement(text)`; every block it leaves alone is
  appended by identity. Same early-return safety as the other two sites. This is the flagship case
  the milestone was measured against.
- `_apply_first_pass`'s rejection branch — the one site that is NOT uniformly full-replace at the
  message level: `_strip_rejection_message` (`content_strip.py`) mutates PER-BLOCK for list
  content, not the whole message at once, and can leave sibling blocks untouched. Verified by
  reading the function directly: every block it actually changes is wholesale-set to the literal
  `"."` (`content_strip.py:43`, `{**block, "content": "."}`), never partially edited in place, and
  every block it leaves alone is appended by identity (`content_strip.py:45`) — so `bt==at`
  exactly for those, and `_extract_block_op`'s `before==after` early-return fires before
  `full_replace` is even consulted. The message-level flag is correct here specifically because
  this pass has no per-block PARTIAL-edit path to protect against — not because the branch is
  "FULL" in the abstract, but because the concrete mutation shape at this call site never produces
  a changed block that isn't a wholesale swap. This distinction — the flag applied at message
  level, the true correctness argument resting on a per-block property — is recorded directly in
  the code comment at the call site, not only here.

## The `.`-absorption edge case resolves as a side effect, not by special-casing

No code was written to detect or handle the `.`-absorption case (`before='abc.', after='.'` →
previously `injected=''`) specifically. It disappears automatically because
`_apply_role_system_strip` is one of the 3 `full_replace=True` sites: the op becomes
`(0, 'abc.', '.')` directly, bypassing the suffix-trim step that used to absorb the shared `.`
into nothing. Confirmed against the 2 real occurrences found in the corpus (both
`_apply_role_system_strip`, both text ending in a truncation-notice period): `injected` changed
from `''` to `'.'` in both, with no special-case branch added anywhere in the fix.

## Empirical regression evidence (as of 2026-07-29, 527 requests, 142 ops)

Captured a full per-op dump (site, class, offset, removed, injected, before-text, after-text)
using the M1 driving loop, once immediately before editing `src/`, once immediately after, on the
same static corpus snapshot (527 requests both times — corpus did not grow between the two
captures). Matched records by `(site, before_text, after_text)`:

- **43/43 PARTIAL ops byte-identical** — 0 mismatches on `(offset, removed, injected)`.
- **99/99 FULL ops now recorded as `(0, before_text, after_text)`** — 0 still trimmed, 0 wrong.
  (99 rather than M1's originally-measured 97: the corpus grew by 2 FULL ops between the M1
  measurement and this fix, both handled correctly by the same code path — no special-casing was
  needed for the newly-arrived ones either.)

As an end-to-end sanity check, the *unmodified* M1 blast-radius script
(`dev/proxy_instrumentation/p1_measure_full_replacement_blast_radius.py`) was re-run against the
fixed code — the same measurement instrument that quantified the defect before the fix now reports
`FULL-class ops: 99, of which 0 currently trimmed` (was `97, of which 17 trimmed`). This
confirms the fix from the same measurement angle the milestone was scoped against.

**Constraint this session surfaced and must not be repeated:** re-running the M1 script this way
initially overwrote `dev/proxy_instrumentation/md/full_replacement_blast_radius_20260729.md` in
place with the post-fix numbers, clobbering the dated pre-fix snapshot that this entry (and the
M1 process-docs entry) rest on as evidence. That file was reverted to its pre-fix committed state.
A script that regenerates a dated report must never be re-run over its own already-committed
output — a post-fix measurement, if ever wanted, belongs in a NEW dated report filename, never
overwriting an existing one.

## Verification boundary (as of 2026-07-29)

Verified at integration level: real production functions (`_extract_block_op`,
`_ops_from_content_change`, `_apply_role_system_strip`, `_apply_bg_launch_ack_strip`,
`_apply_first_pass`, `compose_block`, `_render_span_content`) exercised directly against a real
fixture and real corpus data, plus the full before/after op-dump diff described above. NOT
verified against a restarted live proxy rendering a genuine background-launch ack in real time —
the running proxy uses a frozen source copy and only picks up a source change after restart; that
gate is still open.

## Relevant Symbols / Paths

- `_extract_block_op`, `_ops_from_content_change` (`src/proxy/rule_ops.py`) — `full_replace`
  parameter, defaults preserve prior behavior for all untouched call sites
- The 3 `full_replace=True` call sites (`src/proxy/message_passes.py`):
  `_apply_role_system_strip`, `_apply_first_pass`'s rejection branch, `_apply_bg_launch_ack_strip`
- `apply_edit_to_spans`, `compose_block` (`src/proxy/diff_engine.py`) — consumed unmodified
- `_render_span_content` (`src/proxy_display/render_messages.py`) — consumed unmodified
- Regression guard: Item 4q (`dev/proxy_dual_log/proxy_176_bg_launch_ack_tests.py`) — pins the op
  shape and the composed span shape against the real launch-ack fixture
- Measurement instrument re-run for confirmation:
  `dev/proxy_instrumentation/p1_measure_full_replacement_blast_radius.py`
