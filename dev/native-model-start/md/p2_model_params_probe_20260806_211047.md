# P2 — model_params probe run (2026-08-06T21:10:47.912399+00:00)

**Result: 30/30 checks passed**

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
