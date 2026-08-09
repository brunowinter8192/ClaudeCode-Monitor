## Case 9 — wise2627 REQ#133-136 (2026-08-09) — Client-Side Image Eviction Breaks Message-Chain Cache

**Symptom:** Three CONSECUTIVE rebuilds, not one. CR collapses to a constant floor (21,023) across REQ#134/#135/#136, each with CC in the 289k-295k range, before recovering at REQ#137. Session-JSONL usage (deduplicated by usage tuple):

| REQ | CR | CC | D | Note |
|---|---|---|---|---|
| 133 | 350,315 | 7,989 | 2 | healthy |
| 134 | 21,023 | 289,834 | 2 | rebuild; total context SHRANK ~40k vs #133 |
| 135 | 21,023 | 289,907 | 1,934 | rebuild — did NOT read what #134 wrote |
| 136 | 21,023 | 294,529 | 2 | rebuild — did NOT read what #135 wrote |
| 137 | 315,552 | 3,247 | 2 | recovery |

A second, structurally identical episode recurs later in the SAME session at REQ#144 (CR=21,023 again, CC=314,222, prior max CR=350,315).

**Context:**
- Session: `efa8b270-67a6-4ea7-8409-a72162e95ca2` (wise2627, opus)
- Forwarded dual-log: `src/logs/dual_log/api_requests_opus_wise2627_1786269225_forwarded.jsonl` (delta-encoded, what was actually sent)
- Original dual-log: `src/logs/dual_log/api_requests_opus_wise2627_1786269225_original.jsonl` (full non-delta incoming payloads, 1.4GB, one line per request)
- Session JSONL read several `/tmp/home_fotos/IMG_*.jpg` files via the Read tool during the affected turn — image-heavy session, matches a standing user observation that image-heavy sessions rebuild while text-only sessions don't.

**REQ-number mapping (new methodology, needed because line position ≠ REQ number):**

Ground-truth REQ numbers come from grouping session-JSONL `type=assistant` lines by identical `(cache_read, cache_creation, input, output)` usage tuple — one physical API response streams as multiple JSONL lines (thinking/tool_use blocks), interleaved with `type=user` tool_result lines from mid-stream tool execution, all sharing the SAME usage tuple. Forwarded-log entries are then aligned to these groups by timestamp (`forwarded_delta.timestamp` = send time; a group's match is the LAST forwarded entry sent at or before the group's response timestamp), monotonic two-pointer — NOT a fixed line-index offset. In this session: 156 opus forwarded-log entries vs 153 opus ground-truth groups, 3 forwarded sends absorbed (retries/aborts with no distinct response), 0 unmatched ground-truth groups.

**Root cause, proven from bytes:**

Built a reusable probe, `dev/session_analysis/07_quartet_prefix_diff.py`, that reconstructs full payload state (system/tools/messages) at every opus request by replaying the forwarded delta chain, then diffs consecutive requests segment-by-segment.

