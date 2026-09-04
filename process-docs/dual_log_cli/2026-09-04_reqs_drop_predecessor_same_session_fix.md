# `reqs --drop`'s predecessor: same-session, not merged-chronological — correction, 2026-09-04

Follow-up to this same area's `2026-09-04_reqs_rebuild_and_drop_flags.md`, same day. Review found the
initial `--drop` implementation compared a REQ's CR against the wrong request's CR+CC whenever
`--merged` interleaved sessions.

## The bug

The first cut read `--drop`'s "previous request" off `entries[position - 1]` in whichever list the
caller had already built — one session's own markers by default, or `_merged_entries`' merged,
GLOBALLY chronologically sorted list under `--merged`. That is correct for `--gap` (elapsed real
time between ANY two requests IS what the gap threshold measures, prompt cache warmth is shared
across a project's sessions) but wrong for `--drop`: a real invocation surfaced `REQ 1
capture-crosssession  ...  −648,915`, a shortfall computed against `duallog-search-chars`' totals —
`capture-crosssession`'s own REQ 1 has no real predecessor at all, since the two sessions share no
conversation, only the system/tools prefix. A cache-drop shortfall computed against an unrelated
session's numbers is meaningless output, not merely imprecise.

## The fix

`_entries_for_session` now PRECOMPUTES each entry's `prev_usage` while it is still walking ONE
session's own markers in msg-index order — before `_merged_entries` ever flattens and re-sorts
across sessions by timestamp. That precomputed value rides along on the tuple (extended from
`(dt, marker, tag, usage)` to `(dt, marker, tag, usage, prev_usage)`) and is what
`_rebuild_drop_qualifies` reads, regardless of where the entry ends up positioned after the
cross-session sort. `--merged` therefore still changes ORDER (interleaving) and the `  <tag>`
column, exactly as designed — it just no longer changes what "predecessor" means for `--drop`. A
session's own REQ 1 (whose precomputed `prev_usage` is `None`) never qualifies, no matter where the
merge places it chronologically; every other REQ is always measured against its own session's
immediately preceding request, even when a DIFFERENT session's request is chronologically closer.
`--gap` is untouched: `_bracket_gap_positions` only ever reads `entries[i][0]` (the timestamp), so
its cross-session neighbor pairing — the behavior that IS correct for gap health — is unaffected.

## Verification

- Rewrote the merged-predecessor test in `dev/dual_log_cli/tests/test_reqs.py`
  (`test_merged_drop_predecessor_stays_within_session`) to assert the corrected semantics directly:
  session B's single request sits chronologically BETWEEN session A's two requests, but is session
  B's own REQ 1 (no same-session predecessor) and must not qualify for `--drop` under any
  circumstance; session A's second request must qualify against session A's OWN first request, not
  the chronologically nearer session-B one — constructed so the two readings disagree (against the
  wrong chronological neighbor the check fails; against the correct same-session one it passes with
  shortfall 50), so the test fails under the old bug and passes under the fix. Suite: 28/28.
- Full re-run of all 11 suites in `dev/dual_log_cli/tests/`: all passing.
- Real invocation, `reqs monitor_cc --since 2026-09-04 --worker --merged --drop`: the spurious
  `REQ 1 capture-crosssession ... −648,915` line is gone; the six remaining lines all carry a
  legitimate same-session predecessor. `--rebuild` alone, `--rebuild --drop` combined, and the
  plain (no-flag) `--merged` listing were re-run alongside it and are unaffected by this fix (as
  expected — `--rebuild` never reads a predecessor at all, and the plain path never reads
  `prev_usage`).

## Relevant Symbols / Paths

- `_entries_for_session`, `_merged_entries`, `_rebuild_drop_qualifies`, `_rebuild_drop_lines`,
  `_rebuild_drop_gap_lines` (`src/dual_log_cli/render.py`)
- Area: this same area's `2026-09-04_reqs_rebuild_and_drop_flags.md` (the feature this corrects)
  and `2026-09-04_reqs_merged_flag.md` (the cross-session-neighbor mechanic `--gap` correctly keeps
  and `--drop` correctly does not use).
