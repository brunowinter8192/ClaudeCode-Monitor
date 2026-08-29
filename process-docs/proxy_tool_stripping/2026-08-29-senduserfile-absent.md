# SendUserFile Absent from CC Toolset — No Strip Needed (2026-08-29)

## Context

Earlier CC versions were observed injecting a SendUserFile tool (proactive file
push to an away user; params files/caption/status/display). It was queued as the
next candidate in the per-version strip-followup line, to receive the same
treatment as the other removed built-ins.

## Observation

As of 2026-08-29, a live proxy-pane inspection of a claude-f request showed
SendUserFile nowhere in the request toolset. The request carried 5 kept tool
defs (Bash, Edit, Read, Skill, Write) and 8 stripped ones (Agent, Artifact,
AskUserQuestion, ReportFindings, ScheduleWakeup, ToolSearch, Workflow,
DeferredToolPlaceholder). SendUserFile appeared in neither group.

## Raw-Payload Verification

The pane is a processed view, so the raw `src/logs/dual_log/*_original.jsonl`
logs (raw CC payload before `apply_modification_rules`) were checked directly.
Across the 8 newest `_original` logs (main sessions, workers, and cross-project
sessions; e.g. 186 requests in the largest file), SendUserFile appeared 0 times
as a `tools[].name` def and 0 times in `system`. Every grep hit was
conversation-text echo inside `messages`: a GitHub issue title quoted in a
tool_result, and another project's rule text that mentions the tool by name.
The newest request's full toolset was the 13 defs listed above — no
SendUserFile.

## Outcome

No strip was implemented, and none is possible: the current CC version does not
inject the tool at all, upstream of the proxy. The strip pipeline plays no role
in its absence. If a future CC version reintroduces SendUserFile, it re-enters
the strip-followup line as a new entry in this area.
