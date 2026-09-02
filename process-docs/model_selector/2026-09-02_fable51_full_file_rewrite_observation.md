# Observation: Fable 5.1 Tends to Rewrite Whole Files (2026-09-02)

Single observation, recorded without an issue. Not established as a real problem.

## What was seen

In the first orchestrator session on `claude-fable-5-1` after the 2026-09-01 config switch, the
user noticed the orchestrator producing a complete file instead of the edited part only. The
rule already exists in `~/.claude/shared-rules/global/tool-use.md` ("Prefer Edit for existing
files, because Write resends the full content every time"), so this is not a missing rule but a
model tendency under an existing rule.

## Why it is parked, not escalated

- One occurrence, in one session, as of 2026-09-02.
- Source-code writing goes through workers, which run on Sonnet per `model_selection.json`.
  The orchestrator writes only docs and skills directly, so the surface where the tendency can
  cost anything is small.
- Expected impact: token cost on doc edits, no correctness risk, since Write on a read file
  produces the same end state as Edit.

## If it recurs

Signals worth counting before acting: Write calls on files already present in the session where
an Edit would have covered the change, in orchestrator sessions on Fable. Levers, in order: a
sharper wording in the tool-use rule, then a hook that rejects Write on a path already read in
the session when the diff is small relative to file size.
