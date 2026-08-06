# CC 2.1.223 TOOL_BLOCKLIST extension probe

Session: `api_requests_opus_websearch_1786052022`

| case | pass | detail |
|---|---|---|
| post_strip_set_is_exact | PASS | orig=['Agent', 'Artifact', 'AskUserQuestion', 'Bash', 'DeferredToolPlaceholder', 'Edit', 'Read', 'ReportFindings', 'ScheduleWakeup', 'Skill', 'ToolSearch', 'Workflow', 'Write'] kept=['Bash', 'Edit', 'Read', 'Skill', 'Write'] (non-MCP kept: ['Bash', 'Edit', 'Read', 'Skill', 'Write'], want ['Bash', 'Edit', 'Read', 'Skill', 'Write'], mcp_extra=[]) |
| newly_blocked_actually_removed | PASS | removed_names contains all of ['Artifact', 'DeferredToolPlaceholder', 'ReportFindings']: True (removed=['Agent', 'Artifact', 'AskUserQuestion', 'DeferredToolPlaceholder', 'ReportFindings', 'ScheduleWakeup', 'ToolSearch', 'Workflow']) |
| no_live_tool_use_for_newly_blocked | PASS | tool_use invocations of newly-blocked names in session messages: (none) |
| agent_absent_from_forwarded | PASS | 'Agent' in forwarded tools_names (real pipeline, pre-existing blocklist entry): False (forwarded union=['Artifact', 'Bash', 'DeferredToolPlaceholder', 'Edit', 'Read', 'ReportFindings', 'Skill', 'Write']) — confirms strip fires; drill-down sighting was the intentional whole-stripped display row, not a strip-path bug |
| blocklist_contains_new_entries | PASS | ['Artifact', 'DeferredToolPlaceholder', 'ReportFindings'] subset of TOOL_BLOCKLIST: True |

## Overall: ALL PASS