# CC Injection Inventory — 2026-07-27

Complete inventory of every distinguishable text class present in the raw request
payloads Claude Code sends, as captured in `src/logs/dual_log/*_original.jsonl`. Every
class found is listed regardless of frequency or size — this is an inventory, not a
top-N ranking.

## Methodology

**Dedup metric.** Payloads are cumulative snapshots (each request re-sends the full
conversation history), so a naive per-request scan overcounts by ~50x. Dedup key:
`(file, role, section, block_type, exact segment text)` — a refinement of the prior
codebase convention `(file, exact full message content)`, applied at SEGMENT granularity
(one text/tool_result block, not the whole message) so a message that combines one
repeated block with one genuinely new block correctly counts only the new block as a new
distinct occurrence. A repeat (same file, same exact segment text) contributes to
**cumulative char cost** (it is re-sent and re-billed every request) but not to
**distinct occurrences** (it is the same real event, not a new one).

**Segmentation.** Walks `system[0..3]` blocks, and every message's `content` — plain
string, `text` blocks, and `tool_result` blocks (`.content` string or list of `{type:
text}` sub-blocks). Does not descend into `tool_use.input`, `image`, or `document`
blocks. `tool_result` segments are attributed to the originating tool by resolving
`tool_use_id` against the preceding assistant `tool_use` block in the same payload.

