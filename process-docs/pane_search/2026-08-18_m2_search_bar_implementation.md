# Proxy pane search — Milestone 2: permanent search bar implementation

**Date:** 2026-08-18 (continues the `pane_search` area started by the M1 cost-probe entry)

## Scope

Implemented the permanent row-1 search bar for the PROXY pane only (`src/proxy_display/pane.py`
path) — always-visible query field + match counter (`search: <query> N/M`), click-or-`/` to
focus, Enter to (re)run, `n`/`N` to jump matches, Esc to clear (bar itself never hides). Worker
proxy pane, main pane, and all other tabs explicitly out of scope for this milestone.

## Plan-gate measurement (required before writing feature code)

Per the milestone's condition: measure the real-render-based matching cost on the real M1 log
before committing to the design; if it exceeded ~1s, stop and report rather than silently
switching strategy. Measured on the same 190-entry / 6.8MB forwarded log M1 used:
render-force-expand-all-entries pass (`_render_req_expanded` called for every entry regardless of
its actual expand state) = 14.9-17.2 ms; full search-index build (render + ANSI-strip +
substring-scan for query `'error'`, 19 matches found) = 21.4-25.2 ms. Combined with the one-sweep
reconstruction (~35-37 ms, consistent with the M1 entry's measurement), total Enter-triggered cost
= **~55-60 ms** for 190 entries — well under budget. Proceeded with the real-render-based matcher
as planned; no fallback/simplified matcher was needed.

## Bug found during investigation: `_fwd_req_idx` is not a stable identifier

While designing how to merge one-sweep results back into `proxy_entries`, found that
`_parse_forwarded_log` stamps `entry['_fwd_req_idx'] = req_idx`, a counter reset to 0 at the
START of every call — unique only WITHIN one incremental parse batch, not across a polling
session. `_lazy_load_messages_forwarded` (the pre-existing expand-click feature) matched on this
value while replaying from byte 0, which is wrong whenever a session has had ≥2 incremental poll
batches with new lines in each (essentially always, given the 500 ms poll tick).

Verified concretely: split a real forwarded log into two batches (a truncated-file first call +
a second call continuing from that byte position, same accumulator persisted — exactly mirroring
`pane.py`'s real polling pattern), then compared `_lazy_load_messages_forwarded`'s output against
ground truth (a fresh byte-0 parse matched by `flow_id`). Result: **158/158 out-of-window
entries from the second batch loaded the WRONG request's content.** This was a live, pre-existing
production bug, not something this milestone introduced — but it directly threatened the "expand
a match, see the highlighted line" requirement for exactly the entries search is most useful for
(out-of-window ones).

`flow_id` (from the forwarded_delta line) was confirmed globally unique and always populated
(189/189 unique, 0 empty, vs `request_id` which was always `""`) on the same real log. Fixed
`_lazy_load_messages_forwarded` to stop-on-`flow_id`-match instead of counting `req_idx ==
target_idx` — same call signature, zero changes needed at either caller (`pane.py`,
`worker_proxy_pane.py`). Bundled into this milestone rather than deferred, per explicit
confirmation that search correctness depended on it and it was a live bug regardless. Verified
post-fix: 0/158 mismatches on the same 2-batch scenario, and again via a self-contained synthetic
fixture in the regression suite (portable, no dependency on any one dev machine's real log).

## Design decisions

- **Match granularity: per-entry, via the REAL render function.** `search.build_search_matches`
  calls `render_turn._render_req_expanded` force-expanded for every entry (ignoring that entry's
  own `('req', idx)` toggle, but respecting nested fields/beta/tools-desc sub-toggles as currently
  set) and substring-checks the ANSI-stripped output. Chosen over a duplicated plain-text
  serializer specifically to guarantee "exactly what that request's expanded view shows" can never
  diverge from `render_sections.py`/`render_messages.py`'s many branches (use_dual vs legacy,
  inline vs stacked, flow-scoped span lookups) — a hand-written matcher would need to track every
  one of those branches independently and would drift the moment any of them changed.
- **Header stays marked on an expanded match** (vs. only the inner line) — decided uniform:
  keeps orientation when scrolling inside a long expanded request, and is the simpler
  implementation (embed the marker whenever `entry_idx` is a match, independent of expand state).
- **Search-highlight priority: `hover > SEARCH_CURRENT/MATCH_BG > DIM_YELLOW_BG > DIM_GREEN_BG >
  collision > zebra`.** Hover (transient mouse feedback) stays on top always; search sits directly
  below since it's the user's explicit, just-committed query intent — outranks the passive
  structural strip/inject annotations and the rare collision marker.
- **Reused the existing `SEARCH_MATCH_BG`/`SEARCH_CURRENT_BG` constants** (already present in
  `constants.py` for the main pane's own search bar, `core/monitor_display.py`) rather than adding
  proxy-specific colors — one visual "search" language across panes.
- **Scroll-jump reuses `_proxy_just_expanded`/`item_positions` verbatim** (the same mechanism
  expand-click auto-scroll already used) rather than a new scroll code path — `('req', entry_idx)`
  is always a valid `item_positions` key regardless of expand state, so one anchor works for both
  collapsed and expanded matches.
- **Enter always re-runs the full one-sweep + match rebuild**, not gated on query-unchanged (the
  main pane's `core/monitor_display.py` search bar DOES gate on this). Chosen because the proxy
  one-sweep is cheap enough (~55-60 ms measured) that always re-running picks up new requests that
  streamed in since the last Enter, matching the "(re)runs the search" wording literally.
- **`_resolve_prev_same_family` extracted** from what was inline logic in `render_turn_expanded`
  into a named module-level function — reused by both the real render loop and `search.py`'s
  matcher, so the two can never compute a different `prev_same` for the same entry.

## Verification

- **26/26** integration-level regression checks (`dev/pane_search/p2_search_feature_regression_test.py`)
  against real `pane.py`/`format.py`/`render_turn.py`/`search.py`/`forwarded_parser.py` code
  (via `importlib.import_module`, not mocked) with synthetic entries: bar renders at row 1
  (empty + populated query), line_map/copy_rows shift correctness, collapsed-hit marks only the
  REQ header, expanded-hit marks header AND the specific inner line, `n`/`N` wrap ordering in both
  directions (+ no-op with zero matches), Esc clears query/matches/focus without hiding the bar,
  scroll-jump clamp idempotency across repeated renders, and the `flow_id` lazy-load fix against a
  self-contained synthetic 2-batch fixture.
- **32/32** `dev/click_ui/p3_button_click_probe.py` — its proxy-pane test was rewritten for the new
  header+shift contract (the prior version asserted the OPPOSITE: no header, row 1 = body); all
  pre-existing warnings/workers checks in the same file passed unaffected.
- **14/14 byte-identical** rendering via `dev/proxy_dual_log/A_render_refactor_proof.py`, with the
  baseline captured from the code as it stood BEFORE this milestone's changes and verified against
  the code AFTER — confirms the `_resolve_prev_same_family` extraction and the new optional
  search params threaded through `format_proxy_block`/`render_turn_expanded` introduced zero
  rendering regressions for any of the 14 existing fixture cases (branch1/2, dual formats, tools,
  system blocks, standalone haiku, copy feedback, hover/scroll, collision, expand fixpoint).
- Additional ad-hoc integration check (throwaway script, not committed) against the real gitignored
  190-entry M1 log: windowed parse → one-sweep reconstruction → merge by `flow_id` → search match
  build → collapsed-render header marking → expanded-render header+line marking → flow_id lazy-load
  fix, all confirmed correct end-to-end on real production-shaped data, not just synthetic
  fixtures.
- **Not verified as of this entry:** live tmux/terminal visual rendering of the search bar and
  highlight colors — remains a user visual check, the last verification gate for this feature.
