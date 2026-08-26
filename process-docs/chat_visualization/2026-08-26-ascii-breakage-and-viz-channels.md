# Chat visualizations — ASCII breakage in the CC UI, working channels, open question

Date: 2026-08-26

## Area question

Which visualization forms make sense for daily orchestrator chat output, and which are unreliable enough to ban.

## Findings as of 2026-08-26

Tested live in a Posts session, two channels:

### Rendered files (worked)

- matplotlib 3.10.8 is available system-wide; graphviz is installed as `dot`; `mmdc` (mermaid CLI) and plotly are NOT installed.
- A matplotlib bar chart (PNG, 150 dpi) and a graphviz digraph rendered cleanly and were delivered into the chat via SendUserFile with display=render.
- This channel is reliable for anything continuous (curves, scatter, time series) and for topology (graphs, flows).

### ASCII in chat (broke)

- A Unicode bar chart (full blocks `█`, one glyph per unit, counts right-aligned) rendered correctly in a fenced code block.
- A box-and-arrow state diagram broke in the CC UI: the bottom arrow line lost alignment (screenshot evidence from the user, 2026-08-26). The diagram mixed box-drawing characters with emoji (⏱, 🛑, ⟲).
- Suspected mechanism: emoji render at double width in the UI's monospace font, so every character after an emoji on the same line shifts, and vertical connectors below stop lining up. Unverified beyond the one observation, but the user reports this class of breakage "very often".

## Decision as of 2026-08-26

Daily chat output stays at the pure text level (prose, markdown tables, fenced-block bar charts at most). Box-and-arrow ASCII diagrams in chat are parked until this area answers what subset survives the UI.

## Open questions

- Does a restricted charset (ASCII + box-drawing only, zero emoji, zero double-width glyphs) make box diagrams reliable?
- Where is the cut between "fenced-block text chart is fine" and "render a PNG instead"?
- Are there vendor guides (Anthropic docs / prompting guides) worth capturing into a reference collection on producing visualizations? A capture of code.claude.com/docs was considered and parked in the same session.
