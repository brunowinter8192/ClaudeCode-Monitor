# Background-task completion/kill notice wording inventory — measurement, 2026-08-06

Milestone-1 measurement task: quantify, before any pending-id-tracking design work, how many
DISTINCT background-task completion/kill notice wordings exist in the real recorded corpus, for
main (orchestrator) vs worker sessions, and whether the task id is reliably extractable. No
production code touched. Script: `dev/timer-loop/p1_scan_bg_completion_wordings.py`. Companion to
the `bg_wakeup_id_line` area, which measured the launch-ack side of the same pending-tracking
design (that area's corpus and this one's do not overlap in time).

## Corpus

`src/logs/dual_log/*_original.jsonl`, 64 session files present at scan time (17GB, 7528 lines
raw). Excluded 1: this worker's own live worktree session
(`api_requests_worker_85d6f25b_timer-loop_*`), growing during the investigation itself and
self-contaminated by Read-tool dumps of the exact source files under measurement
(`payload_helpers.py`, `message_passes.py`, `strip_sn_notice.py` — their docstrings/regex literals
contain the literal `<task-notification>`/`<task-id>` strings being counted).

## Method — full per-line parse, not last-line-only

A last-line-only shortcut (parse only each session's final cumulative snapshot, since dual-log
lines are cumulative growing-history snapshots) was benchmarked and rejected: reading only the
last line of the corpus's largest file (5.2GB, 367 lines) costs 22MB and ~30ms — a ~200x speedup
over full-file parsing. But message-count-per-line was checked across the whole corpus (byte-level
`"role":`-occurrence proxy, no full JSON parse) and found **not monotonic** for several worker
session files (`api_requests_worker_cbc9195b_pass-*`) — mid-session decreases consistent with
context compaction/reset. A last-line snapshot would silently miss notices dropped by compaction.
Fell back to a full per-line parse instead, benchmarked at ~5.7s for the 5.2GB file / ~20-30s for
the whole 17GB corpus — cheap enough to not need the shortcut. Deduped via a per-session
**exact-raw-text `seen` set** on the extracted `<task-notification>...</task-notification>`
tag-block text, not a prev-message-count positional delta (the `bg_wakeup_id_line` area's
approach) — the delta approach double-counts on a compaction reset (start index resets to 0,
re-scanning already-counted messages); exact-text-seen dedup is robust to both simple linear growth
and resets since it doesn't depend on message position at all.

## Real wire format (verified from raw corpus)

Genuine notice = `[SYSTEM NOTIFICATION - NOT USER INPUT]` paragraph (role `user`, occasionally the
whole block is the plain-string paragraph) + blank line + `<task-notification>` block:
```
<task-notification>
<task-id>btl3zpsjc</task-id>
<tool-use-id>toolu_...</tool-use-id>
<output-file>/private/tmp/.../tasks/btl3zpsjc.output</output-file>
<status>failed</status>
<summary>Background command "sleep 3300 &amp;&amp; echo done" failed with exit code 143</summary>
</task-notification>
```
Task id arrives via a clean `<task-id>` XML tag — reliably regex-extractable
(`payload_helpers._extract_task_notification_task_id`, already implemented). Structurally simpler
than the launch-ack side's prose `"with ID: <id>."` pattern (no ambiguity about where the id ends).

## Contamination trap (two sources, both filtered by requiring block-initial match)

1. Prose/dev-report discussion quoting notice text mid-sentence (`api_requests_opus_posts_
   1785424929` — a German write-up discussing token cost) and a report-abbreviated
   `<output-file><path>...</path></output-file>` tag shape (567 raw hits, all from that one file)
   that is a documentation summary, not real wire format — the real format never nests `<path>`
   inside `<output-file>`. Neither is block-initial (`text.lstrip().startswith(...)`), so both
   excluded structurally rather than by file exclusion (same resolution pattern as the
   `bg_wakeup_id_line` area's launch-ack contamination).
2. This worker's own live session (see Corpus exclusion above).

## Findings (as of 2026-08-06 scan, 7584-7594 requests across 63 included files — corpus grew
slightly between re-runs, consistent with concurrent live sessions)

