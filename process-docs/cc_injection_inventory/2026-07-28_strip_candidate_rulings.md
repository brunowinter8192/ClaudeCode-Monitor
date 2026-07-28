# Strip-Candidate Rulings — 2026-07-28

The inventory audit produced 3 UNCLASSIFIED classes (CC-authored, no rule fires, no prior audit
ruling). Verdicts below were decided in discussion, not derived by the tool. Corpus at the time of
ruling: 5 sessions / 935 request entries / ~4GB, covering 3 project sessions and 2 worker sessions.

| Class | Distinct occ. | Cum. chars | Ruling |
|---|---|---|---|
| `sys[1]` — `"You are Claude Code, Anthropic's official CLI for Claude."` | 5 | 53,124 | STRIP |
| `sys[0]` — `x-anthropic-billing-header: cc_version=…; cc_entrypoint=…; cch=…; cc_prev_req=…` | 875 | 114,216 | KEEP |
| CC's `[Image: source: <path>.png]` attachment notation | 6 | 59,363 | KEEP |

## sys[1] — STRIP

57 chars, byte-identical in every request of every session, opus and worker families alike, never
touched by any proxy function. Redundant: `sys[2]` is fully replaced with our own injected rules,
which already establish the agent's role. Implemented the same session (separate entry in this area).

## sys[0] billing header — KEEP despite being the largest candidate

Largest by cumulative cost precisely because it changes every request (`cch` + `cc_prev_req` differ
per call). That volatility is also why it stays: a Reddit binary-RE + MITM analysis
(r/ClaudeCode `1s7mitf`) reports the CC standalone binary performing a native-layer string
replacement on `cch=00000` inside the serialized request body — after `JSON.stringify`, before TLS,
invisible from JS. The same analysis attributes ~$0.04/request cache-rebuild cost to that
replacement hitting the wrong occurrence. Editing this line risks breaking prompt caching for a
114k-char saving spread over 875 requests. Not worth it without a dedicated cache-impact
investigation of its own.

## `[Image: source: <path>]` — KEEP

CC appends the source path as text alongside the actual image block. The path is actionable: it lets
a later Read reach the file. Same category as the two standing KEEP rulings — the Read truncation
notice and the `<persisted-output>` wrapper — both preserved because they name the route back to the
full content. Stripping it would save 59k chars and cost the ability to re-open a screenshot.

## What the short list itself says

The headline result is the length of the list, not its contents. Across ~4GB of payload and 5
sessions, every distinguishable text class resolved to: 21 already covered by a rule, 3 deliberately
preserved, 1 injected by our own proxy, 7 our own content — and 3 unhandled, of which one was worth
stripping. No unknown reminder template, no new noise family, no unhandled wrapper. The strip surface
is materially more complete than the audit's premise assumed.

A caveat on generality: the 5-session window is what the version-purge janitor
(`claude_proxy_start.sh:_janitor_version_purge_jsonl_logs`, deletes dual-logs >60min old on any
proxy source change) leaves behind during active proxy development. Rare CC states — plan mode,
disallowed-tool variants, error paths — are underrepresented by construction. The tool is re-runnable
against a larger window whenever one accumulates.
