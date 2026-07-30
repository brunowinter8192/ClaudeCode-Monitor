# 2026-07-30 — Announced-action-strands-the-turn: resolved in the chat-output rule

## The defect

The orchestrator ended an exchange paragraph with an announcement of the next action ("Ich merge
jetzt.", "Ich schicke jetzt den Recap.") and then stopped, forcing a user "ok" before the announced
call ran. Mechanism: the exchange was treated as terminal, so no action frame and no tool call could
follow it in that turn — an announcement placed there structurally guaranteed the action could not
execute. It read as asking permission for work already approved.

## Resolution as of this date

Fixed in the chat-output rule (`~/.claude/shared-rules/opus/chat-output.md`), not by banning the
announcement but by narrowing which exchange kind is terminal:

- Exchanges are split into **informative** (finding, measurement, conclusion, disagreement,
  recommendation, announced next step) and **decision-required** (scope, direction, architecture
  trade-off, irreversible action). Only the decision-required kind ends the turn; an informative
  exchange CONTINUES — tool calls, action frames and further exchanges follow in the same turn.
- Stated directly: "An announced action is executed in the same turn" — an announcement is never
  the last thing in a turn, the tool call follows it immediately.
- The failure mode is named explicitly in the not-allowed list: "announced action as turn end,
  executed only in the next turn".

So candidate (a) from the original framing (forbid future-tense announcements in exchange prose)
was NOT taken. The announcement stays legal; what changed is that the exchange carrying it no
longer terminates the turn.

## Verification boundary

Verified by reading the rule text as of 2026-07-30. Behavioural adherence across sessions is not
measured here — the rule is the artifact, its application is observed per turn.
