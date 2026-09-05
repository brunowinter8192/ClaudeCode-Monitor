# CC 2.1.258 Strip Follow-Up

## Structural change in CC 2.1.258

Two new built-in tool defs shipped, neither in `TOOL_BLOCKLIST`: `SendFeedback` (5618 chars) and
`ListAgents` (1227 chars). Confirmed via the newest main-session recorded log at the time
(`api_requests_opus_monitor_cc_1788611156_original.jsonl`, `src/logs/dual_log/` in the main
checkout — untracked data, not duplicated into worktrees): the original (pre-strip) payload tools
list carried 15 entries —

```
Agent, Artifact, AskUserQuestion, Bash, DeferredToolPlaceholder, Edit, ListAgents, Read,
ReportFindings, ScheduleWakeup, SendFeedback, Skill, ToolSearch, Workflow, Write
```

10 of those (`Agent`, `Artifact`, `AskUserQuestion`, `DeferredToolPlaceholder`, `ReportFindings`,
`ScheduleWakeup`, `ToolSearch`, `Workflow` — 8 already in `TOOL_BLOCKLIST` from earlier
follow-ups, see `19_cc176_strip_followup.md` / `20_cc223_strip_followup.md`) leave `SendFeedback`
and `ListAgents` as the only two passing through unstripped.

A sweep of the full corpus present at the time (`src/logs/dual_log/*_original.jsonl`, 6 files: 5
main-session, 1 older worker session predating this CC build) showed `SendFeedback`/`ListAgents`
at identical byte sizes (5618/1227 chars) across all 5 main-session logs that carried them at all
— stable tool defs, not per-session variation.

## Fix

`SendFeedback`, `ListAgents` added to `TOOL_BLOCKLIST` (`src/constants.py`), same mechanism as
every prior entry in this line — `_strip_unused_tools` (`src/proxy/tools.py`) needed no change,
it already filters purely off the frozenset.

As of this fix, running the real `_strip_unused_tools` on the newest main-session log's original
payload left exactly `{Bash, Edit, Read, Write, Skill}` (0 MCP tools injected in that particular
request — the desired end state "+ proxy-injected MCP tools" is a superset clause that happened to
be empty here, same observation as `20_cc223_strip_followup.md`).

Sanity-checked, corpus-wide this time rather than single-session: no `tool_use` invocation of
either newly-blocked name exists anywhere across all 6 `_original.jsonl` files' messages (a
stripped tool def with a live `tool_use` reference in history would 400 the API on replay) — 0
hits across all 6 files.

## Verification

`dev/proxy_instrumentation/p7_blocklist_258_probe.py` — real `_strip_unused_tools` +
`TOOL_BLOCKLIST` against the newest main-session original log, plus a corpus-wide live-`tool_use`
scan (adapted from `p4_blocklist_223_probe.py`'s single-session probe, generalized to glob
`src/logs/dual_log/*_original.jsonl` at run time rather than hardcoding one session stem, since the
milestone asked for corpus-wide numbers). 4/4 checks passed: exact post-strip set, both new names
actually removed, 6 files scanned with 0 live `tool_use` hits for either name, blocklist
membership. Report: `dev/proxy_instrumentation/md/blocklist_258_probe_report.md`.

Regression: `dev/proxy/test_strip_fix.py` 217/217 passed, unchanged mechanism (this suite covers
the SR/message-strip pipeline, not the tool blocklist directly, but is the standing regression
check every prior follow-up in this line also ran).
