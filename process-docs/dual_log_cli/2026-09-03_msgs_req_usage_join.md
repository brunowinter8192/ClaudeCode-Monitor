# `msgs` REQ Separators Carry Prompt-Cache Usage, 2026-09-03

Continues this area's `msgs` REQ-separator line (request groups, then block sub-lines): the
separator now shows the group owner's
`cache_read_input_tokens` / `cache_creation_input_tokens`, so a reader can follow prompt-cache
behaviour request by request without leaving the CLI.

## The join has three hops, because the dual log stops short of the answer

The dual log never carries a response BODY, only headers (`src/proxy/addon.py`'s
`responseheaders()` writes `_response`: `flow_id`, `request-id`, `status_code`). The usage figures
live in CC's own transcript store instead. So the join is:

1. `_response.jsonl` → `{flow_id: (request_id, status_code)}`.
2. The FIRST non-haiku boundary whose flow resolves there gives an anchor `request_id`. A literal
   fragment search — `"requestId":"<id>"`, WITH the key, never a bare id — across
   `~/.claude/projects/*/*.jsonl` must land on exactly one file; zero or multiple matches both
   degrade to no usage for the whole session, on the reasoning that an ambiguous transcript is not
   safely resolvable either.
3. That one transcript's `type == "assistant"` records give `{request_id: (cr, cc)}`, keeping only
   the first record per id (one API request produces several streaming records with identical
   input-side usage).

`build_usage_by_flow` then keeps only flows whose `_response` status is 200, so an owner that
errored renders without figures rather than a wrong pair scraped from a retried duplicate.

**The bare-id trap is real, not theoretical.** A tool_result block can quote a `request-id` string
verbatim (a live session did this during this work), which a bare-id search would match as if it
were the record's OWN requestId. Anchoring the fragment on `"requestId":` closes that.

## Verification against ground truth

Session `worker_25c51a2e_gcommit-umlaut_1788367120` / transcript
`-Users-brunowinter2000-Documents-ai-monitor-cc--claude-worktrees-gcommit-umlaut/a01546f3-....jsonl`:
40 `_response` lines (2 haiku, 38 sonnet), all 38 sonnet ids resolve, and the first owner's
separator prints `CR 9,096  CC 1,928` — matching the transcript's first sonnet `requestId`'s usage
exactly, independently re-derived by walking the transcript in Python rather than trusting the
CLI's own output.

## Where the resolution actually falls short, and why

A full sweep of every session under `src/logs/dual_log/` (21 sessions at run time; the corpus is
live and grows during the sweep) gives two different coverage numbers depending on what "resolved"
means:

- **Raw non-haiku `_response` lines**: 1679 / 1871 resolve (89.74%).
- **Group OWNERS** (`request_markers`' picks — the only thing a separator ever shows): 1637 / 1647
  resolve (99.39%).

The gap between the two numbers is almost entirely re-fires: `opus_monitor_cc_1788342698` has 97
raw ids missing but only 1 of them is an owner; `opus_jobscraper_1788347399` has 59 missing but
only 2 are owners. A re-fire never gets its own separator, so its usage was never going to be
displayed regardless of whether the join resolves it.

Three distinct root causes were found for the remaining raw shortfalls, checked individually
rather than assumed:

1. **The request itself errored.** `opus_jobscraper_1788329559` and `_1788331154` each have all 3
   of their non-haiku `_response` lines at status 400 — the API never produced a successful
   response, so CC's transcript has no assistant record for those ids at all (confirmed: 0 matches
   for a full-store search on the exact id, not just the expected project directory). These are
   also exactly the sessions behind Measurement 2's 4 non-200 owners (2 each).
2. **A 200 status with no transcript record anyway.** `opus_jobscraper_1788331456` (1 id),
   `_1788347399` (59 ids), `opus_monitor_cc_1788342698` (97 ids) and
   `worker_25c51a2e_rag-chunking_1788333660` (35 ids) each have request ids that show `_response`
   status 200 yet are absent from the resolved transcript. Ruled out explicitly: a transcript SPLIT
   across sibling files in the same project directory — checked for `_1788347399` against all 10
   sibling transcripts in its project dir, 0 of the 59 missing ids found in any of them, and 0
   found anywhere else in the whole store either. The remaining explanation is a stream that
   received response headers (hence a logged `_response` line) but never completed into a written
   assistant turn — most likely a dropped/retried SSE stream superseded by a later request that DID
   succeed and became the group's actual owner. Not investigated further: confirming the retry
   mechanism itself would require correlating against Anthropic's server-side logs, which are not
   on disk.
3. **Live-session lag.** `opus_monitor_cc_1788364366` and `worker_25c51a2e_duallog-usage_1788430479`
   (this very work session's own dual log) each show exactly 1 owner unresolved at measurement
   time, and re-running the join against `opus_monitor_cc_1788364366` moments later (isolated,
   outside the full sweep) resolved 245/246 instead of 0/246 the first pass had shown mid-sweep —
   the session was still being appended to while the anchor's transcript write had not yet landed.
   This is the general "a live session tracks whatever the proxy has appended by then" caveat
   `DOCS.md` already states for the whole package, not a new failure mode.

## Timing

Largest session on disk: `opus_jobscraper_1788347399` (368 MB `_original`, 1451 `msgs` output
lines, 308 REQ groups). `msgs` on it: 0.113 s before this change, 6.97 s after — the entire
overhead is the ONE `grep -rlF` subprocess call per invocation that searches the ~1.3 GB transcript
store for the session's anchor request id; this machine's system `grep` takes ~7 s for a full-store
scan regardless of outcome. A single search covers every group in the session (the anchor is found
once, then the resulting transcript is read once for every owner), so the cost does not scale with
REQ count. A `rg`-class tool would cut this substantially — unavailable as an installed binary on
this machine at time of writing, so `subprocess` shells out to plain `grep -rlF` instead, correct
but slower than the 0.05 s a faster tool achieves on the same store size.

## Verification

`sessions`, `search` and `expand` confirmed byte-identical before/after via `git stash` (stash
verified effective: the three modified files diffed empty against `HEAD` while stashed, matching
this area's own earlier corrective lesson about checking the stash actually took hold). `msgs`' msg
lines and block sub-lines confirmed byte-identical (`grep -v '^──'`) on two sessions
(`gcommit-umlaut_1788367120`: 186 lines; `opus_monitor_cc_1788329627`: 493 lines) and on the
largest session used for timing (1451 lines). Separator lines confirmed identical modulo the new
`  CR c  CC c` fragment via a regex strip. New regression coverage in
`dev/dual_log_cli/tests/test_msgs_usage.py` (10 checks): the separator's usage placement and
digit-grouping, the re-fire suffix staying outside the usage-widened `──`, the unchanged-by-default
case, and `build_usage_by_flow` end to end against fixture `_response`/transcript files (a 200 flow
resolves, a 400 flow is dropped, missing streams/boundaries degrade to `{}`) — all independent of
the live, growing real corpus.
