# 2026-07-30 — Milestone 2: copy-by-click in main/tokens/warnings/workers panes

## Problem

Four panes exposed "copy the entry under the cursor" only via the `y` key: main
(`core/monitor.py`, event buffer rows), tokens (`panes/token_pane.py`, API-call rows), warnings
(`panes/warnings_pane.py`, tool-error rows), workers (`workers/worker_pane.py`, worker rows AND
expanded cache-call rows). The reference pattern (`⎘` symbol, right-aligned, width-guarded, `✓`
flash) already existed twice — `proxy_display/pane.py` + `render_turn.py` (button-region style)
and `core/monitor_display.py`'s pre-existing tool_call REQUEST/RESPONSE split (added earlier,
commit `c7d47b8`, independent of this milestone).

**Scope correction on main pane:** the task table framed main pane as "y-key only", but
`monitor_display.py` already had a working `⎘`-click for `tool_call` events specifically
(`_main_copy_rows`, pre-existing). The gap was narrower than framed: every OTHER event type
rendered in the main pane (`user_prompt`, `thinking`, `system_message`, etc.) had no click
affordance — only `y` (via `resolve_parent_key` + `serialize_main_event(idx)`, default
`part='all'`) could copy them. Extended coverage to those, left the tool_call branch untouched.

## Shared helper

`utils.append_copy_symbol(line, copy_sym, pane_width)` — extracted the pad/width-guard math
common to all four target sites (the two pre-existing reference implementations,
`proxy_display/render_turn.py`'s `_build_req_header_line` and `monitor_display.py`'s tool_call
branch, were deliberately left untouched using their own inline math — this shared helper is only
used by the NEW call sites this milestone added: `monitor_display.py`'s new elif branch,
`format/token_format.py`, `panes/warnings_render.py`, `workers/worker_format.py`).

## Per-pane copy-row population + collision handling

- **tokens**: single key type `(turn_idx, call_idx)` — one row per API call. `format_cache_tracker`
  gained an optional `copy_feedback` param (default `None`, gated behind `if copy_feedback is not
  None:`); `token_pane.py`'s `_build_tokens_output` does substring-detection row registration
  (`'⎘' in line or '✓' in line`), mirroring `proxy_display.format._apply_row_backgrounds`.
  `_handle_tokens_mouse` checks the copy region (`col >= pane_width-2 and row in
  cache_copy_rows`) BEFORE the pre-existing expand-toggle.
- **warnings**: single key type (int error idx). Same pattern, plumbed through
  `_format_warnings_pane`'s existing `pane_width` param (no new param needed for that).
- **workers**: TWO key types sharing one flat `worker_copy_rows: Set[int]` (phys_row is unique
  regardless of kind, so no dispatch needed at registration time) — worker-header rows (str key)
  and expanded cache-call rows (3-tuple key). `format_workers_block` gained `copy_feedback`
  (mixed-key flat dict); a new `_worker_cache_copy_feedback(copy_feedback, name)` helper filters
  it down to a per-worker `(turn_idx,call_idx)` sub-dict before handing it to
  `format_cache_tracker` (needed because `format_cache_tracker`'s own key format is a 2-tuple, and
  multiple workers can be expanded simultaneously with independently-indexed turns/calls — passing
  the flat 3-tuple-keyed dict straight through would never match, and a naive same-index match
  across workers would cross-contaminate the ✓ flash). `_handle_workers_mouse` checks the copy
  region FIRST on both the `worker_cache_line_map` and `worker_line_map` branches, ahead of
  milestone-1's select/expand-toggle logic — verified this doesn't touch selection state on a copy
  click, and a normal (non-edge) click still selects+expands.
