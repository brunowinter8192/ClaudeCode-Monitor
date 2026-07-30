# 2026-07-30 — process-docs cross-references: area-level allowed, file-level still banned

## Decision

The blanket ban on process-docs cross-references is lifted at AREA granularity:

- **Allowed:** referencing another area as a folder — `process-docs/<area>/`.
- **Still banned:** referencing an individual `.md` entry by path. A specific entry is found by RAG
  over `process-docs` + browsing the folder, not by a hardcoded path.
- **Unchanged:** an issue's `Area:` field names the PRIMARY area only.

## Reasoning that carried the decision

Two arguments, both from the user:

1. **Rot was the ban's main cost-side risk, and it does not apply.** process-docs entries are
   write-once dated snapshots. A referenced area folder does not get superseded or deleted the way
   a referenced file could, so a cross-area pointer does not decay into a broken link.
2. **The reference is what makes cross-area work assessable.** Without it, there is no explicit
   record that a follow-up task draws its foundations from a DIFFERENT area — which is exactly the
   judgement the new-area-vs-existing-area criteria require, and the entry point for cross-area
   research.

File-level references stay banned because that is where the rot argument does hold, and because
folder-level pointing already carries the thematic signal.

## Rule change applied

`~/.claude/shared-rules/global/documentation.md` § process docs — the "No cross-references to other
process-docs" rule was replaced by "Cross-references point at AREAS, never at single entries",
stated without justification prose per the user's explicit instruction on rule-text density.
