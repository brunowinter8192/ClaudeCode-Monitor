# `msgs` Shows the Proxy's Strip/Inject Delta and Wire Size, 2026-09-04

Continues this area's command line, and specifically the `expand` overlay work
(`2026-08-30_expand_strip_inject_overlay.md`): `msgs` prints the ORIGINAL payload's chars, so a msg
the proxy stripped down to almost nothing looked exactly as big as one that reached the API intact.
`overlay.build_overlay` already had everything needed to fix that — it was just `expand`-only until
now.

## Reusing the overlay, not re-deriving it

`build_overlay` returns `{(msg_idx, blk_idx): {stripped: [texts], injected: [texts], req}}` for a
whole session. `_run_msgs` now builds it exactly like `_run_expand` does — same call, same
arguments — and passes it into `render_msgs`. `render.py` never touches the text itself, only
`len()` of the stripped/injected lists, since the delta tail is a size, not a preview.

## Where the wire size is anchored

`wire = chars_shown − stripped_chars + injected_chars`, computed against THAT line's own printed
chars value — the parent line's chars for the msg-level tail (summed stripped/injected over every
touched block), each block's own chars for a sub-line. This was a deliberate choice over summing
each block's own wire figure into the parent: the parent line's arithmetic is then self-consistent
on its own (a reader can verify `10,116 − 10,116 + 1 = 1` without cross-referencing sub-lines),
which matters more than whether msg-level chars exactly equals the sum of block-level chars
elsewhere in the pipeline (measured to hold in every real case, but not asserted).

## The "by REQ" omission that was checked before assuming it away

The spec's `by REQ n` only applies when the transforming request differs from the msg's own group —
the same case `expand` already surfaces (msg arrives under REQ 61, gets overwritten by REQ 62). A
multi-block msg raises a question `expand` never had to answer: what if two DIFFERENT blocks of one
msg were touched by two DIFFERENT requests? The parent line's aggregate would then have no single
REQ to name. Checked rather than assumed: swept every session's overlay, grouped by msg, and counted
how many msgs have more than one distinct `req` among their touched blocks — **zero, out of 1949
transformed msgs** across the whole corpus. The parent line still omits `by REQ` in that case rather
than picking one arbitrarily, and a regression test pins the behavior even though it has never
fired; the sub-lines are unaffected either way since each already carries its own single `req`.

## Measurements (as of 2026-09-04, corpus on disk)

**Wire-figure fidelity.** For every transformed coordinate in every session, `chars − stripped +
injected` was compared against the block's REAL chars in the FORWARDED (wire) payload — reconstructed
via `proxy_display.forwarded_parser.reconstruct_all_messages` on the `_forwarded` stream (the same
helper the proxy pane itself uses for a stripped entry's full content, `~35 ms` for a 6.8 MB forwarded
log per its own docstring), matched to the session's last request by `flow_id`. First pass showed 1801
of 2003 coordinates "incomparable" — a false alarm: `reconstruct_all_messages`' block lists are the
REAL `_summarize_message` output, which is `[]` for a plain-string message (the same case
`timeline.build_turns` synthesizes a pseudo-block for), so the comparison needed the identical
pseudo-block fallback on the forwarded side before block 0 lined up. With that fix: **2001 of 2003
transformed coordinates matched exactly (99.9%)**, 0 incomparable. The 2 that differed:

- `opus_jobscraper_1788331456` msg 199 blk 0: original 49 chars, recorded stripped 177 (longer than
  the block itself — the cumulative last-writer-wins accumulator describing content that no longer
  matches, the exact effect `2026-08-30`'s entry measured at 52/741 coordinates), computed wire −127
  (nonsensical as a char count), actual wire 1. Max abs diff: 128.
- `opus_monitor_cc_1788364366` msg 272 blk 0: computed wire 1, actual wire 407 — the overlay's
  cumulative state names a transform whose effect is not what actually went out on this particular
  request. Diff: 406, the largest of the two.

Both are pre-existing overlay-fidelity limitations, not something this feature introduces — the
Gotcha this entry adds points back at `expand`'s original measurement rather than restating it.

**`by REQ` incidence.** 36 msg (parent) lines and 37 lines total (one msg also has its lone
transformed sub-line show the same tag) carry `by REQ` across the corpus. Example:
`worker_25c51a2e_rag-chunking_1788333660` msg 0 — a session with 34 re-fires, where content
stripped by the ORIGINAL request (REQ 1) still sits under a separator numbered in the hundreds by
the time the re-fires finally added a msg.

**Timing**, largest session on disk (`opus_jobscraper_1788347399`, 367 MB `_original`, 1451 `msgs`
lines): 0.141 s before this change, 0.152 s after — the overlay read (64-336 KB of delta JSONL) adds
roughly 11 ms, negligible next to the session load itself, matching the CR/CC feature's own overlay
cost from `2026-09-03`.

## Verification

`sessions`, `expand` and `search` confirmed byte-identical via `git stash` (stash verified
effective: 0 dirty tracked files while stashed). `msgs` confirmed line-count-IDENTICAL on three
sessions with every UNTOUCHED line byte-identical: `spawn-placement-msg_1788374139` (122 lines, 25
transformed), `gcommit-umlaut_1788367120` (224 lines, 43 transformed) and the largest session above
(1451 lines, 314 transformed) — every diff hunk was a 1-for-1 line replacement, never an insertion
or deletion. New regression suite `dev/dual_log_cli/tests/test_msgs_overlay.py` (8 checks): the
spec's own single-block example reproduced byte-for-byte including the real minus sign, `by REQ`
appended/omitted correctly, multi-block parent-sum vs. per-block sub-line figures, the untouched-
sub-line-stays-bare case, the ambiguous-req omission (synthetic, since it has never occurred for
real), and the additive-parameter default-unchanged case. Existing suites (`test_msgs_blocks.py`,
`test_msgs_usage.py`) re-run unchanged, 13/13 each.

## Relevant Symbols / Paths

- `_delta_tail`, `_msg_delta_tail`, `_block_overlay_totals` (`src/dual_log_cli/render.py`)
- `build_overlay` (`src/dual_log_cli/overlay.py`) — unchanged, now called from `_run_msgs` too
- `reconstruct_all_messages` (`src/proxy_display/forwarded_parser.py`) — reused for the fidelity
  measurement only, not part of the shipped feature
- Ground truth: `src/logs/dual_log/api_requests_worker_25c51a2e_spawn-placement-msg_1788374139_*.jsonl`,
  msg 1, the spec's own example
