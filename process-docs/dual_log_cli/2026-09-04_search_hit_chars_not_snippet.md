# 2026-09-04 — Search hit lines show block chars instead of a snippet

The trigger: a real investigation searching the literal `undefined` across sessions. That search
returns dozens of hits, almost all of them prose that happens to contain the word — but one genuine
artifact was known to be a 9-character `assistant text` block, the literal string used AS a value
rather than mentioned in passing. The old hit line — `#706  assistant text  ×1  …some snippet…` —
carried no signal that would separate that one block from the rest without opening several of them
in `expand` first. The snippet showed context around the match; it never showed size.

## The redesign

A hit line now reads `#msg role label  chars` — msg index, role, block label, and the block's
original-payload chars, right-aligned like `label` already was, digit-grouped the same way `msgs`'
block sub-lines format the same value (`1,234c`). Two things came out entirely: the `×N` occurrence
counter and the whitespace-collapsed context snippet (`search.py`'s `_snippet`/`SNIPPET_RADIUS`).

```
#706  assistant text                9c
#84   user      text              158c
#8    assistant text              806c
```

With chars in the line, a 9-character hit next to a column full of three- and four-digit values is
immediately the odd one out — no expanding needed to rule out the rest.

## Where the chars value comes from

It was already sitting one function call away. `timeline.build_turns`/`full_turn` (what `msgs` and
`expand` read) both take a block's chars from `block.get("chars", 0)`, the field
`proxy/message_summary.py` already computes for every block. `search.find_matches` builds on
`timeline.iter_block_texts`, a separate generator over the same blocks that stayed text-only — no
chars key. Adding `"chars": block.get("chars", 0)` to its per-block yield (and
`summary.get("chars", 0)` to its no-blocks pseudo-block fallback, matching `build_turns`' own
fallback) closed that gap with no new computation: same source, same field, three consumers now
agreeing on what "this block's chars" means.

The hit unit did not need to change. A hit is still one (turn, block) pair — the chars value lives
on the block already, so nothing about the deduplication or the one-hit-per-block contract from
2026-08-29 moved.

## What came out of `find_matches`

`count = haystack.count(needle)` existed only to feed the `×N` marker; it is gone, replaced by a
plain `needle in haystack` membership test. `_snippet` and its `SNIPPET_RADIUS` constant are deleted
outright — nothing else called them (grepped `src/`, `dev/`; the only consumer of both `find_matches`
and `render_search` is `__main__.py`, one call site each, same as the 2026-08-29 header-trim entry
in this area found).

## Verification

- New suite `dev/dual_log_cli/tests/test_search_chars.py` (17 checks, all pass): a hit carries
  `chars` and neither `count` nor `snippet`; a block with 3 occurrences of the term still yields
  exactly one hit; the rendered line has no `×` and no snippet ellipsis; a 9-char hit and a 4,200-char
  hit are both present and readable with the right suffix; `no match` is untouched; two sessions with
  different label/chars widths still align (both hit lines end at the same column).
- All six pre-existing `dev/dual_log_cli/tests/*.py` files still pass unchanged (msgs/overlay/
  sys-delta/usage/sidecar/tool-name suites) — nothing in `render_msgs`, `render_expand_full` or
  `render_sessions` was touched by this change (checked via `git diff` on `render.py`: only
  `render_search` and its header comment differ).
- Real invocation, `search undefined monitor_cc --since 2026-09-03 --until 2026-09-03`: hit lines
  render across 7 sessions with aligned `#msg role label chars` columns and no `×`/snippet anywhere
  in the output; a follow-up run of `sessions`, `msgs <s> F T` and `expand <s> <msg>` against the
  same corpus produced ordinary, unaffected output.

## Note for a future reader

The occurrence count (`×N`) is now gone from `search` output entirely, not merely hidden — read the
2026-08-29 header-trim entry in this area if a granularity question comes up again: the one-hit-
per-block rule survives, only its `×N` marker is gone. If a reader ever needs to know exactly how
many times a term appeared inside one block again, that has to come back as an explicit field; there
is currently no trace of it left anywhere in the pipeline (`find_matches` no longer even counts it).
