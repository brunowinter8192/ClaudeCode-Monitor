# Quartet Prefix-Diff Forensic Report

**Forwarded log:** `/Users/brunowinter2000/Documents/ai/monitor-cc/src/logs/dual_log/api_requests_opus_wise2627_1786269225_forwarded.jsonl`
**Session JSONL:** `/Users/brunowinter2000/.claude/projects/-Users-brunowinter2000-Documents-wise2627/efa8b270-67a6-4ea7-8409-a72162e95ca2.jsonl`
**Original log:** `/Users/brunowinter2000/Documents/ai/monitor-cc/src/logs/dual_log/api_requests_opus_wise2627_1786269225_original.jsonl`
**Generated:** 2026-08-09 19:00:47

## Methodology — REQ Number Mapping

Ground-truth REQ numbers are built by grouping session-JSONL `type=assistant` lines by their `(cache_read, cache_creation, input, output)` usage tuple — consecutive identical tuples (including ones separated by interleaved `type=user` tool_result lines from mid-stream tool execution within the SAME response) collapse into one request. This differs from naive line position because a single response streams multiple content blocks (thinking/tool_use) as separate JSONL lines.

Forwarded-log opus-family entries are aligned to these ground-truth requests by timestamp: each `forwarded_delta.timestamp` is the SEND time; a ground-truth request's forwarded state is the LAST forwarded entry sent at or before the request's response timestamp (monotonic two-pointer). Forwarded entries with no corresponding ground-truth response (retried/aborted sends) are silently absorbed — this makes the mapping N:1 in places, not a fixed index offset.

| Metric | Value |
|---|---|
| Opus forwarded-log entries | 156 |
| Opus ground-truth request groups | 153 |
| Ground-truth requests with no forwarded match | 0 |
| Forwarded entries absorbed (retries, no distinct response) | 3 |

**Cache-control breakpoint markers are NOT reported below** (known prior finding): the forwarded delta chain hashes each element with `cache_control` STRIPPED before comparing (`logging._delta_hash` -> `_strip_cache_control`), so a marker-only change (breakpoint moved, no content change) never enters `messages_delta` and is invisible to this reconstruction. A replayed message's `cache_control` can be stale — carried over from an earlier request's delta even when the actually-sent marker position for the CURRENT request differs. The true sent breakpoint positions are not derivable from the quartet reconstruction; use `04_cache_validation.py` against the single-log format, or the live proxy pane, for breakpoint placement.

## Auto-Detected CR-Collapse Points

Rule: `CC > CR` and `CR < 0.2 x max(CR seen so far in session)` (mirrors `03_cache_rebuild_context.py`).

| REQ | CR | CC | D | prior max CR |
|---|---|---|---|---|
| 120 | 0 | 303,818 | 2 | 302,744 |
| 134 | 21,023 | 289,834 | 2 | 350,315 |
| 135 | 21,023 | 289,907 | 1,934 | 350,315 |
| 136 | 21,023 | 294,529 | 2 | 350,315 |
| 144 | 21,023 | 314,222 | 2 | 350,315 |

## Pairs Analyzed

Requested: [(119, 120), (133, 134), (134, 135), (135, 136), (136, 137), (143, 144)]
Analyzed (both sides had a forwarded match): [(119, 120), (133, 134), (134, 135), (135, 136), (136, 137), (143, 144)]

## REQ#119 -> REQ#120

| | CR | CC | D |
|---|---|---|---|
| REQ#119 | 302,744 | 746 | 2 |
| REQ#120 | 0 | 303,818 | 2 |

### System Blocks

| idx | changed | prev_chars | curr_chars | delta_chars |
|---|---|---|---|---|
| 0 | YES | 123 | 123 | +0 |
| 1 | - | 1 | 1 | +0 |
| 2 | - | 55,844 | 55,844 | +0 |
| 3 | - | 1 | 1 | +0 |

### Tools

- Changed: **no**

### Messages (251 -> 253)

- First diverging message index: **251**
- Modified/added/removed rows: 2

| idx | status | prev_chars | curr_chars | delta_chars | prev_img | curr_img | prev_types | curr_types | note |
|---|---|---|---|---|---|---|---|---|---|
| 251 | added | 0 | 1,041 | +1,041 | 0 | 0 | {} | {'thinking': 1, 'text': 1} | - |
| 252 | added | 0 | 241 | +241 | 0 | 0 | {} | {'text': 1} | - |

