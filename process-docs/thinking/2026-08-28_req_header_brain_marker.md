# 2026-08-28 — Brain marker on the proxy pane REQ header (delta semantics)

## Goal

Give the proxy pane's collapsed REQ header row a green 🧠 badge, alongside the existing `strip`/
`inject` word badges, when the messages that request newly adds contain at least one `thinking`
content block — mirroring the token pane's per-request 🧠 indicator (`format/token_format.py`,
`_call_thinking_meta`), shifted by one request (a request's own delta is the assistant's response
to the *previous* request).

## Delta vs. cumulative — the choice that matters

Two candidate semantics for "does this request carry thinking":

- **Delta:** only the messages `messages_delta` newly added/changed for *this* request.
- **Cumulative:** any `thinking` block anywhere in the full accumulated message list at the time
  of this request.

Cumulative is uninformative once one thinking-bearing turn has happened: the accumulated list only
grows, so cumulative stays true for every subsequent request in the conversation, badging almost
the entire pane green regardless of what that specific request actually did. Delta answers "did
*this* request's own new content carry thinking" — the only version worth glancing at in a
collapsed row.

## Implementation

New flat field `has_thinking_delta` (bool), computed once in
`forwarded_parser._extract_forwarded_fields` from a new `delta_messages` param — the summarized
dicts for only the messages this request's `messages_delta` touched (built alongside the existing
`new_summaries` accumulator inside `_parse_forwarded_log`'s per-line loop). It is baked into the
entry at parse time, same lifecycle as `messages_total_chars`, so it survives the deque-window
`messages=None` truncation for entries outside `PROXY_MESSAGES_KEEP_LAST` — a render-time
computation over `entry['messages']` would have silently gone blank for older rows, which is why
this had to be a flat field rather than computed in the renderer.

`render_turn._build_req_header_line` appends a third `tag_badge` slot, `{GREEN}🧠{SOFT_RESET}`,
after `strip`/`inject`, gated on `entry.get('has_thinking_delta', False)`. Boolean only — no
count, no signature-char threshold, unlike the token pane's `🧠Nk` — that richer variant was a
deliberate non-goal here, kept out to avoid duplicating the response-side indicator's job.

No padding-math change was needed. `_build_req_header_line`'s copy-button right-align already sums
`_cell_width(ch)` over every character of the ANSI-stripped header, and `utils._cell_width`
already classifies U+1F9E0 (🧠) as 2 cells via its `0x1F000–0x1FAFF` emoji-block check — the
existing generic computation absorbed the new character without a special case.

## Deliberate edge case: `is_first`

A proxy-session restart mid-conversation re-sends the entire message history in one
`forwarded_delta` line with `is_first=True` — there is no narrower "newly added" slice to point
`delta_messages` at in that case, so the whole message list stands in as the delta for that one
request. Consequence: the badge can light up once on such a restart even though no assistant turn
just happened immediately before it. This was kept rather than special-cased (e.g. suppressing the
badge on `is_first`) because the restart genuinely re-delivers thinking-bearing history to the
model in that single request — flagging it is arguably still correct, just for a different reason
than the steady-state case. Documented inline at both the `is_first` branch and the
`_extract_forwarded_fields` docstring rather than silently accepted.

## Measurement — and why the raw counts moved

Verified via `dev/thinking/render_brain_badge.py`, which parses a real `_forwarded` dual-log
through the actual `_parse_forwarded_log` → `_build_req_header_line` path (not a
reimplementation) and reports per-request brain presence plus an independent cumulative
cross-check.

Against `src/logs/dual_log/api_requests_opus_monitor_cc_1787931850_forwarded.jsonl` as it stood at
implementation time: 48 opus requests, 13 haiku, 26/48 opus carrying 🧠 under delta semantics,
0/13 haiku. Independent cumulative cross-check: 47/48 opus (only the very first opus request, made
before any assistant turn exists, is cumulative-negative).

The milestone spec that kicked this work off cited 38 opus requests / 23 delta-positive on the
same file, with cumulative giving 37. The file is a live, gitignored runtime log
(`src/logs/dual_log/`) that keeps accumulating requests as the app is used in later sessions — its
mtime at measurement time was minutes old, well after the spec was written. Rather than force the
stale numbers, the pattern was cross-checked instead: cumulative-minus-one-negative-request holds
in both the spec's 37/38 and this session's 47/48, which is the structural signature delta-vs-
cumulative predicts (only the very first request in a conversation, before any assistant turn
exists, can be cumulative-negative). The absolute counts differ; the shape that proves delta is
the narrower, informative variant reproduces exactly.

Zero haiku requests carried a `thinking` block in their delta in this data — consistent with haiku
sidecar calls never running extended thinking — so no explicit haiku/standalone gate was added to
the badge condition; it is a natural consequence of the data, not a special case in the code.

## Not touched

Expanded-view block rendering (a separate milestone covers the thinking-text expander inside a
REQ — see the `2026-08-28_summarized_display_activation.md` entry in this area for the underlying
gate that makes thinking text non-empty at all), the token pane, and strip/inject behavior.
