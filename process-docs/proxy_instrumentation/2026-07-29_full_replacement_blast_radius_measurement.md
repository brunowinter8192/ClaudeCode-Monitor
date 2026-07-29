# Blast-radius measurement: full-replacement-aware `_extract_block_op`, 2026-07-29

Milestone-1 measurement task: before any fix, quantify how many of the 17 real
`_ops_from_content_change` call sites in `src/proxy/message_passes.py` a full-replacement-aware
`_extract_block_op` (`src/proxy/rule_ops.py`) would actually change, and by how much. No
production code touched. Script:
`dev/proxy_instrumentation/p1_measure_full_replacement_blast_radius.py`.

## Trigger

`_extract_block_op(before, after)` reduces any content change to one `(offset, removed, injected)`
op by walking off the common prefix/suffix. When a pass replaces a block's ENTIRE content and the
replacement happens to share a leading word with the original — both the CC background-launch ack
and the proxy's own replacement text start with `"Command"` — the recorded op starts mid-text.
`_render_span_content` (`proxy_display/render_messages.py`) then emits the shared leading fragment
unhighlighted on its own line and the rest green below: a 2-line split instead of one contiguous
green block. `_extract_block_op` is reached from all 17 call sites via `_ops_from_content_change`
(`message_passes.py`) — any change there affects every pass, not only the launch-ack one, which is
the risk this measurement quantifies before touching the function.

## Method — classification is semantic per call site, not a ratio threshold

Each of the 17 call sites was classified by reading the underlying strip function: **FULL** = new
block content is constructed independently of the old (a fixed literal, or a freshly-derived
string, with no attempt to preserve surrounding text). **PARTIAL** = a known marker/chunk is
excised from within the text (`regex.sub` / `str.replace` / slice) and everything else in the
block is kept verbatim. **STRUCTURAL** = neither (an index-shift artifact from
`_dedup_wakeup_blocks`'s list-branch dropping a duplicate block, not a designed content
transform). A `len(removed)/len(bt)` ratio was computed per op as corroborating evidence only,
never as the classifier — confirmed necessary: measured FULL ratios spanned [0.973, 1.000] and
PARTIAL ratios spanned [0.015, 1.000] in the same corpus, an overlapping range that a fixed
threshold would misclassify in both directions (a large SR block excised from a mostly-empty
surrounding message scores near 1.0 despite being genuinely PARTIAL; `_apply_first_pass`'s TN
branch scored exactly 1.0 for a message whose only content was the tag itself, despite being
mechanistically PARTIAL — excise-and-keep-remainder, just with nothing left to keep in that
instance).

