# 2026-08-31 — msgs block sub-lines: display variant decision

## Context

Reading a real session (127 msgs) through `msgs`, the multi-block lines proved opaque at the
exact moment they mattered: a `3 blocks 3,862c` line hides whether the volume is thinking,
visible text, or tool input — and that distribution was the finding of the day (thinking-heavy
turns vs. dense visible summaries). The block data already existed on the timeline rows; only
the rendering discarded it.

## Variants weighed (in chat, 2026-08-31)

- A — indented sub-lines under the parent line, one per block, type + chars in the parent's
  columns. Chosen: it is the only compact form that carries per-block SIZES, and the size split
  (thinking vs. text vs. tool_use) is the entire point of looking.
- B — same as A with box-drawing tree characters. Rejected: same information, extra width, and
  the hierarchy is only one level deep, so the tree glyphs signal nothing.
- C — inline type abbreviations in the type column (`th+th+tu[Bash]`). Rejected: keeps one line
  per msg but drops the sizes and introduces a learned abbreviation grammar.
- D — inline with sizes in parentheses. Rejected: breaks column alignment and overflows on
  msgs with five or more blocks.

A `--flat` compatibility flag was considered and dropped — listings are short enough that the
extra lines cost nothing, and sub-lines are whitespace-indented so `grep '^\['` and
`grep -v '^──' | grep -v '^ '` recover the old shapes exactly.

## Outcome

Implemented in `src/dual_log_cli/render.py` (labels reused from `timeline._block_label`,
alignment derived from the parent line's column constants); details and verification in the
milestone's commit and `src/dual_log_cli/DOCS.md`.