**Image blocks involved:** no (0 message(s), 0 image block(s) removed, 0 added)

### Original-vs-Forwarded Attribution (client-side vs proxy-side)

_No `modified`-status message rows to cross-check for this pair._

### Segment Attribution

- First diverging segment (raw, includes per-request system[0] churn): `system[0]`
- First diverging segment (excluding system[0]): `messages[251]`

### CR/CC Reconciliation

| Metric | Value |
|---|---|
| tiktoken estimate: system[0:3] (BP1 hypothesis) | 14,213 |
| tiktoken estimate: system[0:3] + tools (BP1+BP2) | 14,842 |
| Actual CR of REQ#120 | 0 |
| Recovery identity: CR[curr] == CR[prev] + CC[prev]? | **does not hold** (0 vs 303,490) |

## REQ#133 -> REQ#134

| | CR | CC | D |
|---|---|---|---|
| REQ#133 | 350,315 | 7,989 | 2 |
| REQ#134 | 21,023 | 289,834 | 2 |

### System Blocks

| idx | changed | prev_chars | curr_chars | delta_chars |
|---|---|---|---|---|
| 0 | YES | 123 | 123 | +0 |
| 1 | - | 1 | 1 | +0 |
| 2 | - | 55,844 | 55,844 | +0 |
| 3 | - | 1 | 1 | +0 |

### Tools

- Changed: **no**

### Messages (281 -> 284)

- First diverging message index: **0**
- Modified/added/removed rows: 19

| idx | status | prev_chars | curr_chars | delta_chars | prev_img | curr_img | prev_types | curr_types | note |
|---|---|---|---|---|---|---|---|---|---|
| 0 | modified <-IMG | 801,808 | 17,280 | -784,528 | 5 | 0 | {'text': 7, 'image': 5} | {'text': 7} | image(s) evicted: 5 removed (incl. nested tool_result images) |
| 20 | modified <-IMG | 488,416 | 199 | -488,217 | 1 | 0 | {'text': 2, 'image': 1} | {'text': 2} | image(s) evicted: 1 removed (incl. nested tool_result images) |
| 22 | modified <-IMG | 189,799 | 190 | -189,609 | 1 | 0 | {'text': 2, 'image': 1} | {'text': 2} | image(s) evicted: 1 removed (incl. nested tool_result images) |
| 24 | modified <-IMG | 416,869 | 216 | -416,653 | 1 | 0 | {'text': 2, 'image': 1} | {'text': 2} | image(s) evicted: 1 removed (incl. nested tool_result images) |
| 47 | modified <-IMG | 526,886 | 479 | -526,407 | 2 | 0 | {'tool_result': 2, 'image': 2, 'text': 2} | {'tool_result': 2, 'text': 2} | image(s) evicted: 2 removed (incl. nested tool_result images) |
| 64 | modified <-IMG | 1,034,066 | 289 | -1,033,777 | 2 | 0 | {'text': 3, 'image': 2} | {'text': 3} | image(s) evicted: 2 removed (incl. nested tool_result images) |
| 98 | modified <-IMG | 178,279 | 438 | -177,841 | 1 | 0 | {'text': 2, 'image': 1} | {'text': 2} | image(s) evicted: 1 removed (incl. nested tool_result images) |
| 100 | modified <-IMG | 267,899 | 201 | -267,698 | 1 | 0 | {'text': 2, 'image': 1} | {'text': 2} | image(s) evicted: 1 removed (incl. nested tool_result images) |
| 136 | modified <-IMG | 578,480 | 290 | -578,190 | 1 | 0 | {'text': 2, 'image': 1} | {'text': 2} | image(s) evicted: 1 removed (incl. nested tool_result images) |
| 151 | modified <-IMG | 568,577 | 227 | -568,350 | 1 | 0 | {'text': 2, 'image': 1} | {'text': 2} | image(s) evicted: 1 removed (incl. nested tool_result images) |
| 159 | modified <-IMG | 657,473 | 255 | -657,218 | 1 | 0 | {'text': 2, 'image': 1} | {'text': 2} | image(s) evicted: 1 removed (incl. nested tool_result images) |
| 163 | modified <-IMG | 284,994 | 704 | -284,290 | 2 | 0 | {'text': 3, 'image': 2} | {'text': 3} | image(s) evicted: 2 removed (incl. nested tool_result images) |
| 165 | modified <-IMG | 2,456,520 | 1,167 | -2,455,353 | 6 | 0 | {'text': 7, 'image': 6} | {'text': 7} | image(s) evicted: 6 removed (incl. nested tool_result images) |
| 170 | modified <-IMG | 1,102,808 | 622 | -1,102,186 | 2 | 0 | {'text': 3, 'image': 2} | {'text': 3} | image(s) evicted: 2 removed (incl. nested tool_result images) |
| 189 | modified <-IMG | 2,049,950 | 656,473 | -1,393,477 | 4 | 1 | {'text': 5, 'image': 4} | {'text': 5, 'image': 1} | image(s) evicted: 3 removed (incl. nested tool_result images) |
| 278 | modified | 115 | 34 | -81 | 0 | 0 | {'text': 1} | {} | format normalization only (list-of-one-text-block <-> bare string, same text) |
| 281 | added | 0 | 1,810 | +1,810 | 0 | 0 | {} | {'thinking': 1, 'text': 1, 'tool_use': 5} | - |
| 282 | added <-IMG | 0 | 2,720,601 | +2,720,601 | 0 | 5 | {} | {'tool_result': 5, 'image': 5} | - |
| 283 | added | 0 | 115 | +115 | 0 | 0 | {} | {'text': 1} | - |

