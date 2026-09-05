# CC 2.1.258 TOOL_BLOCKLIST extension probe

Newest main-session log: `api_requests_opus_monitor_cc_1788611156_original.jsonl`
Corpus files scanned for live tool_use: 6

| case | pass | detail |
|---|---|---|
| post_strip_set_is_exact | PASS | log=api_requests_opus_monitor_cc_1788611156_original.jsonl orig=['Agent', 'Artifact', 'AskUserQuestion', 'Bash', 'DeferredToolPlaceholder', 'Edit', 'ListAgents', 'Read', 'ReportFindings', 'ScheduleWakeup', 'SendFeedback', 'Skill', 'ToolSearch', 'Workflow', 'Write'] kept=['Bash', 'Edit', 'Read', 'Skill', 'Write'] (non-MCP kept: ['Bash', 'Edit', 'Read', 'Skill', 'Write'], want ['Bash', 'Edit', 'Read', 'Skill', 'Write'], mcp_extra=[]) |
| newly_blocked_actually_removed | PASS | removed_names contains all of ['ListAgents', 'SendFeedback']: True (removed=['Agent', 'Artifact', 'AskUserQuestion', 'DeferredToolPlaceholder', 'ListAgents', 'ReportFindings', 'ScheduleWakeup', 'SendFeedback', 'ToolSearch', 'Workflow']) |
| no_live_tool_use_for_newly_blocked_corpus_wide | PASS | files scanned: 6, tool_use hits for ['ListAgents', 'SendFeedback']: 0  |
| blocklist_contains_new_entries | PASS | ['ListAgents', 'SendFeedback'] subset of TOOL_BLOCKLIST: True |

## Overall: ALL PASS