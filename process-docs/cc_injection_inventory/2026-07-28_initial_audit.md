# CC Injection Inventory — build + defect fixes, 2026-07-28

## What the tool measures

`dev/cc_injection_inventory/cc_injection_inventory.py` answers "what distinguishable text
classes appear in the raw request payloads Claude Code sends, and which of them are we not
already handling?" — a complete INVENTORY of `src/logs/dual_log/*_original.jsonl`, not a
top-N-by-cost ranking: a class occurring once is listed exactly as a class occurring 500
times. Segments: `system[0..3]` blocks, and every message's `content` (plain string, `text`
blocks, `tool_result.content` as string or list of `{type: text}` sub-blocks). Does not
descend into `tool_use.input`, `image`, or `document` blocks.

## Dedup metric and why

Payloads are cumulative snapshots — every request re-sends the full conversation history, so
a naive per-line scan overcounts by ~50-100x. The codebase's prior convention dedups by
`(file, exact full message content)` (whole message). This tool refines that to SEGMENT
granularity — `(file, role, section, block_type, exact segment text)` — so a message that
combines one repeated block with one genuinely new block credits only the new block as a new
distinct occurrence, and the resulting dedup key drives the per-class table directly instead
of needing a second pass over messages. Both metrics are computed and reported side by side
for comparability: on the 2026-07-28 run, segment-level gave 166,175 raw / 1,635 distinct
(101.6x overcount); message-level (prior convention) gave 216,736 raw / 1,989 distinct
(109.0x overcount) over the same corpus.

## Origin classification — 5 labels, ground-truthed by running the real pipeline

Every `role=user` and `role=system` segment is wrapped into a synthetic single-block message
matching its real content shape and run through the actual production pipeline,
`src/proxy/rules.py:apply_modification_rules` — never hardcoded marker lists:

- **COVERED** — chunks the pipeline's `stripped_msg_removed` return value actually contains,
  attributed to a rule code via `strip_vocab.attribute_chunk`.
- **INJECTED** — chunks the SAME pipeline call's `injected_msg_added` return value actually
  contains (added, 2026-07-28, see below).
- **KEEP** — 3 known preserve-guarded cases detected explicitly on the residual: the Read-tool
  truncation notice (`[Truncated:`, guarded in `_apply_role_system_strip`), the
  `<persisted-output>` wrapper (Preview content stripped by the PP rule, wrapper kept), and the
  CLAUDE.md context SR (preserve-guarded in `strip_sr.py` via `_PRESERVE_PREAMBLE`).
- **OURS** — `role=assistant` text (verified: no pass in `rules.py` gates on
  `role=='assistant'`, so it is never touched); `tool_result` residual bucketed by tool name,
  resolved via `tool_use_id` against the preceding assistant `tool_use` block in the same
  payload; top-level user text with no recurring template signal.
- **UNCLASSIFIED** — CC-authored framing left over after all of the above: no rule fires on
  it, and it is not one of the 3 KEEP cases. This is the category the report leads with (a
  dedicated "Strip Candidates" summary, added 2026-07-28, see below) since it is the direct
  answer to "what should we strip that we don't today".

## Defect: tool_result vs top-level text — first version got this wrong

The first working version ran two extraction passes (CLAUDE.md-preserve, leftover-unmatched-
`<system-reminder>`) against the residual text of EVERY segment shape uniformly, including
`tool_result` content. Review of the first full-corpus run found 4 UNCLASSIFIED false
positives, each a `<system-reminder>`-looking literal that was quoted DATA inside a
`tool_result`, not a CC-injected wrapper: two came from a GitHub issue body loaded into
context via RAG that quoted example "Auto Mode"/"Plan Mode" spoofing patterns inside a
markdown fence; one came from the same issue body's "Auto Mode re-injection" pattern
description; one came from a `strings` dump run over the CC binary that happened to contain
the literal template text. The fix: `tool_result.content` is OUR tool's own return value —
a tag-like literal appearing inside it is quoted data by construction, never a CC wrapper.
Both extraction passes now only run on top-level shapes (`plain_string` / `text` blocks,
`_TOP_LEVEL_SHAPES`); anything matching inside `tool_result` content stays part of that
segment's `OURS` residual, bucketed by tool name like the rest of the tool's output. This
dropped the UNCLASSIFIED count from 9 to 4 classes on rerun.