**Image blocks involved:** YES (16 message(s), 30 image block(s) removed, 5 added)

### Original-vs-Forwarded Attribution (client-side vs proxy-side)

| idx | fwd delta_chars | orig prev_chars | orig curr_chars | verdict |
|---|---|---|---|---|
| 0 | -784,528 | 801,808 | 17,280 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 20 | -488,217 | 488,363 | 199 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 22 | -189,609 | 189,746 | 190 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 24 | -416,653 | 416,816 | 216 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 47 | -526,407 | 526,833 | 479 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 64 | -1,033,777 | 1,034,013 | 289 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 98 | -177,841 | 178,226 | 438 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 100 | -267,698 | 267,846 | 201 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 136 | -578,190 | 578,427 | 290 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 151 | -568,350 | 568,524 | 227 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 159 | -657,218 | 657,420 | 255 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 163 | -284,290 | 284,941 | 704 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 165 | -2,455,353 | 2,456,467 | 1,167 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 170 | -1,102,186 | 1,102,755 | 622 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 189 | -1,393,477 | 2,049,897 | 656,473 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 278 | -81 | 455 | 455 | PROXY-SIDE (original identical prev->curr at this index — forwarded diff is ours) |

### Segment Attribution

- First diverging segment (raw, includes per-request system[0] churn): `system[0]`
- First diverging segment (excluding system[0]): `messages[0]`

### CR/CC Reconciliation

| Metric | Value |
|---|---|
| tiktoken estimate: system[0:3] (BP1 hypothesis) | 14,215 |
| tiktoken estimate: system[0:3] + tools (BP1+BP2) | 14,844 |
| Actual CR of REQ#134 | 21,023 |
| Recovery identity: CR[curr] == CR[prev] + CC[prev]? | **does not hold** (21,023 vs 358,304) |

## REQ#134 -> REQ#135

| | CR | CC | D |
|---|---|---|---|
| REQ#134 | 21,023 | 289,834 | 2 |
| REQ#135 | 21,023 | 289,907 | 1,934 |

### System Blocks

| idx | changed | prev_chars | curr_chars | delta_chars |
|---|---|---|---|---|
| 0 | YES | 123 | 123 | +0 |
| 1 | - | 1 | 1 | +0 |
| 2 | - | 55,844 | 55,844 | +0 |
| 3 | - | 1 | 1 | +0 |

### Tools

- Changed: **no**

### Messages (284 -> 286)

- First diverging message index: **189**
- Modified/added/removed rows: 4

