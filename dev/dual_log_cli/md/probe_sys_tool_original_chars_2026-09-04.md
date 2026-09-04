# probe_sys_tool_original_chars

Run 2026-09-04T14:28:22Z against 47 sessions under `/Users/brunowinter2000/Documents/ai/monitor-cc/src/logs/dual_log`.

## 1. Whole-stripped tool coverage

**42 sessions carry a whole-stripped tool**, **336/336 whole-stripped name-instances found** in their own last `_original` request's `tools` list (0 missing).

## 2. Tool content stability across a session

**45 sessions checked** (>=2 `_original` requests); **0 tool-hash mismatches** comparing any earlier request's own tool-by-name content against the last request's.

## 3. System block stability (indices 1-3, family-first vs. family-last)

**44 sessions checked** (family with >=2 requests); **0 show a length or content mismatch** at indices 1-3 between the family's first and last request.

## 4. Recording pattern (whole-tool strip / system_delta, rendered family only)

**42 sessions** carry a whole-tool-strip or system_delta line for the rendered family; **1 have more than one such line**; **0** where the FIRST such line is not `is_first=True` (the known sidecar-interleave write-side artifact, see `process-docs/dual_log_cli/`, not a new finding).

