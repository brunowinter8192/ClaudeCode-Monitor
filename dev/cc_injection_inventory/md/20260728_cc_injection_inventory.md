# CC Injection Inventory — 2026-07-28

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
`role=='assistant'`) -> `OURS` directly.

**tool_result vs top-level text — the enclosing shape decides, not the bytes.**
`tool_result.content` is OUR tool's own return value (bash/git/file output, retrieved
documents) — a `<system-reminder>` or CLAUDE.md-preamble literal appearing INSIDE it is
quoted DATA (a fetched issue body, a `strings` dump of the CC binary, source containing the
tag as a string), never a CC-injected wrapper, so the CLAUDE.md-preserve and leftover-SR
extraction passes only run on top-level shapes (`plain_string` / `text` blocks) — any such
literal inside `tool_result` content stays part of that segment's `OURS` residual, bucketed
by tool name like the rest of the tool's output. On a top-level shape, a leftover unmatched
`<system-reminder>` block after the full pipeline IS a genuine gap (no strip_vocab entry
exists for it) -> `UNCLASSIFIED`. Remaining `tool_result` residual (not otherwise KEEP/
COVERED) is `OURS`, bucketed by tool name.

Remaining top-level user text uses a two-phase signature check: a normalized-text
signature (>=40 chars) needs >=2 SUBSTANTIVELY DISTINCT underlying variants to count as a
recurring CC template -> `UNCLASSIFIED`. Distinctness collapses two kinds of false
recurrence: (a) whitespace-only differences (a trailing-newline shape artifact observed
mid-corpus), and (b) containment — one variant being a verbatim substring (prefix, suffix,
or mid-string extension) of another, which is one human message edited/resent as it grew,
not two occurrences of a template. Short recurring text (greetings/acks like "done",
"ok"), whitespace/containment-collapsed pairs, and all singletons fold into one `OURS`
aggregate (genuinely unique or naturally-repeated human prose). `system[2]`/
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

**Self-scan exclusion.** The default glob excludes THIS session's own worker log
(`api_requests_worker_*` embedding the current task/worktree name) — that file is written
live while the script runs, so including it would make the corpus non-reproducible
mid-scan. An explicit `--logs-glob` is never filtered. Any file excluded this run is listed
below.

## Corpus

| File | Entries | Messages (raw) | Size |
|---|---|---|---|
| `api_requests_opus_monitor_cc_1785190126_original.jsonl` | 142 | 20682 | 61MB |
| `api_requests_opus_posts_1785150574_original.jsonl` | 485 | 185182 | 4GB |
| `api_requests_opus_trading_1785190224_original.jsonl` | 70 | 4920 | 25MB |
| `api_requests_worker_1dda1c81_volnorm-window_1785197559_original.jsonl` | 7 | 47 | 1MB |
| **Total** | **704** | **210831** | **4GB** |

**Excluded (own live worker session, default glob only):**
- `api_requests_worker_25c51a2e_injection-inventory_1785194474_original.jsonl`

**Chosen metric — segments** (one text/tool_result block, used for all class counts below):
raw 162,235 / distinct 1,568 (103.5x overcount)  
**Prior codebase metric — whole messages** `(file, exact full message content)`, for comparison:
raw 210,831 / distinct 1,899 (111.0x overcount)

## Summary

**Total classes:** 30  |  **Total distinct occurrences:** 1,620  |  **Total cumulative chars:** 269,070,529

| Origin | Classes | Distinct occurrences | Cumulative chars |
|---|---|---|---|
| `UNCLASSIFIED` | 4 | 669 | 240,142 |
| `KEEP` | 3 | 7 | 2,812,891 |
| `COVERED` | 16 | 80 | 21,975,061 |
| `OURS` | 7 | 864 | 244,042,435 |

## UNCLASSIFIED (4 classes)