| idx | status | prev_chars | curr_chars | delta_chars | prev_img | curr_img | prev_types | curr_types | note |
|---|---|---|---|---|---|---|---|---|---|
| 189 | modified <-IMG | 656,473 | 1,004 | -655,469 | 1 | 0 | {'text': 5, 'image': 1} | {'text': 5} | image(s) evicted: 1 removed (incl. nested tool_result images) |
| 197 | modified <-IMG | 2,786,164 | 1,230,810 | -1,555,354 | 8 | 3 | {'text': 9, 'image': 8} | {'text': 9, 'image': 3} | image(s) evicted: 5 removed (incl. nested tool_result images) |
| 284 | added | 0 | 2,268 | +2,268 | 0 | 0 | {} | {'thinking': 2, 'tool_use': 5} | - |
| 285 | added <-IMG | 0 | 2,372,774 | +2,372,774 | 0 | 5 | {} | {'tool_result': 5, 'image': 5} | - |

**Image blocks involved:** YES (3 message(s), 6 image block(s) removed, 5 added)

### Original-vs-Forwarded Attribution (client-side vs proxy-side)

| idx | fwd delta_chars | orig prev_chars | orig curr_chars | verdict |
|---|---|---|---|---|
| 189 | -655,469 | 656,473 | 1,004 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 197 | -1,555,354 | 2,786,111 | 1,230,810 | CLIENT-SIDE (original already shrinks prev->curr at this index) |

### Segment Attribution

- First diverging segment (raw, includes per-request system[0] churn): `system[0]`
- First diverging segment (excluding system[0]): `messages[189]`

### CR/CC Reconciliation

| Metric | Value |
|---|---|
| tiktoken estimate: system[0:3] (BP1 hypothesis) | 14,213 |
| tiktoken estimate: system[0:3] + tools (BP1+BP2) | 14,842 |
| Actual CR of REQ#135 | 21,023 |
| Recovery identity: CR[curr] == CR[prev] + CC[prev]? | **does not hold** (21,023 vs 310,857) |

## REQ#135 -> REQ#136

| | CR | CC | D |
|---|---|---|---|
| REQ#135 | 21,023 | 289,907 | 1,934 |
| REQ#136 | 21,023 | 294,529 | 2 |

### System Blocks

| idx | changed | prev_chars | curr_chars | delta_chars |
|---|---|---|---|---|
| 0 | YES | 123 | 123 | +0 |
| 1 | - | 1 | 1 | +0 |
| 2 | - | 55,844 | 55,844 | +0 |
| 3 | - | 1 | 1 | +0 |

### Tools

- Changed: **no**

### Messages (286 -> 288)

- First diverging message index: **197**
- Modified/added/removed rows: 4

| idx | status | prev_chars | curr_chars | delta_chars | prev_img | curr_img | prev_types | curr_types | note |
|---|---|---|---|---|---|---|---|---|---|
| 197 | modified <-IMG | 1,230,810 | 1,425 | -1,229,385 | 3 | 0 | {'text': 9, 'image': 3} | {'text': 9} | image(s) evicted: 3 removed (incl. nested tool_result images) |
| 283 | modified | 115 | 34 | -81 | 0 | 0 | {'text': 1} | {} | format normalization only (list-of-one-text-block <-> bare string, same text) |
| 286 | added | 0 | 1,770 | +1,770 | 0 | 0 | {} | {'thinking': 1, 'text': 1, 'tool_use': 3} | - |
| 287 | added <-IMG | 0 | 1,026,454 | +1,026,454 | 0 | 3 | {} | {'tool_result': 3, 'image': 3} | - |

**Image blocks involved:** YES (2 message(s), 3 image block(s) removed, 3 added)

### Original-vs-Forwarded Attribution (client-side vs proxy-side)

| idx | fwd delta_chars | orig prev_chars | orig curr_chars | verdict |
|---|---|---|---|---|
| 197 | -1,229,385 | 1,230,810 | 1,425 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 283 | -81 | 455 | 455 | PROXY-SIDE (original identical prev->curr at this index — forwarded diff is ours) |

### Segment Attribution

- First diverging segment (raw, includes per-request system[0] churn): `system[0]`
- First diverging segment (excluding system[0]): `messages[197]`

### CR/CC Reconciliation

| Metric | Value |
|---|---|
| tiktoken estimate: system[0:3] (BP1 hypothesis) | 14,215 |
| tiktoken estimate: system[0:3] + tools (BP1+BP2) | 14,844 |
| Actual CR of REQ#136 | 21,023 |
| Recovery identity: CR[curr] == CR[prev] + CC[prev]? | **does not hold** (21,023 vs 310,930) |

