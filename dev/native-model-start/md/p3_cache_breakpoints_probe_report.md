# Surface 1 — cache breakpoint placement (issue #63, CC 2.1.223)

Real `ProxyAddon.request()` replay of all recorded requests, in chronological order, per session. Cache-control positions inspected on the actual bytes about to be sent.

## Session: posts (`api_requests_opus_posts_1786051932`, 158 requests)

- BP1 (system[2]) positions observed: [2] (want: exactly `[2]`) — missing on 0 requests []
- BP2 (last non-defer tool) positions observed: [4] — missing despite tools present on 0 requests []
- Content diffs at a common (non-tail-growth) message index, after cache_control + shape-churn normalization: 7
  - by category: {'session_bootstrap': 2, 'tail_draft_edit': 4, 'mid_turn_marker': 1}

| seq | msg_idx | category | prev snippet | curr snippet |
|---|---|---|---|---|
| 1 | 0 | session_bootstrap | `[{"type": "text", "text": "quota", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]` | `[{"type": "text", "text": "<session>\nwelche issues haben wir offen?\n</session>\n\nWrite the title ` |
| 2 | 0 | session_bootstrap | `[{"type": "text", "text": "<session>\nwelche issues haben wir offen?\n</session>\n\nWrite the title ` | `[{"type": "text", "text": "<system-reminder>\nAs you answer the user's questions, you can use the fo` |
| 23 | 44 | tail_draft_edit | `[{"type": "text", "text": "kein", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]` | `[{"type": "text", "text": "M1. bool bleibt auf jeden fall", "cache_control": {"type": "ephemeral", "` |
| 55 | 108 | tail_draft_edit | `[{"type": "text", "text": "[Image #7] hier muss alles au\u00dfer bash edit read write skill raus."},` | `[{"type": "text", "text": "[Image #7] hier muss alles au\u00dfer bash edit read write skill raus. wo` |
| 84 | 167 | tail_draft_edit | `ok also die hook message klarer machen, passt bekommt der worker als milestone mit` | `background done — check worker or other process
Output: /private/tmp/claude-501/-Users-brunowinter20` |
| 135 | 274 | mid_turn_marker | `[{"type": "text", "text": ".", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]` | `The user sent a new message while you were working:
jetzt

This is how Claude Code surfaces messages` |
| 137 | 279 | tail_draft_edit | `[{"tool_use_id": "toolu_01FbZZRhr2CPYqFwJR7yymKW", "type": "tool_result", "content": "--- Result 1 (` | `[{"tool_use_id": "toolu_01FbZZRhr2CPYqFwJR7yymKW", "type": "tool_result", "content": "--- Result 1 (` |

## Session: websearch (`api_requests_opus_websearch_1786052022`, 123 requests)

- BP1 (system[2]) positions observed: [2] (want: exactly `[2]`) — missing on 0 requests []
- BP2 (last non-defer tool) positions observed: [4] — missing despite tools present on 0 requests []
- Content diffs at a common (non-tail-growth) message index, after cache_control + shape-churn normalization: 3
  - by category: {'session_bootstrap': 2, 'tail_draft_edit': 1}

| seq | msg_idx | category | prev snippet | curr snippet |
|---|---|---|---|---|
| 1 | 0 | session_bootstrap | `[{"type": "text", "text": "quota", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]` | `[{"type": "text", "text": "<session>\nwelche issues haben wir offen?\n</session>\n\nWrite the title ` |
| 2 | 0 | session_bootstrap | `[{"type": "text", "text": "<session>\nwelche issues haben wir offen?\n</session>\n\nWrite the title ` | `[{"type": "text", "text": "\n"}, {"type": "text", "text": "welche issues haben wir offen?"}]` |
| 97 | 202 | tail_draft_edit | `[{"type": "text", "text": " 22 zur Render-Wartezeit, erkl\u00e4re", "cache_control": {"type": "ephem` | `[{"type": "text", "text": "22 zur Render-Wartezeit, erkl\u00e4re. definitiv eine issue noch zum einf` |

## Verdict

**FINDING**

- BP1 stable at system[2] across both sessions: True (missing entirely on 0 requests total)
- BP2 stable (single tool-index value per session): True (missing despite tools present on 0 requests total)
- `session_bootstrap` (CC reshaping msg 0 in the first 2-3 requests): 4 — expected, one-time, not a caching concern
- `tail_draft_edit` (last/second-to-last message text changes — active user typing/editing before submit, correctly excluded from BP3's stable-prefix boundary): 5 — expected, not a real prefix bust
- `deep_history_mutation` (a message NOT near the tail changed content — CC itself reordering/inserting, e.g. an async bg-task notification landing before an already-sent user message): 0 — **real finding, CC-side behavior, not proxy-caused, not fixable from our side**
- `mid_turn_marker` (the flagged interaction: a mid-turn-user-message position, previously always "." pre-fix, now carries genuinely different real text across occurrences post the 2026-08-07 preserve-guard fix): 1 — **real finding, THE interaction this probe was built to check**