**Origin classification.** For every `role=user` and `role=system` segment, a synthetic
single-block message is built matching the segment's real content shape and run through
the REAL production pipeline (`src/proxy/rules.py:apply_modification_rules`) — no
hardcoded marker lists. Chunks the pipeline actually removes are attributed to a rule
code via `strip_vocab.attribute_chunk` -> `COVERED`. The 3 known preserve-guarded cases
(Read-tool truncation notice, `<persisted-output>` wrapper, CLAUDE.md context SR) are
detected explicitly on the pipeline's residual output -> `KEEP`. `role=assistant` text is
never touched by any pass (verified: no `_apply_*` pass in `rules.py` gates on
`role=='assistant'`) -> `OURS` directly. Remaining `tool_result` residual is `OURS`,
bucketed by tool name. Remaining top-level user text uses a two-phase signature check:
normalized-text signatures >=40 chars with >=2 SUBSTANTIVELY DIFFERENT underlying variants
(exact text after stripping leading/trailing whitespace — this excludes a trailing-newline
shape artifact observed mid-corpus that would otherwise double-count long human messages)
are CC-authored templates (a human doesn't retype a whole sentence verbatim) ->
`UNCLASSIFIED`. Short recurring text (greetings/acks like "done", "ok"), whitespace-only
variants, and all singletons are folded into one `OURS` aggregate (genuinely unique or
naturally-repeated human prose). `system[2]`/
`system[3]` are unconditionally fully replaced by the proxy (`_apply_system_passes` /
`_strip_sys3`) -> `COVERED`; `system[0]`/`system[1]` are never touched by any proxy
function -> `UNCLASSIFIED`.

**Grouping.** A class = one rule code (COVERED), one known wrapper (KEEP), one tool name
or the single user/assistant-text bucket (OURS), or one normalized-template signature
(UNCLASSIFIED) — variable data (paths, IDs, counts, timestamps) normalized to placeholders
before signature comparison so e.g. 50 differently-IDed background-launch acks group into
one row.

**Known simplification:** role=user segments are tested independently per block (not as
part of the full multi-block message) — message-level gates that only look at a single
block's own content (all strip passes here) are unaffected; this does not change any
COVERED/KEEP decision in this corpus.

## Corpus

| File | Entries | Messages (raw) | Size |
|---|---|---|---|
| `api_requests_opus_monitor_cc_1785190126_original.jsonl` | 120 | 14724 | 44MB |
| `api_requests_opus_posts_1785150574_original.jsonl` | 485 | 185182 | 4GB |
| `api_requests_opus_trading_1785190224_original.jsonl` | 64 | 4094 | 21MB |
| `api_requests_worker_25c51a2e_injection-inventory_1785194474_original.jsonl` | 78 | 6422 | 39MB |
| **Total** | **747** | **210422** | **4GB** |

**Chosen metric — segments** (one text/tool_result block, used for all class counts below):
raw 161,863 / distinct 1,650 (98.1x overcount)  
**Prior codebase metric — whole messages** `(file, exact full message content)`, for comparison:
raw 210,422 / distinct 2,033 (103.5x overcount)

## Summary

**Total classes:** 37  |  **Total distinct occurrences:** 1,703  |  **Total cumulative chars:** 271,542,876

| Origin | Classes | Distinct occurrences | Cumulative chars |
|---|---|---|---|
| `UNCLASSIFIED` | 9 | 716 | 464,243 |
| `KEEP` | 3 | 8 | 2,722,635 |
| `COVERED` | 18 | 83 | 23,390,188 |
| `OURS` | 7 | 896 | 244,965,810 |

## UNCLASSIFIED (9 classes)

| Class | Role | Section | Block type | Distinct occ. | Cum. chars | Sample |
|---|---|---|---|---|---|---|
| Recurring unattributed user-message text ("Damit fehlt der Bezugswert, von dem eine Abweichung überhaupt gemessen würde. Du zahlst dann # Euro für "ein Zimmer und ") | `user` | `messages` | `text` | 2 | 192,740 | `Damit fehlt der Bezugswert, von dem eine Abweichung überhaupt gemessen würde. Du zahlst dann 558 Euro für "ein Zimmer und ein Bad", egal wie groß die sind. ja d…` |
| sys[0] billing header (x-anthropic-billing-header) | `—` | `system` | `system[0]` | 687 | 91,176 | `x-anthropic-billing-header: cc_version=2.1.205.312; cc_entrypoint=cli; cch=59049;` |
| Recurring unattributed user-message text ("[Image: source: <PATH> #-#-# um #.#.#.png]") | `user` | `messages` | `text` | 5 | 53,845 | `[Image: source: /Users/brunowinter2000/Desktop/Bildschirmfoto 2026-07-28 um 00.41.42.png]` |
| sys[1] "You are Claude Code..." intro line | `—` | `system` | `system[1]` | 4 | 42,408 | `You are Claude Code, Anthropic's official CLI for Claude.` |
| Unmatched <system-reminder> block ("<system-reminder>This file is already in your context Deferred tools appear by name in <system-remin") | `user` | `messages` | `tool_result_str` | 1 | 38,555 | `<system-reminder>This file is already in your context\nDeferred tools appear by name in <system-reminder> messages.\n<system-reminder>\n<system-reminder>\n^<sys…` |
| Recurring unattributed user-message text ("background done — check worker or other process Output: <PATH>/<UUID><PATH>") | `user` | `messages` | `text` | 14 | 28,593 | `background done — check worker or other process\nOutput: /private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/1cc1b0be-1b47-4b7d-9c40-77474a52…` |
| Unmatched <system-reminder> block ("<system-reminder> Auto mode still active (see full instructions earlier in conversation). Execute au") | `user` | `messages` | `tool_result_str` | 1 | 7,728 | `<system-reminder>\nAuto mode still active (see full instructions earlier in conversation). Execute autonomously, minimize interruptions, prefer action over plan…` |
| Unmatched <system-reminder> block ("<system-reminder> ## Auto Mode Active Auto mode is active. The user chose continuous, autonomous exe") | `user` | `messages` | `tool_result_str` | 1 | 5,502 | `<system-reminder>\n## Auto Mode Active\nAuto mode is active. The user chose continuous, autonomous execution. ...\n</system-reminder>\n` |
| Unmatched <system-reminder> block ("<system-reminder> ## Exited Plan Mode You have exited plan mode. ... </system-reminder>") | `user` | `messages` | `tool_result_str` | 1 | 3,696 | `<system-reminder>\n## Exited Plan Mode\nYou have exited plan mode. ...\n</system-reminder>\n` |

## KEEP (3 classes)

| Class | Role | Section | Block type | Distinct occ. | Cum. chars | Sample |
|---|---|---|---|---|---|---|
| CLAUDE.md context block (SR, preserve-guarded in strip_sr.py) | `user` | `messages` | `text` | 2 | 2,520,296 | `<system-reminder>\nAs you answer the user's questions, you can use the following context:\n# claudeMd\nCodebase and user instructions are shown below. Be sure t…` |
| <persisted-output> wrapper (Preview stripped by PP rule, wrapper kept) | `user` | `messages` | `tool_result_str` | 5 | 174,739 | `<persisted-output>\nOutput too large (93.1KB). Full output saved to: /Users/brunowinter2000/.claude/projects/-Users-brunowinter2000-Documents-ai-monitor-cc/1cc1…` |
| Read-tool truncation notice (role=system, preserved by RS guard) | `system` | `messages` | `plain_string` | 1 | 27,600 | `[Truncated: PARTIAL view — /Users/brunowinter2000/.claude/projects/-Users-brunowinter2000-Documents-ai-monitor-cc/1cc1b0be-1b47-4b7d-9c40-77474a526310/tool-resu…` |

## COVERED (18 classes)

| Class | Role | Section | Block type | Distinct occ. | Cum. chars | Sample |
|---|---|---|---|---|---|---|
| role=system message content — RS-covered ("The following deferred tools are now available via ToolSearch. Their schemas are NOT loaded — callin") | `system` | `messages` | `plain_string` | 3 | 6,411,064 | `The following deferred tools are now available via ToolSearch. Their schemas are NOT loaded — calling them directly will fail with InputValidationError. Use Too…` |
| role=system message content — RS-covered ("The task tools haven't been used recently. If you're working on tasks that would benefit from tracki") | `system` | `messages` | `plain_string` | 3 | 4,621,317 | `The task tools haven't been used recently. If you're working on tasks that would benefit from tracking progress, consider using TaskCreate to add new tasks and …` |
| role=system message content — RS-covered ("Note: <PATH> was modified, either by the user or by a linter. This change was intentional, so make s") | `system` | `messages` | `plain_string` | 5 | 4,037,761 | `Note: /Users/brunowinter2000/Documents/wise2627/wohnungssuche/buerge-vater/schriftverkehr.md was modified, either by the user or by a linter. This change was in…` |
| sys[3] session/environment context block — fully replaced with '.' (`_strip_sys3`) | `—` | `system` | `system[3]` | 4 | 3,846,603 | `Write code that reads like the surrounding code: match its comment density, naming, and idiom.\n\nFor actions that are hard to reverse or outward-facing, confir…` |
| sys[2] CC agent system prompt — fully replaced by proxy rules (`_apply_system_passes`) | `—` | `system` | `system[2]` | 8 | 1,590,588 | `Generate a concise, sentence-case title (3-7 words) that captures the main topic or goal of this coding session. The title should be clear enough that the user …` |
| `stripped_po_preview` (rule PP) | `user` | `messages` | `tool_result_str` | 5 | 1,237,936 | `Preview (first 2KB):\n=== ToolSearch-related SR text ===\nisToolSearchToolAvailable\nTool search disabled: ToolSearchTool is not available (may have been disall…` |
| role=system message content — RS-covered ("<system-reminder> The following deferred tools are now available via ToolSearch. Their schemas are N") | `system` | `messages` | `plain_string` | 2 | 774,168 | `<system-reminder>\nThe following deferred tools are now available via ToolSearch. Their schemas are NOT loaded — calling them directly will fail with InputValid…` |
| role=system message content — RS-covered ("The user sent a new message while you were working: Zwei Dinge, die ich in der Prüfung noch nicht au") | `system` | `messages` | `plain_string` | 1 | 271,834 | `The user sent a new message while you were working:\nZwei Dinge, die ich in der Prüfung noch nicht auflösen konnte.\nWie hoch die ortsübliche Vergleichsmiete in…` |
| role=system message content — RS-covered ("<system-reminder> The task tools haven't been used recently. If you're working on tasks that would b") | `system` | `messages` | `plain_string` | 3 | 175,814 | `<system-reminder>\nThe task tools haven't been used recently. If you're working on tasks that would benefit from tracking progress, consider using TaskCreate to…` |
| `stripped_env_context_sr` (rule ENV) | `user` | `messages` | `text` | 3 | 107,508 | `<system-reminder>\nAs you answer the user's questions, you can use the following context:\n# userEmail\nThe user's email address is brunowinter7934@gmail.com.\n…` |
| `stripped_sn_notice_paragraph` (rule SNP) | `user` | `messages` | `text` | 14 | 75,276 | `[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated background-task event, NOT a message from the user.\nDo NOT interpret this as user acknowledgement,…` |
| `trimmed_task_notification` (rule TN) | `user` | `messages` | `text` | 14 | 62,397 | `<task-notification>\n<task-id>b9b1swhaw</task-id>\n<tool-use-id>toolu_01QrYyMVJPmTRN48ftgHSA3x</tool-use-id>\n<output-file>/private/tmp/claude-501/-Users-brunow…` |
| `stripped_bg_launch_ack` (rule BL) | `user` | `messages` | `tool_result_str` | 8 | 54,641 | `Command running in background with ID: b9b1swhaw. Output is being written to: /private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/1cc1b0be-1b…` |
| role=system message content — RS-covered ("<system-reminder> <new-diagnostics>The following new diagnostic issues were detected: cc_injection_i") | `system` | `messages` | `plain_string` | 2 | 49,926 | `<system-reminder>\n<new-diagnostics>The following new diagnostic issues were detected:\n\ncc_injection_inventory.py:\n  ✘ [Line 32:8] Import "proxy.rules" could…` |
| `stripped_hook_error_prefix` (rule HP) | `user` | `messages` | `tool_result_str` | 5 | 33,341 | `PreToolUse:Bash hook error: [python3 /Users/brunowinter2000/Documents/ai/monitor-cc/src/hooks/block_broad_grep.py]:` |
| `stripped_git_lock_advice` (rule GL) | `user` | `messages` | `tool_result_str` | 1 | 25,944 | `Another git process seems to be running in this repository, e.g.\nan editor opened by 'git commit'. Please make sure all processes\nare terminated then try agai…` |
| role=system message content — RS-covered ("The date has changed. Today's date is now #-#-#. DO NOT mention this to the user explicitly because ") | `system` | `messages` | `plain_string` | 1 | 8,064 | `The date has changed. Today's date is now 2026-07-28. DO NOT mention this to the user explicitly because they are already aware.` |
| `stripped_task_tools_nag` (rule NAG) | `user` | `messages` | `tool_result_str` | 1 | 6,006 | `<system-reminder>\nThe task tools haven't been used recently. ...\nMake sure that you NEVER mention this reminder to the user\n</system-reminder>\n` |

## OURS (7 classes)

| Class | Role | Section | Block type | Distinct occ. | Cum. chars | Sample |
|---|---|---|---|---|---|---|
| Tool result output — Bash | `user` | `messages` | `tool_result_str` | 356 | 136,746,464 | `/Users/brunowinter2000/Documents/ai/monitor-cc\ngit@github.com:brunowinter8192/monitor-cc.git` |
| Tool result output — Read | `user` | `messages` | `tool_result_str` | 50 | 46,183,216 | `1	"""Shared vocabulary for proxy strip semantics.\n2	\n3	Single source of truth for bucket codes, rule codes, tag literal codes,\n4	chunk→rule attribution, and …` |
| Assistant response text | `assistant` | `messages` | `text` | 195 | 40,984,006 | `> - `gh-cli list_issues brunowinter8192 monitor-cc` — 7 offene Issues\n\n**Sieben Issues sind offen, thematisch in vier Blöcken.**\nProxy/CC-Anpassung: #44 (Str…` |
| User typed message (unique one-off text, no recurring template detected) | `user` | `messages` | `text/plain_string` | 248 | 13,943,924 | `quota` |
| Tool result output — Edit | `user` | `messages` | `tool_result_str` | 21 | 6,315,944 | `The file /Users/brunowinter2000/Documents/wise2627/wohnungssuche/vermieter/siman_karl-von-drais-strasse-16-18/vor-unterschrift.md has been updated successfully.…` |
| Tool result output — Write | `user` | `messages` | `tool_result_str` | 22 | 773,202 | `File created successfully at: /Users/brunowinter2000/Documents/ai/monitor-cc/process-docs/strip_efficacy_audit/2026-07-28_template_catalog_efficacy_cc205.md (fi…` |
| Tool result output — Skill | `user` | `messages` | `tool_result_str` | 4 | 19,054 | `Launching skill: gh-cli-search` |
