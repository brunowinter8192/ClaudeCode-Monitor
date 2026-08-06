# CC 2.1.223 Strip Follow-Up

## Structural change in CC 2.1.223

Three new built-in tool defs shipped, none in `TOOL_BLOCKLIST`: `Artifact`, `ReportFindings`,
`DeferredToolPlaceholder`. Confirmed via the recorded session
`api_requests_opus_websearch_1786052022` (69 lines with a non-empty tools list in
`_original.jsonl`): the ORIGINAL (pre-strip) payload tools list is 13 entries —

```
Agent, Artifact, AskUserQuestion, Bash, DeferredToolPlaceholder, Edit, Read,
ReportFindings, ScheduleWakeup, Skill, ToolSearch, Workflow, Write
```

5 of those (`Agent`, `AskUserQuestion`, `ScheduleWakeup`, `ToolSearch`, `Workflow`) were already
in `TOOL_BLOCKLIST` from earlier follow-ups (`19_cc176_strip_followup.md` for `Workflow`). The
forwarded (post-strip) union across all 46 requests in the session was 8 names — the 13 minus
those 5 — confirming `Artifact`, `ReportFindings`, `DeferredToolPlaceholder` were passing
through unstripped.

## Fix

`Artifact`, `ReportFindings`, `DeferredToolPlaceholder` added to `TOOL_BLOCKLIST`
(`src/constants.py`), same mechanism as every prior entry — `_strip_unused_tools`
(`src/proxy/tools.py`) needs no change, it already filters purely off the frozenset.
Post-fix, running the real `_strip_unused_tools` on the session's original payload leaves
exactly `{Bash, Edit, Read, Write, Skill}` (no MCP tools were injected in this particular
session — the desired end state "+ proxy-injected MCP tools" is a superset clause that happens
to be empty here).

Sanity-checked no `tool_use` invocation of any of the 3 newly-blocked names exists anywhere in
the session's original messages (a stripped tool def with a live `tool_use` reference in history
would 400 the API on replay) — zero hits.

## Agent investigation (no bug found)

Live observation: `Agent` — already in `TOOL_BLOCKLIST` since before this session — still
appeared in the rendered tools drill-down of the live websearch pane. Investigated whether the
strip fails to fire (bug) or the drill-down renders the pre-strip side (no bug, just a finding).

Checked both sides of the real pipeline against the recorded session:
- Forwarded (post-strip) `tools_names` union across all 46 requests: `Agent` absent.
- Stripped dual-log (`_stripped.jsonl`) `tools_delta` for the relevant flow: `"Agent": {"whole":
  true}` — the strip DID fire and the removal was recorded.

The drill-down (`src/proxy_display/render_sections.py::render_tools`, the
`entry['_stripped_spans'].get('tools', {})` loop with `val.get('whole') and name not in
forwarded_names`) INTENTIONALLY renders a yellow `▶ name` row for every whole-stripped tool, so
the user can see what was removed. `Agent` showing up there is that row, not a leak of the
original payload into the forwarded request. No code change made.

## Verification (as of 2026-08-07)

`dev/proxy_instrumentation/p4_blocklist_223_probe.py` — real `_strip_unused_tools` +
`TOOL_BLOCKLIST` against `api_requests_opus_websearch_1786052022`. 5/5 checks passed: exact
post-strip set, all 3 new names actually removed, no live `tool_use` for any of them, `Agent`
confirmed absent from forwarded (supports the no-bug finding above), blocklist membership.
Regression: `dev/proxy/test_strip_fix.py` 150/150, unchanged.
