# Doc & Structure Audit — All-Repos Run (2026-07-25)

On 2026-07-25 the iterative-dev-doccheck skill was applied across all active repos. This entry is the run record for the recurring maintenance task: it fixes WHEN each repo was last audited, so the next run can date-check against it via RAG.

## Repos audited this date

| Repo | Status |
|---|---|
| `Meta/ClaudeCode/cli/reddit` | DONE |
| `Meta/ClaudeCode/cli/gh` | DONE |
| `Meta/ClaudeCode/cli/websearch` | DONE |
| `Meta/ClaudeCode/cli/rag` | DONE |
| `Meta/iterative-dev` | DONE |
| `monitor-cc` | DONE (this session — findings below) |
| `trading` | STARTED, deferred to next session (context limit) |

## monitor-cc findings (this session)

- process-docs: 65 → 56 area folders. Consolidations: `message_queue` (from queue_panel_state_model + ghostty_native_delivery + a menubar_nspanel entry), `bead_tracker` (bead_tracker_chained + a menubar_nspanel entry), `menubar_session_status` (+worker_status_sensor_selection, +menubar_worker_detection), `hook_fp_audit` (+hook_false_positives), `proxy_noise_strip` (+hook_error_prefix_strip, +an audit_logging entry), `refactoring` (+pane_loop_pattern), `logging` (+proxy_version_log), new `ram_audit` (RAM research moved out of latency). All other folders passed the area test with a nameable driving question.
- 20 entry-to-entry cross-references replaced with descriptive in-area phrasing; own-repo issue refs and bead-tracking refs neutralized; 2 German filenames + all German prose translated.
- dev: area names aligned to process-docs (`cc_source_research`→`cc_internals`, `bead_tracker_chain`→`bead_tracker`, `coteditor/07_reports`→`coteditor/log`), reports moved into type-named folders (`md/`), missing `dev/rag_helpfulness/DOCS.md` added, 2 hand-written German dev reports translated (15 captured-data baselines under `dev/tool_use_analysis/md/` intentionally left — expected German-grep hits, not defects).
- DOCS.md: 39 stale LOC counts across 16 files synced to actual `wc -l`. No placement violations, no README.
- Issues: 3 open bodies brought to the lean format; #40 (area consolidation) closed by this run. The "8-12 target areas" in #40 was deliberately not forced — most folders carry their own driving question; 56 is the compliant count.

## trading state at deferral

Step 0 contact-layer question answered by the user: `concepts/` is the user-facing layer → EXCLUDED from every audit step (never relocate/translate/reformat). Initial scans done, nothing changed yet: 10 process-docs areas look structurally sound (numbered session entries per area, zero entry-to-entry cross-refs); German-language scan showed mostly false positives (domain term "Kenngröße", author names with umlauts, quoted German user statements) — a genuine prose check remains open. Next session: full Steps 1-5 on trading.

## Run-tracking convention

Each future all-repos (or single-repo) doccheck run writes its own dated entry into `process-docs/doc_compliance/` naming the repos covered and the date. The maintenance issue on monitor-cc points at this area; the entries are the history.