## REQ#136 -> REQ#137

| | CR | CC | D |
|---|---|---|---|
| REQ#136 | 21,023 | 294,529 | 2 |
| REQ#137 | 315,552 | 3,247 | 2 |

### System Blocks

| idx | changed | prev_chars | curr_chars | delta_chars |
|---|---|---|---|---|
| 0 | YES | 123 | 123 | +0 |
| 1 | - | 1 | 1 | +0 |
| 2 | - | 55,844 | 55,844 | +0 |
| 3 | - | 1 | 1 | +0 |

### Tools

- Changed: **no**

### Messages (288 -> 291)

- First diverging message index: **288**
- Modified/added/removed rows: 3

| idx | status | prev_chars | curr_chars | delta_chars | prev_img | curr_img | prev_types | curr_types | note |
|---|---|---|---|---|---|---|---|---|---|
| 288 | added | 0 | 9,647 | +9,647 | 0 | 0 | {} | {'thinking': 1, 'text': 1} | - |
| 289 | added | 0 | 331 | +331 | 0 | 0 | {} | {} | - |
| 290 | added | 0 | 115 | +115 | 0 | 0 | {} | {'text': 1} | - |

**Image blocks involved:** no (0 message(s), 0 image block(s) removed, 0 added)

### Original-vs-Forwarded Attribution (client-side vs proxy-side)

_No `modified`-status message rows to cross-check for this pair._

### Segment Attribution

- First diverging segment (raw, includes per-request system[0] churn): `system[0]`
- First diverging segment (excluding system[0]): `messages[288]`

### CR/CC Reconciliation

| Metric | Value |
|---|---|
| tiktoken estimate: system[0:3] (BP1 hypothesis) | 14,217 |
| tiktoken estimate: system[0:3] + tools (BP1+BP2) | 14,846 |
| Actual CR of REQ#137 | 315,552 |
| Recovery identity: CR[curr] == CR[prev] + CC[prev]? | **HOLDS** (315,552 vs 315,552) |

## REQ#143 -> REQ#144

| | CR | CC | D |
|---|---|---|---|
| REQ#143 | 328,436 | 4,096 | 2 |
| REQ#144 | 21,023 | 314,222 | 2 |

### System Blocks

| idx | changed | prev_chars | curr_chars | delta_chars |
|---|---|---|---|---|
| 0 | YES | 123 | 123 | +0 |
| 1 | - | 1 | 1 | +0 |
| 2 | - | 55,844 | 55,844 | +0 |
| 3 | - | 1 | 1 | +0 |

### Tools

- Changed: **no**

### Messages (303 -> 305)

- First diverging message index: **210**
- Modified/added/removed rows: 4

| idx | status | prev_chars | curr_chars | delta_chars | prev_img | curr_img | prev_types | curr_types | note |
|---|---|---|---|---|---|---|---|---|---|
| 210 | modified <-IMG | 1,278,886 | 808 | -1,278,078 | 3 | 0 | {'text': 4, 'image': 3} | {'text': 4} | image(s) evicted: 3 removed (incl. nested tool_result images) |
| 216 | modified <-IMG | 4,658,864 | 1,203,937 | -3,454,927 | 8 | 2 | {'text': 9, 'image': 8} | {'text': 9, 'image': 2} | image(s) evicted: 6 removed (incl. nested tool_result images) |
| 303 | added | 0 | 4,079 | +4,079 | 0 | 0 | {} | {'thinking': 1, 'text': 1} | - |
| 304 | added <-IMG | 0 | 4,169,454 | +4,169,454 | 0 | 8 | {} | {'text': 9, 'image': 8} | - |

**Image blocks involved:** YES (3 message(s), 9 image block(s) removed, 8 added)

### Original-vs-Forwarded Attribution (client-side vs proxy-side)

| idx | fwd delta_chars | orig prev_chars | orig curr_chars | verdict |
|---|---|---|---|---|
| 210 | -1,278,078 | 1,278,833 | 808 | CLIENT-SIDE (original already shrinks prev->curr at this index) |
| 216 | -3,454,927 | 4,658,811 | 1,203,937 | CLIENT-SIDE (original already shrinks prev->curr at this index) |

### Segment Attribution

- First diverging segment (raw, includes per-request system[0] churn): `system[0]`
- First diverging segment (excluding system[0]): `messages[210]`