| Class | Role | Section | Block type | Distinct occ. | Cum. chars | Sample |
|---|---|---|---|---|---|---|
| sys[0] billing header (x-anthropic-billing-header) | `—` | `system` | `system[0]` | 644 | 85,887 | `x-anthropic-billing-header: cc_version=2.1.205.312; cc_entrypoint=cli; cch=59049;` |
| Recurring unattributed user-message text ("background done — check worker or other process Output: <PATH>/<UUID><PATH>") | `user` | `messages` | `text` | 16 | 58,495 | `background done — check worker or other process\nOutput: /private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/1cc1b0be-1b47-4b7d-9c40-77474a52…` |
| Recurring unattributed user-message text ("[Image: source: <PATH> #-#-# um #.#.#.png]") | `user` | `messages` | `text` | 5 | 55,803 | `[Image: source: /Users/brunowinter2000/Desktop/Bildschirmfoto 2026-07-28 um 00.41.42.png]` |
| sys[1] "You are Claude Code..." intro line | `—` | `system` | `system[1]` | 4 | 39,957 | `You are Claude Code, Anthropic's official CLI for Claude.` |

## KEEP (3 classes)

| Class | Role | Section | Block type | Distinct occ. | Cum. chars | Sample |
|---|---|---|---|---|---|---|
| CLAUDE.md context block (SR, preserve-guarded in strip_sr.py) | `user` | `messages` | `text` | 3 | 2,609,678 | `<system-reminder>\nAs you answer the user's questions, you can use the following context:\n# claudeMd\nCodebase and user instructions are shown below. Be sure t…` |
| <persisted-output> wrapper (Preview stripped by PP rule, wrapper kept) | `user` | `messages` | `tool_result_str` | 3 | 166,813 | `<persisted-output>\nOutput too large (93.1KB). Full output saved to: /Users/brunowinter2000/.claude/projects/-Users-brunowinter2000-Documents-ai-monitor-cc/1cc1…` |
| Read-tool truncation notice (role=system, preserved by RS guard) | `system` | `messages` | `plain_string` | 1 | 36,400 | `[Truncated: PARTIAL view — /Users/brunowinter2000/.claude/projects/-Users-brunowinter2000-Documents-ai-monitor-cc/1cc1b0be-1b47-4b7d-9c40-77474a526310/tool-resu…` |

## COVERED (16 classes)

| Class | Role | Section | Block type | Distinct occ. | Cum. chars | Sample |
|---|---|---|---|---|---|---|
| role=system message content — RS-covered ("The following deferred tools are now available via ToolSearch. Their schemas are NOT loaded — callin") | `system` | `messages` | `plain_string` | 3 | 6,676,794 | `The following deferred tools are now available via ToolSearch. Their schemas are NOT loaded — calling them directly will fail with InputValidationError. Use Too…` |
| role=system message content — RS-covered ("The task tools haven't been used recently. If you're working on tasks that would benefit from tracki") | `system` | `messages` | `plain_string` | 3 | 4,756,879 | `The task tools haven't been used recently. If you're working on tasks that would benefit from tracking progress, consider using TaskCreate to add new tasks and …` |
| role=system message content — RS-covered ("Note: <PATH> was modified, either by the user or by a linter. This change was intentional, so make s") | `system` | `messages` | `plain_string` | 5 | 4,037,761 | `Note: /Users/brunowinter2000/Documents/wise2627/wohnungssuche/buerge-vater/schriftverkehr.md was modified, either by the user or by a linter. This change was in…` |
| sys[3] session/environment context block — fully replaced with '.' (`_strip_sys3`) | `—` | `system` | `system[3]` | 4 | 3,544,172 | `Write code that reads like the surrounding code: match its comment density, naming, and idiom.\n\nFor actions that are hard to reverse or outward-facing, confir…` |
| `stripped_po_preview` (rule PP) | `user` | `messages` | `tool_result_str` | 3 | 1,196,395 | `Preview (first 2KB):\n=== ToolSearch-related SR text ===\nisToolSearchToolAvailable\nTool search disabled: ToolSearchTool is not available (may have been disall…` |
| sys[2] CC agent system prompt — fully replaced by proxy rules (`_apply_system_passes`) | `—` | `system` | `system[2]` | 8 | 864,848 | `Generate a concise, sentence-case title (3-7 words) that captures the main topic or goal of this coding session. The title should be clear enough that the user …` |
| role=system message content — RS-covered ("The user sent a new message while you were working: Zwei Dinge, die ich in der Prüfung noch nicht au") | `system` | `messages` | `plain_string` | 1 | 271,834 | `The user sent a new message while you were working:\nZwei Dinge, die ich in der Prüfung noch nicht auflösen konnte.\nWie hoch die ortsübliche Vergleichsmiete in…` |
| `stripped_sn_notice_paragraph` (rule SNP) | `user` | `messages` | `text` | 16 | 153,996 | `[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated background-task event, NOT a message from the user.\nDo NOT interpret this as user acknowledgement,…` |
| `trimmed_task_notification` (rule TN) | `user` | `messages` | `text` | 16 | 126,687 | `<task-notification>\n<task-id>b9b1swhaw</task-id>\n<tool-use-id>toolu_01QrYyMVJPmTRN48ftgHSA3x</tool-use-id>\n<output-file>/private/tmp/claude-501/-Users-brunow…` |
| `stripped_bg_launch_ack` (rule BL) | `user` | `messages` | `tool_result_str` | 10 | 103,544 | `Command running in background with ID: b9b1swhaw. Output is being written to: /private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/1cc1b0be-1b…` |
| `stripped_env_context_sr` (rule ENV) | `user` | `messages` | `text` | 2 | 95,232 | `<system-reminder>\nAs you answer the user's questions, you can use the following context:\n# userEmail\nThe user's email address is brunowinter7934@gmail.com.\n…` |
| role=system message content — RS-covered ("<system-reminder> The following deferred tools are now available via ToolSearch. Their schemas are N") | `system` | `messages` | `plain_string` | 2 | 60,446 | `<system-reminder>\nThe following deferred tools are now available via ToolSearch. Their schemas are NOT loaded — calling them directly will fail with InputValid…` |
| `stripped_hook_error_prefix` (rule HP) | `user` | `messages` | `tool_result_str` | 4 | 37,241 | `PreToolUse:Bash hook error: [python3 /Users/brunowinter2000/Documents/ai/monitor-cc/src/hooks/block_broad_grep.py]:` |
| `stripped_git_lock_advice` (rule GL) | `user` | `messages` | `tool_result_str` | 1 | 32,016 | `Another git process seems to be running in this repository, e.g.\nan editor opened by 'git commit'. Please make sure all processes\nare terminated then try agai…` |
| `stripped_task_tools_nag` (rule NAG) | `user` | `messages` | `tool_result_str` | 1 | 9,152 | `<system-reminder>\nThe task tools haven't been used recently. ...\nMake sure that you NEVER mention this reminder to the user\n</system-reminder>\n` |
| role=system message content — RS-covered ("The date has changed. Today's date is now #-#-#. DO NOT mention this to the user explicitly because ") | `system` | `messages` | `plain_string` | 1 | 8,064 | `The date has changed. Today's date is now 2026-07-28. DO NOT mention this to the user explicitly because they are already aware.` |

