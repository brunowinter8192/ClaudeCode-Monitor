# `reqs --merged` — one chronological chain across a project's sessions, 2026-09-04

Continues this area's `reqs`/`--gap` line (both introduced earlier the same day). `--gap` finds
slow stretches within ONE session; `--merged` exists because "within one session" is the wrong
scope for what `--gap` is actually trying to measure — the prompt cache.

## Why per-session gap evaluation can be wrong in both directions

The prompt cache hangs on the shared system/tools prefix every worker of a project sends on its
first request. Once warm, ANY request from ANY session of that project — not just the one that
warmed it — keeps it warm for every other. Evaluating `--gap` per-session can therefore:

- **Hide a real cache-cooling gap.** Session A's own last request was 10 minutes ago (looks fine
  in isolation), but no OTHER session of the project has sent anything in the last 40 minutes —
  the cache is actually cold, and a per-session view of A alone never shows it.
- **Manufacture a false one.** Session A's two requests are 95 minutes apart — looks like a
  qualifying gap in isolation — but session B (same project) sent a request 30 minutes into that
  window. The cache was kept warm by B the entire time; A's own 95-minute gap never mattered.

`--merged` fixes both by moving the unit of "consecutive" from "within one session" to "across
every session in scope" — exactly the scope the cache itself operates at.

## No bridging-specific code — it falls out of "pair global neighbors"

The milestone named two required behaviors: a within-session gap bridged by another session's
request must NOT qualify, and a genuine cross-session gap must. Neither needed a dedicated rule.
`_bracket_gap_lines` (renamed/generalized from the single-session `_gap_lines` this same day)
already only ever compares CONSECUTIVE entries in whatever list it is given. Feed it one session's
own markers and "consecutive" means "next in that session"; feed it `_merged_entries`' merged,
globally-sorted list and "consecutive" means "next in time across every session in scope" — the
exact same walk, exact same threshold/floor/`printed-once` logic, just a different `entries` list.
A same-session gap that another session's request lands inside is automatically replaced by two
SMALLER cross-session gaps in the merged sequence (the bridging request's neighbors are no longer
each other); a gap with nothing between two sessions' requests is automatically evaluated as one
pair, exactly like a same-session gap would be. Both are just what "neighbor" means once the
comparison unit changes — nothing else had to change.

## Refactor along the way, not required by the milestone but low-risk and DRY

`_req_line` gained a `tag` parameter (alongside the existing gap `tail`, renamed `gap_tail` for
clarity) so both the tagged (`--merged`) and untagged (per-session) paths share one line-builder.
`_gap_lines` (per-session) now delegates to the SAME `_bracket_gap_lines` core `render_reqs_merged`
uses, passing an empty tag for every entry — re-verified byte-identical against the full existing
`--gap` test suite (17/17, unchanged) before adding anything new. One documented, deliberate
micro-behavior change from this consolidation: the OLD per-session `_gap_lines` skipped only the
PAIRS touching a marker with an unparseable timestamp (leaving its two neighbors uncompared to
each other); the shared core filters such markers out BEFORE pairing (required for `--merged`,
since a chronological merge needs a sort key), so the two valid neighbors either side of a bad one
now get compared directly instead of neither being compared at all. Real dual-log timestamps are
never malformed (write-side guarantee, `datetime.now(timezone.utc)`), so this is a purely
theoretical case with zero observed occurrences — not a regression on anything that matters.

## Verification

- Extended `dev/dual_log_cli/tests/test_reqs.py` with the three cases the milestone named: merge
  order across two sessions with INTERLEAVED timestamps (strict chronological order proven, each
  line's tag correct); a 95-minute within-session gap bridged by another session's request 30
  minutes in — construct to fail BOTH resulting sub-gaps (30m, 65m) against a 90-minute threshold —
  zero qualifying lines, header only; a genuine 100-minute cross-session gap with nothing between —
  qualifies, after-REQ carries both its tag and `+100m`. Suite now 20/20 (was 17/17).
- Full re-run of all 11 suites in `dev/dual_log_cli/tests/`, all passing — confirms the `_gap_lines`
  refactor changed nothing observable for the pre-existing per-session `--gap` behavior.
- Real invocation, `reqs monitor_cc --merged --gap 20 --worker`: real cross-session output
  including `REQ 206 18:10:11  duallog-search-chars  +89m` — the SAME real REQ/gap the earlier
  `--gap`-only entry already found, now additionally tagged. `reqs proxy-tn-wrap` (no `--merged`)
  re-diffed byte-for-byte against the pre-`--merged` baseline: identical. `--merged --gap -1`
  rejected with the same `"--gap must be 0 or greater"`, exit 2, as before `--merged` existed.

## Relevant Symbols / Paths

- `render_reqs_merged`, `_merged_entries`, `_session_tag`, `_bracket_gap_lines`, `_req_line`
  (`src/dual_log_cli/render.py`)
- `_run_reqs`'s `--merged` dispatch (`src/dual_log_cli/__main__.py`)
- Ground truth for the real invocation:
  `src/logs/dual_log/api_requests_worker_25c51a2e_duallog-search-chars_1788525693_forwarded.jsonl`
- Area: this same area's `2026-09-04_reqs_gap_flag.md` — the feature `--merged` generalizes
