# Worker-Proxy Pane Scroll Clamp — Parity Fix + Off-By-One Correction, 2026-07-28

Continues the 2026-07-21 main-pane scroll-clamp fix (`2026-07-21_top_overshoot_state_clamp.md`,
this area): same symptom class, same fix shape, applied to the worker-proxy pane, which never
received the original fix and additionally needed a viewport-height correction the main pane
didn't.

## Symptom (user-reported)

Scrolling up past the top of content in the worker-proxy pane (`src/proxy_display/
worker_proxy_pane.py`) keeps incrementing the offset invisibly; scrolling back down does nothing
until the accumulated excess unwinds. Same asymmetric overshoot as the 2026-07-21 main-pane bug —
`button == 64` (scroll-up) only lower-bounds at 0, no upper bound; `format_proxy_block`'s own
internal render-time clamp keeps the DISPLAY correct but never writes the clamped value back to
`worker_proxy_scroll_offset`.

## Why the main pane's fix didn't already cover this

The worker pane computes the identical `max_scroll` expression the main-pane fix introduced — but
only inside the `_wp_just_expanded` auto-scroll branch (fires on entry-expand, not on a plain
scroll tick). A plain wheel scroll never reaches that branch, so the write-back never happened for
the worker pane at all.

## The header-offset trap (worker pane's added complexity over the main pane)

The two panes do not share a viewport height. `pane.py` clamps against `pane_height - 1` directly
— the main pane has no header, full pane height IS the content viewport. The worker pane renders a
worker-switcher header ABOVE the body and derives `content_height = max(1, pane_height -
header_lines)` — the body's real viewport is `content_height`, not `pane_height`; clamping against
`pane_height` would count the header's own rows as scrollable body space and leave the true bottom
of content unreachable. Fixed (session 1 of this date) with a write-back clamp mirroring
`pane.py`'s placement exactly: immediately after the first `format_proxy_block(...)` call inside
the `else` branch (worker selected AND entries exist — the only branch where `total_lines` exists;
the two placeholder branches never touch the scroll state, so a stale offset from a placeholder
visit simply sits inert and self-corrects on the next real render).

## Follow-up defect: off-by-one against content_height itself

Review caught a second-order bug in the same change: `format_proxy_block` (`src/proxy_display/
format.py`) doesn't use its `pane_height` argument directly — it derives its own real viewport
internally as `viewport_lines = max(1, pane_height - 1)`. The main pane's clamp already accounts
for this (`viewport_lines_n = pane_height - 1`, matching the renderer exactly). The worker pane's
new clamp — and the PRE-EXISTING `_wp_just_expanded` branch's `max_scroll`/`start`/`item_line`
math, which carried the same gap since before this session touched the file — used
`content_height` directly, one line short of what `format_proxy_block` actually renders with
(`content_height - 1`, since `content_height` is passed AS the `pane_height` argument).

Effect, worked through concretely (10-line content, `content_height=5` so the renderer's true
per-screen viewport is `max(1,5-1)=4`): true `max_scroll = total_lines - viewport = 10-4 = 6`
(the offset at which the very first content line becomes reachable). The old, under-counted clamp
gave `max_scroll = 10-5 = 5` — one less than the renderer can actually tolerate. At offset 5 the
renderer shows starting from content line 1, never line 0: the external clamp caps the offset a
full step BEFORE the renderer's own internal ceiling, so the topmost line becomes permanently
unreachable — a "dead" wheel-scroll step that produces no visible change no matter how many more
times it's pressed. Because `format_proxy_block`'s own internal clamp still bounds what it draws
(to ITS correct, larger ceiling) regardless of the caller's under-shot state value, nothing ever
rendered out of bounds — this was a state-vs-true-capability gap, not a corrupted display, which
is why it read as "one dead step" rather than a visible glitch.

**The relationship is easy to get backwards:** since `max_scroll = total_lines - viewport`, a
SMALLER real viewport requires a LARGER max_scroll (more scroll steps needed to traverse the same
content), not a smaller one — intuition ("viewport shrank by 1, so the limit should shrink by 1
too") points the wrong way.

## Fix

Introduced `viewport_lines_n = max(1, content_height - 1)` once, right before the first
`format_proxy_block` call, and used it (never `content_height` directly) at both clamp sites: the
write-back clamp added earlier this date, and the pre-existing `_wp_just_expanded` branch's three
uses (`max_scroll`, `start`, the `item_line` bounds check). Single source of the viewport value so
the two sites cannot drift apart again. `content_height` itself is still passed unchanged as the
`pane_height` argument to both `format_proxy_block` calls — only the caller-side mirror of the
renderer's internal math changed.

## Verification — this session

No live terminal available from the worktree, so verification is a direct integration-level call
to the real `_build_worker_proxy_output`, not a live scroll. `os.get_terminal_size` forced to the
OSError fallback (deterministic 50×80); `format_proxy_block` stubbed to return a controlled
`total_lines` (isolates the clamp arithmetic from real entry rendering, which needs a live
terminal + live entries to set up meaningfully); `_format_worker_proxy_header` stubbed to a fixed
250-char string (wraps to 4 rows at width 80 via `visual_line_count`, giving `header_lines=4`,
`content_height=46`, `viewport_lines_n=45` — a header tall enough to make the content_height-vs-
pane_height distinction unmistakable in the numbers). Six cases, all pass:

1. Offset 99999 clamps to 55 (`total_lines(100) - viewport_lines_n(45)`), proven distinct from
   both the pane_height-based value (50) and the pre-off-by-one-fix content_height-based value
   (54) — confirms the fix lands on the renderer's true ceiling, one more than the previous
   (already-shipped-this-session) clamp allowed.
2. Post-clamp scroll-down (offset 55 → 52) moves immediately — no unwind delay.
3. No-entries placeholder: no crash, offset untouched (branch never executes the clamp).
4. Re-selecting a worker with entries afterward clamps a stale offset back down — self-correcting.
5. No-worker-selected placeholder: no crash, offset untouched.
6. Independent 10-line/content_height=5 arithmetic check proving the DIRECTION of the fix
   (`new_max_scroll == old_max_scroll + 1`, never a decrease) — see the worked example above.

Verification script discarded from `/tmp` after use — one-shot, no standing regression-guard value
beyond this change. Live scrolling in a running monitor pane remains the user's own follow-up
check.
