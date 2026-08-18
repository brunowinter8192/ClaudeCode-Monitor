# Search-bar rollout — sub-milestone 5: workers pane reaches parity

**Date:** 2026-08-18 (continues the `pane_search` area — sub-milestone 1 extracted the shared
mechanics and retrofitted the proxy pane, sub-milestone 2 the main pane, sub-milestone 3 the
worker-proxy pane, sub-milestone 4 the tokens pane; this entry retrofits the workers pane,
`src/workers/worker_pane.py` + `src/workers/worker_format.py`)

## Scope

Workers pane only. First pane in the rollout with a genuine 2-level expand structure
(`worker_expand_states[name]` container → `worker_cache_expand_states[name][(turn_idx,
call_idx)]` nested calls) and the FIRST needing a real reconstruction strategy —
`worker_turns` is populated only for currently-EXPANDED workers (see `_refresh_workers_data`),
so finding matches across ALL workers requires force-parsing every listed worker's own JSONL on
Enter.

## Cost measurement (plan-gate requirement)

Measured `read_new_lines`+`parse_jsonl_lines`+`extract_cache_turns`+
`token_search.build_token_search_matches` against the 9 largest real session JSONLs available
(up to 6.3MB — standing in for a fully-loaded 9-worker fleet, same underlying parse primitives a
real worker JSONL uses): **parse 180ms + search 23ms = 203ms total for 9 files.**
Comfortably under the ~1s budget — proceeded with force-parse-every-worker-on-Enter as planned,
no fallback/simplified matcher needed.

## Three-tier match key design

Reused `panes.token_search.build_token_search_matches(query, turns, pane_width)`
**unmodified** per worker, wrapping its output with the worker name:
- **`name`** (bare str) — a match in the worker's own identity text (`name + purpose`). Reuses
  the exact shape `line_keys` already used for header/purpose rows.
