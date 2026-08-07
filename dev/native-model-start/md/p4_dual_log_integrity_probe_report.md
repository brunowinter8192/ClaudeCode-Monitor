# Surface 2 — dual_log integrity + schema drift (issue #63, CC 2.1.223)

## Session: posts (`api_requests_opus_posts_1786051932`, 158 requests)

- Composition checks (blocks with recorded ops): 3290
- Failures: 0

## Session: websearch (`api_requests_opus_websearch_1786052022`, 123 requests)

- Composition checks (blocks with recorded ops): 1709
- Failures: 0

## Part A verdict — composition invariant

Total blocks checked across both sessions: 4999
Inv1 (C0 reconstruction) failures: 0
Inv2 (Cfwd reconstruction) failures: 0

## Part B — schema drift

- Top-level payload keys observed: ['context_management', 'diagnostics', 'fallbacks', 'max_tokens', 'messages', 'metadata', 'model', 'output_config', 'stream', 'system', 'temperature', 'thinking', 'tools']
  - NOT in the pipeline's explicitly-named set: ['fallbacks', 'thinking']
- System-block key-shapes observed: [('cache_control', 'text', 'type'), ('text', 'type')]
- Content-block `type` values observed: ['image', 'text', 'thinking', 'tool_result', 'tool_use']
  - NOT in message_summary.py's known set: ['image']

### Pass-through verification for unmodeled top-level keys

`apply_modification_rules`/`cache.py` build the modified payload via `dict(payload)` (shallow copy) + selective overwrite of `system`/`messages`/`tools` — any key not explicitly touched forwards byte-identical by construction. Verified directly per key below (not assumed):

| key | forwarded unchanged | sample value |
|---|---|---|
| `fallbacks` | True | `[{'model': 'claude-opus-5'}]` |
| `thinking` | True | `{'type': 'disabled'}` |

## Verdict

**FINDING**
- Composition invariant: CLEAN (0 failures / 4999 checks)
- New top-level keys (`['fallbacks', 'thinking']`): CLEAN — not specially modeled, but verified byte-identical pass-through, not dropped
- New content-block types: FINDING: ['image'] not in message_summary.py's handled set (falls through to its generic json.dumps summary — display-only gap, not a strip-pipeline correctness issue; composition invariant above already confirms no pass mishandles these blocks)