# 2026-08-29 — A context filter for the sessions listing

Fourth entry of this area. The `sessions` listing already had an inclusive start-day window; this
adds the other axis a reader actually navigates by — which project or worker a session belongs to.
Usage is `sessions [context] [--since D] [--until D]`, with the context as an optional positional
and all active criteria combined with AND.

## Matching rule

Case-insensitive substring against the **rendered** context value, i.e. `opus/websearch` or
`worker/duallog`, not the bare name. Two consequences, both wanted:

- `websearch` matches `opus/websearch` and `duallog` matches `worker/duallog`, which is the
  everyday case.
- `opus/` and `worker/` become selectors for a whole family. Measured: 31 + 32 = 63, an exact
  partition of the corpus — a useful check that nothing falls between the two prefixes.

Matching against the name part alone would have lost the second property for no gain.

## One filter function, not two

`filter_sessions` was extended from `(sessions, since, until)` to
`(sessions, context="", since="", until="")` rather than gaining a sibling function. The AND
semantics then live in one loop instead of being implied by the call order of two functions, and
the early-out for "no criteria at all" stays a single condition. The call site passes keywords,
because a fourth positional is easy to misorder.

Filtering stayed in `discovery` — the render-only property established when the table was trimmed
holds unchanged.

## The one asymmetry

A session whose start timestamp is empty is dropped by an active DATE filter (it cannot be placed
on a calendar) but kept by a CONTEXT filter (its context is known either way). The tempting
simplification — one "skip incomplete sessions" guard covering both — would silently hide sessions
from a context query that has nothing to do with time. Written into the function comment and the
package gotchas, because it is invisible at the call site.

## Verification

Corpus at the time of the change: 63 sessions.

- `sessions websearch` → **6** rows, all `opus/websearch`, 2026-08-25 through 2026-08-28.
- `sessions websearch --since 2026-08-28 --until 2026-08-28` → **2**:
  `api_requests_opus_websearch_1787942049`, `api_requests_opus_websearch_1787924727`.
- Both cross-checked against a direct pass over `list_sessions` rather than the filter under test.
- `websearch` / `WEBSEARCH` / `WebSearch` → 6 / 6 / 6.
- `duallog` → 1 (`worker/duallog`), `opus/` → 31, `worker/` → 32.
- `wise2627 --since 2026-08-28` → 5 of that context's 9, so a context works with one date flag alone.
- `zzznope` → `no sessions found`, exit 0. `websearch --since nope` → exit 2, the date error still
  raised before any directory scan.
- Plain `sessions` unchanged at 63 rows; `timeline` and `search` re-checked and unaffected.

## Note for anyone re-running these numbers

The corpus rotates. This session count is 63 and the oldest start day is 2026-08-24; the
2026-08-23 session that appeared in this area's opening entry has since been removed by the
proxy's own count-30 log rotation (`src/claude_proxy_start.sh`). Absolute counts here are
snapshots, not invariants — the ratios and the partition check are the parts that carry over.
