# Tool Comparison Goes Name-Based — Index Comparison Cannot Tell a Removal From Its Renumbered Neighbours, 2026-09-03

Continues this area's sys/tool delta line work
(`2026-09-03_msgs_sys_tool_delta_lines.md`, `2026-09-03_sidecar_exclusion_and_delta_hash_fix.md`).
Review of that second entry's Measurement 3 caught a third defect in the same feature:
`skill-help_1788343931` REQ 196 — the corpus's one confirmed real prompt-cache rebuild — printed
`tool[Skill] changed` and `tool[Write] changed`, but neither tool's own definition had moved.

## What actually happened at REQ 196

`counts.tools` drops 6→5 between REQ 195 and REQ 196. Diffing the raw `tools_delta` by hash
confirmed: `SendFeedback` (index 3 at REQ 1) is simply gone from the list, and every tool after it
renumbered down one slot — `Skill` index 4→3, `Write` index 5→4 — with byte-identical content at
both ends (hashes `7f5d2a9538`/`99a890965a` unchanged). The proxy computes its own delta per
POSITION (`src/proxy/logging.py`'s `_build_forwarded_delta`: `i >= len(prev_tools) or
curr_tool_hashes[i] != prev_tools[i]`), so both renumbered slots legitimately differ from what used
to occupy that position and both land in `tools_delta` — the write side is not at fault here, it
genuinely cannot know a tool moved rather than changed, because it has no name-keyed state, only a
positional list. Index-based read-side comparison inherited the same blindness.

## The fix: track tools by name, not position

`_tool_lines` (renamed from the shared `_delta_lines`, which now only handles system blocks under
`_sys_lines`) keeps two pieces of running state across the whole family walk:

- `name_by_index` — the FULL current index→name map, not just the indices a given request's own
  delta touches. Untouched indices carry their name forward from the previous request.
- `hash_by_name` — content hash last seen under each NAME, independent of position.

A removal is inferred as a pure set difference: the names active immediately BEFORE this request
(`name_by_index`'s values, snapshotted before applying the delta) minus the names active AFTER
(every valid index `0..counts.tools-1`, taken from the delta where touched, carried forward
otherwise). A name in that difference prints `tool[Name]  removed` — no chars column at all, since
there is no current content to size (`render._req_delta_lines` special-cases `chars is None`
accordingly). A touched index whose new occupant is a name that was ALREADY active with the SAME
hash — the pure-shift case — prints nothing. A touched index whose name is new, or whose hash
differs from what was last recorded under that name, still prints `new`/`changed` exactly as before.

**Blind spot, stated rather than guarded against:** this is a set difference over names, not a trace
of which specific edit happened. It cannot distinguish "tool X removed" from "tool X removed AND a
DIFFERENT tool whose name happens to already be active elsewhere in the list was added in the SAME
request" — both scenarios show only the net membership change. This needs two tool-list edits
landing in one API call; not observed anywhere in the 24-session corpus swept for this work, so it
is documented in DOCS.md rather than defended against with unobserved-failure complexity.

## Measurements (as of 2026-09-03, corpus on disk)

**skill-help_1788343931 REQ 196, before → after:**
```
        tool[Skill]               327c  changed          ->          tool[SendFeedback]        removed
        tool[Write]               402c  changed
```
Exactly the expected single line, nothing else — verified via `msgs skill-help_1788343931 584 586`.

**Corpus-wide tool-line tag counts, before vs. after** (24 non-haiku sessions, every family's own
first request's untagged full listing counted separately since it carries no tag to compare):
before — 172 untagged (first-request listings) + 2 `changed`; after — 172 untagged (unchanged) + 1
`removed`, 0 `changed`, 0 `new`. Only `skill-help_1788343931` differs; every other session's tool
lines are byte-identical to before this change (all 28 other sessions: only the untagged is_first
count, unchanged).

**Byte-identity**, via `git stash`: `sessions` identical; `msgs`/`search`/`expand` identical on
`gcommit-umlaut_1788367120` (234 lines), `devproxy-docs_1788377950` (183 lines),
`rag-chunking_1788333660` (514 lines) and the largest session `opus_jobscraper_1788347399` (1463
lines) — none of these four ever exercises a tool removal or index shift, so their tool lines were
never touched by index-based comparison's bug and stay untouched by this fix too.
`skill-help_1788343931`'s `msgs` output is the only one that changed: 1297 lines → 1296 (the two
false `changed` lines collapse into one true `removed` line).

## Verification

New regression suite `dev/dual_log_cli/tests/test_tool_name_comparison.py` (14 checks): a removed
tool is named and its shifted-but-unchanged neighbour prints nothing (the exact false-positive
pattern); a tool whose OWN content changes at its new position still prints `changed`; a brand-new
name prints `new`; a name removed and later reintroduced is `new` again (presence is judged against
the immediately preceding request's active set, not the tool's own history); the exact skill-help
shape (6→5 tools, one removed from the middle) reproduced end to end via `request_boundaries`; and
`render._req_delta_lines` skips the chars column entirely for a `removed` item. Existing suites
re-run unchanged: `test_msgs_blocks.py` (13/13), `test_msgs_overlay.py` (13/13),
`test_msgs_usage.py` (13/13), `test_sidecar_exclusion.py` (13/13),
`test_msgs_sys_delta.py` (26/26 — its own tool fixtures never shift an index, so this revision does
not touch it; a docstring note points to the new file for name-based coverage).

## Relevant Symbols / Paths

- `_sys_lines`, `_tool_lines`, `request_boundaries` (`src/dual_log_cli/timeline.py`)
- `_req_delta_lines` (`src/dual_log_cli/render.py`)
- `_build_forwarded_delta` (`src/proxy/logging.py`) — read only, confirms the write side's
  per-position comparison is the origin of the renumbering, not a bug there
- Ground truth: `src/logs/dual_log/api_requests_worker_25c51a2e_skill-help_1788343931_forwarded.jsonl`,
  the sonnet-family request pair at REQ 195/196 (`counts.tools` 6→5)
