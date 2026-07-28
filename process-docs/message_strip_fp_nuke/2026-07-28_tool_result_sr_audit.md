# tool_result SR-Strip FP Audit — Measurement Only, 2026-07-28

Same FP-nuke class as `bg_launch_ack_anchor.md` / `rs_pass_truncation_notice.md` in this area:
a strip pass's marker matching descends into `tool_result` content and can fire on QUOTED data
(RAG results, file Reads, docs describing the strip itself) instead of a genuine per-request CC
injection. This session scoped the question specifically to the `<system-reminder>`-template
family (`strip_sr.py`) and measured, rather than assumed, how often that specific family actually
fires inside `tool_result` across five real dual-log sessions (`api_requests_opus_monitor_cc`,
`api_requests_opus_posts`, `api_requests_opus_wise2627` [2.2GB], `api_requests_worker_*_pdf-refs`,
`api_requests_worker_*_capture-monitor-cc-ref`; a sixth file, this worker's own live
`sr-fp-audit` session log, was excluded by name — its own Read/Bash calls on this investigation
would otherwise masquerade as evidence).

## Method

Threaded the 11 real `_apply_*` pass functions from `message_passes.py` through every payload's
messages in `rules.py::apply_modification_rules`'s exact order, using each pass's own per-block
diff (`pass_ops_by_msg_blk`) to attribute a removal to a specific `(msg_idx, blk_idx)` and check
that block's PRE-pass `type`. Only removals landing on a `type == 'tool_result'` block count.
Deduplicated per `(file, exact removed text)` — dual-logs are cumulative snapshots, the same
message reappears in every later request of a session. Template classification used `strip_sr.py`'s
own `_match_template`/`_ENV_CONTEXT_RE`/`_IMP_LINE_RE` registries (imported, not reinvented).
Quoted-vs-genuine verdicts were written by hand after reviewing each occurrence's tool_use origin
(resolved `tool_use_id → tool name/input` from the payload's own assistant blocks) and surrounding
context (fence-parity signal: odd `` ``` `` count before the removal = inside an open fence).

## Result — split by pass family (the critical correction this session made)

30 tool_result-level removals total, but pooling them into one number is wrong: 3 of the 11 passes
(`_apply_first_pass`'s SR branches, `_apply_cumulative_sr_strips`, `_apply_final_sr_pass`) actually
import and match through `strip_sr.py`; the other 3 that fired here (`_apply_bg_launch_ack_strip`,
`_apply_hook_prefix_strip`, `_apply_po_preview_strip`) match their own, unrelated markers and never
touch `strip_sr.py` at all. An early draft of the audit report pooled all 30 into "28 genuine CC
injections found inside tool_result, the fix must not blanket-disable descent" — true for the pool,
but the pooled 29 (after final corpus growth) were ALL non-SR-family (real hook-error prefixes, real
background-launch acks, real persisted-output previews on genuinely oversized Bash output — all
correctly matching their own markers, out of this issue's scope). Split by family:

- **SR strip family: 1 tool_result-level occurrence in the entire corpus.** A `rag-cli search`
  over `monitor-cc-docs` (querying this exact bug) returned a process-docs paragraph that fences a
  literal, real-newline example of the env-context system-reminder block ("CC injects this SR
  block on nearly every request:\n```\n<the block>\n```\n334 chars..."), and `_apply_first_pass`
  stripped it out of the tool_result as if it were a live per-request injection. Confirmed false
  positive — `fence_odd_before = True`, i.e. the removed text sits between a matched open/close
  markdown fence pair, the concrete signal available to distinguish this from genuine content.
  **0 genuine SR-family injections found** in ~660 requests across 5 real sessions — a thin (n=1)
  sample, backed by the structural argument that CC injects these fixed SR templates into
  top-level user-message text, never as part of another tool's own return value, but explicitly
  not "structurally impossible", just "no counter-example found here".
- **Non-SR passes: 29 occurrences, all genuine, all out of this issue's scope.**

## Ground-truth non-reproduction (reported honestly, not smoothed over)

The task's stated ground truth (a prior session's 2-segment finding: `stripped_task_tools_nag` +
`stripped_all_sr_msg0` + `stripped_git_lock_advice`, "quoted SR text and a quoted git-lock advice
block out of retrieved reference material") did NOT reproduce as an actual strip in this corpus
snapshot. Built a reusable check (`_scan_ground_truth_git_lock`): 33 requests carry the git-lock
marker substring inside a `tool_result`, 0 are literal matches of the real 5-line advice block
(real newlines) — every hit is `strip_git_lock.py`'s own escaped source code (`\n` as two literal
characters in the .py file, which the exact-substring strip never matches, by construction) or
prose mentioning the marker. The only place the literal block was found at all was this worker's
own excluded self-session log, as an artifact of investigating `strip_git_lock.py` itself — not
production evidence. Plausible explanation: the dual-log directory is a rolling window (already
documented in `dev/proxy/replay_sn_notice_strip.py`'s own prior count-divergence finding), so the
snapshot behind the original 2-segment finding likely rotated out before this measurement.

## Artifacts

Script + full occurrence-level report: `dev/strip_fp_tool_result/audit_tool_result_sr_strips.py`,
`dev/strip_fp_tool_result/md/audit_tool_result_sr_strips.md` (per-occurrence template, tool,
verbatim text, file+line, verdict+evidence; aggregate split by family).

## Implication for the next milestone

A fix aimed at the SR-strip family's tool_result FP-nuke risk should key on the fence-pair /
documentation-quoting signal demonstrated by the one confirmed occurrence, not on disabling
`tool_result` descent wholesale — the non-SR passes' descent into `tool_result` is correct and
necessary (their own genuine content legitimately lives there), and even within the SR family nothing
in this measurement shows blanket disabling is warranted over a targeted anchor/context guard.
