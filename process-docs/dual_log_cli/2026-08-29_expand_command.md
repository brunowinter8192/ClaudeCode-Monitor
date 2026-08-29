# 2026-08-29 — expand: two reading modes around one turn, and the drill it replaces

Eighth entry of this area. `search` finds a turn index; `timeline` prints a whole session. Between
them there was nothing that answers "what happened AROUND turn 721", and the single-turn drill
(`timeline <s> --turn N --full`) could only show one turn with no surroundings at all. `expand`
fills that gap and absorbs the drill.

## Two modes, one command

**Overview** — `expand <session> <turn> [--before N] [--after N]`. Classifier lines only: turn
index, role, message type, chars. No block sub-lines, no previews, no filtering. The timeline's REQ
boundary markers are interleaved, and the anchor carries a `▶`. Every turn in the window is listed.

**Read** — `expand <session> <turn> --full --before N --after N [--only CLASSIFIER]`. The complete
block content of the selected turns, optionally narrowed to one classifier.

## The floor, and why the two modes disagree about defaults

Overview `--before`/`--after` default to 30 **and have a hard floor of 30** — an explicit
`--before 5` or `--before 0` is raised, only larger values are honoured. The mode's whole purpose is
to show what surrounds a turn; a caller who narrows it to ±2 gets a view that looks like context but
is not, and nothing in the output would reveal the choice. Raising it silently is the deliberate
trade: the floor is documented in `--help` and the rendered header always states the real window
(`window turns 691-751 of 0-765, anchor #721`), so the effective bounds are never hidden.

Read mode is the mirror image: both bounds are **required explicit numbers with no floor**. Nothing
sensible can be defaulted when the output is measured in kilobytes per turn, and a missing bound
exits 2 naming the required form rather than guessing. `--full --before 0 --after 0` is therefore
the single-turn read, which is exactly what the deleted drill did.

## --only matches the message-level classifier

The filter compares against the turn's **role** (user/assistant/system) or its **message type**
(tool_result, tool_use, thinking, text, task-notification, …) — the same two values the overview
lines print. A turn whose message type is `tool_use` usually also carries `thinking` and `text`
blocks, and `--only thinking` deliberately does not select it. Overview and read mode stay in the
same units; a block-level filter would need its own flag and a different output shape.

`--only` without `--full` exits 2 instead of being ignored, because overview mode promises every
turn in the window and a silently-dropped filter would break that promise invisibly.

## The removal, and a contrast worth keeping

`timeline --turn N [--full]` is gone: the argparse flags, the `_run_timeline` branch, and
`render_turn_full` (verified unreferenced across `src/`, `dev/` and `process-docs/` before
deleting). `full_turn` survives — `expand --full` is now its only caller.

This break is **loud**: `timeline <s> --turn 5` exits 2 with `unrecognized arguments: --turn 5`.
That contrasts with the `search` argument flip recorded in this area, which stays silent because
both old arguments remain structurally valid under the new signature. Same area, same day, two
breaking changes with opposite failure modes — deleting a flag is safer to ship than reordering
positionals, and that is the reusable lesson rather than a fact about either command.

## Verification

- `expand websearch_1787924727 721` → **61 classifier lines** (turns 691-751), REQ markers
  interleaved, anchor `▶ #721` marked.
- Floor: `--before 5` and `--before 0` both yield `turns 691-751`, identical to the default;
  `--before 100` yields `turns 621-751`.
- `--full --before 2 --after 2` on turn 713 dumps turns 711-715 complete.
- `--only tool_result` over the 7 turns 713-719 returns exactly the one tool_result turn (#716),
  cross-checked against that window's classifier listing; `--only system` selects by role; a
  filter with no match prints `no turn in the window matches --only thinking`.
- `--full --before 0 --after 0` prints exactly turn 721.
- Error paths all exit 2 with a naming message: `--full` with no bounds or one bound, negative
  bounds, out-of-range turn, `--only` without `--full`, unknown session.
- Windows clamp at both ends: anchor #2 → `turns 0-32`, anchor #764 → `turns 734-765`.
- Regressions: `timeline`, `sessions` (61), `search` unchanged; piped output 0 bytes on stderr.

## An artifact in the data, not the renderer

Several assistant turns dump as `block 0 thinking 0 chars` followed by an empty line: the payload's
thinking block carries an empty text with only a signature. The renderer prints what is there. Worth
knowing before someone reads an empty block as a bug in `expand`.