## OURS (7 classes)

| Class | Role | Section | Block type | Distinct occ. | Cum. chars | Sample |
|---|---|---|---|---|---|---|
| Tool result output — Bash | `user` | `messages` | `tool_result_str` | 333 | 139,662,829 | `/Users/brunowinter2000/Documents/ai/monitor-cc\ngit@github.com:brunowinter8192/monitor-cc.git` |
| Assistant response text | `assistant` | `messages` | `text` | 186 | 42,084,282 | `> - `gh-cli list_issues brunowinter8192 monitor-cc` — 7 offene Issues\n\n**Sieben Issues sind offen, thematisch in vier Blöcken.**\nProxy/CC-Anpassung: #44 (Str…` |
| Tool result output — Read | `user` | `messages` | `tool_result_str` | 43 | 40,949,033 | `1	"""Shared vocabulary for proxy strip semantics.\n2	\n3	Single source of truth for bucket codes, rule codes, tag literal codes,\n4	chunk→rule attribution, and …` |
| User typed message (unique one-off text, no recurring template detected) | `user` | `messages` | `text/plain_string` | 256 | 14,302,752 | `quota` |
| Tool result output — Edit | `user` | `messages` | `tool_result_str` | 20 | 6,250,334 | `The file /Users/brunowinter2000/Documents/wise2627/wohnungssuche/vermieter/siman_karl-von-drais-strasse-16-18/vor-unterschrift.md has been updated successfully.…` |
| Tool result output — Write | `user` | `messages` | `tool_result_str` | 22 | 772,563 | `File created successfully at: /Users/brunowinter2000/Documents/ai/monitor-cc/process-docs/strip_efficacy_audit/2026-07-28_template_catalog_efficacy_cc205.md (fi…` |
| Tool result output — Skill | `user` | `messages` | `tool_result_str` | 4 | 20,642 | `Launching skill: gh-cli-search` |
