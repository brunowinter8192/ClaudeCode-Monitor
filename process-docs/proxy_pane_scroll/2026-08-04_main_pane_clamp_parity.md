# Main Pane Scroll Clamp — Third Instance of the Same Symptom Class, 2026-08-04

Continues the proxy-pane scroll-clamp work (2026-07-21 original fix, 2026-07-28 worker-pane
parity fix — same area): third occurrence of the same symptom class, this time in the MAIN pane
(tab 0, `src/core/monitor.py` + `src/core/monitor_display.py`), which had never received either
prior fix.

## Symptom (user-reported)

Scrolling up energetically past the top of content in the main pane keeps growing the scroll
state invisibly; scrolling back down does nothing until the accumulated excess unwinds. Display
stays correctly pinned at the top throughout — same state-vs-display divergence as both prior
instances.

## Root cause — identical shape to 2026-07-21

`_handle_main_mouse` (`monitor.py`, wheel-up, `button == 64`): `main_scroll_offset = max(0,
main_scroll_offset + 3)` — lower-bound only, no upper bound. `render_main_buffer`
(`monitor_display.py`): `start = max(0, total - buffer_height - scroll_offset)` clamps the
DISPLAYED slice but never writes the clamped value back to the `main_scroll_offset` global. Same
mechanism as the proxy pane, different file.

## Off-by-one check — does NOT apply here

The worker-pane fix (2026-07-28) needed a `content_height - 1` correction because
`format_proxy_block` derives its own internal viewport (`pane_height - 1`) independent of what the
caller passes as `pane_height`, and the worker pane additionally consumes header rows before the
body. The main pane has neither trap: `render_main_buffer` computes `buffer_height = pane_height -
1` itself and uses that value DIRECTLY as the slice viewport (`all_lines[start:start +
buffer_height]`) — no header, no second internal `-1` layered on top by a separate rendering
function. Structurally this pane matches `pane.py` (2026-07-21), not the worker pane's added
complexity — the plain fix shape applied, not the off-by-one-corrected variant.

## Fix

Write-back clamp inside `render_main_buffer` (`monitor_display.py`), placed immediately after
`_search_total_lines = len(all_lines)` is computed (this pane computes `total` inline rather than
via a separate render-then-return-total call like the proxy panes, so the clamp sits directly in
the renderer rather than in a caller):

```python
max_scroll = max(0, _search_total_lines - buffer_height)
if scroll_offset > max_scroll:
    scroll_offset = max_scroll
    main_scroll_offset = max_scroll
```

`main_scroll_offset` added to the function's existing `global` declarations. Clamping the local
`scroll_offset` (used a few lines later for `start = max(0, total - buffer_height -
scroll_offset)`) keeps display and state derived from the same clamped number in the same call;
writing back to the global makes the very next wheel-down tick see the true ceiling instead of a
phantom excess.

`_handle_main_mouse`'s wheel-up handler left untouched by design — same "single write-back, not a
handler rewrite" pattern as both prior entries.

## Why `ensure_match_visible` and the sticky-scroll delta don't need their own clamp

- `ensure_match_visible` sets `main_scroll_offset = max(0, _search_total_lines - buffer_height -
  new_start)` with `new_start = max(0, target_line - 2) >= 0`. Since `new_start >= 0`, the result
  is algebraically bounded by `total - buffer_height` — i.e. always `<= max_scroll` by
  construction, independent of the new clamp.
- The sticky-scroll delta in `monitor.py` (`_refresh_main_data`) only lower-bounds at 0 after
  applying a buffer-growth delta and could in principle push `main_scroll_offset` above
  `max_scroll` on an odd delta. It self-corrects within one frame: the next `_build_main_output`
  call always goes through `render_main_buffer`, which re-clamps and writes back. Same
  self-correction property the 2026-07-21 and 2026-07-28 fixes both rely on for their own
  auto-scroll branches.

## Verification — this session

Integration-level call to the real `render_main_buffer`, no live terminal needed: populated
`main_event_buffer` with 50 `session_banner` events (1 content line + 1 blank separator each = 100
total lines), `pane_height=50` → `buffer_height=49` → `max_scroll=51`. Four cases, all pass:

1. `scroll_offset=99999` → clamped to `51` (both the value used for `start` and the written-back
   global).
2. In-range `scroll_offset=10` → passes through unchanged, global untouched.
3. `scroll_offset=51` (== max_scroll) → `start=0`, topmost content line (`session_banner` text)
   present in the rendered output — the offset at which the very first line becomes reachable.
4. Post-clamp simulated wheel-down (`51 - 3 = 48`, mirroring `_handle_main_mouse`'s subtraction
   logic) → next `render_main_buffer` call renders `start=3` immediately, no unwind delay.

Script discarded from `/tmp` after use — one-shot, no standing regression-guard value beyond this
change. `py_compile` clean on both changed/checked files. Live mouse-wheel scroll-feel in a
running monitor pane not verified from the worktree — remains the user's own follow-up check, same
caveat as both prior entries in this area.