- **main**: no new row-registry needed — reused the pre-existing `_main_copy_rows` dict shape
  (`phys_row → (event_idx, part)`), just added a third `part` value `'all'`.
  `_handle_main_mouse`'s dispatch (`_main_copy_rows.get(row)` → `serialize_main_event(event_idx,
  part)`) was already fully generic over `part`, so ZERO changes were needed in `monitor.py`.

## Two pre-existing bugs found while implementing parity (both fixed, in scope — see below)

1. **`warnings_render._serialize_warnings` int/tuple key mismatch.** `error_line_map` stores a
   bare `int` (matches `error_expand_states`' key type, matches what `resolve_parent_key` returns),
   but `_serialize_warnings` checked `isinstance(key, tuple) and len(key) == 2` — a leftover from
   before a refactor that removed a second `zero_results` key kind and simplified the map to bare
   ints, without updating the serializer. Confirmed via git history
   (`_serialize_warnings(key, tool_errors, zero_results)` → `_serialize_warnings(key,
   tool_errors)`). Result: `y` in the warnings pane silently copied `''` for every row, unnoticed
   until this milestone's click-vs-`y` parity check made the always-empty output visible. Fixed by
   changing the isinstance check to `int`.
2. **`worker_pane._handle_workers_key`'s `y`-resolution order.** The two-tier fallback
   (`resolve_parent_key(worker_line_map, hover_row)`, then `worker_cache_line_map` only if the
   first returned `None`) looked correct but `resolve_parent_key` walks backward to row 1 — it
   ALWAYS finds the owning worker's header/purpose row above any of that worker's cache-call rows,
   so the `worker_cache_line_map` fallback was dead code. Hovering an expanded cache-call row and
   pressing `y` always copied the parent worker's identity summary, never the specific call.
   Fixed with a new local resolver, `_resolve_workers_hover_key`, that compares which map's
   nearest-ancestor row is numerically closer to `hover_row` and prefers that one — correct for
   both a cache-row hover (picks the cache tuple) and a subsequent worker's own header hover after
   a prior worker's expanded cache block (picks the worker name, not the prior worker's trailing
   cache row).

Both were necessary infrastructure for deliverable 3 (exact click/`y` parity) — without them, the
"parity" a naive implementation would produce was parity between two equally-broken paths, not a
working copy feature. Not fixed: a pre-existing, out-of-scope gap in the SAME tool_call branch of
`monitor_display.py` this milestone left untouched — it registers `_main_copy_rows` unconditionally,
even when the symbol doesn't fit at a narrow `pane_width` (an invisible hit zone at extreme
widths); flagged, not touched, since deliverable 6 forbade disturbing existing mouse handling and
it predates this milestone.

## Verification

`dev/click_ui/p2_copy_click_probe.py` — no live tmux/terminal; seeds real module globals per pane
with synthetic data, drives the real render functions, monkeypatches `copy_to_clipboard` per
module to a capturing stub (no OS clipboard dependency), dispatches synthetic clicks through the
real `_handle_*_mouse` functions, and compares the captured string against the real `y`-key path
(`_handle_*_key` / the main-loop's inline `resolve_parent_key`+`serialize_main_event` sequence) —
nothing hardcoded, both sides run the real serializer. **37/37 checks passing**: copy-row
coverage + click/`y` parity for all four panes (13 main incl. pre-existing tool_call split, 5
tokens, 7 warnings incl. the bug-fix regression guard, 9 workers incl. both row kinds and the
milestone-1 no-collision checks), plus width-guard checks at 3 levels (pure-function
`append_copy_symbol`, and one render-integration check per pane at `pane_width=10`).
`dev/format_cache_tracker` differential proof (`dev/display/A_format_cache_tracker_proof.py`)
re-run against a true pre-change baseline (git-stashed): 60/60 cases byte-identical, confirming
`format_cache_tracker`'s new `copy_feedback=None` default changes nothing for existing callers.
Full milestone-1 probe (35/35) and the `pane_error_log` exception-guard suite (52/52) re-run
clean, confirming neither this milestone's new mouse-handler branches nor the worker-pane
resolver fix disturbed prior behavior. `dev/display/test_hover_map.py`: 40/40 passing checks
identical before/after (its one pre-existing crash, a dead `_parse_log_file` import unrelated to
this work, reproduces identically on the pre-change commit — confirmed via git stash, not a
regression).

Not verified: a real mouse click through an actual terminal emulator against a live tmux pane —
needs a human click-test in the running panes, same boundary as milestone 1.

## Scope note

Deliberately left untouched: gpu/news panes (milestone 4), the pre-existing tool_call
request/response copy-click in `monitor_display.py` (unconditional row registration at narrow
widths — a pre-existing gap, not introduced or touched here), and the two reference
implementations' own inline symbol-placement math (`proxy_display/render_turn.py`,
`monitor_display.py`'s tool_call branch) — the new shared `append_copy_symbol` helper is used only
by this milestone's new call sites.
