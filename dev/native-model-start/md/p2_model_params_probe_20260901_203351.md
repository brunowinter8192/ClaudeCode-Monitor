# P2 — model_params probe run (2026-09-01T20:33:51.266507+00:00)

**Result: 55/55 checks passed**

| Check | Result |
|---|---|
| opus family: injected=True | PASS |
| opus family: model REWRITTEN to claude-fable-5 (legacy behavior) | PASS |
| opus family: thinking applied | PASS |
| opus family: effort applied via output_config | PASS |
| opus family: max_tokens applied | PASS |
| sonnet family: injected=True | PASS |
| sonnet family: model REWRITTEN to claude-sonnet-5 (legacy behavior) | PASS |
| haiku family: no legacy section -> untouched, injected=False | PASS |
| injected=True | PASS |
| model field UNCHANGED (still claude-fable-5, not rewritten) | PASS |
| thinking applied | PASS |
| effort applied via output_config | PASS |
| max_tokens applied | PASS |
| claude-opus-5 hit: injected=True, model untouched | PASS |
| claude-sonnet-5 hit: injected=True, model untouched | PASS |
| injected=False | PASS |
| payload identical (same dict values) | PASS |
| suffixed id 'claude-opus-4-8[1m]' vs table key 'claude-opus-4-8' -> exact match FAILS | PASS |
| injected=True (from model_params, not legacy) | PASS |
| model NOT rewritten despite legacy model_override.model=claude-fable-5 being present too | PASS |
| thinking/effort/max_tokens match model_params values | PASS |
| empty model_params {} -> injected=False (no entry for this model) | PASS |
| model NOT rewritten to claude-fable-5 — legacy path never consulted despite being 'enabled' | PASS |
| empty {} entry for a matched model -> injected=False, untouched | PASS |
| partial entry (effort only): injected=True | PASS |
| effort applied | PASS |
| thinking NOT added (key absent from entry) | PASS |
| max_tokens UNCHANGED from original payload (key absent from entry, not injected) | PASS |
| no raise propagated | PASS |
| injected=False, payload untouched | PASS |
| (a) first request applies config1 (effort=low) | PASS |
| (a) first request applies config1 (max_tokens=32000) | PASS |
| (a) fixated dict now holds an entry for claude-fable-5 | PASS |
| (b) SAME fixated dict: config2 change ignored, still effort=low | PASS |
| (b) SAME fixated dict: config2 change ignored, still max_tokens=32000 | PASS |
| (b) injected still True on the pinned replay | PASS |
| (c) fresh dict applies config2 (effort=high) | PASS |
| (c) fresh dict applies config2 (max_tokens=128000) | PASS |
| (d) legacy first call: injected=True | PASS |
| (d) legacy first call: model REWRITTEN (byte-identical to unfixated Test 1) | PASS |
| (d) legacy first call: thinking applied | PASS |
| (d) legacy first call: effort applied | PASS |
| (d) legacy first call: max_tokens applied | PASS |
| (d) fixated dict now holds an entry for claude-opus-4-8 | PASS |
| (d) SAME fixated dict: still injected despite config now disabled | PASS |
| (d) SAME fixated dict: model still rewritten to claude-fable-5 | PASS |
| miss: injected=False on first call | PASS |
| miss: fixated dict still records the (empty) snapshot | PASS |
| miss stays pinned: still injected=False despite the entry now existing | PASS |
| miss stays pinned: payload2 unchanged | PASS |
| load failure: injected=False, no raise | PASS |
| load failure: nothing pinned for claude-fable-5 | PASS |
| next call retries live and succeeds: injected=True | PASS |
| next call retries live and succeeds: effort=medium applied | PASS |
| next call retries live and succeeds: now pinned for claude-fable-5 | PASS |
