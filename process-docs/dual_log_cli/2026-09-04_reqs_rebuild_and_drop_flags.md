# `reqs --rebuild`/`--drop` — usage-driven REQ filtering, 2026-09-04

Continues this area's `reqs`/`--gap`/`--merged` line (all introduced earlier the same day). Both
new flags read the SAME per-request CR/CC (`cache_read_input_tokens` / `cache_creation_input_tokens`)
`msgs` already resolves via `usage.build_usage_by_flow` — nothing new is joined against CC's
transcript store, only a new filter/render layer over the existing REQ chain.

## What each flag selects

- `--rebuild`: CC(n) > CR(n) — the request's own cache WRITE outweighed what it read back, the
  signal that something upstream had to be rebuilt from scratch rather than served from cache.
- `--drop`: CR(n) < CR(n-1) + CC(n-1) — the PREVIOUS request's total cached amount (what it read
  plus what it just wrote) was NOT fully read back by n, meaning the cache cooled between the two.
  Exactly equal does NOT qualify — the boundary is strict `<`, not `<=`. "previous" is whichever
  request sits immediately before n in the chronological sequence the render is already building:
  the same session's own previous REQ by default, or the merged chain's previous REQ (any session)
  under `--merged`. REQ 1 of a chain — position 0, not "any REQ numbered 1" — has no predecessor
  and never qualifies for `--drop`; a session's own REQ 1 landing elsewhere in a `--merged` chain
  DOES have one and is evaluated normally.

Both flags combine with AND (a REQ must pass every active one), and a REQ whose own usage — or,
for `--drop`, its predecessor's — never resolved is skipped under either flag, never shown
tail-less. Every printed line under either flag carries a `"  CR c  CC c"` tail (`_fmt_usage`,
same digit grouping `msgs` uses); `--drop` additionally appends `"  −N"` (`N = CR(n-1)+CC(n-1) −
CR(n)`, U+2212 like every other `_delta_tail`-family figure).

## Combining with `--gap`: filter the candidate set, not the pairing

The milestone's exact wording — "apply the flags as a filter on the lines --gap would print,
before-line included" — settled the design question of whether `--gap M --rebuild` should mean
"gap-qualifying pairs, restricted to ones that are ALSO a cache rebuild" (pairing stays primary) or
"the exact set of lines `--gap M` alone would print, each one independently re-checked against
`--rebuild`/`--drop`" (filtering is a second pass over that same candidate set). The wording picked
the second reading, so `_bracket_gap_lines`' selection half was split out into a new pure function,
`_bracket_gap_positions(entries, gap_minutes) -> {position: gap_tail}`, reused by both the plain
`--gap` renderer (unchanged output) and the new `_rebuild_drop_gap_lines`, which walks that SAME
position set and applies `_rebuild_drop_qualifies` to each — importantly against `entries[position
- 1]`, the candidate's own chronological predecessor, NOT whichever entry the gap pairing happened
to bracket it with (the two can differ: a `--drop` predecessor is always one position back, while
the qualifying GAP can pair a candidate with an entry several positions away).

## Shared entry shape, extended rather than duplicated

`_merged_entries`/`_gap_lines` already built `[(dt, marker, tag), …]` chronological sequences for
`--merged`/`--gap`. Both were extended to `[(dt, marker, tag, usage), …]` — a 4th slot, `None` when
the caller has no usage map (the plain/`--gap`-only paths, unaffected) or an actual `(cr, cc)` pair
when one does. A new `_entries_for_session` factors the per-session half of `_merged_entries`'s own
walk (dt-parse, drop-on-unparseable, usage lookup) so a single-session `--rebuild`/`--drop` run
(no `--merged`) builds the identical shape without going through the cross-session merge/sort at
all. `_rebuild_drop_lines` (no `--gap`) and `_rebuild_drop_gap_lines` (`--gap` combined) are the
only two consumers that ever read the 4th slot; every pre-existing renderer keeps ignoring it,
which is what keeps the plain and `--gap`-only outputs byte-identical to before this feature.

## `_run_reqs` never joins the transcript store unless asked

`usage.build_usage_by_flow` does a scoped but non-trivial `~/.claude/projects/` search per session.
`_run_reqs` now builds `usage_by_stem = {stem: build_usage_by_flow(session, boundaries)}` — one
call per loaded session — ONLY when `args.rebuild or args.drop`; a plain `reqs`/`reqs --gap`/`reqs
--merged` run passes `usage_by_stem=None` straight through, so it does zero extra I/O and takes the
exact pre-existing code paths in `render.py` (the `filtering` flag there gates on `rebuild or drop`,
same condition).

## Verification

- Extended `dev/dual_log_cli/tests/test_reqs.py` with hand-built `usage_by_stem` maps (no real
  transcript store touched): `--rebuild` keeping only the CC>CR, resolved REQ and skipping both a
  CC<CR one and an unresolved one; `--drop`'s exact-equal boundary (CR(n) == CR(n-1)+CC(n-1)) NOT
  qualifying, immediately followed by a genuine shortfall case that does, carrying `"  −100"`; REQ 1
  never qualifying for `--drop` even with resolved usage; a `--merged --drop` case where session B's
  own REQ 1 qualifies against session A's usage as its cross-session predecessor; a REQ absent from
  the usage map entirely producing header-only output under either flag; `--rebuild --drop` together
  excluding a REQ that passes `--rebuild` alone but fails `--drop`'s exact-equal boundary (AND
  semantics); and a case confirming a passed-but-unused `usage_by_stem` leaves the neither-flag
  output byte-identical. Suite now 28/28 (was 14/14 before this session's additions — the file also
  already covered `--gap`/`--merged`/`filter_by_family` from earlier same-day work).
- Full re-run of all 11 suites in `dev/dual_log_cli/tests/`: all passing, confirming the
  `_bracket_gap_lines`/`_merged_entries`/`_gap_lines` refactors changed nothing observable for the
  pre-existing `--gap`/`--merged`/`msgs`/other-command behavior.
- Real invocation, `reqs monitor_cc --since 2026-09-04 --worker --merged --rebuild`: 5 sessions
  merged, 12 REQs qualifying, each line carrying its tag and `"  CR c  CC c"` tail — including
  `REQ 206 18:10:11  duallog-search-chars  CR 0  CC 501,138`, the exact example line the milestone
  named. `--drop` and `--rebuild --drop` on the same scope produced narrower, `−N`-tailed subsets as
  expected; `--merged --gap 5 --rebuild` combined both filters onto the same two REQs `--gap 5
  --merged` alone already found, now additionally carrying the usage tail. Plain `reqs --merged` (no
  new flags) re-diffed against its pre-this-session output: byte-identical.

## Relevant Symbols / Paths

- `_rebuild_drop_qualifies`, `_usage_tail`, `_rebuild_drop_lines`, `_rebuild_drop_gap_lines`,
  `_bracket_gap_positions`, `_entries_for_session`, `_merged_entries`, `_gap_lines`,
  `_bracket_gap_lines`, `_req_line`, `render_reqs`, `render_reqs_merged` (`src/dual_log_cli/render.py`)
- `_run_reqs`'s `usage_by_stem` construction and the `--rebuild`/`--drop` argparse flags
  (`src/dual_log_cli/__main__.py`)
- Area: this same area's `2026-09-04_reqs_gap_flag.md` and `2026-09-04_reqs_merged_flag.md` — the
  `--gap`-candidate-set and merged-chain-predecessor mechanics this feature reuses rather than
  reimplements; `process-docs/cache/` for the broader prompt-cache-cooling context both flags are
  reading a symptom of.
