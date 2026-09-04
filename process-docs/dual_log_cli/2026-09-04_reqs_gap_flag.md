# `reqs --gap MINUTES` — only the REQs bracketing a slow gap, 2026-09-04

Continues this area's `reqs` line (introduced, then given local-time rendering, both earlier the
same day). `reqs` on its own already answers "when did each request happen"; `--gap` answers a
sharper question an agent actually asks while debugging latency or a stuck session: "where were
the SLOW stretches" — without making the reader eyeball a long REQ list computing deltas by hand.

## Design: a pure per-session list transform, not a new filter

`--gap` never touches session SELECTION (scope/`--since`/`--until`/`--main`/`--worker` all still
run exactly as before, in `_run_reqs`) — it only changes what `render_reqs` prints FOR a session
already selected. This is what makes it compose for free with every other `reqs` flag without any
interaction code: `_gap_lines` receives the SAME `(msg_index, marker)` list the plain path already
builds and reduces it, nothing upstream needs to know `--gap` exists.

## The "prints once" rule falls out of a `set`, not a special case

The milestone's own requirement — a REQ that ends one qualifying gap and starts the next prints
once — was tempting to handle with an explicit "is this the same REQ as last time" check. Instead,
`_gap_lines` walks consecutive pairs in order and tracks PRINTED POSITIONS in a `set`: a pair's
"before" REQ is only appended if its position hasn't been marked yet. Since every qualifying
pair's "after" REQ marks its OWN position immediately after being printed, a later pair trying to
print that SAME position as its "before" simply finds it already marked and skips the append —
the REQ's one existing line (carrying its "after" tail from the earlier gap) is left untouched, no
second line, no special-casing "is this REQ shared between two gaps". The same mechanism handles
the entirely unrelated "session with zero qualifying pairs" case for free: `range(len(ordered) -
1)` is empty for 0 or 1 requests, so `_gap_lines` returns `[]` without a dedicated guard, and
`render_reqs`'s existing per-session loop already appends the `session <stem>` header line
regardless of whether any REQ lines followed it.

## Threshold semantics decided before writing the boundary test

"`--gap MINUTES`" reads as an integer threshold, but a real gap is a continuous duration — needed
an explicit decision on how the two meet at the boundary, since the milestone named "threshold
boundary >=" as a required test. Chosen: floor to WHOLE minutes (`total_seconds() // 60`), never
round, and compare that floored integer against the threshold with `>=`. This makes the boundary
EXACT and reproducible in a test: a gap of precisely `N*60` seconds floors to `N` and qualifies for
`--gap N`; `N*60 - 1` seconds floors to `N-1` and does not. A round-to-nearest alternative would
have made the boundary fuzzy (a gap of `N*60 - 29` seconds would round UP to `N` and qualify,
moving the true cutoff earlier than the number the user typed) — floor keeps "at least N whole
minutes elapsed" as the literal, unambiguous reading of the flag.

## Verification

- Extended `dev/dual_log_cli/tests/test_reqs.py` with the four cases the milestone named: one
  qualifying pair (only its two REQs print, non-adjacent REQ 3 omitted entirely since its own gap
  doesn't qualify); two adjacent qualifying gaps sharing a REQ (REQ 2 prints exactly once, carrying
  only its own "+90m" tail); no qualifying gap (only the session header line); and the `>=`
  threshold boundary (5400s qualifies for `--gap 90`, 5399s does not) — 6 new checks, existing
  suite now 17/17.
- Full re-run of all 11 suites in `dev/dual_log_cli/tests/`, all passing — confirming the
  no-`--gap` path is untouched (every pre-existing `render_reqs` call in the suite omits
  `gap_minutes`, so they all still exercise the original unconditional loop).
- Real invocation, `reqs monitor_cc --gap 15 --since 2026-09-03 --until 2026-09-04`: multiple real
  sessions correctly show ONLY their header line (no qualifying gap); one real session shows a line
  reading `REQ 206 18:10:11  +89m` — near-exactly the milestone's own illustrative example
  (`REQ 206 18:10:11  +90m`), on real corpus data. `reqs proxy-tn-wrap` (no `--gap`) re-run and
  diffed byte-for-byte against the pre-`--gap` baseline from the local-time entry earlier the same
  day: identical. `--gap -5` rejected with `"--gap must be 0 or greater"`, exit 2.

## Relevant Symbols / Paths

- `_gap_lines`, `_req_line`, `render_reqs` (`src/dual_log_cli/render.py`)
- `_run_reqs`'s `--gap` validation (`src/dual_log_cli/__main__.py`)
- Ground truth for the near-exact-match real invocation:
  `src/logs/dual_log/api_requests_worker_25c51a2e_duallog-search-chars_1788525693_forwarded.jsonl`
- Area: this same area's `2026-09-04_reqs_command.md` and `2026-09-04_local_time.md` — the two
  entries this feature builds directly on top of
