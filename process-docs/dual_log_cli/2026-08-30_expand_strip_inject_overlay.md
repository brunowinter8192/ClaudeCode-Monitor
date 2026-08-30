# `expand` Shows the Proxy's Transformations, 2026-08-30

Continues this area's command line. Until now the duallog CLI read only the `_original` stream, so
it showed what CC *would* have sent without the proxy — the modifications the proxy actually makes
were invisible to anyone reading through the CLI, and only visible in the TUI proxy pane. `expand`
now also reports what was stripped from and injected into each displayed block. Related area:
`process-docs/proxy_tool_stripping/` holds the delta-stream design and the attribution lag this
builds on.

## How a msg-centric view maps onto flow-centric streams

The mapping turned out to need no scoping work, and the reason is structural: `expand` renders msgs
of exactly ONE payload — the last non-haiku `_original` request — so there is no request header
that a foreign flow's span could appear under. The proxy pane's flow-scoping exists precisely to
prevent that, and it has no analogue here. What a msg needs is the CUMULATIVE state of its
coordinate, which is what `accumulate_dual_log` already leaves in `acc['messages'][msg][blk]`.

**The content direction is inverted from the pane's, and that shapes the output.** The pane reads
`_forwarded` (post-strip) and colours in what was removed. duallog reads `_original` (pre-strip), so
the block body already IS the original text. A whole-content nuke therefore prints its text twice —
once as the block body, once under `── stripped by REQ n ──`. That looks redundant and is not: a
partial strip prints only the removed fragment there, and without the repetition a reader cannot
tell whole from partial.

## Output

```
▶ ═══ msg #179 14:41:41 system 49 chars, 1 block(s) ═══
── block 0  system  49 chars ──
<total_tokens>14990609 tokens left</total_tokens>
── stripped by REQ 62 ──
<total_tokens>14990609 tokens left</total_tokens>
── injected by REQ 62 ──
.
```

Plain text, no ANSI anywhere — the CLI's consumers are agents reading through pipes, so the labels
carry the meaning that colour carries in the pane. Sections appear only for blocks the proxy
touched, which is what keeps an untouched msg byte-identical to the pre-change output. Several
stripped chunks in one block get one section each.

## Attribution: reuse rather than re-derive

The write-side lag documented in `process-docs/proxy_tool_stripping/` applies to these streams too —
a request's trailing total_tokens strip is recorded on the FOLLOWING request's delta line. Rather
than re-implement that correction, `overlay.py` imports `accumulate_dual_log` from
`src/proxy_display/parser.py` and reads its `_lag_msg_idx_by_flow_id` directly, so duallog inherits
both the per-coordinate accumulation and the correction unchanged. `_owners_by_index` resolves a
coordinate to its performing flow (lag set wins over the raw recorder) and
`timeline.request_numbers_by_flow` turns that into the REQ number `msgs` already prints. Both
numbering consumers now share `_running_request_numbers`, so the overlay cannot drift from `msgs`.

Two questions a reader might conflate, both answered correctly and differently: `msgs` puts msg 176
under `── REQ 61 ──` because that is when it ARRIVED; `expand` reports `── stripped by REQ 62 ──`
because CC overwrote index 176 in place afterwards and REQ 62 is what nuked the new content.

## Measurements that shaped the design (before implementing)

Over `opus_monitor_cc_1788091735` and `opus_gh_cli_1787995963`, 741 stripped coordinates:

| recorded text vs the block duallog displays | count |
|---|---|
| exact match | 670 |
| substring of it | 19 |
| differs only by whitespace (similarity ≥ 0.972) | 52 |
| **unrelated (stale content)** | **0** |

Coordinates touched by more than one flow: **0** — so the last-writer-wins accumulator is never
ambiguous here. The 52 whitespace variants are the known spurious-newline artifact (one differs by a
single `\n` in 892 chars). This killed a containment gate I had considered: requiring the recorded
text to occur in the displayed content would have silently dropped those 52 legitimate overlays.
The overlay is therefore shown unconditionally.

Reading cost stays negligible: `_stripped`/`_injected` are 64-336 KB of delta JSONL per session,
against the multi-GB `_original` this package already refuses to parse whole. Only `expand` builds
the overlay, so `sessions`, `msgs` and `search` never open those files.

## Verification (as of 2026-08-30)

`expand <session> 179` shows the original total_tokens content plus both labelled sections,
attributed to REQ 62 — the request that performed the strip, not REQ 63 whose line records it.

Attribution cross-checked against `proxy_display`'s own ownership for every coordinate: **746
coordinates, 0 mismatches**, 524 of them lag-corrected, 0 coordinates left without a REQ number, 0
overlay coordinates absent from the streams. Non-zero block indices (6 across both sessions) render
under the correct block header.

`sessions`, `msgs`, `search` and `expand` of untouched msgs were captured on the pre-change package
via `git stash` (verified to have taken effect) and again after: byte-identical in every case. Only
`expand` of touched msgs differs, by exactly the added sections.

**Not verified:** behaviour on a session whose `_stripped`/`_injected` streams are missing entirely.
The code no-ops per stream when the path is absent, but no such recorded session was available to
run against.

## Relevant Symbols / Paths

- `build_overlay()`, `_owners_by_index()`, `_texts()` (`src/dual_log_cli/overlay.py`)
- `request_numbers_by_flow()`, `_running_request_numbers()` (`src/dual_log_cli/timeline.py`)
- `_overlay_lines()`, `render_expand_full()` (`src/dual_log_cli/render.py`)
- `accumulate_dual_log()`, `_lag_msg_idx_by_flow_id` (`src/proxy_display/parser.py`) — reused, untouched
- Ground truth: `src/logs/dual_log/api_requests_opus_monitor_cc_1788091735_*.jsonl`, msg 179 / REQ 62