Exactly 3 distinct wordings, bucketed by (status, exit-code, normalized summary template):

1. `status=failed, exit=143` — 340 deduped events, 17 of 31 main-session files, 0 worker files.
   All 4 mechanisms fire (SN marker, TN contains-gate, task-id extract, output-file extract).
2. `status=completed, exit=0` — 11 deduped events, 7 of 31 main-session files, 0 worker files.
   Same mechanisms fire.
3. `status=failed, exit=144` — 1 deduped event (task-id `bvkgj0vd7`, command `"Reindex"`,
   `api_requests_opus_wise2627_1785586009`) — a genuine command-internal failure exit status, not
   a kill-signal code. Matters for the pending-clearing design: completion notices are not
   restricted to `{0, 143, 137}`; the TN branch's `<task-notification>` contains-gate is
   status/exit-code-agnostic and fires correctly here regardless. No `137` (SIGKILL) observed
   anywhere in the corpus. No bare (unwrapped) `strip_bg_completed.py`-family notice observed
   block-initial anywhere — every genuine occurrence is TN-wrapped; that pass's bare-form regex is
   defensive/unexercised by this corpus's real data.

Main-vs-worker (post-exclusion, 31 main / 32 worker files): 18 of 31 main files carry >=1 genuine
notice, 0 of 32 worker files do. This is an observation about this corpus, not a structural
guarantee — the TN delivery mechanism is a CC-side feature independent of session role; these 32
worker files (30 matching `cbc9195b_pass-*`, 2 not — `52fce57c_block-images`, `52fce57c_mode-
flags`) simply may not have backgrounded a Bash call that then completed/was killed during the
recorded window. The excluded own-session worker file DID receive genuine notices from its own
backgrounded commands before being excluded for contamination — direct proof worker sessions can
receive them.

Canonical-timer vs other background tasks: identical `<task-notification>` template regardless of
task identity. The only variance is the quoted command/description string in `<summary>`, driven
by whether the launcher passed a `description` param to the Bash tool call — every 55-minute
orchestrator ceiling timer is the same underlying `sleep 3300 && echo done` call; varying labels
(`"Timer 55min"`, `"55min-Timer für Los-2-Implementierung"`, `"55min ceiling timer"`, ...) are
different callers' description choices for the same command, not different commands. At scan time:
33 deduped canonical-literal timer events vs 307 labeled-timer events within the `failed/143`
bucket.

## Bugs caught and fixed during the same session

1. Dedup-importance table computed `deduped = sum(rec['count'] ...)` — the GLOBAL per-wording
   count across all sessions, not the per-session contribution (same latent bug pattern exists in
   the `bg_wakeup_id_line` area's script). Fixed by tracking a `session_counts` Counter per wording
   bucket and summing only that session's entry. Verified against an independent exploratory
   per-file distinct-task-id count (e.g. `rag_cli` 110, `wise2627_1785586009` 1) — matched exactly
   after the fix.
2. Q3 prose hardcoded "18 remaining worker session files (`cbc9195b_pass-*`)" from an earlier
   exploration pass, stale by the time of the final run (corpus had grown to 32 worker files, only
   30 of which match that naming pattern). Fixed by computing the zero-hit worker file count and
   the pattern-match breakdown dynamically from the same `session_is_worker` map used for the
   corpus-count line above it, so the two numbers in the same section cannot diverge again.

## Tooling note

macOS ships no `timeout` coreutil (exit 127 on a `timeout N ...` invocation) — plain foreground
commands only. An early broad exploration script (raw `f.read()` of full multi-GB files + 3
regex passes per file) triggered this session's own proxy auto-backgrounding (long-running
foreground Bash gets backgrounded by CC, injecting a `[SYSTEM NOTIFICATION]`-style wake-up hint
into the transcript) — its output was lost (no `.output` file captured for that particular
run). Recovered by rewriting the exploration as a streaming per-line JSON parse (matching this
script's final design), which completes well within foreground duration.
