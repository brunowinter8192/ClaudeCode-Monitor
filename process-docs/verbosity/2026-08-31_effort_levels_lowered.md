# 2026-08-31 — Effort levels lowered: proxy override discovered, opus→low, fable→medium

## Context

Continuing this area's line on overworking/overthinking pain: turns felt slow, splintered
across excessive tool calls, with heavy thinking volume. Hypothesis in chat: the model is
calibrated for lower effort than it was running at.

## Vendor-doc findings (monitor-cc-reference, as of 2026-08-31)

- From Opus 4.7 onward the model respects effort levels strictly; at `low` and `medium` it
  scopes work to what was asked instead of going above and beyond — directly matching the
  observed overworking symptom.
- Effort affects ALL tokens including tool calls: lower effort means fewer tool calls, which
  addresses the splintering directly.
- Caveat for Opus 5 specifically: effort controls thinking volume, NOT visible response
  length; response length is steered by prompt. For text verbosity, prompting (positive
  concision examples over prohibitions) is the documented lever.
- Vendor recommendation for agentic work is `xhigh`/`high`, with the explicit note to step
  down to `medium`/`low` wherever evals show quality holds — i.e. lowering is sanctioned as
  a measured decision, which matches this area's open measurement goal.

## Key discovery: the proxy forced effort high for every model

`~/.claude/settings.json` carried `"effortLevel": "medium"`, but the proxy's `model_params`
in `~/.claude/shared-rules/proxy_rules.json` overwrote `output_config.effort` per request to
`"high"` for claude-fable-5, claude-opus-5, and claude-sonnet-5 alike. So the client-side
setting was dead, and all pain observations up to this date were made at effort HIGH, not
medium. Any effort experiment must be made at the proxy layer to be real.

## Change (as of 2026-08-31)

In `proxy_rules.json` `model_params`: claude-opus-5 `high`→`low`, claude-fable-5
`high`→`medium`, claude-sonnet-5 left at `high` (no user instruction). `effortLevel` in
settings.json was also set to `low`, knowingly redundant given the proxy override.

## Evidence base from session inspection (duallog, wise2627)

- A sampled orchestrator session showed ~2.5k-char thinking blocks preceding trivial filing
  decisions — thinking-heavy, while the visible Exchange text was dense and format-conform.
- Hypothesis recorded: the pain is primarily thinking volume plus tool-call splintering, less
  the visible reply text, because the communication rules already discipline the latter.
- Context volume has a rules-driven component independent of effort: one 312-char question
  pulled ~35k chars of context (CLAUDE.md injection, deferred-tools list, a rules-mandated
  28-issue full read). Lowering effort does not touch that class.

## Open

The area's measurement goal stands: compare post-change turns against this date's baseline
before judging whether low/medium hold quality.
