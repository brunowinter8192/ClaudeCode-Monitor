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

## Outcome

No strip was implemented. Either the current CC version no longer injects the
tool, or the existing strip pipeline already covers it upstream. If a future CC
version reintroduces SendUserFile, it re-enters the strip-followup line as a new
entry in this area.
