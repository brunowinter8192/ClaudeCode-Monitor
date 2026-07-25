# Doc-Compliance Sweep — dev/ Folder Renames + Source-Path Sync (2026-07-25)

A follow-up iterative-dev-doccheck pass aligned three remaining `dev/` area names with their matching `process-docs/<area>/` counterparts (doc-only renames had already been committed separately) and fixed the source-side references (script constants, path strings) that a pure doc-side pass cannot touch.

## Renames + source-path fixes

- `dev/bead_tracker_chain/` → `dev/bead_tracker/` (matches `process-docs/bead_tracker/`). Fixed the self-referencing usage-comment path in `smoke.py`, the `dev/DOCS.md` bullet, and one reference in `process-docs/bead_tracker/chained_bd_parse.md`.
- `dev/coteditor/07_reports/` → `dev/coteditor/log/`. The folder holds `.log` capture output, not `.md` reports — a type-named folder (`log/`), not the generic `NN_reports` numbering scheme used elsewhere in this codebase's older dev scripts. Fixed `_REPORTS_DIR` in `07_space_jump_probe.py` and path mentions in both `process-docs/coteditor/2026-07-24_*.md` entries. A probe instance may still be writing to the old `07_reports/` path on the user's machine at time of this pass — not managed, only the repo-side path made consistent.
- `dev/worker_status_probes/`: verified on disk — `csv/` and `md/` already exist, `01_reports/` does not (an earlier pass had already split raw CSVs into `csv/` and the comparison report into `md/`, but two `process-docs/menubar_session_status/*.md` files still cited the old `01_reports/` path). Fixed both references to point at the real `csv/`/`md/` split.

## rag_helpfulness gap

`dev/rag_helpfulness/` contained only `md/01_inventory.md` with no producing script and no `DOCS.md` (the extraction logic that produced the inventory was superseded by `dev/tool_use_analysis/rag_query_audit.py`, which never got backported into this folder). Added a minimal `DOCS.md` documenting the gap rather than reconstructing the missing script.

## German-language artifact sweep

`grep -rlE ' (und|oder|nicht|wurde|dass) ' dev/*/md/` surfaced 17 files. 15 are in `dev/tool_use_analysis/md/` — these quote captured German user turns / pane content inside baseline reports and were left untouched (captured data, never edited per the write-once rule for forensic records). 2 were genuine hand-written German analysis prose and were translated in full:

- `dev/cc_internals/md/20260428_env_var_inventory_v2.1.121.md` — full env-var inventory report (methodology, ~70 env-var rows across 6 categories, recommendations, open questions) was entirely German prose with English identifiers; translated end-to-end.
- `dev/hook_error_correlation/md/2026-05-29.md` — German section headers and analysis prose (e.g. "Zählung", "Join-Analyse", table column "Grund") translated; embedded captured content (shell commands, hook error messages, timestamps) left verbatim since those are session data, not authored prose.

While correcting `dev/hook_error_correlation/DOCS.md` for the `md/` output-path rename, also fixed two unrelated pre-existing DOCS.md defects discovered in the same file: a leftover German word ("historisch" → "historical") and a stale `## Reports` section pointing at `reports/YYYY-MM-DD.md` instead of the actual `md/YYYY-MM-DD.md` output path already documented two sections above it.

## Consequence for future audits

A future German-artifact grep over `dev/*/md/` returning ~15 hits (all under `dev/tool_use_analysis/md/`) is EXPECTED — captured baseline data, not missed translation work. Any NEW hit outside that folder is a real defect.
