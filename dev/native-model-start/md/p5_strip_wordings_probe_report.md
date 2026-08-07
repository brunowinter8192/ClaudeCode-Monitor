# Surface 3 — strip wordings on CC 2.1.223 (issue #63)

## Part A — fn_map census (real recorded dual-logs, historical record)

### posts (`api_requests_opus_posts_1786051932`)

| function | occurrences |
|---|---|
| `unknown` | 25 |
| `_apply_role_system_strip` | 19 |
| `_apply_bg_launch_ack_strip` | 13 |
| `_apply_bg_exit_strip` | 12 |
| `_strip_tool_descriptions` | 8 |
| `_apply_system_passes` | 5 |
| `_strip_unused_tools` | 5 |
| `_apply_interrupt_marker_strip` | 2 |
| `_strip_sys3` | 1 |
| `_apply_hook_prefix_strip` | 1 |

### websearch (`api_requests_opus_websearch_1786052022`)

| function | occurrences |
|---|---|
| `_apply_role_system_strip` | 16 |
| `_strip_tool_descriptions` | 8 |
| `_apply_hook_prefix_strip` | 6 |
| `_apply_system_passes` | 5 |
| `_strip_unused_tools` | 5 |
| `unknown` | 2 |
| `_apply_bg_exit_strip` | 2 |
| `_strip_sys3` | 1 |
| `_apply_final_sr_pass` | 1 |

- `_apply_bg_launch_ack_strip` fired wherever its marker text was present in the session's raw original log: True
  - marker present per session: {'posts': True, 'websearch': False} — websearch session genuinely never contains an explicit run_in_background launch-ack wording (0 raw occurrences confirmed) — not a strip-coverage gap, a data-availability fact
- TN/bg-completed replacement fired in both sessions (`_apply_first_pass` OR `_apply_bg_exit_strip`): True

## Part B — unstripped-wording sweep (real CURRENT code, replayed over all requests)

- Total marker occurrences checked (original content containing a known bg-marker): 1818
  - by marker: {'bg_launch_ack_wording1': 0, 'bg_launch_ack_wording2': 0, 'bg_completed_marker': 909, 'task_notification_tag': 909}
- Survived unstripped into forwarded output: 0

## Verdict

**CLEAN**
- fn_map census confirms both bg-launch-ack (wherever its wording occurs) and TN/bg-exit strips fired in the 223-era historical logs: True
- No bg-related marker wording survived unstripped into any forwarded payload (top-level content only, matching the real passes' own `_top_level_content_contains` gate — tool_result search-result content quoting these markers as prose is correctly excluded, not a strip target), against the CURRENT worktree code: True (0/1818 survived)
- Observation (not a finding, out of the two named strip targets' scope): the websearch session's backgrounded commands went through CC's 120s auto-timeout path ("Command did not complete within its 120s timeout and was moved to the background") rather than an explicit `run_in_background=true` launch-ack — a structurally different message our proxy does not strip (and was not asked to).