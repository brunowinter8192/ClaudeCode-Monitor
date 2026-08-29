# 2026-08-29 — Adopting the proxy pane's grammar: msgs, blocks, and block-level classifiers

Twelfth entry of this area, and the second revision of a decision recorded in it. The CLI spoke of
"turns" with an aggregated type per turn; the proxy pane speaks of messages made of blocks. Two
vocabularies for one thing, and the CLI's was the lossy one. This aligns them.

## Three changes, one motive

**The unit is the msg.** `expand`'s positional, every header, every `--help` line and the docs now
say msg — one API message, whose parts are blocks. Internal identifiers still say `turns` in places
(`data["turns"]`, `hit["turn"]`); the split is deliberate and cheap to live with, and the package
gotchas record that new output says msg.

**Overview rows follow pane grammar.** A single-block msg keeps its type inline
(`#713 18:17:02 user text 952`). A multi-block msg shows a block COUNT plus total chars and ALWAYS
lists its blocks as `[i] type chars` sub-rows (`#715 18:17:38 assistant 3 blocks 1.6k`), with the
aggregated type gone. That label named only one of the blocks it stood for, and printing it beside
a count would have been the same half-truth in a new place.

**`--only` matches block types.** A msg is selected when its role matches and ANY of its blocks
matches the type; a selected msg always shows all of its blocks, in both modes.

## What the block-level move actually changed

Measured on the same window (msgs 683-743 of `opus_websearch_1787924727`):

| filter | old (aggregated type) | new (any block) |
|---|---|---|
| `thinking` | 5 msgs `[694, 709, 712, 721, 730]` | 11 msgs, adding `[697, 700, 715, 724, 727, 733]` |
| `user/text` | 6 msgs `[695, 707, 710, 713, 722, 731]` | 8 msgs, adding `[692, 719]` |

The six new `thinking` msgs are assistant msgs aggregated as `tool_use` that carry reasoning — the
thinking the old filter could not see. The two new `user/text` msgs aggregate as `tool_result` and
`task-notification` while carrying text blocks.

The task's checklist expected `--only user/text` to stay at 6 rows. It does not, and that is the
change working: an expectation written against the old semantics cannot survive the semantics
being replaced. Recorded here rather than quietly satisfied by pinning the old behaviour.

## Vocabulary, measured again

Block types across a 12-session sweep: `text` 1548, `system` 2163, `thinking` 1175, `tool_use` 1872,
`tool_result` 1872, `task-notification` 112, `image` 25. `image` is new to the vocabulary — it never
appeared while matching ran on aggregated message types, because no message aggregates to it.
Together with the str-content pseudo-types (`system`, `system-reminder`, `task-notification`,
`command-message`) that makes nine accepted types.

Block-count distribution from the same sweep, which is what makes the two row shapes worth having:
5340 single-block msgs against 1384 multi-block ones, the largest carrying 18 blocks.

## Plumbing

`iter_block_texts` now yields the msg's full `block_types` list instead of its aggregated `type`, so
`search` filters by the same predicate `expand` uses. Without that, `search --only text` would have
meant "a block of type text" while `expand --only text` meant "a msg aggregating to text" — one flag
with two meanings, which is worse than either meaning alone.

## Verification

- `expand … 713 --only user/text` → 8 rows with the multi-block ones expanded into sub-rows.
- `expand … 715 --before 0 --after 0` → `▶ #715 18:17:38 assistant 3 blocks 1.6k` plus
  `[0] thinking 0`, `[1] text 1.5k`, `[2] tool_use 113`.
- `--only thinking` → 11 msgs (was 5).
- No `turn` wording in any `--help` or output string; the only live-output hit is log CONTENT
  ("vor zig turns" inside a user message), not the CLI's own wording.
- `--full --only thinking` selects by block and dumps all blocks of the selected msg.
- Regressions: sessions 61, timeline intact (`msgs 766 messages, 840.1k chars`), search unchanged,
  all three error paths still exit 2, 0 bytes stderr piped, corpus smoke over 61 sessions clean.
