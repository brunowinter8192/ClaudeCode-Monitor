# searxng-cli → websearch: hook + news_pane rename (M5)

Continuation of the cross-project CLI rename (`naming_unification`): the CLI project `searxng-cli` was renamed `websearch` (wrapper in PATH, repo path `Meta/ClaudeCode/cli/websearch`). This session covers the monitor-cc-side blast radius of that rename.

## Scope found via grep(`rewrite_searxng`) — 4 files

- `src/hooks/rewrite_searxng_scrape_noise.py` → `rewrite_websearch_scrape_noise.py` (git mv). `_SCRAPE_RE` anchor `\bsearxng-cli\s+scrape_url\b` → `\bwebsearch\s+scrape_url\b`; workflow fn, `log_fire` hook-name string, comments renamed to match.
- `dev/hook_smoke/test_rewrite_searxng_scrape_noise.py` → `test_rewrite_websearch_scrape_noise.py` (git mv). 16 case command strings + `HOOK` path + test fn renamed.
- `src/hooks/DOCS.md` — registry entry, `_shell_strip.py` called-by list (both the module section and the duplicate list inside Gotchas), `hook_setup.py`-listed filename. Also corrected a stale `(~95 LOC)` approximation to the actual `wc -l` (111) while the entry was open for edit.
- `src/hooks/hook_setup.py` — filename string in `_HOOK_SCRIPTS`.

## Scope missed by that grep, caught on review — `news_pane`

`src/news_pane/log_parser.py` held `SEARXNG_ROOT = Path('.../cli/searxng-cli')` — a hardcoded absolute path, not a `rewrite_searxng` string match, so the initial grep pass missed it entirely. The old directory no longer exists post-rename (renamed to `.../cli/websearch` on disk) — this made `SEARXNG_ROOT`, `LOG_DIR` (derived from it), and the pipeline-launch `subprocess.Popen` in `pane.py` point at a dead path. Renamed `SEARXNG_ROOT` → `WEBSEARCH_ROOT` with the new path; updated the one importer (`pane.py`, both the import list and the two `Popen`/`cwd` usages). `TARGET_COLLECTION = 'searxng_crypto'` was explicitly left untouched — it is a RAG collection name (data label in Postgres), not a filesystem path; renaming it is a DB operation, out of scope for a code/path rename. `DOCS.md` prose ("lives in searxng-cli" → "lives in websearch") and the `SEARXNG_ROOT` mentions in Purpose/Gotchas updated to match; `searxng_crypto` mentions left as-is throughout.

**Lesson for future milestones of this rename:** grepping the OLD module/function name only catches code-identifier references. Hardcoded absolute paths to the renamed directory are a distinct, silent blast-radius class — worth a separate `grep -rn '/cli/searxng-cli'` (or equivalent literal-path search) pass per rename milestone, not just the symbol-name grep.

## Deliberately left untouched

- `process-docs/**` (write-once history, per rule).
- `dev/tool_use_errors/md/2026-05-22_opus.md`, `dev/jsonl/json/baseline_20260610_030515.json` — dated historical report / raw session-capture data mentioning `searxng-cli` as literal text (directory listings, captured commands from before the rename). Snapshots of a past state, not active code — editing them would misrepresent what was actually observed at capture time.

## Verification (as of 2026-07-25)

- `venv/bin/python3 dev/hook_smoke/test_rewrite_websearch_scrape_noise.py` → `All 16 tests passed.` (integration-level: real subprocess, real stdin JSON, real stdout parse).
- Manual probe: `{"tool_input": {"command": "websearch scrape_url \"https://x.com/a\" | head -45"}}` piped into `rewrite_websearch_scrape_noise.py` → `updatedInput.command == 'websearch scrape_url "https://x.com/a"'` (pipe stripped, confirms the new anchor matches).
- `from src.news_pane.log_parser import WEBSEARCH_ROOT` + `from src.news_pane import pane` both import cleanly; `pane.WEBSEARCH_ROOT` resolves to the new path.
- `grep -rn "rewrite_searxng\|SEARXNG_ROOT" src/ dev/` → 0 hits.
- NOT verified: live PreToolUse firing through the actual CC hook system (requires `~/.claude/settings.json` registration — out of scope, orchestrator's job); visual/tmux rendering of the news pane.