3 sites are FULL: `_apply_role_system_strip` (content set to literal `.`),
`_apply_bg_launch_ack_strip` (block text wholesale-replaced by `_build_launch_ack_replacement`),
`_apply_first_pass`'s rejection branch (`_strip_rejection_message` sets matched content to literal
`.`). 13 sites are PARTIAL (all the SR-family passes, `_apply_first_pass`'s other 4 branches,
`_apply_po_preview_strip`, `_apply_bg_exit_strip`, `_apply_hook_prefix_strip`,
`_apply_git_lock_strip`, `_apply_bd_noise_strip`, `_dedup_wakeup_blocks`'s str-branch). 1 site
(`_dedup_wakeup_blocks`'s list-branch) is STRUCTURAL — 0 occurrences in the measured corpus.

`_apply_first_pass` is one function with 5 internal elif-branches carrying 3 different
classifications; sub-classified per message by re-evaluating the same branch conditions the real
function uses (`_top_level_content_contains`, `_message_has_rejection`, imported from their real
modules, not reimplemented).

## Findings (as of 2026-07-29, 522-523 requests scanned, 140 ops captured across all 17 sites)

- FULL-class ops: 97 (82 `_apply_role_system_strip`, 15 `_apply_bg_launch_ack_strip`, 0
  rejection-branch in this corpus). Of those, currently recorded as trimmed (`offset>0` or a
  trimmed suffix — would render as a 2-piece split today, would become one contiguous span under a
  full-replacement-aware op): **17** — all 15 `_apply_bg_launch_ack_strip` ops (100% of that site,
  the flagship defect) + 2 `_apply_role_system_strip` ops (2.4% of that site).
- 9 of the 17 call sites had 0 ops in this corpus (all 5 `_apply_first_pass` sub-branches except
  TN, `_apply_cumulative_sr_strips`, `_apply_final_sr_pass`, `_apply_git_lock_strip`,
  `_apply_bd_noise_strip`, `_dedup_wakeup_blocks` both branches) — stated plainly, not folded into
  the observed-site table.

**Hypothesis, not established fact, for the 0-op PARTIAL sites:** `_apply_role_system_strip` runs
FIRST in the real pipeline and wholesale-replaces any role='system' message content (without a
`<task-notification>` tag) with `.`. One candidate explanation for several PARTIAL sites' 0-op
count is that their target markers (deferred-tools nag, task-tools nag, skills/agent-types/
claudeMd SR blocks) arrived on role='system' messages in this corpus and were consumed wholesale
by `_apply_role_system_strip` before the later, genuinely-PARTIAL passes ever saw them — one
concrete render instance in the report is consistent with this (deferred-tools + agent-types +
skills text arriving on a role='system' message, wholesale-`.`-replaced). This supports the
hypothesis for that one instance; it does not establish the mechanism generally. An equally
consistent alternative is plain absence of those markers on role='user' messages in this corpus,
which would produce the identical 0-count with no upstream-consumption effect at all. Not
distinguished — would require directly checking role='user' messages for these markers, out of
scope for this measurement.

## Flagged edge case — `.`-replacement absorbed as a common suffix

For the 2 FULL sites whose replacement is the literal `.` (`_apply_role_system_strip`,
`_apply_first_pass`'s rejection branch), when the ORIGINAL block text also happens to end in `.`,
the single-char injected `.` gets absorbed entirely as the common suffix — the recorded op then has
an EMPTY `injected` string. Confirmed directly against `_extract_block_op` (independent review,
2026-07-29): `before='abc.', after='.'` → `offset=0, removed='abc', injected=''`. Measured: 2 of 82
`_apply_role_system_strip` ops in this corpus hit this exact condition.

The rendered before/after comparison in the report does NOT demonstrate this edge case visually —
the absorbed `.` remains present in `compose_block`'s output as an unmodified `equal` span (same
character position in both before/after), it does not disappear from the rendered text. What
changes is only the span TAG on that character (`equal`/DIM today vs `injected`/green under a
full-replacement-aware op) — an ANSI color/background attribute, not a text-content difference.
After stripping ANSI codes for the markdown report, the two renders are textually near-identical.
The finding rests on the op data alone (`injected == ''` vs the hypothetical `injected == '.'`),
not on the rendered text — the bg-launch-ack case elsewhere in the same report IS a genuine
visible text-split and is unaffected by this caveat.

## Corpus was not static during measurement — op counts are a lower bound

Request counts varied 519-523 across reruns of the same script within one measurement session, and
diverged from a related same-day measurement's 511 on the nominally identical 4-file corpus —
`opus_posts_1785338463` grew from 105 to 143 lines (mtime after both measurement runs) during/
after the session. All op counts above are a lower bound on a moving snapshot, not a final static
total. The qualitative findings (bg-launch-ack always FULL+trimmed; role_system_strip as the
dominant FULL site; the semantic FULL/PARTIAL split; the ratio-range overlap) are not expected to
change in kind under a rescan, only in magnitude.

## Relevant Symbols / Paths

- `_extract_block_op`, `_ops_from_content_change` (`src/proxy/rule_ops.py`) — function under
  measurement
- `compose_block` (`src/proxy/diff_engine.py`), `_render_span_content`
  (`src/proxy_display/render_messages.py`) — real rendering pipeline reused (unmodified) to
  produce the before/after comparisons
- `dev/proxy_instrumentation/p1_measure_full_replacement_blast_radius.py` — measurement script,
  re-runnable
- `dev/proxy_instrumentation/md/full_replacement_blast_radius_20260729.md` — full report
  (per-site evidence table, ratio distributions, 3 rendered before/after cases)
- Corpus: `src/logs/dual_log/api_requests_{opus_monitor_cc_1785336796,opus_posts_1785338463,
  opus_wise2627_1785324012,worker_25c51a2e_tn-role-system_1785344818}_original.jsonl`