## Defect: prefix-extension read as a fake recurring template

The two-phase resolution for top-level user text groups by a normalized-template signature
(paths/IDs/numbers -> placeholders, truncated to 120 chars) and requires >=2 distinct variants
to count as a genuine recurring CC template (vs. one-off human prose). Review found one row —
a German apartment-rental message — where the "2 variants" were actually a 224-char message
and a verbatim 526-char extension of it (the same message, edited/resent as it grew), merged
into one signature purely by truncation. Fixed with `_distinct_variant_count`: variants are
sorted longest-first and any shorter variant that is a verbatim substring of an already-kept
longer one is dropped before counting — collapses both this containment case and the
previously-fixed trailing-newline whitespace-shape artifact (a corpus-wide shift partway
through one long session where CC started appending `\n` to user text content, which had
inflated one file's UNCLASSIFIED count from 9 real classes to 91 mostly-false rows before that
first fix).

## Defect: default corpus glob scanning the tool's own live session

The default glob (`<dual_log_dir>/api_requests_*_original.jsonl`) matched the log file of the
worker session running the audit itself — written live, growing mid-scan, making the run
non-reproducible. Fixed with `_current_task_name()` (detects the `.claude/worktrees/<name>/`
nesting) + `_is_own_live_session_log()`: only a file matching BOTH the `api_requests_worker_`
prefix AND the current task/worktree name is excluded — verified on a live corpus containing
both the current session's own log and an unrelated, already-completed worker session's log
(`..._volnorm-window_...`), confirming only the former was excluded. An explicit `--logs-glob`
bypasses the exclusion entirely (user takes responsibility for corpus scope). Excluded files
are listed in the report's Corpus section.

## Discovery: INJECTED — the proxy's own text round-trips into later history

Review traced a recurring UNCLASSIFIED row — `"background done — check worker or other
process\nOutput: <path>"` — back to `strip_bg_completed.py`'s `_WAKEUP_TEXT`, injected by
`_apply_first_pass` (task-notification branch) or `_apply_bg_exit_strip` when a background
command's notification/exit is replaced. Once the proxy sends this replacement text to
Anthropic, CC's own session transcript is built from what was actually sent over the wire
(not what CC "intended"), so the injected text reappears verbatim as ordinary top-level user
text in every later request's cumulative history — none of the 4 original labels fit (not
CC-authored, not our tool/user output, not something a rule removes or preserves). Added a
5th origin label, `INJECTED`, ground-truthed the same way as `COVERED` — reading the SAME
pipeline call's `injected_msg_added` return value (chunks the pipeline actually ADDS) rather
than a heuristic. Injected chunks are subtracted from the segment's residual before any
further OURS/UNCLASSIFIED classification runs, so they are counted once, correctly.

## Result as of the 2026-07-28 run

Corpus: 4 files, 733 entries, 216,736 raw messages, ~4GB total (`opus_monitor_cc`,
`opus_posts`, `opus_trading`, and one unrelated already-completed worker session; the current
session's own worker log excluded per the fix above). 33 classes total:

| Origin | Classes | Distinct occ. | Cum. chars |
|---|---|---|---|
| UNCLASSIFIED | 3 | 682 | 188,291 |
| KEEP | 3 | 7 | 2,921,154 |
| COVERED | 19 | 93 | 22,874,022 |
| INJECTED | 1 | 20 | 84,271 |
| OURS | 7 | 895 | 255,109,012 |

The 3 UNCLASSIFIED classes (the strip-candidate list as of this run): the `sys[0]` billing
header (`x-anthropic-billing-header: cc_version=...`, 673 distinct occ. / 89,454 chars — never
touched by any proxy function anywhere in `src/proxy/*.py`), the `sys[1]` "You are Claude
Code..." intro line (4 occ. / 41,610 chars, likewise untouched), and CC's `[Image: source:
<path>]` attachment-reference notation (5 occ. / 57,227 chars). `system[2]`/`system[3]` are
unconditionally fully replaced by the proxy regardless of content (`_apply_system_passes` /
`_strip_sys3`) and so are COVERED, not UNCLASSIFIED, despite sitting right next to `sys[0]`/
`sys[1]` in the same array.

Full report: `dev/cc_injection_inventory/md/20260728_cc_injection_inventory.md`.
