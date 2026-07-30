# 2026-07-30 — Interrupt-marker strip and has_bg abort gate verified on a live proxy

Both mechanisms landed 2026-07-30 against synthetic payloads only. This entry records the live
verification of each, and two unrelated defects observed along the way that were deliberately not
fixed.

## Interrupt-marker strip — verified in two halves, on two different workers

**Half 1 — the marker never reaches the model.** Throwaway worker `esc-test` was dispatched with a
read-only task and interrupted by hand. Its dual-log
(`src/logs/dual_log/api_requests_worker_25c51a2e_esc-test_1785440868_*.jsonl`) scanned for the
marker across every `role='user'` text block:

```
ORIGINAL : 0 marker blocks
FORWARDED: 0 marker blocks
INJECTED : msg 1 blk 0 -> [['injected', '.']]
```

Zero occurrences on both sides, with a `'.'` injected at exactly the affected location — the strip
fired on live traffic. Note the ORIGINAL side reads 0 as well: `_original.jsonl` records the
already-normalized payload, so absence there is not independent evidence; the injected `'.'` is.

**Half 2 — the worker resumes when prodded.** `esc-test` hit its context limit before it could be
prodded, leaving this half open. It was closed on the next worker (`click-ui`): interrupted
mid-milestone, then sent a bare "weiter", it continued the task instead of asking for
instructions. The proxy pane rendered the message as the expected pair — the injected `'.'` in
green above, the stripped `[Request interrupted by user]` in olive below (user screenshot
reviewed in-session).

## has_bg abort gate

Verified live by the user in the same session: the orchestrator's sleep timer holds while an idle
worker has a live background task, and an idle worker without one still aborts promptly.

## Two defects observed and deliberately left

**Invisible hit zone in the main pane.** `src/core/monitor_display.py`'s pre-existing tool_call
copy-row branch registers its `_main_copy_rows` entry unconditionally, including when the pane is
too narrow to render the `⎘` symbol — a clickable region with nothing visible to click. Every
copy-row site added 2026-07-30 (`utils.append_copy_symbol` callers) follows the opposite rule: no
room means no symbol AND no region. The old site was left as-is to keep the milestone's scope
clean; it is the one place in the codebase where the no-invisible-hit-zone rule does not hold.

**Header overflow at very small pane widths.** The gpu and news pane title lines are never passed
through `truncate_visible`, so below a certain width the title runs past the pane edge. Measured
after the 2026-07-30 shrinking-rule change: gpu overflows below width 13, news below width 24.
This is an improvement, not a regression — before the change the same overflow started at width 26
(gpu) and 34 (news), because the decorative `'═'` run had a fixed length. A pane that narrow is
unusable regardless, which is why it was not pursued.
