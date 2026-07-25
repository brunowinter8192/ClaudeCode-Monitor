# dev/rag_helpfulness/

## Role
Holds the 2026-05 rag-cli call inventory report — a scan of proxy JSONL logs for rag-cli invocations (query text, char count, ok/fail). The extraction logic that produced it was superseded by `dev/tool_use_analysis/rag_query_audit.py`; no producing script remains in this folder.

## Files
- `md/01_inventory.md` — rag-cli call inventory across 61 scanned proxy JSONL files (27 with calls).