### CR/CC Reconciliation

| Metric | Value |
|---|---|
| tiktoken estimate: system[0:3] (BP1 hypothesis) | 14,216 |
| tiktoken estimate: system[0:3] + tools (BP1+BP2) | 14,845 |
| Actual CR of REQ#144 | 21,023 |
| Recovery identity: CR[curr] == CR[prev] + CC[prev]? | **does not hold** (21,023 vs 332,532) |

## Findings Summary

### Proven from bytes

- Image content blocks — both top-level message blocks and images nested inside a `tool_result` wrapper's own `content` array — are removed (byte-for-byte, not re-encoded, `content` truncated to `[]` in the tool_result case) from historical messages between some consecutive requests — see `<-IMG` flagged rows per pair above.
- `system[1]`, `system[2]`, `system[3]` are byte-identical across all analyzed pairs; only `system[0]` (per-request billing/entrypoint header) changes every request. The problem statement's hypothesis that divergence sits in `system[3]`/tools is REFUTED for this incident — those segments never differ across the analyzed pairs.
- `tools` array is byte-identical across all analyzed pairs — not a factor here.
- Per pair, the first diverging message index (excluding the constant `system[0]` churn) is reported above with exact index and char magnitude — see "Segment Attribution" per pair.
- **Image-eviction rows (20 cross-checked): 20 CLIENT-SIDE, 0 PROXY-SIDE.** ALL image-eviction rows are CLIENT-SIDE — the incoming (original, pre-proxy) payload already shows the same shrink at the same index; the image eviction happens BEFORE our proxy ever sees the request. **Fix-vs-document verdict: DOCUMENT — this is upstream/client behavior, not a proxy bug; do not chase a proxy-side fix for the image eviction.**
- **Non-image rows (2 cross-checked, 2 of them format-normalization-only): 0 CLIENT-SIDE, 2 PROXY-SIDE.** ALL are PROXY-SIDE — the original payload is byte-identical prev->curr at this index while forwarded differs. Where the note is "format normalization only", the identical original text is our own cache_control-stripping / message-shape normalization collapsing a single-text-block list to a bare string during forwarding — a benign proxy transform, unrelated to images and not a factor in the CR/CC collapse (single-digit char magnitude, see per-pair tables).
- REQ#119->REQ#120: recovery identity CR[curr]==CR[prev]+CC[prev] does NOT hold (checked from ground-truth CR/CC directly).
- REQ#133->REQ#134: recovery identity CR[curr]==CR[prev]+CC[prev] does NOT hold (checked from ground-truth CR/CC directly).
- REQ#134->REQ#135: recovery identity CR[curr]==CR[prev]+CC[prev] does NOT hold (checked from ground-truth CR/CC directly).
- REQ#135->REQ#136: recovery identity CR[curr]==CR[prev]+CC[prev] does NOT hold (checked from ground-truth CR/CC directly).
- REQ#136->REQ#137: recovery identity CR[curr]==CR[prev]+CC[prev] HOLDS (checked from ground-truth CR/CC directly).
- REQ#143->REQ#144: recovery identity CR[curr]==CR[prev]+CC[prev] does NOT hold (checked from ground-truth CR/CC directly).

### Interpretation / hypotheses (not provable from bytes alone)

- The BP1 cross-session hypothesis (CR=21,023 == cached read of `system[0:2]`) is only PARTIALLY supported: tiktoken (cl100k_base, an approximation of Claude's real tokenizer) estimates `system[0:3]` at roughly two-thirds of 21,023 tokens — same order of magnitude, consistent with cl100k's known undercount on structured content, but not an exact match. Confirming the exact BP1 byte-identity against another project's session log was out of scope of the provided data (only this session's logs were read).
- When the recovery identity does NOT hold for a pair where messages are byte-identical up to some index, cache non-availability is consistent with Anthropic-side cache-write propagation latency (a large `CC` write may not be immediately readable moments later) — this is a plausible explanation for requests spaced tens of seconds apart, not something provable from the sent bytes.
- WHERE the eviction happens (client vs proxy) is settled by the original-vs-forwarded cross-check above where available. WHY it triggers on this specific turn (a deliberate size/token-budget threshold vs. some other condition) is not determinable from these logs alone — only the byte-level EFFECT and its origin side are proven.
