# P2 — pending_bg_state probe run (2026-08-06T20:28:38.912501+00:00)

**Result: 35/35 checks passed**

| Check | Result |
|---|---|
| state file created | PASS |
| task_arm1 present | PASS |
| status == pending | PASS |
| armed_at present | PASS |
| no cleared_at yet | PASS |
| status == cleared | PASS |
| cleared_at present | PASS |
| armed_at preserved from arm | PASS |
| no state file created for worker context | PASS |
| status still cleared after 5 resightings post-restart | PASS |
| cleared_at unchanged (never re-cleared/re-armed) | PASS |
| orphan TN creates a cleared tombstone | PASS |
| tombstone has no armed_at (never armed by us) | PASS |
| later ack does not arm the orphan-tombstoned id | PASS |
| dict insertion order is descending (test validity) | PASS |
| final status == cleared | PASS |
| armed_at IS present -> ack was processed before TN despite insertion order | PASS |
| no 'no_prior_arm' artifact — arm genuinely happened first | PASS |
| seed write succeeded | PASS |
| tombstone older than 24h pruned | PASS |
| tombstone younger than 24h kept | PASS |
| pending entry NEVER pruned by proxy, however old armed_at is | PASS |
| corrupt state file -> no raise | PASS |
| real ProxyAddon.request() still forwards with a corrupt state file | PASS |
| real request path armed task_e2e_arm | PASS |
| request still forwarded | PASS |
| real request path cleared task_e2e_clear | PASS |
| worker_context derived correctly | PASS |
| no state file created via real worker request | PASS |
| default (is_main=False) wording unchanged | PASS |
| main wording starts with the sharpened message | PASS |
| main wording differs from default wording | PASS |
| main wording explicitly mentions going idle | PASS |
| main wording explicitly mentions this task's ID | PASS |
| main wording still carries the recovered ID line | PASS |
