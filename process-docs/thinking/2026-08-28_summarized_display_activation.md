# 2026-08-28 — Activating summarized thinking for main sessions: two independent gates

## Goal

Make the thinking text visible for main sessions on every model, and render it in the proxy
pane behind its own expander inside a REQ. The pane's thinking line reads
`[0] thinking  text: 0c sig:1,848c` — the signature proves the model thought, the empty text
is what this work targets.

The parked worker-visibility spec in this area (2026-05) proposed a CLI-flag route for workers
and never ran; its Phase B is the pane-side half of this task.

## Why the CLI-flag route does not apply to main sessions

Main sessions run through the proxy, which injects the `thinking` object into every forwarded
payload itself (`src/proxy/inject_helpers.py`). No launcher flag is needed.

Important detail found while reading that module: `model_params` in `proxy_rules.json` is
checked for **key presence**, and when present it is the *only* path consulted — `model_override`
and `model_override_worker` are ignored entirely, even though both are still in the file and
still carry `display: "omitted"`. The lookup is an exact match on `payload["model"]`, with no
family bucketing. So only the three `model_params` entries matter, and the table is keyed by
model ID, not by main-vs-worker context — main and worker sessions cannot be separated here.
Sonnet workers inherit whatever `claude-sonnet-5` gets.

## The mechanism: header and body parameter are mutually exclusive

Two independent gates must both be open. This is the core finding and it was not obvious.

**Gate 1 — the body parameter.** Per Anthropic's thinking documentation, `display` takes exactly
two values, `"summarized"` and `"omitted"`, and is valid alongside `type: "adaptive"`. `"omitted"`
is the default on Fable 5, Mythos 5, Opus 5, Sonnet 5, Opus 4.8 and 4.7; the docs state explicitly
that on Fable 5 and Mythos 5 the setting works the same as on other models. So the parameter is
correct for all three model IDs in the table.

**Gate 2 — the `redact-thinking-2026-02-12` beta header.** Claude Code pushes this header when
all of the following hold (deminified in anthropics/claude-code#31326 and #32810):

```js
hasThinking && modelSupportsInterleavedThinking(model) && !isVerboseMode()
  && getSettings().showThinkingSummaries !== true
  && getFeatureFlag("tengu_quiet_hollow", false)
```

`showThinkingSummaries` is undefined by default, so `undefined !== true` passes and the header
goes out. The server then strips the thinking text regardless of anything in the body.

The two gates are treated as mutually exclusive **by the client itself**: anthropics/claude-code#86959
reports that when `display` is set, the redact beta is spliced back out of the betas array
(`if(cc&&Yl){...ji.splice(...)}`). That is the strongest available evidence that the header wins
over the body parameter when both are present — a proxy-side body injection alone would be
neutralised.

Consistent with that, #49268 comment 3 records that `showThinkingSummaries: true` **alone** did not
work on Opus 4.7 (header removed, but `display` still unset, so the model default `omitted` won),
while `--thinking-display summarized` **alone** did work end-to-end on a first-party Max
subscription — because the flag sets `display` *and* triggers the header removal in the same code
path. Neither switch is sufficient on its own; the flag only looked sufficient because it operated
both gates.

## Measurement on this system

The latest `_forwarded` dual-log for this project (`api_requests_opus_monitor_cc_1787915025`,
model `claude-opus-5`) carried `redact-thinking-2026-02-12` in its `anthropic_beta` list on every
logged request — 85 hits in one file — and `~/.claude/settings.json` contained no
`showThinkingSummaries` key at all. Both gates were closed.

Note that the session ran `claude-opus-5`, not `claude-fable-5` as `model_override` would suggest,
which is a second consequence of `model_override` being dead config.

## Subscription auth is not a blocker

A candidate blocker surfaced in the web pass (#52376, re-filed as #83925: "subscription sessions
get an empty thinking field where API-key sessions get text"). It does not apply here: #83925 scopes
itself to *cloud* sessions at claude.ai/code via the mobile app or browser, and #49268 comment 3
records the flag working on a first-party Max subscription in a local terminal.

## Cost and latency

From the pricing table in the thinking docs: billing is identical under both `display` values —
the full internal thinking tokens are billed either way, and summary generation is free. What
changes is latency: `omitted` exists specifically for faster time-to-first-text-token, since the
server skips streaming thinking tokens entirely. The docs describe the summarization overhead as
minimal because summaries stream as they arrive.

One-off cost not in the original gap list: any change to the thinking configuration invalidates
prompt-cache breakpoints, since the configuration is rendered into the prompt. That is a single
expensive request at the switch, not a standing cost.

## What was changed

- `~/.claude/settings.json` — added `"showThinkingSummaries": true` (opens gate 2).
- `~/.claude/shared-rules/proxy_rules.json` — `display` flipped from `"omitted"` to `"summarized"`
  in all three `model_params` entries: `claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`
  (opens gate 1). Both files validated as parsable JSON after the edit.

`model_override` and `model_override_worker` were left at `"omitted"` deliberately — they are
unreachable while `model_params` exists, and changing dead config would silently alter the legacy
fallback's behaviour.

Both files live outside every repository, so neither appears in any commit.

## Verified and unverified

Verified: both files parse and carry the intended values; `proxy_rules.json` is mtime-reloaded by
`rules_config`, so the body parameter takes effect on the next request without a restart.

Unverified: everything downstream. `settings.json` is read by Claude Code at startup, so gate 2
stays closed until a fresh session, and the header was still present in the log at the time of
writing. The check that remains is, on a new session: `redact-thinking-2026-02-12` absent from
`anthropic_beta` in the newest `_forwarded` entry, and the pane's thinking line showing
`text:` greater than zero.

The claim that the header overrides the body parameter rests on the spliced-out-beta reading of
the client code plus the two issue reports above. It has not been tested directly here, and the
cheapest direct test is exactly the verification above: if the thinking text stays empty after a
restart with both switches set, the reading is wrong.

## Open work

- **Proxy-side header strip** — remove `redact-thinking-2026-02-12` from the outgoing
  `anthropic-beta` header in the proxy, making the behaviour independent of Claude Code settings
  and of CC updates. Conditional: only needed if the settings route fails, but it is the more
  durable route either way. `src/proxy/addon.py` already parses `anthropic_beta` out of the HTTP
  request header for the forwarded log, and header modification is established in the
  `process-docs/proxy_header_mods/` area.
- **Pane expander** — the summary must sit behind its own expander *inside* a REQ, alongside the
  existing sys/tools drill-downs, not print inline. `src/proxy_display/render_messages.py`'s
  `_render_block_spans` currently emits `full_text` for every block unconditionally, and
  `src/proxy/message_summary.py` already populates `full_text` with the thinking text — so once
  the text is non-empty it will flood an expanded REQ with no toggle. A nested drill-down pattern
  already exists in that package (`search.py` names fields/beta/tools-desc states).

Neither has been started, and the pane work needs a populated summary first to size against.