1. `system[1]`, `system[2]`, `system[3]`, and `tools` are byte-identical across every REQ#133-137 and REQ#143-144 pair. Only `system[0]` (a 123-char per-request billing/entrypoint header, `x-anthropic-billing-header: ... cch=...`) changes every single request — this is BEFORE the BP1 breakpoint conceptually but empirically does not itself trigger a rebuild (REQ#133 still reads CR=350,315 despite `system[0]` differing from REQ#132). The task's original hypothesis (divergence sits in `system[3]`/tools) is REFUTED for this incident — those segments never differ.
2. The real divergence is entirely inside `messages`. At REQ#134, a bulk pass removes image content blocks — both top-level `type:image` blocks AND images nested inside a `tool_result.content` array (`content` truncated to `[]`) — from 14 historical messages simultaneously, INCLUDING `messages[0]`, the very first message in the array. Message-level cache breakpoints form a rolling hash-chain from position 0; mutating `messages[0]` invalidates every downstream breakpoint at once, forcing a full messages-segment rebuild (CC=289,834) while CR collapses to the stable system+tools floor (21,023).
3. The eviction is PROGRESSIVE across the next two turns, not a one-shot event: REQ#135 evicts further images from `messages[189]` and `messages[197]`; REQ#136 continues on `messages[197]`. Because each of these turns still mutates a message positioned before/at the last-written cache breakpoint, CR stays pinned at 21,023 for three consecutive requests even though system+tools never change.
4. REQ#137 finally sends a payload with no further-back mutation, so it reads everything REQ#136 wrote: `CR[137] = CR[136] + CC[136]` — verified programmatically from ground truth: `315,552 == 21,023 + 294,529`, exact match. This is the "recovery arithmetic" identity; it does NOT hold for any of the REQ#134/135/136 pairs (checked generically for every analyzed pair, not assumed).
5. `CR=21,023` (BP1 hypothesis: cached read of `system[0:3]`) is only PARTIALLY supported — tiktoken (cl100k_base, an approximation of Claude's real tokenizer) estimates `system[0:3]` at ~14,213-14,217 tokens, roughly two-thirds of 21,023: same order of magnitude, consistent with cl100k's known undercount on structured content, not an exact match. Cross-session confirmation against another project's session log was out of scope of the data read for this investigation.

**Client-side vs proxy-side attribution (the fix-vs-document decision):**

Extended the probe with an `--original-log` mode: streams the 1.4GB original log line-by-line (never whole-file; a first-300-char regex peek for `flow_id` avoids a full JSON parse of the ~9MB-average irrelevant lines, matched entries via the shared `flow_id` field between the two dual-logs), then cross-checks each modified message index against the SAME index in the original (pre-proxy) incoming payloads of the two requests being compared.

Result: **all 20 image-eviction message-index cross-checks across REQ#133-137 and REQ#143-144 are CLIENT-SIDE** — the incoming (original) payload already shows the identical shrink at the identical index, before our proxy modification pass ever runs. The only 2 PROXY-SIDE hits are an unrelated, benign transform: `messages[278]`/`messages[283]` (role=`system`, trivial 1-character `"."` content) shrinks from `[{"type":"text","text":".","cache_control":{...}}]` (a single-text-block list) to a bare string `"."` — a content-shape normalization introduced by our own cache_control-stripping pass, not an image-adjacent change, and not a factor in the CR/CC collapse (single-digit char magnitude).

**Fix-vs-document verdict: DOCUMENT.** The image eviction that drives all three consecutive rebuilds is upstream/client behavior (Claude Code or the Anthropic client itself, before the request reaches our proxy) — there is no proxy-side code change that would prevent it. This closes the investigation without a mitigation action item.

**Classification:** Client-side, driven cache invalidation — a first-in-history-message mutation from progressive image eviction, distinct from every rebuild family in the earlier catalog (proxy dead, hot-reload, shape demotion, rule-file edit during session, server-side eviction, tool-marker movement on growth). New family: **client-side image eviction touching an early message index**.

**What We Cannot Answer Yet:**

- WHY the eviction triggers on this specific turn (a deliberate size/token-budget threshold being crossed vs. some other condition) — only WHERE it happens (client-side) and WHAT it does (byte-level effect) are proven from these logs.
- Whether the eviction targets the OLDEST images first as a strict FIFO, or some other prioritization — observed order (messages[0], then scattered indices up to [170], then partially [189], then [197] over subsequent turns) is consistent with an age-ordered sliding retention window but not conclusively proven.
- Whether cache-write propagation latency (Anthropic-side) also contributes to REQ#135/#136 not reading REQ#134's freshly-written cache even at message indices that WERE byte-identical between those requests — plausible for large `CC` writes read moments later, not provable from sent bytes alone.

**Mitigation:** None proposed — root cause is upstream of the proxy. If the eviction pattern recurs and needs future investigation, `dev/session_analysis/07_quartet_prefix_diff.py --req-range A-B --auto-detect --original-log <path>` reproduces this full analysis (segment attribution, image-block involvement, client-vs-proxy attribution, CR/CC reconciliation) on any session with the same three dual-log inputs (forwarded, original, session JSONL).

**Cache-control breakpoint markers are NOT derivable from the forwarded delta chain** (separate finding, applies to any future case built on this tooling): the delta hashing (`src/proxy/logging.py: _delta_hash` -> `_strip_cache_control`) strips `cache_control` before comparing elements, so a marker-only change (breakpoint moved, content unchanged) never enters `messages_delta` and a replayed message's `cache_control` can be stale. Use `04_cache_validation.py` against the single-log format, or the live proxy pane, for actual sent breakpoint placement — not the quartet reconstruction.

Ninth case overall, first one classified as client-side image eviction.
