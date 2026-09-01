# 2026-09-01 — config-side switch to claude-fable-5-1 (orchestrator edits, outside the repo)

Companion note to the same-day milestone entries in this area (model-ID + per-model
effort/max_tokens rows) and to `process-docs/param_fixation/`. Records the direct edits to the
user config under `~/.claude/shared-rules/` that preceded and seeded the menubar work — these
files are user config outside every repository, so the edits live in no commit.

## What was edited, and when

- `model_selection.json`: `main` switched `claude-fable-5` → `claude-fable-5-1` (worker stayed
  `claude-sonnet-5`). Done by hand in chat BEFORE the menubar knew the new ID — the Models tab
  at that point still cycled a fixed 3-value list, which is what motivated the menubar
  milestone in the first place.
- `proxy_rules.json`: new `model_params` entry
  `"claude-fable-5-1": {"thinking": {"type": "adaptive", "display": "summarized"}, "effort": "high", "max_tokens": 64000}`,
  added alongside the untouched existing entries. The implementing worker later found this
  entry on disk and correctly read it as pre-seeded for the task.

## Effort-value research folded into the same work

A web check (litellm's Anthropic effort documentation, scraped 2026-09-01) settled the allowed
effort values as `low`/`medium`/`high` plus a model-gated `max` (validation error on
non-supporting models); `high` is documented as byte-equivalent to omitting the parameter.
Both findings shaped the menubar milestone: `max` was deliberately excluded from the panel's
cycle, and `high`/`64000` became the display default for a model without a `model_params`
entry (a missing entry means no injection, which the API treats as `high`).

## Rebuilds

The menubar bundle was rebuilt and installed twice this day from merged `integration` state
(after the param-rows milestone and after the panel-polish milestone), both runs detached per
the standing codesign-budget note in this area. Orange rows and the Apply success flash were
left for a user live check at session end.
