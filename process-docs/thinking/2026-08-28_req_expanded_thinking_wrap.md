# 2026-08-28 — Thinking-block drill-down + wrapping in the expanded REQ view

## Goal

A thinking content block inside an expanded REQ used to print its full text unconditionally,
hard-truncated to the pane width by `truncate_visible`. Two problems: no toggle (now that
thinking summaries are non-empty, a configuration change recorded elsewhere in
`process-docs/thinking/` — every expanded REQ floods with reasoning text nobody asked for), and truncation instead of
wrapping (real thinking text is typically one 250-600 char line with no newlines, so most of it
was simply cut off at a ~180-cell pane width).

Fix: give the thinking block its own drill-down (▶/▼, default collapsed), matching `sys`/`tools`/
`beta`/`fields`. Expanded: wrap to pane width instead of truncate.

## The plumbing

`_render_block_spans` (the function that renders one block's header + content) had neither
`entry_idx`, `expand_states`, nor `pane_width` — needed all three to build an expand key and wrap
to width. Threaded them down through the whole call chain: `_render_block_spans` ←
`_render_new_messages`/`_render_modified_messages`/`_render_flow_extra_messages` ← `render_messages`
(gained a leading `entry_idx` param) ← `render_turn._render_req_expanded` (already had it in
scope — one-line call-site update). `pane.py`'s `_entry_idx_from_key` / `worker_proxy_pane`'s
`_wp_entry_idx_from_key` needed no change — verified directly (not assumed) that their existing
`isinstance(key[0], str): return key[1]` branch already covers a 4-tuple key
`('think', entry_idx, msg_idx, bidx)`.

Three pre-existing dev/ scripts called `render_messages()` with the old 5-arg signature
(`dev/proxy_instrumentation/p3_badge_inline_probe.py`, `render_recorded_request.py`,
`dev/display/test_hover_map.py`) — updated their call sites to pass `entry_idx` (already in scope
at each site), a mechanical consequence of the signature change, not a behavior change.

## The wrap helper

No wrapping helper existed anywhere in the repo — only `truncate_visible` (cut + `…`). Added
`utils.wrap_visible(text, width_cells)`: cell-aware (via `_cell_width`, consistent with
`truncate_visible` — NOT a character count), word-wraps on spaces, hard-splits a single word
wider than the target width. Lives in `utils.py` next to `truncate_visible`/`_cell_width`, the
natural home since it depends on `_cell_width` directly and belongs to the same "render text into
a fixed terminal width" family.

`render_messages._wrap_thinking_text(full_text, indent, pane_width)` wraps the width math around
it: `width_cells = pane_width - len(indent)` (indent is the 8-space content indent
`_render_span_content` prepends to every line — `len()` suffices since it's plain spaces, all
cell-width 1), splits `full_text` on existing `\n` first (paragraph boundaries — real thinking
text has none, but the reconstruction never guarantees that), wraps each paragraph independently,
rejoins with `\n`. The result is fed into the EXISTING, unmodified `_render_span_content` as its
`full_text` argument — no new content-rendering path, the wrapped string just flows through the
same function every other block type already uses.

## Byte-identical guarantee — how it was actually proven, not just claimed

The constraint was: every other block type's rendered output must stay byte-identical.
`_render_block_spans` was restructured so the thinking branch is a separate, self-contained `if`
that returns early; the non-thinking branch below it is the exact same code (same header f-string,
same unconditional `_render_span_content` call, same indent constant) that existed before this
milestone — entry_idx/expand_states/pane_width are simply never read on that path.

Proof, not assertion: wrote `dev/thinking/render_thinking_expander.py`, which loads the
PRE-CHANGE `render_messages.py` straight from git (`git show` at the commit preceding this edit)
into an isolated package tree under `/tmp` — a real, separately-rooted package so the old file's
relative imports (`from ..constants import ...`) resolve without colliding with the live `src`
package already in `sys.modules` — and calls its old-signature `_render_block_spans` against the
same real block data (from the milestone's forwarded log) the new function renders. Measured
2026-08-28: 4/4 non-thinking block types found in the log (text, tool_use, tool_result, image) —
identical output, old vs. new.

Cross-checked against the existing repo-wide byte-identical harness,
`dev/proxy_dual_log/A_render_refactor_proof.py` (14 synthetic fixture cases, pre-existing
baseline): 12/14 cases untouched byte-for-byte; the other 2 (`branch1_basic`, `expand_fixpoint`)
are the two synthetic cases that happen to contain a thinking block, and the only difference in
either is the added `▶`/`▼` prefix on the thinking block's header line (verified line-by-line) —
exactly the deliberate, intended change, not drift. That baseline was deliberately NOT
recaptured — the 2-case divergence is expected and explained here, not silently absorbed.

## Verification on the real log

`dev/thinking/render_thinking_expander.py` against
`api_requests_opus_monitor_cc_1787931850_forwarded.jsonl`, through the real render path
(`render_turn._render_req_expanded`, not a reimplementation):

- **Ownership determined empirically:** a message re-appears in every LATER entry's accumulated
  `messages` (parsed with `keep_last=None`), but only the entry whose own delta introduced it
  actually renders it in `_render_req_expanded` — same delta-vs-cumulative distinction the brain
  marker (milestone 1, same area) is built on. Filtered candidate thinking blocks down from 646
  raw sightings across the accumulated history to 26 blocks each entry actually owns and renders,
  by checking `think_key` presence in that entry's own from-scratch collapsed render rather than
  assuming a naive index match.
- **Collapsed (26/26):** diffed a from-scratch collapsed render against a single-key-expanded
  render of the same entry — the prefix before the header line and the suffix after the content
  block are byte-identical between the two; the only difference is the header symbol plus the
  inserted content. This proves collapsed contributes exactly one line, not by counting but by
  showing there is nothing else that could differ.
- **Expanded (52/52 = 26 blocks × pane_width ∈ {180, 60}):** whitespace-normalized text match
  against `blk['full_text']` (proves no character lost or duplicated by wrapping, independent of
  where the wrap re-flowed whitespace) and max content-line width ≤ pane_width. At pane_width=12
  (informal extra stress point during development, not in the committed report) even mid-word
  hard-splitting wrapped correctly with max width exactly 12. The longest real block tested was
  2,434 chars, wrapping to 20 lines at pane_width=180.
- User's own independent sample check (reported back, not run by the agent): a 1,482-char
  thinking text wrapped to exactly 100 cells at pane_width=100, no line clipped.

## KNOWN, UNMEASURED LIMITATION — do not treat as ruled out

`_render_span_content(full_text, i_blk, s_blk, indent, ...)` — the function the wrapped text is
handed to — ignores its `full_text` argument ENTIRELY whenever `i_blk` is new-format span data
(`isinstance(i_blk[0], (list, tuple))` — a list of `(tag, text)` tuples from a strip/inject
pass). In that branch it renders `i_blk`'s own `span_text` chunks instead, completely bypassing
whatever was passed as `full_text`. Consequence: a thinking block that carries strip/inject spans
at its own `(msg_idx, bidx)` coordinate would render those spans UNWRAPPED, silently skipping this
milestone's wrap.

A probe was run against the real dual-log used for this milestone's measurements, looking for any
thinking-block coordinate with non-empty `i_blk`/`s_blk` spans — it found zero. That result is
NOT evidence the case cannot occur: the probe's own correctness was never independently verified
(e.g. against a synthetic fixture deliberately constructed to exercise a thinking block WITH
spans), so a bug in the probe returning a false "zero" cannot be distinguished from the case
being genuinely absent from this one log. Stated here exactly as that — a known, unmeasured gap,
not a proven-impossible case. Not fixed in this milestone; span-aware wrapping was explicitly out
of scope and was not implemented.

## Not touched

The token pane, strip/inject behavior, and the milestone-1 brain badge — all confirmed unaffected
by re-running the two `dev/pane_search/` parity suites (154/154 passing) after this change.
