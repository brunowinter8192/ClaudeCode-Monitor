# 2026-07-30 — Milestone 3: pane-chrome buttons (workers freeze, proxy undo, warnings refresh)

## Problem

Three pane-level (not per-row) keyboard-only actions remained: workers pane's `f` (toggle
freeze), proxy pane's `u` (undo last expand/collapse), warnings pane's `r` (force refresh). Task
explicitly framed these as belonging in the pane's header/chrome, following the button-region
pattern already established twice (`gpu_pane`/`news_pane`'s `_button_regions`, milestone 1's
`_worker_proxy_header_regions`).

## Per-pane header-infrastructure reality (drove three different implementation shapes)

The three panes had three DIFFERENT starting points for "where does chrome live":

- **warnings**: already had a real fixed header (`_format_warnings_header`, row 1, overdrawn
  after body print) — the button just needed to be added to existing infrastructure.
- **workers**: has NO fixed header at all — the "Workers [LIVE]/[FROZEN]" line is `all_lines[0]`,
  part of the SAME scrollable content as everything else (default scroll is bottom-anchored, so
  with many workers this line can scroll out of view — a pre-existing characteristic, not
  something this milestone was asked to fix, per "don't redesign layout"). The freeze badge
  already existed and already read `[LIVE]`/`[FROZEN]` — no new visible text was needed, only a
  region registration gated on whether that specific line survived viewport clipping this render.
- **proxy**: had NO header of any kind — every row is body content, no title, no chrome line.
  Adding a button here meant introducing a header/body split from scratch, closely mirroring
  `worker_proxy_pane.py`'s already-battle-tested pattern (including its documented `-1`
  viewport-math gotcha: `format_proxy_block`'s internal `viewport_lines = max(1, pane_height - 1)`
  means the caller-side clamp must use `max(1, content_height - 1)`, not `content_height` itself,
  or scroll state silently drifts one line short — the exact bug class `worker_proxy_pane.py`'s
  own DOCS already documents having been found and fixed once).

## Width-guard philosophy: no wrap, unlike milestone 1

Milestone 1's header markers (multiple worker names concatenated on one line) wrap-SPLIT across
row boundaries rather than dropping a marker. This milestone's task explicitly pointed at
milestone 2's copy-symbol convention instead ("no room = no region, not wrap"), since each of
these three buttons is a single short label, not a multi-marker line. All three
(`_format_proxy_header`, `_format_warnings_header`, `format_workers_block`'s freeze region) use
the same "fits pane_width or is omitted entirely" gate — no wrap-splitting code. For the two
brand-new buttons (proxy `[undo]`, warnings `[refresh]`), "omitted" means BOTH the button text and
the region disappear together when there's no room. For the workers freeze badge, only the REGION
is gated — the badge text (`[LIVE]`/`[FROZEN]`) is pre-existing content that always renders
regardless of my changes; narrowing its clickability at extreme widths doesn't touch what was
already there.

## State-reflecting labels

- Workers freeze: the existing `[LIVE]`/`[FROZEN]` text already encodes state — no new text
  needed, just made it click-target-aware.
- Proxy undo: color-coded (`WHITE` when `_proxy_undo_stack` is non-empty, `DIM` when empty) but
  ALWAYS registered as a clickable region regardless of stack state — clicking an empty-stack
  button is a safe no-op via `_undo_proxy_expand()`'s own `if not _proxy_undo_stack: return False`
  check, identical to what pressing `u` already does. No special-casing needed in the click
  handler for the empty case.
- Warnings refresh: stateless action (not a toggle), so no state-dependent label was needed —
  just an always-present `[refresh]` button next to the pre-existing `[r]efresh · last: ...` text.

## Collision resolution (deliverable 5)

All three check their header-region dict FIRST inside the `button == 0` branch, before any
existing row-based logic (`proxy_line_map`, `error_line_map`, `worker_cache_line_map`/
`worker_line_map`). This is safe by construction, not just by ordering: header regions live on
phys_row 1 (warnings, proxy) or on whichever row the freeze line happens to render at (workers,
computed per-render from actual viewport position) — and none of the body line-maps ever populate
an entry at that exact row (warnings: `header_offset = 2` hardcodes body starting at row 2, so row
1 is structurally unreachable by `error_line_map`; proxy: body content starts at
`header_lines + 1` after the new shift; workers: the freeze-badge row is `all_lines[0]`, and
worker rows/cache rows only ever start after it). Checking header-first is therefore both correct
(no valid competing claim on that row) and efficient (short-circuits before the more expensive
row-map lookups).

## Signature changes forced by the design

- `worker_pane._handle_workers_mouse`: gained a `frozen: bool` param and changed its return type
  from bare `bool` to `(input_changed, updated_frozen)` — mirrors `_handle_workers_key`'s existing
  `(changed, frozen)` contract exactly. Every internal `return True`/`return False` became
  `return True, frozen`/`return False, frozen`.
- `proxy.pane._build_proxy_output`: changed return type from `str` to `(output, header)` —
  `run_proxy_loop` now overdraws the header after the body print, the same pattern
  `warnings_pane.py` and `worker_proxy_pane.py` already use.
- `warnings_render._format_warnings_pane`: its `last_refresh_ts: float` param was replaced with a
  caller-supplied `header: str` — `_format_warnings_header` is now called exactly ONCE per render
  (inside `_build_warnings_output`) and its result threaded both into the body-render call and
  into the overdraw print, instead of being independently recomputed at each site (which, once the
  header started taking `pane_width`/`regions_out`, would have silently produced two DIFFERENT
  header strings — the overdraw call would have stripped the button back off right after the
  initial print showed it).

These three signature changes required updating milestone 1 and 2's existing probes
(`p1_worker_selection_click_probe.py`, `p2_copy_click_probe.py`) at their `_handle_workers_mouse`
call sites and one `_format_warnings_pane` call site — both re-verified green (35/35, 37/37) after
the fix, confirming the milestone-1/2 behavior itself was untouched, only the call shape changed.

## Verification

`dev/click_ui/p3_button_click_probe.py` — no live tmux/terminal; seeds real module state per pane,
drives the real render functions (including a synthetic proxy entry set matching
`dev/display/test_hover_map.py`'s `_make_entry` shape, to exercise the new header/body split
end-to-end, not just the button in isolation), dispatches synthetic clicks through the real
`_handle_*_mouse` functions, compares against the real key path. **24/24 checks passing on the
first full run** (all three panes: region presence, click/key parity, state-reflecting label
before click, no collision with pre-existing row clicks, width guard). Full regression suite
re-run clean: milestone-1 probe 35/35, milestone-2 probe 37/37, `pane_error_log` exception-guard
suite 52/52 (exercises `run_proxy_loop`/`run_workers_loop`/`run_warnings_loop` directly with
injected exceptions — confirms the loop-shape changes in all three panes didn't disturb the
exception guard), `dev/display/test_hover_map.py` 40/40 (its one pre-existing crash, a dead
`_parse_log_file` import, reproduces identically and is unrelated to this work).

Not verified: a real mouse click through an actual terminal emulator against a live tmux pane —
same boundary as milestones 1 and 2, needs a human click-test.

## Scope note

Deliberately left untouched: gpu/news panes (milestone 4); the workers pane's freeze-badge
scrolling-out-of-view behavior at default scroll with many workers (pre-existing, not a
regression); the pre-existing main-pane tool_call copy-row width-guard gap noted in milestone 2
(unrelated to this milestone, still not touched).