- **`(name, 'turn', turn_idx)`** — a match in that turn's prompt line within worker `name`.
- **`(name, turn_idx, call_idx)`** — a match in that call's content. Reuses the exact 3-tuple
  shape `worker_format.py` already built for cache rows — critically keeps `('turn', idx)`
  -tagged keys OUT of `worker_cache_line_map` (mirrors the tokens-pane decision), since
  `_build_workers_output`'s `isinstance(key, tuple)` dispatch would otherwise misroute a
  `(name, 'turn', idx)` tuple into the click-map. Verified this never happens: turn-header lines
  coming back from `format_cache_tracker` always carry `key=None` in `line_keys` (confirmed in
  sub-milestone 4, unchanged) — `worker_format.py`'s own `zip` loop only ever produces `(name,
  ck[0], ck[1])` when `ck is not None`, so no `('turn', idx)`-shaped value can ever reach
  `line_keys` regardless of what `state.matches` (the flat, worker-tagged match list) contains.

## Composing with `format_cache_tracker` (sub-milestone 4's kwargs)

`format_workers_block` gained `search_match_set`/`search_current_key`/`search_query`
(worker-tagged-shape keys, same as `state.matches`). Two new helpers,
`_scope_matches_to_worker(matches, name)` / `_scope_current_key_to_worker(current_key, name)`,
strip the leading worker name and convert to `token_format`'s own shape (`('turn', idx)` /
`(turn_idx, call_idx)`), filtered to keys belonging to THIS worker only, before threading into
the EXISTING per-worker `format_cache_tracker(...)` call. `format_cache_tracker` then does 100%
of the collapsed-container-mark / expanded-substring-highlight work internally — zero new
highlighting code needed for the nested view. Only the worker's own header line needed new
embedding logic (unconditional container-mark + sentinel, mirroring `token_format`'s
turn-header treatment), added directly in `format_workers_block`.

Verified the cross-worker isolation directly (not assumed): a test with two independently
EXPANDED workers, only one matching, confirmed the non-matching worker's own rendered nested
view carries ZERO search-highlight codes anywhere — the scoping derivation genuinely prevents a
match belonging to worker A from bleeding into worker B's own view.

## The sentinel bug — third occurrence, plus a found-not-fixed collateral note

`_build_workers_output` hand-rolls its own zebra/hover loop exactly like `token_pane.py`;
`ZEBRA_BG_A == ''` applies identically. Same fix: embed with `_BG_RESTORE_SENTINEL` at
construction time (`worker_format.py`), resolve via `search_bar.resolve_bg_restore(line,
chosen_bg)` per row (`worker_pane.py`).

**Found, not fixed (pre-existing, unrelated):** `_build_workers_output`'s `LIGHT_RED_BG`
detection (`line.startswith(LIGHT_RED_BG)`) was ALREADY dead for nested cache-call rows before
this milestone — `format_workers_block` prepends a literal `"  "` (2 spaces) before every line
returned from `format_cache_tracker` (`all_lines.append(f"  {cl}")`), so a cc_broken row's
`LIGHT_RED_BG` prefix was never actually at string position 0. Switched to `in` anyway (same
low-risk generalization as the tokens-pane fix — provably equivalent to the old check whenever
no marker is present) but did not restructure the indent — out of scope, a pre-existing
characteristic of this pane's layout unrelated to search.

## Jump-to-match — respecting the dormant pane-level scroll

Per the survey's explicit framing: `worker_scroll_offset` (pane-level) is a deliberate
bottom-anchor fail-safe, never touched by jump-to-match. Design:
1. Every jump (Enter and every `n`/`N` step) auto-expands (`worker_expand_states[name] = True`)
   and auto-selects (`worker_selected_name` + `_write_selection`) the match's worker, uniformly
   across all 3 match levels (mirrors proxy's own jump-auto-expand).
2. For a turn/call-level match, computes `worker_scroll_offsets[name]` (the per-worker scroll
   the pane already fully supports) via a FRESH, self-contained `format_cache_tracker(turns,
   ..., nav_out=nav)` call made DIRECTLY at jump time — not through `format_workers_block`, and
   not from a cached last-render position.
3. The outer viewport stays exactly as today (bottom-anchored, no repositioning) — if the
   matched worker is scrolled off the top of a long list, that's the same pre-existing
   limitation that already prevents any other means of reaching it.

**Self-healing design, discovered as necessary during implementation (not merely anticipated):**
`_refresh_workers_data` clears `worker_turns` EVERY POLL TICK for any worker not yet
expand-gated. A match found at Enter-time for a worker the user hasn't jumped to yet would have
its cached turns evicted before a later `n`/`N` reaches it. Fix: `_jump_to_workers_match` ALWAYS
re-parses the target worker's JSONL fresh at jump time (cheap — bounded to one worker, same
~10-30ms/file measured above) and merges into `worker_turns[name]` immediately, rather than
trusting whatever `_workers_search_on_commit` cached at Enter-time. Verified directly: a test
simulates the poll-tick clear + un-expand between two jumps and confirms the second jump
re-populates `worker_turns` correctly rather than finding it empty.

Also self-healing against a vanished worker: if the matched name is no longer in the current
`workers` list (or its JSONL can't be resolved), the jump is an inert no-op — `worker_expand_states`
gets a harmless, never-read stub entry, no exception.

## Decision: no "worker-switch reset" analog — reasoned, not overlooked

Every prior pane (proxy/worker-proxy/tokens) tracks exactly ONE current session/worker, giving
a clean single reset trigger, mirrored identically across 3 prior milestones. This pane shows
ALL workers simultaneously — there is no equivalent single-item switch to reset search state on.
The self-healing jump design (above) makes this safe without a reset: a stale match referencing
a since-vanished worker just becomes an inert no-op instead of showing wrong data. Confirmed as
the right call given the pane's actual architecture, not a gap carried over from not thinking
about it — the reasoning is written up here specifically because every other milestone in this
area DID add a reset, so the absence here needs its own justification on record.

## `on_commit` closure — the one real deviation from the established wrapper pattern

Every prior pane's `on_commit` callback took only `state` (`search_bar.handle_search_input`'s
generic signature). This pane's `_workers_search_on_commit` genuinely needs the current tick's
`workers` list and `project_filter` too (to force-parse and to write the IPC selection file) —
neither of which `search_bar.py` itself has any business knowing about. Solved with a closure at
the call site (`_handle_workers_search_input`): `on_commit = lambda state:
_workers_search_on_commit(state, workers, project_filter)`, passed into
`search_bar.handle_search_input`'s `on_commit` parameter, which only ever calls it with `state`.
No change to `search_bar.py` needed — its `on_commit` contract already accepts any callable
taking a single `state` argument.

## Verification

- **76/76** new regression checks (`dev/pane_search/p7_workers_pane_parity_test.py`) against
  real `src.workers.worker_pane`/`src.workers.worker_format` functions (via
  `importlib.import_module`, real calls — not mocked), including REAL throwaway JSONL fixture
  files (`find_worker_jsonl` monkeypatched only at the tmux-session→path resolution boundary;
  `read_new_lines`→`parse_jsonl_lines`→`extract_cache_turns` run unmocked): the full mechanics
  suite (drag-select, deletion, `n`/`N`, Esc, reverse-video), the 2-row header + shifted freeze
  badge (still clickable at its new row), worker-level and call-level matches with explicit
  cross-worker leak checks, the sentinel repro (folded into the match tests, which already
  exercise the exact code path), the `LIGHT_RED_BG` collateral-fix regression guard, and three
  dedicated jump-to-match tests (dormant-scroll-untouched, self-healing-stale-turns,
  vanished-worker-noop).
- **48/48** `p2`, **62/62** `p3`, **77/77** `p4`, **77/77** `p5`, **78/78** `p6` — all
  prior-milestone suites re-run clean (this milestone touched only `worker_pane.py`,
  `worker_format.py`, one new dev/ test file, and DOCS.md).
- **35/35** `p1_worker_selection_click_probe`, **37/37** `p2_copy_click_probe`, **32/32**
  `p3_button_click_probe` — all re-run clean WITHOUT modification (every existing workers-pane
  click test discovers its own rows dynamically via `worker_line_map`/`_worker_header_regions`
  rather than hardcoding row numbers, confirmed before implementing — unlike the worker-proxy
  pane's wrap-straddle test in sub-milestone 3, no test-side fix was needed here for the row
  shift).
- **14/14 byte-identical** via `dev/proxy_dual_log/A_render_refactor_proof.py --mode verify` —
  confirms zero impact on `proxy_display/` (untouched this milestone).
- `dev/display/test_hover_map.py`: 40/40 of the tests that don't hit the pre-existing, unrelated
  `ImportError: _parse_log_file` (confirmed again this milestone — `parser.py` untouched, same
  finding first flagged in the sub-milestone 3 entry, still unaddressed, out of scope for every
  milestone in this rollout).
- Import-level sanity: `src.workers.worker_pane`, `src.workers.worker_format` import cleanly
  post-migration (`ast.parse` + real `importlib.import_module`, no mocking).
- **Not verified as of this entry:** live tmux/terminal visual rendering of the workers pane's
  bar and 2-row header, the `/` focus hotkey's live dispatch (a one-line branch inside
  `run_workers_loop`'s while-loop, not unit-tested at the loop level — consistent with every
  prior milestone in this area), and real trackpad drag-select. Standard "user visual check"
  gate, same as every prior entry in this area.
