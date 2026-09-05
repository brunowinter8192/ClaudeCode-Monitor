# strip_sr.py — env-context `_ENV_CONTEXT_RE` replay (CC 2.1.258 fix)

Corpus: `/Users/brunowinter2000/Documents/ai/monitor-cc/src/logs/dual_log` — 14 `*_original.jsonl` files, 2916 request entries. Counts below are UNIQUE (file, exact inner text) — dual-logs are cumulative snapshots, the same block reappears in every later request of the same session.

## Before / after

| Bucket | Before (old regex) | After (new regex) |
|---|---|---|
| env-context, stripped | 7 | 10 |
| env-context, left — PURE (no `# claudeMd`, genuinely broken by CC 2.1.258) | 3 | 0 |
| env-context, left — BUNDLED (`# claudeMd` + `# userEmail` in one block, preserved by design) | 3 | 3 |
| CLAUDE.md context, preserved (no userEmail hint at all) | 0 | 0 |

Newly stripped by the fix (present in "after" stripped, absent from "before"): 3 distinct blocks — all are the PURE-left bucket moving to stripped (the CC 2.1.258 bug this task fixes); the BUNDLED bucket is unchanged before/after (3/3 in this corpus) because `_ENV_CONTEXT_RE.fullmatch` correctly never matches a block that also carries real `# claudeMd` project content — that block must stay preserved whole, losing the CLAUDE.md content would be worse than leaving ~250-550 bytes of unstripped env-context noise inside it.

CLAUDE.md-context-preserved (no userEmail hint) count is IDENTICAL before/after by construction — the fix only widens `_ENV_CONTEXT_RE`, it does not touch `_PRESERVE_PREAMBLE` or its position; 0/0 in this corpus window is a property of which sessions happen to be in the current rotating `dual_log/` window, not evidence the guard never fires (see `process-docs/strip_efficacy_audit/2026-07-28_template_catalog_efficacy_cc205.md`, which measured 2 pure CLAUDE.md-preserved occurrences in a different corpus window).
