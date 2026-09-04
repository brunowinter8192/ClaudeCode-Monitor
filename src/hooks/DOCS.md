# src/hooks/

## Role

Global CC safety hooks — scripts that intercept Bash, Edit, and Read tool calls and either **block** known-destructive patterns, **silently rewrite** known-broken patterns before execution, or **feed an instruction back** after a call has already failed. Registered in `~/.claude/settings.json` (global, fires for ALL projects on this machine, not just Monitor_CC). Each hook script reads CC's JSON payload from stdin and either exits 0 (allow / silent-rewrite via `hookSpecificOutput.updatedInput` JSON to stdout) or 2 (block, stderr shown to user).

**Three hook classes:**

- **Block hooks** (`block_*.py`, PreToolUse) — exit 2 + stderr when detecting damage patterns (irreversible commands, context-flooding outputs). Damage-prevention only.
- **Rewrite hooks** (`rewrite_*.py` plus the recently-upgraded `block_path_typo.py`, PreToolUse) — exit 0 + JSON `hookSpecificOutput.permissionDecision: "allow"` + `updatedInput.{command|file_path}` containing the corrected input. Pattern-class: a broken input has a unique computable corrected form. CC v2.1+ supports this for Bash + Read + Write under `acceptEdits` mode (Issue [#47853](https://github.com/anthropics/claude-code/issues/47853) OP). Edit-Matcher exhibits an anomaly under investigation — see `process-docs/tool_use_safety/2026-05-22_block_path_typo_edit_no_fire.md`.
- **Feedback hooks** (`feedback_*.py`, PostToolUseFailure) — exit 0 + JSON `hookSpecificOutput.additionalContext`. The call already ran and already failed; nothing is blocked or modified, the model just receives an extra instruction alongside the error it already sees. Pattern-class: the failure itself is legitimate, but the model's *reaction* to it needs discipline.

Design rationale and statistics: `process-docs/tool_use_safety/2026-05-12_session_findings.md`. Hook API capabilities and auto-rewrite conversion: `process-docs/tool_use_safety/2026-05-22_hook_api_auto_rewrite_works.md`.

## Public Interface

Each hook script is a standalone `python3 <script>.py` entry invoked by CC. Not imported by any module. Install via `hook_setup.py` (run once).

## Modules

### _shell_strip.py (194 LOC)

**Purpose:** Shared utility — provides `_strip_non_shell_active(command)`, the position-preserving shell-region stripper used by twenty-three Bash-scanning hooks. Replaces heredoc bodies, single/double-quoted strings, and ANSI-C `$'...'` quotes with spaces of the same length before pattern matching runs. Command substitutions `$(...)` and backtick expressions are kept shell-active. Fail-open: any parse error returns the original command unchanged (never silently allows a blocked pattern due to a strip failure). `_strip_impl` is decomposed into 6 private scan helpers (`_scan_heredoc`, `_scan_ansi_c_quote`, `_scan_cmd_subst`, `_scan_backtick`, `_scan_single_quote`, `_scan_double_quote`), each returning `(fragment, new_i)`.
**Reads:** n/a (pure logic module, not a standalone script).
**Writes:** n/a.
**Called by:** `block_broad_find.py`, `block_broad_grep.py`, `block_busywait_loop.py`, `block_dangerous_kill.py`, `block_duallog_chained.py`, `block_gh_cli_chained.py`, `block_gh_cli_local_path.py`, `block_linkedin_cli_isolated.py`, `block_manual_worker_cleanup.py`, `block_pipe_scraper_isolated.py`, `block_po_read.py`, `block_rag_cli_chained.py`, `block_rag_cli_index_isolated.py`, `block_rag_corpus_read.py`, `block_rag_docs_layer.py`, `block_search_subreddits_limit.py`, `block_venv_no_redirect.py`, `block_websearch_scrape_chained.py`, `block_worker_cli_read_chained.py`, `block_worker_kill_while_working.py`, `block_worker_send_background.py`, `block_worker_spawn_placement.py`, `rewrite_chained_sleep.py` via `sys.path` insertion + `from _shell_strip import _strip_non_shell_active`.
**Calls out:** stdlib only (no imports).

---

### _known_cli.py (68 LOC, 2026-09-04 duallog addition)

**Purpose:** Shared utility — provides `is_allowed_chain_segment(segment)`, the single allow-predicate used by the chained-CLI block hooks (`block_gh_cli_chained.py`, `block_rag_cli_chained.py`, `block_websearch_scrape_chained.py`, `block_worker_cli_read_chained.py`, `block_duallog_chained.py`) to decide whether a foreign-looking Bash segment is actually fine; composed from `is_known_cli_segment`, `is_guard_segment`, `is_echo_segment`, and `is_loop_scaffold_segment`. 2026-08 cross-CLI relax: `is_known_cli_segment` passes any segment invoking a `KNOWN_CLI_TOOLS` entry — `gh-cli`, `rag-cli`, `worker-cli`, `reddit-cli`, `linkedin`, `websearch`, and (since 2026-09-04) `duallog` (sourced by grepping every CLI token actually referenced across `src/hooks/*.py`; `bd` deliberately excluded — retired, see `rewrite_bd_invalid_repo.py` deletion) — regardless of which tool or subcommand. `duallog` was added so a `block_duallog_chained.py`-governed call can chain with the other six CLIs (and vice versa — e.g. a `duallog search foo` segment now passes `block_gh_cli_chained.py`'s own chain check too), not just with itself. `is_guard_segment` recognizes `cd`, `test`, and `[ ... ]` bracket-test segments. **2026-08 loop-scaffold relax:** real case blocked wrongly — `for n in 62 61 59; do echo "===== #$n ====="; gh-cli get_issue owner repo $n; done` — none of `for ...`, `do echo ...`, `done` are known-CLI/guard segments. `is_echo_segment` passes a pure `echo`/`printf` segment (output-only, cannot filter/truncate another segment's output). `is_loop_scaffold_segment` passes a `for ...`/`while ...` header, a bare `do`/`done`, or `do <segment>` where `<segment>` is itself a known-CLI call, guard, or echo/printf — a foreign command inside `do <cmd>` (e.g. `do curl ...`) still fails all four predicates and blocks.
**Reads:** n/a (pure logic module, not a standalone script).
**Writes:** n/a.
**Called by:** `block_gh_cli_chained.py`, `block_rag_cli_chained.py`, `block_websearch_scrape_chained.py`, `block_worker_cli_read_chained.py`, `block_duallog_chained.py` via `sys.path` insertion + `from _known_cli import is_allowed_chain_segment`.
**Calls out:** stdlib only (`re`).

---

### _fire_log.py (48 LOC)

**Purpose:** Shared utility — provides `log_fire(hook_name, decision, tool_name, command, reason=None, rewritten=None, session_id=None)`, the single fire-event appender used by all active hooks. Appends one JSON line per fire to `src/logs/hook_firing.jsonl`. For `decision="block"` and `decision="feedback"`: includes `reason` field (the message text), omits `rewritten`. For `decision="rewrite"`: includes `rewritten` field (new command/path), omits `reason`. Fail-silent: any exception in the write path is swallowed so a logging failure never breaks the hook itself. Log path overridable via `MONITOR_CC_HOOK_FIRING_LOG` env var (used for test isolation in `dev/hook_smoke/`).
**Reads:** n/a (pure logic module, not a standalone script).
**Writes:** `src/logs/hook_firing.jsonl` (appends one line per fire; path resolved from `__file__` relative to `src/`).
**Called by:** all active hook scripts (including `block_po_read.py`) via `sys.path` insertion + `from _fire_log import log_fire`. Called at the decision-point only (immediately before `sys.exit(2)` for blocks; immediately before `print(json.dumps(output))` for rewrites). NOT called on passthroughs.
**Calls out:** stdlib only (`json`, `os`, `datetime`).

---

### block_dangerous_kill.py (91 LOC)


**Purpose:** PreToolUse hook — blocks `pkill -f <pattern>` and `ps|grep|kill` pipe chains. Both patterns target processes via text substring matching against the full cmdline, which routinely kills unintended processes (CC worker sessions whose prompt text contains the matched string). Exits 2 + stderr with concrete safer alternatives. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message with alternatives) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** stdlib only (`json`, `re`).

**Blocked patterns:**
- `pkill -f <anything>` — cmdline-substring matching, kills worker prompts
- `ps ... | ... grep ... | ... kill ...` — same problem via pipe chain

**Allowed patterns (not blocked):** `pkill -x <name>` (exact), `pkill <name>` (name-only), `kill <numeric_pid>`, `kill -<signal> <numeric_pid>`, `worker-cli kill <name>`, `launchctl bootout/kickstart`.

**Allowlist (`_PKILL_F_ALLOWLIST`):** explicit literal strings for `pkill -f` arguments that are safe to pass through. Checked against original (un-stripped) command via `_PKILL_F_ARG_RE` (handles single-quoted, double-quoted, unquoted). Conservative: any non-allowlisted `pkill -f` in the same command still blocks. Current entries: `"dolt sql-server"` (bd Beads SQL backend — bd's orphan-cleanup SIGKILLs any process with this cmdline string, making it impossible for a worker to carry it).

**Quote/heredoc stripping.** Before regex matching, `_strip_non_shell_active()` (imported from `_shell_strip.py`) removes heredoc bodies, single-quoted, double-quoted, and ANSI-C `$'...'` regions from the command string. Command substitutions `$(...)` and backtick expressions are kept shell-active. Eliminates false-positives where `pkill -f` appears as literal text inside heredoc bodies (test scaffolding, `bd comments add` session notes, Python string literals).

---

### block_chained_sleep.py.disabled

**Disabled 2026-05-24** — superseded by `rewrite_chained_sleep.py`. Renamed via `git mv` (file still in repo for history). Previously blocked all non-canonical `sleep N` chains. Replaced by a rewrite hook that strips trivial-sync sleeps (`echo`, `true` cmd_before) and passes load-bearing patterns through. See `process-docs/hook_fp_audit/sleep_pattern_audit_2026-05-24.md` for audit rationale.

---

### rewrite_chained_sleep.py (143 LOC)

**Purpose:** PreToolUse hook (Bash) — **rewrites** chained `sleep N` by stripping it when the immediately-preceding segment is in `_TRIVIAL` (single-token read-only-fast commands) or `_TRIVIAL_PAIRS` (two-token exact pairs for safe subcommands of multi-verb CLIs). Sleep-first chains, load-bearing predecessors, and loop-body sleeps are passed through unchanged (no-op). Exits 0 in all cases (fail-open rewrite hook — never blocks). Uses `_shell_strip._strip_non_shell_active` for position-preserving heredoc + quote removal before tokenizing.
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stdout (JSON `hookSpecificOutput.permissionDecision: "allow"` + `updatedInput.command`) when sleep(s) were stripped; nothing when no-op.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active` (same-dir import via `sys.path` insert).

**Allowlist:**
- `_TRIVIAL` (first token of preceding segment): `echo`, `true`, `grep`, `cat`, `ls`, `wc`, `head`, `tail`, `find`
- `_TRIVIAL_PAIRS` (`(tokens[0], tokens[1])` exact pair): `(git,status)`, `(git,log)`, `(git,diff)`, `(git,show)`, `(rag-cli,search)`, `(worker-cli,status)`, `(worker-cli,list)`, `(worker-cli,response)`

**Strip condition (ALL must hold):**
1. A chain operator (`&&`, `||`, `;`) immediately precedes `sleep N` (only whitespace between op and sleep)
2. `tokens[0]` of the preceding segment is in `_TRIVIAL`, OR `(tokens[0], tokens[1])` is in `_TRIVIAL_PAIRS`
3. Sleep is NOT inside a `for|while|until ... done` span

**Pass-through (no-op) conditions:**
- Sleep-first chain (no preceding chain op) — intent is timing
- cmd not in `_TRIVIAL` and pair not in `_TRIVIAL_PAIRS` (e.g. `git push`, `rag-cli index`, `worker-cli send/kill`, `launchctl`, `tmux`)
- Flag between command and subcommand (e.g. `git -C <path> status` → `tokens[1]='-C'` → pair not found → no strip; conservatively fail-toward-preserve)
- Single `&` background operator — not in `_CHAIN_RE`, so sleep has no preceding chain op → no strip
- Sleep inside loop body

**Smoke:** `dev/hook_smoke/test_rewrite_chained_sleep.py` (31 cases: 18 strip, 13 pass-through).

---

### block_search_subreddits_limit.py (54 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks `reddit-cli search_subreddits` and `cli.py search_subreddits` invocations that carry a `--limit` flag. Subreddit discovery must return the full result set; capping it prematurely hides candidates. Exits 2 + stderr. Exits 0 on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active` (same-dir import via `sys.path` insert); `_fire_log.log_fire`.

**Blocked patterns:** `reddit-cli search_subreddits "query" --limit N`; `cli.py search_subreddits "query" --limit N` — `--limit` caps the result set before the caller can select from it.

**Allowed patterns:** `reddit-cli search_subreddits "query"` without `--limit`; commands not containing `search_subreddits`; parse errors (fail-open). `_LIMIT_RE` is searched only after `_SEARCH_RE` matches — non-matching commands exit at the first gate.

---

### block_unauthorized_background.py (78 LOC, Milestone 2 worker-cli wait exemption 2026-08)

**Purpose:** PreToolUse hook — **silently rewrites** any Bash command dispatched with `run_in_background=true` that is neither a sleep-only timer habit NOR the canonical `worker-cli wait`, flipping `run_in_background` to `false` via `hookSpecificOutput.updatedInput`. Two exempt shapes: (1) sleep-only commands (bare `sleep N` OR `sleep N && echo <anything>`) — kept exempt even though `rewrite_background_sleep.py` normalizes them, so this hook stays correct regardless of hook execution order; (2) `worker-cli wait` with optional `project_path`/`--timeout N` args in any combination — the canonical pull-based wake-up command (iterative-dev plugin `worker-cli wait`) that raw sleep-timer habits get rewritten to. All other background commands are foreground-forced without exception. Exits 0 in all cases (fail-open rewrite hook — never blocks). Logs `decision="rewrite"` with `rewritten="run_in_background: true → false"`.
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command, run_in_background}}`).
**Writes:** stdout (JSON `hookSpecificOutput.permissionDecision: "allow"` + `updatedInput.{command, run_in_background: false}`) on non-canonical bg; nothing on passthrough.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** stdlib only (`json`, `re`).

**Rewrite condition:** `run_in_background=true` AND command matches NEITHER `_SLEEP_ONLY_BG` (`^\s*sleep\s+\d+(?:\.\d+)?\s*(?:&&\s*echo\b[^;&|\n]*)?\s*$`) NOR `_WAIT_FORM` (`^\s*worker-cli\s+wait\b[^;&|\n]*$` — `\b` word-boundary after `wait` rejects `waitfoo`-shaped tokens; `[^;&|\n]*` tail-guard rejects a chained `worker-cli wait && other_cmd`).

**Passthrough (no output):**
- Any sleep-only command (`sleep N`, `sleep N && echo done`, `sleep N && echo "custom text"`) with `run_in_background=true`
- Any `worker-cli wait` form (bare, with `project_path`, with `--timeout N`, with both) with `run_in_background=true`
- Any command with `run_in_background=false` or field absent (foreground — no restriction)
- Parse errors (fail-open)

**No quote-stripping.** Checks the `run_in_background` bool field and the two canonical regexes only — no general command-text scanning.

**Smoke:** `dev/hook_smoke/test_block_unauthorized_background.py` (14 cases: 3 sleep-only ALLOW, 4 `worker-cli wait` ALLOW, 6 FORCE incl. chained-wait and word-boundary, 1 foreground PASS).

---

### rewrite_background_sleep.py (88 LOC, Milestone 2 rewrite target change 2026-08; orchestrator-only guard 2026-08 Milestone 3b)

**Purpose:** PreToolUse hook (Bash) — **rewrites** ANY sleep-only background command to the canonical `worker-cli wait` (iterative-dev plugin — blocks in-process until all workers of the project go stably idle, or `--timeout`; its own exit IS the wake-up, replacing the old push-based raw-sleep + menubar-kill mechanism). Matches bare `sleep N` OR `sleep N && echo <anything>` (regex `_SLEEP_ONLY_BG`). No "already canonical" exemption needed: `_SLEEP_ONLY_BG` requires a literal `sleep` token, which can never match the target string `"worker-cli wait"` — every sleep-only match, including the OLD canonical `sleep 3300 && echo done`, is now a stale habit and gets rewritten. Pairs with `block_unauthorized_background.py`, which exempts both sleep-only commands AND `worker-cli wait` forms from foreground-forcing (that hook stays global — it only ever flips `run_in_background`, never the command text, so a worker's `sleep N` staying `sleep N` in the background is already harmless there). **Orchestrator-only (2026-08, live incident, `_in_worktree()`/`_WORKTREE_FRAGMENT`, same convention the removed `block_timer_*` hooks used):** skipped entirely when the hook's own cwd is inside a worktree — a worker's own background sleep (e.g. waiting on its own long test run) must never get promoted to `worker-cli wait`, since run from the worker's worktree cwd that command resolves the worktree path as the project, finds no workers there, and blocks up to the full default timeout; that stray wait becomes a live child under the worker's own `claude` process, which then makes the ORCHESTRATOR's own `worker-cli wait` see a live background task and refuse to finish too — one misfire cascading into two stuck waits. `_in_worktree()` fails open TOWARD "skip rewrite" on any `os.getcwd()` failure (deliberately the opposite fail-open direction from most hooks here — a missed rewrite for the orchestrator is harmless, rewriting a worker's sleep on an unreliable cwd read is the exact incident being prevented). Exits 0 in all cases (fail-open rewrite hook — never blocks).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command, run_in_background}}`); `os.getcwd()` (worktree exemption).
**Writes:** stdout (JSON `hookSpecificOutput.permissionDecision: "allow"` + `updatedInput.command`) when command is a sleep-only form; nothing on passthrough.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** stdlib only (`json`, `os`, `re`, `sys`).

**Rewrite condition (ALL must hold):**
1. Hook cwd is NOT inside `.claude/worktrees/` — orchestrator-only guard
2. `run_in_background == True`
3. Command matches `_SLEEP_ONLY_BG`: `^\s*sleep\s+\d+(?:\.\d+)?\s*(?:&&\s*echo\b[^;&|\n]*)?\s*$`

**Passthrough (no output):**
- Hook cwd inside `.claude/worktrees/` — worker session, never rewritten regardless of command shape
- `run_in_background=false` or field absent — foreground, any sleep form allowed
- Any non-sleep-only command (including `worker-cli wait` itself, already canonical) — `_SLEEP_ONLY_BG` fails to match; `block_unauthorized_background.py` handles the allow/force decision for these
- Parse errors (fail-open)

**Smoke:** `dev/hook_smoke/test_rewrite_background_sleep.py` (14 cases: 6 positive rewrite incl. the old canonical target, 5 negative no-op incl. `worker-cli wait` passthrough, 3 worktree-cwd no-op cases proving the orchestrator-only guard actually fires — cwd forced explicitly per case via `subprocess.run(..., cwd=...)`, both a plain non-worktree tempdir and a `.claude/worktrees/`-shaped one, since this suite's own on-disk path contains that fragment and would otherwise leak into every case's inherited cwd).

---

### block_broad_grep.py (104 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks recursive `grep -r`/`-R` calls on directories when no `--include=` scope is present. Unrestricted recursive grep matches JSONL logs, node_modules, and vendored content, producing 10MB+ output that floods the context window. Exits 2 + stderr with fix options. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message with fix options) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** stdlib only (`json`, `re`).

**Blocked patterns:**
- `grep -rn <pattern> <dir>` without `--include=` where last arg is not a specific file
- `grep -R <pattern> .` and similar broad recursive scans

**Allowed patterns:**
- `grep -rn pattern src/ --include='*.py'` — has `--include` scope
- `grep -rn pattern workflow.py` — last arg is a specific file (ends in known extension)
- `grep -n pattern file.py` — no recursive flag
- `git grep -r ...` — git grep uses gitignore, exempted
- `grep -r foo . | head -N` — output immediately piped to `head` (bounded, no context-flood risk)

**Head-bounded exemption.** `_grep_segment()` returns `(segment, after_segment)` where `after_segment` is everything from the pipe separator onward. `_is_head_bounded(after)` checks `^\s*\|\s*head\b` — true only when `head` is the DIRECT next pipe after the grep segment, not a head elsewhere in the chain.

**Quote/heredoc stripping.** Before segment extraction, `_strip_non_shell_active()` (from `_shell_strip.py`) removes heredoc bodies and quoted regions. Prevents false-positives when a `grep -r` example appears as a literal string inside a `worker-cli send` message or `bd create` description.

---

### block_broad_find.py (130 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks `find` invocations over broad/unbounded search roots when no `-maxdepth N` predicate is present and output is not immediately `| head`-bounded. Broad roots: `~`, `~/`, `$HOME`, `/`, and the `.claude` subtree (`~/.claude` or any path under it). A `find ~/.claude -type d -iname '*searxng*'` without depth or head limits traverses hundreds of session/worktree dirs and floods context (~80 results — the trigger incident). Exits 2 + stderr with three escapes. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message with fix options) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active` (same-dir import via `sys.path` insert); `_fire_log.log_fire`; stdlib (`json`, `os`, `re`, `sys`).

**Blocked patterns:**
- `find ~/.claude -type d -iname '*searxng*'` — `.claude` subtree, no maxdepth, no head
- `find ~ -name foo` — home dir root, unbounded
- `find ~/ -type f` — trailing-slash form normalised via `os.path.normpath`
- `find $HOME -type f` — `$HOME` resolved to home dir
- `find / -name bar` — filesystem root
- `find ~/.claude/projects -type d` — any subpath under `.claude`

**Allowed patterns:**
- `find ~/.claude -type d ... | head -20` — output immediately piped to `head` (bounded)
- `find ~ -maxdepth 2 -name foo` — `-maxdepth` limits traversal depth
- `find src/ -name '*.py'` — non-broad root (project subdirectory)
- `find . -type f` — `.` is not a broad root
- `find /Users/x/Documents/ai/monitor-cc -name '*.py'` — specific project path
- `echo "find ~ -name foo"` — quoted: blanked by `_strip_non_shell_active`, no match

**Head-bounded exemption.** `_find_segment()` returns `(segment, after_segment)`. `_is_head_bounded(after)` checks `^\s*\|\s*head\b` — true only when `head` is the DIRECT next pipe after the find segment.

**Root extraction.** After `\bfind\b` (word boundary excludes `mdfind`, `findmnt`), leading global options (`-H`, `-L`, `-P`, `-O<level>`, `-D debugopts`) are skipped token-by-token. Tokens are collected as roots until the first predicate (token starting with `-`, `(`, `!`, `,`). Each root is normalised: `$HOME`/`${HOME}` prefix replaced with `~` first, then `os.path.expanduser` + `os.path.normpath` — covers all subpath forms (`$HOME/.claude`, `${HOME}/foo`) uniformly.

**Quote/heredoc stripping.** Before segment extraction, `_strip_non_shell_active()` (from `_shell_strip.py`) removes heredoc bodies and quoted regions. Prevents false-positives when `find ~/.claude ...` appears as literal text inside a `worker-cli send` message.

---

### block_gh_cli_chained.py (95 LOC, 2026-08 loop-scaffold relax)

**Purpose:** PreToolUse hook (Bash) — engages on any of the 7 gh-cli search/research tools (`search_repos`, `search_code`, `get_repo_tree`, `get_file_content`, `index_issues`, `index_discussions`, `index_releases`) OR the 2 read commands `get_issue`/`list_issues` (2026-08: absorbed from the deleted `rewrite_gh_cli_read_noise.py` — rewrite-and-strip-noise superseded by block, same incident-class reasoning as `block_websearch_scrape_chained.py`). `get_issue`/`list_issues` are PROTECTED: no redirect (`_GH_READ_SEGMENT_RE` + `_REDIRECT_RE`) — output is bounded and must land directly in context, retiring the old rewrite hook's "save full output to disk" redirect allowance. The other 7 keep their pre-existing redirect-allowed behavior unchanged. **2026-08 cross-CLI relax:** every OTHER segment in the command must now be a known CLI call, guard, echo/printf, or loop scaffold (`_known_cli.is_allowed_chain_segment`), not specifically one of these 9 gh-cli tools — chaining `gh-cli index_issues ... && rag-cli search ...` is now allowed, where it used to block. This also subsumes the old dedicated `repo_freshness`-as-legal-segment carve-out (any gh-cli subcommand, including `repo_freshness`, `create_issue`, etc., now passes as a known-CLI segment) — simpler mechanism, same practical outcome for the incident it fixed. **2026-08 loop-scaffold relax:** `for`/`while` batch loops over `gh-cli` calls (real case: `for n in 62 61 59; do echo "=== #$n ==="; gh-cli get_issue owner repo $n; done`) used to block on every `for`/`do`/`done`/`echo` segment — now allowed via `_known_cli.is_allowed_chain_segment`'s loop-scaffold/echo predicates; a foreign command inside the loop body (`do curl ...`) still blocks. `create_issue`/`update_issue`/`delete_issue` are not PROTECTED (writes, one-line confirmation, no truncation risk) but ARE now checked as ordinary known-CLI segments rather than being fully hook-exempt. Exits 2 + stderr on violation. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_known_cli.is_allowed_chain_segment`, `_fire_log.log_fire`; stdlib (`json`, `re`).

**Blocked patterns:**
- `gh-cli search_repos "q" | grep foo` — piped to a non-CLI command
- `gh-cli get_file_content o/r path | head -10` — piped to head
- `gh-cli get_issue 123 o/r | head` / `gh-cli list_issues o/r | grep open` — 2026-08: no longer exempt, protected read commands piped
- `gh-cli get_issue 123 o/r > /tmp/out.txt` — protected read command redirected
- `for n in 1 2 3; do curl http://evil.com/$n; gh-cli get_issue o r $n; done` — foreign command inside a loop body still blocks

**Allowed patterns:**
- `gh-cli index_issues "q" o/r --limit 30 --offset 0` — standalone with tool-native args
- `gh-cli index_issues "a" o/r && gh-cli index_discussions "b" o/r` — multiple search/research calls combined
- `gh-cli get_issue 123 o/r && gh-cli list_issues o/r` — protected read commands combined with each other
- `gh-cli repo_freshness o/r && gh-cli index_issues "q1" o/r` — any gh-cli subcommand joins a chain already in scope (via the generic known-CLI check, not a dedicated carve-out)
- `gh-cli index_issues "q" o/r && rag-cli search "q" coll` — cross-CLI chain (2026-08 relax; used to block)
- `gh-cli get_file_content o/r path > /tmp/out.txt` — the 7 search/research tools keep redirect-allowed
- `cd /tmp && gh-cli index_issues "q" o/r` — leading guard
- `gh-cli search_repos "q" && echo done` — bare echo segment (2026-08 loop-scaffold relax)
- `for n in 62 61 59; do echo "=== #$n ==="; gh-cli get_issue o r $n; done` — batch loop over a known CLI (2026-08 loop-scaffold relax)
- any command with none of the 9 protected/trigger tools — not policed

**Segment split.** `_SEPARATOR_RE` splits the (quote-stripped) command on `&&` `||` `;` `|` newline and space-bounded `&`; `>&`/`2>&1` redirects survive intact (no whitespace before `&`). `_GH_TRIGGER_RE` (fires the hook at all) matches the 7 + `get_issue`/`list_issues`. Per segment: `_GH_READ_SEGMENT_RE` match → check `_REDIRECT_RE`, block if present, else pass; else `is_allowed_chain_segment()` (known-CLI, guard, echo/printf, or loop scaffold) → pass; else block.

**Smoke:** `dev/hook_smoke/test_block_gh_cli_chained.py` (34 cases incl. protected-redirect/pipe blocks for get_issue/list_issues, cross-CLI-relax passes, get_issue/list_issues combine passes, repo_freshness/echo incident replay, for/while loop-scaffold passes, foreign-command-in-loop-body block). Incident replay probe (verbatim commands + stderr-content checks, not folded into the smoke suite): `dev/hook_smoke/probe_gh_cli_repo_freshness_incident.py`.

---

### block_gh_cli_local_path.py (108 LOC, 2026-08-07)

**Purpose:** PreToolUse hook (Bash) — blocks `gh-cli get_file_content`/`gh-cli download_files` when a positional path argument (the one(s) after `owner`/`repo`) starts with `/` or `~` — a local filesystem path where a repo-relative path is required. Observed failure class: agents pass Claude Code tool-result paths (`~/.claude/projects/.../tool-results/...`) or other absolute/`~` paths as `get_file_content`'s `path`; the GitHub API then 404s/validation-errors. Same philosophy as `block_gh_cli_chained.py` — the skill prose that used to teach this is being removed, the hook teaches at block time instead. Tokenizes the matched segment via `shlex.split` (quote-preserved, sliced from the ORIGINAL command using indices computed against the `_strip_non_shell_active`-stripped copy — same position-preserving trick `block_rag_cli_document_repeat.py` uses), walks tokens classifying value-consuming flags vs positionals: `get_file_content`'s `--offset`/`--limit` and `download_files`'s `--dest` each consume their own value token, everything else is a positional. **False-positive trap solved:** `download_files --dest DIR` — `DIR` is a LOCAL directory by design (where downloaded files land), explicitly excluded from the positional-path check via the per-subcommand `_VALUE_FLAGS` set, regardless of whether `--dest` appears before or after the repo-path positionals. Only positions `[2:]` (after owner/repo) are checked — `get_file_content` has exactly one (`path`), `download_files` has one-or-more (`paths`, `nargs="+"` in the real CLI). Fail-open on any parse/tokenize error.
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message naming the offending value) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_fire_log.log_fire`; stdlib (`json`, `re`, `shlex`).

**Smoke:** `dev/hook_smoke/test_block_gh_cli_local_path.py` (15 cases: 5 block — `/Users/...`, `~/...`, absolute `download_files` positional, `~/...` among multiple `download_files` positionals, local path with a preceding `--limit` flag; 4 pass — repo-relative path, the `--dest` trap case in both flag positions, `--metadata-only` flag present; 4 untouched — `get_repo_tree`/`index_issues`/`repo_freshness`/non-gh-cli; 2 shell-strip — single-quote, heredoc). Report: `dev/hook_smoke/md/block_gh_cli_local_path_smoke_report.md`.

---

### block_rag_cli_chained.py (92 LOC, 2026-08 path-substring FP fix)

**Purpose:** PreToolUse hook (Bash) — engages when any SEGMENT (post-split) starts with an actual `rag-cli` invocation, optionally env-var-prefixed (`_RAG_CLI_SEGMENT_RE`, local `_ASSIGN_PREFIX` pattern matching `_known_cli.py`'s). **2026-08 path-substring FP fix:** the trigger used to be a bare `\brag-cli\b` search over the WHOLE command — matched `rag-cli` as a PATH SUBSTRING too (observed FPs: `ls /Users/.../cli/rag-cli/data/pdf/searxng`, `cd <rag-cli path> && ls`, both blocked with the piping message although no rag-cli tool was invoked). Fixed by splitting first (`_SEPARATOR_RE.split`), then checking whether ANY resulting segment starts with `rag-cli` — a path argument to `ls`/`cd`/etc. is never itself a segment start, so it can no longer trigger the hook. `rag-cli search` is PROTECTED: no redirect (`_RAG_SEARCH_SEGMENT_RE` + `_REDIRECT_RE`) — output is bounded and must land directly in context (2026-08: absorbed from the deleted `rewrite_rag_cli_search_noise.py` — rewrite-and-strip-noise superseded by block). Other rag-cli subcommands (`index`, `delete`, `list_documents`, etc.) keep their pre-existing redirect-allowed behavior unchanged. **2026-08 cross-CLI relax:** every OTHER segment (in ANY position, not just trailing) must be a known CLI call, guard, echo/printf, or loop scaffold (`_known_cli.is_allowed_chain_segment`) — replaces the old "trailing-only, same-tool-only" rule (`rag-cli index ... && rag-cli delete ...` allowed, `rag-cli index ... && rag-cli search ... && gh-cli get_issue ...` now ALSO allowed, where a non-rag-cli trailing segment used to block unconditionally). **2026-08 loop-scaffold relax:** `for`/`while` batch loops over `rag-cli` calls and bare `echo`/`printf` segments (e.g. `rag-cli index ... && echo done`) now pass via `_known_cli.is_allowed_chain_segment`'s loop-scaffold/echo predicates; a foreign command inside a loop body still blocks. Exits 2 + stderr on violation. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_known_cli.is_allowed_chain_segment`, `_fire_log.log_fire`; stdlib (`json`, `re`).

**Blocked patterns:**
- `rag-cli index --collection x ; tail /tmp/x.txt` — rag-cli followed by tail via `;`
- `rag-cli search "q" coll | grep foo` / `rag-cli list_documents coll | head` — piped to a non-CLI command
- `rag-cli search "q" coll > /tmp/out.txt` — protected search command redirected
- `for c in a b c; do curl http://evil.com/$c; rag-cli search "$c" coll; done` — foreign command inside a loop body still blocks
- `rag-cli index --collection x && ls /Users/x/cli/rag-cli/data/pdf/y` — a REAL rag-cli invocation still triggers full protection even though the chained segment's path also mentions `rag-cli` (the fix only changed what counts as the TRIGGER, not what counts as an allowed chained segment)

**Allowed patterns:**
- `rag-cli index --collection x > /tmp/x.txt` — non-search subcommand, redirect-allowed
- `[ -f .rag-docs.json ] && rag-cli update_docs .` — leading guard
- `cd /some/path && rag-cli index --collection x` — leading cd guard
- `rag-cli delete --collection x && rag-cli index --collection x` — both segments are rag-cli
- `rag-cli search "q" coll && gh-cli get_issue owner/repo 5` — cross-CLI chain (2026-08 relax; used to block)
- `rag-cli index --collection x && echo done` — bare echo segment (2026-08 loop-scaffold relax)
- `for c in a b c; do echo "collection: $c"; rag-cli search "$c" coll; done` — batch loop over a known CLI (2026-08 loop-scaffold relax)
- `ls /Users/.../cli/rag-cli/data/pdf/searxng` / `cd /Users/.../cli/rag-cli && ls` — `rag-cli` present only as a path substring, no segment starts with it (2026-08 FP fix)
- any command with no segment starting with `rag-cli` — not policed (anchor exits early)
- `rag-cli` inside single-quoted string / heredoc body — blanked by `_strip_non_shell_active`, anchor fails

**Segment split.** Same `_SEPARATOR_RE` as `block_gh_cli_chained.py`: splits on `&&` `||` `;` `|` newline and space-bounded `&`; `>&`/`2>&1` redirects survive intact. Split happens ONCE, up front; the resulting segment list is reused both for the trigger check (`any(_RAG_CLI_SEGMENT_RE.match(seg) ...)`) and the per-segment policing loop. Per segment: `_RAG_SEARCH_SEGMENT_RE` match → check `_REDIRECT_RE`, block if present, else pass; else `is_allowed_chain_segment()` (known-CLI, guard, echo/printf, or loop scaffold) → pass; else block.

**Smoke:** `dev/hook_smoke/test_block_rag_cli_chained.py` (24 cases incl. search-protected redirect/pipe blocks, cross-CLI-relax passes, pre-existing redirect/guard/cd/two-rag-cli/no-rag-cli/single-quote/heredoc cases, for/while loop-scaffold passes, foreign-command-in-loop-body block, path-substring FP-fix passes, real-invocation-still-blocks regression check).

---

### block_websearch_scrape_chained.py (91 LOC, 2026-08 loop-scaffold relax)

**Purpose:** PreToolUse hook (Bash) — replaces the deleted `rewrite_websearch_scrape_noise.py`. `websearch scrape_url` is PROTECTED: no redirect (`_SCRAPE_SEGMENT_RE` + `_REDIRECT_RE`) — the page returns in full and must land directly in context. **Proven incident (2026-08-24):** `websearch scrape_url URL > /tmp/f.md 2>&1; wc -l /tmp/f.md; head -120 /tmp/f.md` — the rewrite hook silently stripped the redirect, leaving the dependent `wc`/`head` segments to hit a nonexistent file; the call exited 1 and surfaced as `[ERROR]` although the scrape succeeded. Blocking instead of rewriting forces a standalone re-issue — no dependent segment can ever desync from a silently-edited command. Same shape as `block_gh_cli_chained.py`/`block_rag_cli_chained.py`: every OTHER segment must be a known CLI call, guard, echo/printf, or loop scaffold (`_known_cli.is_allowed_chain_segment`) — `search_web`/`search_engine_drilldown` are simply `websearch` segments, not policed for redirects. **2026-08 loop-scaffold relax:** `for`/`while` batch loops over `scrape_url` and bare `echo`/`printf` segments now pass; a foreign command inside a loop body still blocks. Exits 2 + stderr on violation. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_known_cli.is_allowed_chain_segment`, `_fire_log.log_fire`; stdlib (`json`, `re`).

**Blocked patterns:**
- `websearch scrape_url URL > /tmp/f.md 2>&1; wc -l /tmp/f.md; head -120 /tmp/f.md` — the proven incident
- `websearch scrape_url URL | head -50` — piped
- `websearch scrape_url URL ; tail -5 /tmp/x.md` — chained with a non-CLI command via `;`
- `for u in a b; do curl http://evil.com/$u; websearch scrape_url "$u"; done` — foreign command inside a loop body still blocks

**Allowed patterns:**
- `websearch scrape_url URL` — standalone
- `websearch scrape_url URL1 && websearch scrape_url URL2` — same-tool combine (2026-08 cross-CLI relax)
- `websearch scrape_url URL && rag-cli search "q" coll` — cross-CLI chain
- `cd /tmp && websearch scrape_url URL` — leading cd guard
- `websearch scrape_url URL && echo done` — bare echo segment (2026-08 loop-scaffold relax)
- `for u in a b; do echo "scraping: $u"; websearch scrape_url "$u"; done` — batch loop over a known CLI (2026-08 loop-scaffold relax)
- `websearch search_web "query"` — different subcommand, not protected

**Segment split.** Same `_SEPARATOR_RE`/mechanic as `block_gh_cli_chained.py`/`block_rag_cli_chained.py`.

**Smoke:** `dev/hook_smoke/test_block_websearch_scrape_chained.py` (21 cases incl. the verbatim incident command, redirect/pipe/foreign-segment blocks, cross-CLI-relax passes, for/while loop-scaffold passes, foreign-command-in-loop-body block).

---

### block_worker_cli_read_chained.py (91 LOC, 2026-08 loop-scaffold relax)

**Purpose:** PreToolUse hook (Bash) — replaces the deleted `rewrite_worker_cli_capture_noise.py` / `rewrite_worker_cli_response_noise.py` (one hook covers both subcommands — they were direct clones of each other). `worker-cli capture`/`worker-cli response` are PROTECTED: no redirect and no pipe (`_READ_SEGMENT_RE` + `_REDIRECT_RE`) — clean, bounded output (2026-06-22 capture redesign) must land directly in context. **Retires two old allowances** documented on the deleted rewrite hooks: `worker-cli capture X > /tmp/file` ("legitimate — save clean output to disk") and `worker-cli capture X | tail -40` ("documented legitimate fallback") — both predate the capture redesign that made its output natively context-ready like `response`'s; the workaround's rationale no longer holds. Same shape as `block_gh_cli_chained.py`/`block_rag_cli_chained.py`: every OTHER segment must be a known CLI call, guard, echo/printf, or loop scaffold (`_known_cli.is_allowed_chain_segment`) — unlike `linkedin`/`websearch`/gh-cli/rag-cli-search, `cd` is a real pattern here (`worker-cli capture`/`response` resolve the target project via `resolve_project_path`, which falls back to cwd when the optional `project_path` positional is omitted). `status`, `list`, `send`, `merge`, `spawn`, `kill`, `revive`, `wait` are simply `worker-cli` segments, not policed for redirects. **2026-08 loop-scaffold relax:** `for`/`while` batch loops over `capture`/`response` and bare `echo`/`printf` segments now pass; a foreign command inside a loop body still blocks. Exits 2 + stderr on violation. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_known_cli.is_allowed_chain_segment`, `_fire_log.log_fire`; stdlib (`json`, `re`).

**Blocked patterns:**
- `worker-cli capture janitor | tail -40` — piped (retired fallback)
- `worker-cli capture janitor > /tmp/out.txt` — redirected (retired legitimate-use allowance)
- `worker-cli response janitor | head -20` — piped
- `worker-cli capture janitor ; grep ERROR /tmp/x.log` — chained with a non-CLI command via `;`
- `for w in a b; do curl http://evil.com/$w; worker-cli capture "$w"; done` — foreign command inside a loop body still blocks

**Allowed patterns:**
- `worker-cli capture janitor` / `worker-cli response janitor` — standalone
- `worker-cli capture janitor && worker-cli response janitor` — same-tool combine (2026-08 cross-CLI relax)
- `worker-cli capture janitor && rag-cli search "q" coll` — cross-CLI chain
- `cd /path/to/project && worker-cli capture janitor` — leading cd guard (real pattern — see Purpose)
- `worker-cli capture janitor && echo done` — bare echo segment (2026-08 loop-scaffold relax)
- `for w in janitor scribe; do echo "capturing: $w"; worker-cli capture "$w"; done` — batch loop over a known CLI (2026-08 loop-scaffold relax)
- `worker-cli status janitor` / `worker-cli list` — different subcommands, not protected

**Segment split.** Same `_SEPARATOR_RE`/mechanic as `block_gh_cli_chained.py`/`block_rag_cli_chained.py`.

**Smoke:** `dev/hook_smoke/test_block_worker_cli_read_chained.py` (23 cases incl. redirect/pipe/foreign-segment blocks, cross-CLI-relax passes, cd-guard passes, for/while loop-scaffold passes, foreign-command-in-loop-body block).

---

### block_duallog_chained.py (89 LOC, new 2026-09-04)

**Purpose:** PreToolUse hook (Bash) — triggered by the 2026-09-04 incident: the orchestrator ran `duallog expand <session> 1 --before 0 --after 0 | head -60` and later `| tail -25`, reading only PART of a msg — impossible to notice what got cut, and the whole point of `expand` is a msg's content in full. Unlike `block_worker_cli_read_chained.py`, EVERY `duallog` subcommand (`sessions`, `msgs`, `expand`, `search`) is protected, not just a subset — one anchor regex (`_DUALLOG_SEGMENT_RE`, `^duallog\b`) covers all four, since `duallog` has no "unprotected" subcommand the way `worker-cli status`/`list` are. A protected segment must carry no redirect and no pipe (`_REDIRECT_RE`; pipes are caught structurally — `_SEPARATOR_RE` splits on `|` first, turning the pipe target into its own foreign segment). Same shape as the other four chained-CLI hooks: every OTHER segment must be a known CLI call, guard, echo/printf, or loop scaffold (`_known_cli.is_allowed_chain_segment`). Exits 2 + stderr on violation, naming re-issuing the call standalone and reading the whole output. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_known_cli.is_allowed_chain_segment`, `_fire_log.log_fire`; stdlib (`json`, `os`, `re`, `sys`).

**Blocked patterns:**
- `duallog expand s 1 --before 0 --after 0 | head -60` — the trigger incident, first observed form
- `duallog expand s 1 --before 0 --after 0 | tail -25` — the trigger incident, second observed form
- `duallog expand s 1 > /tmp/out.txt` — redirected
- `duallog search foo ; grep bar /tmp/x.log` — chained with a non-CLI command via `;`

**Allowed patterns:**
- `duallog expand s 5` — standalone
- `duallog sessions && duallog msgs x` — same-tool combine (via `_DUALLOG_SEGMENT_RE` matching both segments directly)
- `cd /x && duallog search foo` — leading cd guard
- `duallog search foo && gh-cli get_issue owner/repo 5` — cross-CLI chain (`duallog` is now a `KNOWN_CLI_TOOLS` entry, see `_known_cli.py`)

**Segment split.** Same `_SEPARATOR_RE`/mechanic as `block_gh_cli_chained.py`/`block_rag_cli_chained.py`/`block_worker_cli_read_chained.py`.

**Smoke:** `dev/hook_smoke/test_block_duallog_chained.py` (6 cases incl. the two verbatim incident forms, a redirect block, same-tool combine, cd-guard, and standalone — plus the standard malformed-payload fail-open check).

---

### block_rag_cli_index_isolated.py (98 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks any `rag-cli index` call that shares the Bash invocation with anything other than shell variable assignments and a `cd`, or that carries any command/process substitution anywhere. `rag-cli index` runs for minutes; `block_rag_cli_chained.py`'s trailing-only rule misses noise placed BEFORE the index segment (e.g. `tail <log> \n echo ... \n cd ... && rag-cli index ...` — a poll-then-index pattern that grabs the collection lock mid-run). This hook enforces the tighter rule: any number of assignment-only segments, any number of `cd` segments, exactly one `rag-cli index` segment (optionally env-var-prefixed, e.g. `PYTHONUNBUFFERED=1 rag-cli index ...`), nothing else — in any position, and no `$(...)`/backtick/`<(...)`/`>(...)` anywhere in the raw command (a subshell has no legitimate reason to exist in an isolated index call, and is a proven vector for smuggling a second command through an assignment value, argument, or redirect target). Backslash+newline line-continuations are collapsed before segment-splitting (not treated as a separator). Out of scope for all other rag-cli subcommands (`search`, `delete`, `list_documents`, etc.), which stay governed by `block_rag_cli_chained.py`. Exits 2 + stderr on violation. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_fire_log.log_fire`; stdlib (`json`, `re`).

**Blocked patterns:**
- `tail -20 /tmp/x.log \n echo ... \n cd ... && rag-cli index --collection x > /tmp/out.log 2>&1` — the observed incident: polling noise before a leading cd + index
- `tail -20 /tmp/x.log && rag-cli index --collection x` — noise before index
- `rag-cli index --collection x && echo done` — noise after index
- `rag-cli index --collection x ; tail /tmp/x.log` — noise after index via `;`
- `rag-cli delete --collection x && rag-cli index --collection x` — a second rag-cli command (even `rag-cli`) is not exempt
- `rag-cli index --collection x | tee /tmp/log` — piped
- `tail -20 /tmp/x.log && PYTHONUNBUFFERED=1 rag-cli index --collection x` — env-var-prefixed index does NOT exempt a preceding non-cd/non-assignment segment (2026-08-01 fix — see Gotchas)
- `RAG_ROOT=/x \n tail /tmp/y.log \n cd "$RAG_ROOT" && PYTHONUNBUFFERED=1 rag-cli index --collection x` — the standalone assignment line is allowed, the `tail` line still blocks
- `X=$(tail /tmp/a.log) rag-cli index --collection x` / `` X=`tail /tmp/a.log` rag-cli index --collection x `` — command substitution smuggled through an assignment value (2026-08-02 fix — see Gotchas)
- `rag-cli index --collection $(cat /tmp/name.txt)` / `rag-cli index --collection x > `pwd`/out.log` — substitution in an argument or redirect target
- `rag-cli index --collection x > >(tail -5)` / `< <(cat /tmp/y)` — process substitution
- `X=$((1+1)) rag-cli index --collection x` — arithmetic expansion (`$((` starts with `$(`, same gate)
- `cd "$(pwd)" && rag-cli index --collection x` — substitution nested inside a double-quoted `cd` target
- `rag-cli index --collection x &tail /tmp/y` / `rag-cli index --collection x&tail /tmp/y` — bare `&` smuggles a second command regardless of surrounding whitespace (2026-08-02 fix — see Gotchas)

**Allowed patterns:**
- `rag-cli index --collection x` — bare, standalone
- `rag-cli index --collection x > /tmp/out.log 2>&1` — redirect is not a separator, stays in the segment
- `cd /some/path && rag-cli index --collection x` — cd + index, nothing else
- `cd /path && rag-cli index --collection x > /tmp/out.log 2>&1`
- `PYTHONUNBUFFERED=1 rag-cli index --collection x` — env-var prefix on the index segment itself
- `RAG_ROOT=~/path \n cd "$RAG_ROOT" && PYTHONUNBUFFERED=1 rag-cli index --collection x \\\n > /tmp/out.log 2>&1` — the canonical skill form: standalone assignment line, cd, env-prefixed index, backslash-continued redirect
- `X="a;b" rag-cli index --collection x` — quoted metacharacter in an assignment value, not command substitution
- `rag-cli index --collection x &> /tmp/out.log` — `&>` redirect, not the bare backgrounding `&` separator
- any command without `rag-cli index` — out of scope, anchor exits early (`rag-cli search`/`delete`/`list_documents` all pass)
- `rag-cli index` inside a quoted string / heredoc body — blanked by `_strip_non_shell_active`, anchor fails

**Segment split.** `_SEPARATOR_RE` splits on `&&` `||` `;` `|` newline and bare `&` (background) — the single-`&` alternative uses `(?<![&>])&(?![&>])` (lookaround, no whitespace requirement) so it excludes `&&`/`&>`/`N>&M` (`2>&1`) but still catches `&` with no surrounding spaces at all (`x&tail`); redirects (`>`, `2>&1`) survive intact as part of their segment. Before splitting, `_LINE_CONTINUATION_RE` (`\\\n`) is collapsed to a space so a backslash-continued line stays one logical segment. Fast-path anchor `_RAG_INDEX_RE` (`\brag-cli\s+index\b`) searched first; if absent, exit 0 immediately. `_SUBSHELL_RE` (`\$\(|`|<\(|>\(`) is then checked against the RAW (unstripped) command — a hard gate independent of segment classification, since `_strip_non_shell_active` keeps `$()`/backticks shell-active outside quotes but blanks them inside `"..."` even though real bash still evaluates them there. Every segment must then match one of three classifiers: `_RAG_INDEX_SEGMENT_RE` (`^(?:VAR=val\s+)*rag-cli\s+index\b` — env-assignment prefix optional), `_CD_SEGMENT_RE` (`^cd\b`), or `_ASSIGNMENT_ONLY_SEGMENT_RE` (`^(?:VAR=val\s*)+$` — one or more bare assignments, nothing else) — all position-independent; exactly one index segment is required, more than one blocks.

**Gotchas:**
- **2026-08-01 fix — env-var prefix bypass.** The original `_RAG_INDEX_SEGMENT_RE` was anchored `^rag-cli\s+index\b` with no assignment-prefix allowance. An env-prefixed segment (`PYTHONUNBUFFERED=1 rag-cli index ...`) matched neither the index regex nor the cd regex, so `index_segments` came back empty and the early-exit `if not index_segments: sys.exit(0)` treated the whole command as out-of-scope — silently ALLOWING any noise placed alongside an env-prefixed index call. Fixed by making the assignment prefix part of `_RAG_INDEX_SEGMENT_RE` itself, and adding `_ASSIGNMENT_ONLY_SEGMENT_RE` as a third allowed classifier (needed because a real skill invocation commonly declares `RAG_ROOT=...` on its own line before `cd "$RAG_ROOT"`). See `process-docs/tool_use_safety/`.
- **Line continuation:** without the `_LINE_CONTINUATION_RE` collapse, `rag-cli index --collection x \` + newline + `> /tmp/x.log` split into two segments at the bare `\n`, and the second (`> /tmp/x.log`) matched neither classifier — a legitimate backslash-continued redirect blocked.
- **2026-08-02 fix — command-substitution and bare-`&` smuggling.** `_ASSIGN_TOKEN`'s value part (`\S*`) happily swallows `$(tail /tmp/a.log)`, so an assignment segment could carry an arbitrary command through a value that segment-classification alone never inspects — closed with the standalone `_SUBSHELL_RE` gate. Separately, the original single-`&` pattern required whitespace on both sides (`\s&(?=\s|$)`), so `x &tail` / `x&tail` (no space, or no trailing space) matched no separator at all and stayed glued into the index segment — real bash still tokenizes `&` as a background operator regardless of adjacent whitespace, so the lookaround was tightened to drop the whitespace requirement while still excluding `&&`/`&>`/`N>&M`. See `process-docs/tool_use_safety/`.

**Smoke:** `dev/hook_smoke/test_block_rag_cli_index_isolated.py` (37 cases: 20 block covering the observed incident, the 2026-08-01 env-prefix/assignment-line holes, and the 2026-08-02 command-substitution/process-substitution/arithmetic-expansion/bare-`&` holes; 17 allow covering bare/redirect/cd/env-prefix/assignment-line/line-continuation/quoted-metacharacter/`&>`-redirect/out-of-scope-subcommand/no-rag-cli/single-quote/heredoc).

---

### block_rag_docs_layer.py (119 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks `rag-cli search` calls on any `*-docs` collection that lack a `--document` or `--exclude` filter naming `process-docs`. The `<Project>-docs` RAG collections mix `process-docs/**` (process history) and `**/DOCS.md` (code module map); an unscoped search dilutes results across both layers. Process-layer search: `--document 'process-docs/%'` (or a specific `process-docs/<area>/%'`). Code-layer search: `--exclude 'process-docs/%'`. Exits 2 + stderr on violation. Exits 0 on any parse/tokenization error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message with the two valid filter forms) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_fire_log.log_fire`; stdlib (`json`, `re`, `shlex`).

**Blocked patterns:**
- `rag-cli search "q" monitor-cc-docs` — no filter at all
- `cd /x && rag-cli search "q" foo-docs` — collection ends `-docs`, no filter, after a leading cd
- `rag-cli search "q" monitor-cc-docs --document 'src/search/%'` — filter present but value doesn't contain `process-docs` (known edge case, see Gotchas)

**Allowed patterns:**
- `rag-cli search "q" monitor-cc-docs --document 'process-docs/%'` — process-layer filter
- `rag-cli search "q" monitor-cc-docs --exclude 'process-docs/%'` — code-layer filter
- `rag-cli search "q" monitor-cc-docs --document='process-docs/%'` — `=`-form filter
- `rag-cli search "q" monitor-cc-reference` — collection doesn't end `-docs`, rule inapplicable
- `rag-cli list_documents monitor-cc-docs` — not `search`, out of scope
- `rag-cli search` token inside a quoted string — blanked by `_strip_non_shell_active`, anchor fails

**Segment extraction.** Same technique as `rewrite_rag_cli_search_noise.py`: `_RAG_RE` (`\brag-cli\s+search\b`) is matched against the shell-stripped command; the segment end is found via the same chain-operator/noise regexes. Because `_strip_non_shell_active` is position-preserving, the match indices are then sliced out of the **original** (unstripped) command — recovering real quoted argument values (e.g. `'process-docs/%'`) for `shlex.split` tokenization, rather than the blanked stripped form.

**Predicate.** `_segment_violates()`: `shlex.split` the original segment → find `collection` (2 tokens after the `search` literal) → if it doesn't end with `-docs`, no violation → else violation unless any `--document`/`--exclude` token (space-separated or `--flag=value` form) has a value containing the substring `process-docs`.

**Known edge case:** a code SUB-area search like `--document 'src/search/%'` does not contain `process-docs`, so it is blocked under this predicate — the correct form for scoped code search is `--exclude 'process-docs/%'` (broad code-layer exclusion), not a positive `--document` on a code subpath. A more permissive predicate (e.g. accepting any `--document` value NOT starting with `process-docs` as implicitly code-layer) was intentionally not implemented — deferred pending real usage data.

**Smoke:** `dev/hook_smoke/test_block_rag_docs_layer.py` (11 cases: 3 block, 8 allow).

---

### block_rag_corpus_read.py (108 LOC, 2026-08)

**Purpose:** PreToolUse hook (Bash) — blocks raw-content-read commands (`cat`, `grep`, `head`, `tail`, `sed`, `awk`, `rg`, `less`, `more`) targeting a path under rag-cli's document-chunk store (`rag-*/data/documents/`). Reading these files directly bypasses the ranking/formatting `rag-cli search`/`rag-cli read_document` perform and returns raw chunk-store files instead of search results — see `process-docs/tool_use_safety/2026-08-28_rag_cli_path_indirection_bypass.md`, which documents a worker routing around the (then-buggy) `block_rag_cli_chained.py` FP by reading the corpus through `cat`/interpreter indirection because the block message never named an allowed alternative. This hook's `_BLOCK_MESSAGE` explicitly names both sanctioned forms (`rag-cli search <query> <collection>`, `rag-cli read_document <collection> <doc_id>`) for that reason. File management and deletion over the corpus tree (`ls`, `rm`, `mv`, `mkdir`) are deliberately NOT policed — those are sanctioned operator actions, only bypassing rag-cli's own read path is blocked. Bash-only by design (no Read-tool matcher) — Read already has its own directory/oversize handling; this hook's scope is shell indirection specifically. `_CORPUS_PATH_RE` matches `rag-[^/\s]*` (not a literal `rag-cli`) so a renamed checkout or worktree (`rag-cli-eval`, `rag-cli-convert`) is still caught — a glob dodge around a literal-string match. Exits 2 + stderr on violation. Exits 0 on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message naming both sanctioned rag-cli forms) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_fire_log.log_fire`; stdlib (`json`, `re`).

**Blocked patterns:**
- `cat /Users/x/cli/rag-cli/data/documents/github_issues/123.md` — direct read of a corpus document
- `grep -r foo /Users/x/cli/rag-cli/data/documents/` — recursive grep over the corpus tree
- `head -50 "/Users/x/cli/rag-cli/data/documents/x.md"` — quoted corpus path (path recovered from the ORIGINAL, unstripped segment — quoting alone does not evade the check)
- `cat /Users/x/cli/rag-cli-eval/data/documents/z.md` — renamed checkout (glob dodge via `rag-[^/\s]*`)
- `rag-cli index --collection x && cat /Users/x/cli/rag-cli/data/documents/z.md` — the corpus-read segment blocks regardless of what else is chained alongside it

**Allowed patterns:**
- `ls /Users/x/cli/rag-cli/data/documents/` — file management, not a content read
- `rm -rf /Users/x/cli/rag-cli/data/documents/old` / `mv ...` / `mkdir ...` — deletion and management stay sanctioned
- `cat /etc/hosts` — no corpus path involved
- `rag-cli search "q" coll` / `rag-cli read_document coll doc1` — the sanctioned forms themselves, untouched (this hook only polices raw shell reads)
- `echo "you could cat data/documents/x"` — quoted mention, not an actual read (segment starts with `echo`, not a read command)
- corpus path text inside a heredoc body — blanked by `_strip_non_shell_active` before segment-start matching, so the body line never matches `_READ_CMD_RE`
- `cat data/documents/foo.md` (relative, no `rag-*` prefix visible in the command text) — known text-only-matching limitation, shared with the sibling rag-cli isolation hooks (none of them resolve paths against cwd)

**Segment split.** Same `_SEPARATOR_RE` as the chained-CLI hook family (`&&` `||` `;` newline `|` space-bounded `&`). `_split_segments()` walks `_SEPARATOR_RE.finditer()` over the STRIPPED command once, yielding `(stripped_segment, original_segment)` pairs at IDENTICAL index ranges in both copies (same length, position-preserving strip) — `_READ_CMD_RE.match()` runs against the stripped copy (command-name detection, immune to heredoc/quote-mimicry), `_CORPUS_PATH_RE.search()` runs against the ORIGINAL copy (recovers a real path even when quoted, since quoting blanks to spaces in the stripped copy but not the original).

**Gotchas:**
- **Trim-boundary bug (caught in dev, not shipped):** the first `_trim_pair()` draft trimmed both copies using `stripped_seg.strip()`'s boundary. A quoted argument at the very END of a segment blanks to trailing SPACE characters in the stripped copy, indistinguishable from real trailing whitespace — `.strip()` removed them, and the identical index range then cut the real (quoted) path text out of the original copy too, silently under-matching `head -50 "/path/.../data/documents/x.md"`. Fixed by computing the trim range from the ORIGINAL segment's own whitespace boundary instead (real whitespace only, quote characters are never whitespace) and applying that range to both copies.
- **Argument-role blindness:** the hook does not distinguish a grep PATTERN argument from a file-path argument (no `shlex`-based flag/positional parsing, unlike `block_rag_docs_layer.py`) — `grep "rag-cli/data/documents" /tmp/notes.txt` searching FOR that literal string is not mistaken for a real corpus read only because `_CORPUS_PATH_RE`'s leading boundary (`^` or `/` immediately before `rag-`) fails to match a quote character; a differently-worded pattern could in principle still false-block. Accepted: the failure direction (blocking a rare crafted string) is the safe one for a policy hook, and a full grep-flag parser was judged over-detailed for this hook's scope.

**Smoke:** `dev/hook_smoke/test_block_rag_corpus_read.py` (24 cases incl. all 9 read commands blocked, glob-dodge renamed-checkout blocks, quoted-path block, mutation/management allows, no-corpus-path allows, sanctioned-form allows, echo/heredoc shell-strip allows, relative-path limitation, malformed-payload fail-open, block-message content checks).

---

### block_noop_edit.py (42 LOC)

**Purpose:** PreToolUse hook (Edit) — blocks Edit calls where `old_string == new_string`. CC rejects these with "No changes to make: old_string and new_string are exactly the same" — the hook surfaces this before the round-trip. Exits 2 + stderr. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {old_string, new_string}}`).
**Writes:** stderr (block message with re-read advice) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Edit entry). Never imported.
**Calls out:** stdlib only (`json`).

**Blocked patterns:** any Edit where `old_string` and `new_string` are identical non-None strings.

**Allowed patterns:** any Edit with different strings; missing/non-string fields (fail-open).

---

### block_read_directory.py (43 LOC)

**Purpose:** PreToolUse hook (Read) — blocks Read calls where `file_path` points to a directory. CC rejects these with "Read tool cannot read directories" — the hook surfaces this before the round-trip and suggests `ls` instead. Exits 2 + stderr. Exits 0 on any parse/internal error or nonexistent path (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {file_path}}`).
**Writes:** stderr (block message with `ls` alternative) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Read entry). Never imported.
**Calls out:** stdlib only (`json`, `os`).

**Blocked patterns:** `file_path` resolves to an existing directory (`os.path.isdir`).

**Allowed patterns:** file paths, nonexistent paths, missing/non-string field (all fail-open).

---

### block_read_oversize.py.disabled

**Disabled 2026-07-22** — pre-empted CC's own >256KB Read rejection (redundant), pinned to a CC-internal size number that goes stale on CC updates, and its "grep the file first" advice contradicts the just-added `block_po_read.py` (which forbids partial shell-reads of persisted-output exports — the two hooks disagreed on the correct escape for an oversize file). Renamed via `git mv` (file still in repo for history, not registered in `_HOOK_SCRIPTS`). Not replaced by another hook — CC's native size rejection is left to fire on its own.

---

### block_bd_cli_worker.py (62 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks `bd` CLI invocations from inside a worker session (worktree CWD). Workers running `bd` commands write bead data to the worktree's `.beads/` copy, silently corrupting main-repo bead state on merge or worktree removal. Exits 2 + stderr. Exits 0 when not running from a worktree or on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** stdlib only (`json`, `re`, `os`).

**Blocked patterns:** any Bash command containing `bd <subcommand|flag>` when `os.getcwd()` contains `.claude/worktrees/`.

**Allowed patterns:** any `bd` call from outside a worktree (main session); quoted `bd` examples in strings; non-`bd` commands; parse errors (fail-open).

---

### block_cd_drift.py (71 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks Bash commands that `cd` into a `.claude/worktrees/` path without `cd`-ing back at the end of the chain. Bash tool calls share CWD across invocations; a dangling worktree `cd` causes the next call to write to the wrong tree. Exits 2 + stderr with the fix. Exits 0 when the last `cd` target is not a worktree path, or on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message with fix alternatives) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** stdlib only (`json`, `re`, `os`).

**Blocked patterns:** command contains a `cd .claude/worktrees/...` target AND that worktree path is the LAST `cd` target (no cd-back).

**Allowed patterns:** `cd <worktree> && ... && cd <main-repo>` (cd-back at end); commands with no worktree `cd`; calls from inside a worktree (workers live there — hook skips entirely); parse errors (fail-open).

---

### block_dev_imports_src.py (69 LOC, 2026-08 regression-suite exemption)

**Purpose:** PreToolUse hook (Write + Edit) — blocks dev/ scripts that import from `src/`. dev/ modules are self-contained pipeline probes; importing from `src/` breaks isolation and makes dev/ non-runnable without the full production tree. Fires on Write and Edit for files under a `dev/` path. **2026-08 exemption:** a `dev/` file is NOT a probe — and is skipped entirely, imports allowed — when it sits under a `tests/` directory segment AND its filename matches pytest's own discovery convention (`test_*.py`, `*_test.py`, or `conftest.py`). A regression suite is the categorical opposite of a probe: it exists to import and exercise the live `src/` tree, and the exemption keys off pytest's own naming convention rather than any one project's directory layout (e.g. `websearch`'s `dev/tests/`). Both conditions are required — a bare `tests/` dir doesn't exempt a stray probe someone drops there, and pytest-shaped naming alone doesn't exempt a renamed probe outside an actual test directory. Exits 2 + stderr on an unexempted match. Exits 0 on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {file_path, content|new_string}}`).
**Writes:** stderr (block message with fix) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Write and PreToolUse/Edit entries). Never imported.
**Calls out:** stdlib only (`json`, `re`).

**Blocked patterns:** Write or Edit where `file_path` matches `/dev/` AND the written content contains `^from src\.` or `^import src\.` AND the file is NOT a pytest-shaped test file under a `tests/` directory.

**Allowed patterns:** files outside `dev/`; dev/ files without `src/` imports; a `dev/.../tests/test_*.py` (or `*_test.py`/`conftest.py`) file with `src/` imports — regression suite, not a probe; parse errors (fail-open).

---

### block_except_pass.py (50 LOC)

**Purpose:** PreToolUse hook (Write + Edit) — blocks code that contains bare `except ...: pass` (silent exception swallow). Silently swallowing exceptions is prohibited — scripts must fail visibly when they cannot fulfill their purpose. Fires on Write and Edit for any file. Exits 2 + stderr with allowed alternatives. Exits 0 on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {content|new_string}}`).
**Writes:** stderr (block message with alternatives) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Write and PreToolUse/Edit entries). Never imported.
**Calls out:** stdlib only (`json`, `re`).

**Blocked patterns:** `except [OptionalType]:\n    pass` — any bare exception-swallow block in written content.

**Allowed patterns:** `except ... : raise`; `except ... as e: logger...; raise`; `finally: resource.close()`; parse errors (fail-open).

---

### block_git_add_deps.py (61 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks `git add` commands that target dependency directories (`venv/`, `.venv/`, `node_modules/`). In worktrees these directories are symlinks pointing to the main repo; staging them creates circular self-references on merge. Exits 2 + stderr. Exits 0 on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** stdlib only (`json`, `re`).

**Blocked patterns:** `git add` (with optional `-C path`) where command also contains `venv/`, `.venv/`, or `node_modules/` as a target.

**Allowed patterns:** `git add` targeting specific files; `git add .` without a dependency directory in scope (no explicit dep target in the command); parse errors (fail-open).

---

### block_git_destructive.py (97 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks destructive git operations: `git commit --amend`, `git push --force`/`-f`/`--force-with-lease`, `git commit/push --no-verify`, `git commit --allow-empty`, and `git config` modifications (read-only config variants allowed). Pattern connectors use `[^|;&\n]*` — matches cannot span across newlines in multi-line commands (closes cross-line FP: `git push` on line N + `[ -f file ]` on a later line). Enforces the Git Safety Protocol from `tool-use.md`. Exits 2 + stderr with the specific violation and a suggestion. Exits 0 on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message with label + suggestion) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** stdlib only (`json`, `re`).

**Blocked patterns:**
- `git commit --amend`
- `git push --force` / `--force-with-lease` / `-f`
- `git commit|push --no-verify`
- `git commit --allow-empty`
- `git config` (modify — write operations); read-only flags (`--list`, `--get`, `--show-origin`, etc.) are exempt

**Allowed patterns:** `git commit` (without `--amend`/`--no-verify`/`--allow-empty`); `git push` (without force flags); `git config --list|--get|...` (read-only); parse errors (fail-open).

---

### block_path_typo.py (119 LOC)

**Purpose:** PreToolUse hook (Bash + Read + Write + Edit) — detects path typos `.claire/` (tokenizer typo of `.claude/`) and `..letter` (double-dot immediately followed by lowercase letter, e.g. `..claude/`, `..src/`) and **auto-rewrites** them to `.claude/` and `../letter` respectively. Upgraded 2026-05-22 commit `ce8d220` from block-and-hint to auto-rewrite. File name preserved (`block_path_typo.py`) for `~/.claude/settings.json` compatibility; internal semantics are now rewrite.
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command|file_path[+old_string,new_string,replace_all for Edit]}}`).
**Writes:** stdout (single-line JSON `hookSpecificOutput.permissionDecision: "allow"` + `updatedInput.{command|file_path[+all 4 Edit fields]}` + `systemMessage`) on match; nothing on passthrough.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash, PreToolUse/Read, PreToolUse/Write, and PreToolUse/Edit entries). Never imported.
**Calls out:** stdlib only (`json`, `re`).

**Detected patterns:**
- `.claire/` anywhere in command (Bash) or file_path (Read/Write/Edit), after quote-stripping
- `..letter` — two dots followed by lowercase letter in path context (boundary char `^`, `/`, whitespace, `=`)

**Rewrites:**
- `.claire/` → `.claude/` (literal `str.replace`)
- `..<letter>` → `../<letter>` (regex `(^|[/\s=])(\.\.)([a-z])` → `\1\2/\3`, preserves the boundary char and letter)

**Edit-specific:** `updatedInput` for Edit carries ALL 4 fields (`file_path`, `old_string`, `new_string`, `replace_all`) per Issue #47853 OP requirements — only `file_path` is rewritten, the other three are passed through unchanged from `tool_input`.

**Edit-Matcher anomaly:** the hook is registered for Edit but evidence suggests it doesn't fire on Edit tool calls (bash + Read confirmed working in same session). See `process-docs/tool_use_safety/2026-05-22_block_path_typo_edit_no_fire.md`. The auto-rewrite form is correct; the issue is on the CC-side firing pipeline for Edit.

**Allowed (passthrough):** `.claude/` (correct spelling); `../` (valid parent traversal); quoted strings containing typo patterns (stripped before matching); parse errors (fail-open).

---

### block_venv_no_redirect.py (50 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks `./venv/bin/python <script>.py` calls that have no file redirect (`> file`) or `| tee`. Dev scripts produce verbose output that floods the context window; redirecting to `/tmp/` is mandatory (Rule 4, `tool-use.md`). Exits 2 + stderr with the required form. Exits 0 when redirect/tee present, or on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message with required form) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** stdlib only (`json`, `re`).

**Blocked patterns:** `./venv/bin/python <anything>.py` (or `venv/bin/python ...`) without `> <file>` or `| tee` in the command.

**Allowed patterns:** command includes `> /tmp/file.md` or `| tee /tmp/file.md`; commands not matching the venv-python-script pattern; parse errors (fail-open).

**Quote/heredoc stripping.** Before pattern checks, `_strip_non_shell_active()` (from `_shell_strip.py`) removes quoted regions. Prevents false-positives when `./venv/bin/python dev/...` appears as a literal example inside a `worker-cli send` message.

---

### block_worker_spawn_placement.py (99 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks `worker-cli spawn` calls that either (a) target a different project than the current session or (b) pass `--no-worktree`. Spawns always land in a worktree of the current project; cross-project or worktree-less spawns are a mis-dispatch. Exits 2 + stderr. Exits 0 when the session itself runs from inside a worktree (worker sessions don't spawn workers) or on any parse/resolution error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`); `os.getcwd()` (session CWD for project-root resolution).
**Writes:** stderr (multi-line block message naming the allowed `worker-cli spawn`/`worker-cli worktree` form) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active` (same-dir import via `sys.path` insert); `_fire_log.log_fire`.

**Blocked patterns:**
- `worker-cli spawn <name> <prompt> <path> ...` where `<path>` resolves to a different git-root than the current session's project — message points to `worker-cli worktree <name> <target_repo>` to create AND register the target-project worktree
- `worker-cli spawn ... --no-worktree` — flag present anywhere after the `spawn` subcommand

**Allowed patterns:** `project_path` of `c` or `.` (resolve to current project by definition); same-project absolute/relative paths; non-spawn commands; spawn from inside a worktree CWD (skipped); parse or path-resolution errors (fail-open).

**Project-root resolution** (mirrors worker-cli's `resolve_project_path`):
1. `os.path.abspath(expanduser(path))` → absolute form
2. Strip `/.claude/worktrees/<name>` suffix (find `/.claude/worktrees/`, keep prefix)
3. `os.path.realpath()` — normalises symlink components (`/Users` vs `/System/Volumes/Data/Users`)
4. Walk parent dirs until a `.git` directory is found → that dir is the project root; `None` if filesystem root reached

Comparison is **case-insensitive** (`.lower()` on both roots) — macOS FS is case-insensitive; established convention from `session_finder.py`.

**Quote/heredoc stripping.** Before regex matching, `_strip_non_shell_active()` (from `_shell_strip.py`) removes heredoc bodies and quoted regions. Prevents matches when `worker-cli spawn` appears as literal text inside a `worker-cli send` message.

---

### block_worker_send_background.py (54 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks `worker-cli send` commands dispatched with `run_in_background=true`. `worker-cli send` is a fire-once, must-confirm action; backgrounding risks SIGTERM-kill before delivery (exit 143, silent message loss) or the orchestrator's next action running before the send completes. Canonical pattern: send in a standalone foreground Bash call; any wake-up timer dispatched as a separate `worker-cli wait` call (Milestone 2, 2026-08 — message text updated, block condition unchanged). Exits 2 + stderr. Exits 0 when `run_in_background` is absent or false, or on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command, run_in_background}}`).
**Writes:** stderr (block message with fix) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active` (same-dir import via `sys.path` insert); `_fire_log.log_fire`.

**Blocked patterns:** any `worker-cli send <name> <message>` with `run_in_background=true`.

**Allowed patterns:** `worker-cli send` with `run_in_background=false` or field absent; commands without `worker-cli send`; `worker-cli send` appearing inside a quoted string (blanked by `_strip_non_shell_active`); parse errors (fail-open).

---

### block_worker_kill_while_working.py (102 LOC, message text corrected 2026-09-04)

**Purpose:** PreToolUse hook (Bash) — blocks `worker-cli kill <name>` when the named worker is currently `working`. Double-gate: (1) regex `\bworker-cli\s+kill\s+([\w.-]+)` on shell-stripped command captures name token(s); (2) runs `worker-cli status <name>` subprocess (timeout 3s) and blocks only when the first output token is exactly `working`. Quoted/heredoc kill commands inside `worker-cli send` messages are stripped by `_strip_non_shell_active` → no match → guaranteed allow. All non-working statuses (idle, dead, unknown), subprocess errors, timeouts, and all exceptions → allow. Exits 2 + stderr. **2026-09-04:** `_BLOCK_MESSAGE` shortened to `"worker '{name}' is working — do not kill a working worker. Not possible.\n"` — the old text ("stop it first ... or: worker-cli send '{name}' 'stop'") suggested exactly the workaround the new sibling hook (`block_worker_send_while_working.py`) now forbids, so the message no longer names an alternative at all.
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`); `worker-cli status <name>` output (subprocess).
**Writes:** stderr (block message naming the worker) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active` (same-dir import via `sys.path` insert); `_fire_log.log_fire`; `subprocess` (`worker-cli status` by absolute path via `_resolve_worker_cli()`: `shutil.which` first, then glob `~/.claude/plugins/cache/brunowinter-plugins/iterative-dev/*/bin/worker-cli` newest — CC hook env PATH does not include plugin-cache bins); `shutil`, `glob` (stdlib).

**Double-gate rationale:** pure regex alone would block a `kill` dispatched right after a worker finishes (race). The live status check ensures block iff the worker is verifiably `working` at hook-fire time — zero false positives for idle/finished/nonexistent workers.

**Known accepted residual:** a shell comment containing the literal kill + a live-working-worker-name blocks (e.g. `echo hi # worker-cli kill foo`). Consistent with the whole hook family — none of the 31 hooks strip comments. The double-gate makes this unlikely in practice.

**Smoke:** `dev/hook_smoke/test_block_worker_kill_while_working.py` (13 cases: 3 block, 9 allow, 1 accepted-residual block; asserts only on `decide()`'s `(block, name)` tuple, never the message text, so the 2026-09-04 wording change needed no test update).

---

### block_worker_send_while_working.py (102 LOC, new 2026-09-04)

**Purpose:** PreToolUse hook (Bash) — sibling to `block_worker_kill_while_working.py`, same shape applied to `worker-cli send` instead of `kill`: blocks `worker-cli send <name> <message>` when the named worker is currently `working`. Same double-gate — (1) regex `\bworker-cli\s+send\s+([\w.-]+)` on shell-stripped command captures the name token; (2) live `worker-cli status <name>` subprocess (timeout 3s), blocking only when the first output token is exactly `working` — and the identical `decide(command, status_fn)`/`_resolve_worker_cli`/`_live_worker_status`/`_parse_command` set, copied rather than shared, matching this hook family's convention of small, fully independent scripts. Worker statuses are exactly `working`/`idle`/`dead`; only `working` blocks. Exits 2 + stderr with `"worker '{name}' is working — do not send messages to a working worker. Not possible.\n"`. Exits 0 on idle, dead, an unknown/empty status, a `worker-cli status` subprocess error or timeout, or any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`); `worker-cli status <name>` output (subprocess).
**Writes:** stderr (block message naming the worker) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active` (same-dir import via `sys.path` insert); `_fire_log.log_fire`; `subprocess` (`worker-cli status`, same absolute-path resolution as the kill guard); `shutil`, `glob` (stdlib).

**Double-gate rationale, known accepted residual:** identical to `block_worker_kill_while_working.py`'s — see that entry.

**Smoke:** `dev/hook_smoke/test_block_worker_send_while_working.py` (12 cases: `decide()`-level — 3 block (single working, one-of-two working, working with a `%` suffix), 7 allow (idle, dead, unknown/empty status, quoted self-reference, heredoc self-reference, non-send command, `status_fn` exception); plus 2 subprocess-level checks against the real entrypoint: malformed stdin fails open, and a command naming an unresolvable real worker fails open).

---

### block_manual_worker_cleanup.py (59 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks raw manual worker-cleanup commands that bypass `worker-cli kill <name>` and leave orphaned state. Two patterns: (1) `tmux kill-session -t worker-*` — kills the tmux session without removing the worktree, registry entry, or branch; (2) `git worktree remove .claude/worktrees/*` — removes the worktree without stopping the session or clearing the registry. Both patterns use `[^;&|\n]*` (not `.*`) to prevent bridging across shell separators — `tmux kill-session -t main ; cmd -t worker-x` does not trigger. `git branch -D` is deliberately excluded (worker branches have no distinguishing prefix; blocking would FP on normal feature-branch deletes). Exits 2 + stderr with `worker-cli kill <name>` as the fix. Exits 0 on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message with worker-cli kill alternative) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active` (same-dir import via `sys.path` insert); `_fire_log.log_fire`.

**Blocked patterns:**
- `tmux kill-session -t worker-*` — direct session kill (any `-t` form including `-tNAME` no-space)
- `git worktree remove .claude/worktrees/*` — direct worktree remove (handles `-C path`, `--force`, absolute paths)

**Allowed patterns:** `worker-cli kill <name>`; `tmux kill-session -t non-worker-session`; `tmux kill-session` (no -t); `git worktree remove /non-claude/path`; `git worktree list`/`add`; `git branch -D`; quoted patterns inside `worker-cli send` messages (stripped); cross-separator patterns (separator guard); parse errors (fail-open).

**Smoke:** `dev/hook_smoke/test_block_manual_worker_cleanup.py` (21 cases: 8 block, 13 allow including 2 separator-guard cases and 2 quoted-string cases).

---

### block_po_read.py (79 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks shell reads that feed a Claude Code persisted-output export path (`tool-results/<id>.txt` under a `.claude/` dir — CC's full-output export when a tool result exceeds the inline preview limit) to a content-reading or content-partitioning tool (`head`, `tail`, `grep`, `egrep`, `fgrep`, `rg`, `sed`, `awk`, `cut`, `less`, `more`, `cat`, `tac`, `nl`, `zcat`, `split`, `dd`). These exports must be consumed via the Read tool — a partial shell view (`head`/`tail`/`grep`/piped `cat … | head`) or a partitioning escape (`split -l N <path> /tmp/...`, `dd if=<path> of=...`) risks acting on an incomplete result. Discriminator is path-schema only (`/.claude/` substring AND `.txt` suffix on the same token) — no size threshold, no Read-tool matcher (Read stays fully allowed). Direct structural clone of `block_log_read.py.disabled`'s Branch B (reader-tool + matching input-path segment → block) with no state file / no session counting. Exits 2 + stderr on match. Exits 0 on any parse error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_name, tool_input: {command}}`).
**Writes:** stderr (block message naming the Read-tool paging escalation) on match only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active` (same-dir import via `sys.path` insert); `_fire_log.log_fire`.

**Blocked patterns:**
- `head`/`tail`/`grep`/`cat`/`sed`/`rg`/etc. on `~/.claude/projects/.../tool-results/<id>.txt` (or `/Users/.../.claude/.../<id>.txt`)
- `cat <PO-export-path> | head -20` — reader + path co-occur in the same pipeline segment
- `split -l N <PO-export-path> /tmp/...`, `dd if=<PO-export-path> of=...` — partitions content for later partial consumption, same escape class as head/tail (live incident 2026-07: `split` bypassed the hook and fed a copy to `awk`)

**Allowed patterns:** any reader tool on a file NOT under `.claude/` (e.g. `/tmp/foo.txt`); any reader tool on a `.claude/` path NOT ending `.txt` (e.g. `settings.json`); a PO-export path as a redirect WRITE target (`echo x > .../x.txt`, stripped before the input-path check); a PO-export path appearing only inside a quoted string (blanked by `_strip_non_shell_active`); parse errors (fail-open).

**Segment split.** Same `_SEGMENT_SPLIT`/`_REDIRECT_STRIP` mechanic as `block_log_read.py.disabled`: split on `&&`/`||`/`|`/`;`/newline, strip redirect-write targets per segment before checking for a reader-tool + PO-path co-occurrence.

**Block message escalation.** States the verified-correct escape: read via the Read tool; when the total exceeds the per-call token cap, page with MULTIPLE Read calls via `offset`/`limit` (offset starts at 1); files with very long single lines need a small line-count limit per call.

**Smoke:** `dev/hook_smoke/test_block_po_read.py` (16 cases: 9 block including the piped `cat | head` case and the `split`/`dd` partitioning cases, 7 no-op including redirect-write, quoted-string, and parse-error fail-open).

---

### block_linkedin_cli_isolated.py (95 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks the `linkedin` CLI (the LinkedIn project's `~/.local/bin/linkedin` wrapper) from sharing a Bash invocation with ANY other segment — no piping (`grep`/`head`/`tail`/`sed`/`awk`/`wc`), no chaining with an unrelated command, and no more than one `linkedin` call per invocation. Rule collapses to one check: if any segment is a `linkedin` invocation, more than one segment total (of any kind) is a violation — this single condition covers both "chained with something else" and "two `linkedin` calls" without a separate count check. Differs from `block_gh_cli_chained.py` (the closest structural analog by segment-matching, but explicitly allows multiple calls of its protected tools) — `linkedin` holds a process lock for its whole dispatch and cold-starts Chrome (~7s) per invocation, so a second call in the same block does not run in parallel, it blocks on the first's lock. The count-based enforcement itself is closer to `block_rag_cli_index_isolated.py`'s `len(index_segments) > 1` check. One deliberate allowance: a single env-var-assignment prefix on the `linkedin` segment itself (`LINKEDIN_HEADED=1 linkedin get_messages`) — grounded in a real usage (`src/linkedin/browser.py` reads `LINKEDIN_HEADED` for headed-browser debugging), not invented for symmetry with `block_rag_cli_index_isolated.py`'s assignment handling. No `cd` allowance — unlike `rag-cli index` (path-relative), `linkedin` resolves via `$PATH` from any directory, so chaining a `cd` before it serves no legitimate purpose. **Explicitly does NOT chase command/process substitution** (`$(...)`, backticks, `<(...)`, `>(...)`) the way `block_rag_cli_index_isolated.py` hardens against it — that hook's target has real correctness stakes (a multi-minute indexing operation holding a collection lock); this hook's target is a performance guard only, so a false negative here just loses the optimization while a false positive would block legitimate work outright. This scope decision is stated in the hook file itself (not only here), specifically so a future reader does not "fix" it as an oversight the way the `rag-cli index` hardening fixed a real observed incident. Exits 2 + stderr on violation. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message explaining the process-lock/cold-Chrome reason, not just the rule) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_fire_log.log_fire`; stdlib (`json`, `re`).

**Blocked patterns:**
- `linkedin get_notifications | grep NEW` — piped to grep (also: head/tail/sed/awk/wc)
- `linkedin get_messages --count 3 && linkedin get_notifications` — two `linkedin` calls, even both valid
- `linkedin get_messages ; linkedin get_notifications` — same, via `;`
- `linkedin get_messages && echo done` — chained with an unrelated command
- `echo start && linkedin get_messages` — unrelated command BEFORE the `linkedin` call (no leading-segment exemption, unlike `block_rag_cli_chained.py`'s trailing-only rule)
- `LINKEDIN_HEADED=1 linkedin get_messages | grep NEW` — env-prefix does not exempt a second segment

**Allowed patterns:**
- `linkedin get_notifications --count 15` — standalone
- `linkedin get_messages --days 3` — standalone, any subcommand/flags
- `linkedin get_messages > /tmp/out.txt` — redirect is not a separator, one segment
- `LINKEDIN_HEADED=1 linkedin get_messages` — env-prefixed standalone (real usage, see Purpose)
- `linkedin` — bare, no subcommand: still exactly one segment, pinned ALLOWED not a special case
- `cd /path/to/.../linkedin && git status` — "linkedin" as a path segment inside `cd`, unrelated command follows: neither segment starts with the `linkedin` token, out of scope entirely
- `python3 cli/linkedin/cli.py get_messages` — path containing "linkedin", not the `linkedin` command itself — out of scope (this hook does not detect direct `cli.py` invocations, only the literal wrapper command)
- `grep linkedin file.txt` — "linkedin" as a grep argument, not a command
- `linkedin-web scrape` — different tool name, boundary check requires whitespace/end-of-segment after the token, not just a non-word character
- `echo "call linkedin later"`, `echo 'linkedin get_messages | grep NEW'` — quoted mentions, blanked by `_strip_non_shell_active` before segment-splitting
- any command with no `linkedin` token at all — not policed

**Segment split.** Same `_SEPARATOR_RE` as `block_gh_cli_chained.py`/`block_rag_cli_chained.py`: splits on `&&` `||` `;` `|` newline and space-bounded `&`; `>&`/`2>&1` redirects survive intact. `_LINKEDIN_SEGMENT_RE` (`^(?:VAR=val\s+)*linkedin(?:\s|$)`) requires the token at segment-start, optionally env-assignment-prefixed, followed by whitespace or end-of-segment — NOT a bare `\blinkedin\b` word boundary, which would incorrectly match `linkedin-web`/`linkedin2` (`-`/digits are non-word characters too, so `\b` alone doesn't exclude them).

**Smoke:** `dev/hook_smoke/test_block_linkedin_cli_isolated.py` (25 cases: 11 block covering pipe/chain/two-calls/leading-unrelated-command/env-prefix-then-pipe, 13 allow covering standalone/redirect/env-prefix/bare-no-subcommand/false-positive-avoidance (path segment, cd, grep argument, lookalike tool name, quoted mentions), 1 malformed-stdin fail-open).

---

### block_pipe_scraper_isolated.py (103 LOC)

**Purpose:** PreToolUse hook (Bash) — blocks `python -m src.crawler.pipe_scraper` (websearch project's long-running scraper) calls that share the Bash invocation with anything other than shell variable assignments and a `cd`, or that carry any command/process substitution anywhere. Direct clone of `block_rag_cli_index_isolated.py` with the anchor swapped: CC auto-backgrounds a Bash call only when it stands ALONE in the invocation; a worker chaining a poll (`tail`, `&& echo done`) onto the scraper call in the same invocation defeats auto-backgrounding, and the worker sleeps until the multi-minute scrape finishes instead of staying awake to poll. Segment classifier `_SCRAPER_SEGMENT_RE` additionally tolerates an interpreter path prefix before `python`/`python3` (`./venv/bin/python`, `/usr/bin/python3`) since the scraper is always invoked via a venv interpreter, not a bare CLI name. Exits 2 + stderr on violation. Exits 0 on any parse/internal error (fail-open).
**Reads:** stdin (CC PreToolUse JSON payload: `{tool_input: {command}}`).
**Writes:** stderr (block message) on violation only.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_fire_log.log_fire`; stdlib (`json`, `re`).

**Blocked patterns:**
- `python -m src.crawler.pipe_scraper --url-file /tmp/x.txt && tail /tmp/x_scrape.log` — poll chained after the scraper
- `tail /tmp/x_scrape.log && ./venv/bin/python -m src.crawler.pipe_scraper --url-file /tmp/x.txt` — poll chained before the scraper
- `./venv/bin/python -m src.crawler.pipe_scraper --url-file /tmp/x.txt | tee /tmp/log` — piped
- `X=$(tail /tmp/a.log) ./venv/bin/python -m src.crawler.pipe_scraper --url-file /tmp/x.txt` — command substitution smuggled through an assignment value
- `./venv/bin/python -m src.crawler.pipe_scraper --url-file $(cat /tmp/name.txt)` — substitution in an argument
- `./venv/bin/python -m src.crawler.pipe_scraper --url-file /tmp/x.txt &tail /tmp/y` — bare `&` smuggles a second command regardless of surrounding whitespace

**Allowed patterns:**
- `cd "$WEBSEARCH" && ./venv/bin/python -m src.crawler.pipe_scraper --url-file /tmp/x.txt --output-dir "$OUTPUT_DIR" > /tmp/x_scrape.log 2>&1` — the canonical form: cd + venv-python-module call + redirect, nothing else
- `./venv/bin/python -m src.crawler.pipe_scraper --url-file /tmp/x.txt` — bare, standalone
- `PYTHONUNBUFFERED=1 ./venv/bin/python -m src.crawler.pipe_scraper --url-file /tmp/x.txt` — env-var prefix on the scraper segment itself
- any command without `-m src.crawler.pipe_scraper` — out of scope, anchor exits early
- `src.crawler.pipe_scraper` inside a quoted string / heredoc body — blanked by `_strip_non_shell_active`, anchor fails

**Segment split.** Identical `_SEPARATOR_RE`/`_LINE_CONTINUATION_RE`/`_SUBSHELL_RE` mechanic as `block_rag_cli_index_isolated.py`: bare `&` uses the whitespace-independent lookaround, backslash-continued lines collapse to one segment before splitting, and `_SUBSHELL_RE` gates on the RAW command independent of segment classification. Every segment must match one of three classifiers: `_SCRAPER_SEGMENT_RE` (`^(?:VAR=val\s+)*(?:\S+/)?python3?\s+-m\s+src\.crawler\.pipe_scraper\b` — env-assignment prefix and interpreter path prefix both optional), `_CD_SEGMENT_RE` (`^cd\b`), or `_ASSIGNMENT_ONLY_SEGMENT_RE` (`^(?:VAR=val\s*)+$`) — all position-independent; exactly one scraper segment is required, more than one blocks.

---

### block_rag_cli_document_repeat.py (196 LOC)

**Purpose:** PreToolUse hook (Bash) — the first STATEFUL hook in this family. Blocks the 2nd (or later) single-document `rag-cli index --collection X --document Y` / `rag-cli delete --collection X --document Y` call to the SAME `(subcommand, collection)` within a 10-minute rolling window, across SEPARATE Bash invocations. `block_rag_cli_index_isolated.py` already forbids CHAINING (>1 `index` segment in one Bash call) but each individually-isolated `--document` call passes that hook fine — the gap it cannot see is REPETITION across calls: an observed incident issued ~40 consecutive `rag-cli index --document <file>` calls (and ~48 `rag-cli delete --document <file>` calls) instead of one collection-wide call, none of which individually run long enough to auto-background, so the worker stayed awake for dozens of turns instead of sleeping through one long run. State-persistence architecture is a direct clone of the disabled `block_polling_loop.py.disabled`'s pattern (append-only JSONL, self-pruned to the window on every write, count by session_id+target) — the only established stateful-hook precedent in this codebase; the alternative `last_cmd_state.jsonl`/adjacency-based "last command" pattern was deliberately NOT used (it was redesigned then fully removed in 2026-07-20/21 specifically because adjacency tracking false-positive-blocked legitimate interleaved commands — see `2026-07-20_timer_guard_concurrent_redesign.md`). Segment/argument extraction reuses `block_rag_docs_layer.py`'s technique (regex segment-end scan on the shell-stripped command, then `shlex.split` the ORIGINAL unstripped segment to recover real quoted flag values). Threshold 2, not 3: a genuine single-document op is singular by definition (pull one file back in) — a SECOND `--document` call to the same collection+subcommand within the window is already the opening move of the per-file loop, not a second legitimate one-off. Window 600s, not the polling-loop's 30s: a full model turn sits between two rag-cli calls, so a short window would expire before a real repeat pattern registers. Exits 2 + stderr (naming the collection-wide form as the fix) on the 2nd+ call. Exits 0 on any parse/state error (fail-open — a state-file failure can only undercount, never overcount, so it never causes a false block).
**Reads:** stdin (CC PreToolUse JSON payload: `{session_id, tool_input: {command}}`); `src/logs/rag_doc_repeat_state.jsonl` (own state, read-modify-write each call).
**Writes:** stderr (block message naming the collection-wide escape) on the 2nd+ call only; `src/logs/rag_doc_repeat_state.jsonl` (rewritten in full each call — self-pruning overwrite, not append-only on disk even though logically append+prune).
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PreToolUse/Bash entry). Never imported.
**Calls out:** `_shell_strip._strip_non_shell_active`, `_fire_log.log_fire`; stdlib (`json`, `re`, `shlex`, `datetime`, `os`).

**Blocked patterns:**
- `rag-cli index --collection monitor-cc-docs --document a.md` then (separate Bash call, same session, within 10 min) `rag-cli index --collection monitor-cc-docs --document b.md` — 2nd single-document index call to the same collection
- `rag-cli delete --collection monitor-cc-docs --document a.md` then `rag-cli delete --collection monitor-cc-docs --document b.md` (same session) — delete is covered identically to index

**Allowed patterns:**
- `rag-cli index --collection monitor-cc-docs --document a.md` — a single one-off `--document` call, alone, always passes
- `rag-cli index --collection monitor-cc-docs` (no `--document`, any number of times) — collection-wide call never touches the state file, out of scope by design
- a 2nd `--document` call from a DIFFERENT `session_id` — session-scoped counting, no cross-session leakage
- any command without `rag-cli index`/`delete` — anchor exits early
- a segment with `--collection` but no `--document` (or vice versa) — `_extract_target` returns `None`, not counted

**State mechanic.** `_STATE_FILE` (env-var override `MONITOR_CC_RAG_DOC_REPEAT_STATE` for test isolation) holds one JSON line per qualifying occurrence: `{ts, session_id, target}` where `target = "<subcommand>:<collection>"`. On every qualifying call: read entries with `ts >= now - 600s` (self-pruning — older entries silently dropped), append the new occurrence, overwrite the file, then count entries matching `(session_id, target)`; block if count `>= 2`. Accepted trade-off (not discovered later): a legitimate collection-wide call interspersed between two `--document` calls does NOT reset the window — purely time-based, matching the established precedent and avoiding the false-positive history of adjacency-based state.

**Smoke:** `dev/hook_smoke/test_block_rag_cli_document_repeat.py` (7 cases: single `--document` call allow, 2nd call block, 3x collection-wide always-allow, cross-session independence, delete-subcommand-also-counts, malformed-stdin fail-open).

---

### feedback_bash_error.py (74 LOC, 2026-08-29)

**Purpose:** PostToolUseFailure hook (Bash) — the first hook of the feedback class and the first non-PreToolUse hook in this package. When a Bash call comes back as an error, it feeds one fixed instruction back to the model via `hookSpecificOutput.additionalContext`: diagnose before retrying, retry corrected once, stop and report after two failures on the same goal. Stateless — the message itself carries the two-failure rule, so the hook counts nothing. Exits 0 in every path; it cannot block, because the call has already run.
**Reads:** stdin (CC PostToolUseFailure JSON payload: `{tool_name, tool_input: {command}, error, is_interrupt, session_id, …}` — note `error`, NOT `tool_response`).
**Writes:** stdout (single-line JSON `hookSpecificOutput.{hookEventName, additionalContext}`) on fire only; one `decision="feedback"` line to `hook_firing.jsonl`.
**Called by:** CC hook system (`type: command` in `~/.claude/settings.json` PostToolUseFailure/Bash entry). Never imported.
**Calls out:** `_fire_log.log_fire`; stdlib (`json`, `os`, `sys`).

**Fires when ALL hold** (three gates, each fail-closed):
1. `tool_name == "Bash"` — the matcher already scopes it; the check makes a mis-registration harmless rather than noisy.
2. `error` is a non-empty string — the *shape* signal that a failure happened. Deliberately keyed on shape rather than on `hook_event_name`, which is the part most likely to be renamed by a future CC version; a success payload has no `error` at all, so a hook wrongly registered on `PostToolUse` stays silent.
3. `is_interrupt` falsy — a user ESC also produces a failure payload, and instructing the model to diagnose and retry something the USER stopped is exactly wrong.

**Silent (no output, exit 0):** success payloads, user interrupts, non-Bash tools, whitespace-only or absent `error`, malformed/empty stdin, non-dict JSON.

**Smoke:** `dev/hook_smoke/test_feedback_bash_error.py` (10 cases on the real captured payloads: 1 fire incl. message text + fire-log shape, 6 silent gates, 3 fail-open stdin cases).

---

### hook_setup.py (260 LOC)

**Purpose:** Idempotent installer with three defense layers. **Layer 1 — Worktree Guard:** `_guard_not_worktree()` checks `Path(__file__).resolve().parts` for consecutive `.claude`/`worktrees` components; exits 2 with a clear error message (stderr) if running from a worktree — preventing dead-path registration. **Layer 2 — Stale-hook Sweep:** `_sweep_stale_hooks()` iterates ALL event keys in `settings["hooks"]` (not only `PreToolUse`), checks every `python3 <path>` entry, and removes any whose script path fails `os.path.exists()`; drops now-empty groups, saves atomically, then runs the normal add-loop. **Layer 3 — Two-Condition Install Gate:** `decide_entries()` (pure, injectable `git_query_fn` + `tree_query_fn`) partitions `_HOOK_SCRIPTS` into installable vs. skipped BEFORE the add-loop runs. A script installs only when BOTH: (a) `_script_on_main()` confirms it's committed on `main` (`git cat-file -e main:src/hooks/<script>`, cached `_main_branch_resolves()` check first); (b) `_script_in_worktree()` confirms `os.path.exists(_HOOKS_DIR / script)` — present in the CURRENT working tree, at the exact path about to be registered. Condition (a) prevents the incident this layer was built for: a hook merged into `integration`, auto-registered via `.githooks/post-merge` using its absolute working-tree path, then orphaned machine-wide the moment the tree checked out `main` — every Bash call on every project failed with `[Errno 2] No such file or directory` until the entry was removed by hand. Condition (b) closes the mirror-image hole found in review: (a) alone lets a script that IS on `main` but was deleted/renamed in the CURRENT tree (while its `_HOOK_SCRIPTS` entry stayed) pass the gate and get registered as a dead path — same outage, entering from the other side; note `_sweep_stale_hooks()` runs BEFORE this gate, so without condition (b) the sweep would remove that exact dead entry and the install loop would immediately put it back. Main-branch presence is checked first — a script failing it never reaches the tree check, so a script missing from both reports the main-branch reason. Decision is per-script (cached by filename, shared across a script's multiple matcher entries) — one unmergeable/deleted script never blocks the other 38. `_report_skipped()` prints one deduped stderr line per skipped script naming it and the reason. Re-running heals stale entries from any source (worktree accident, repo move, feature-branch script since merged, etc.). Runs completely silent on success — no stdout output; stderr only for error conditions (worktree guard, JSON parse failure, skipped-script lines).
**Reads:** `~/.claude/settings.json`; local `main` branch git state (`git rev-parse --verify`, `git cat-file -e`); working-tree filesystem (`os.path.exists`).
**Writes:** `~/.claude/settings.json` (atomic via temp + `os.replace()`; up to two saves per run — one after sweep if stale entries found, one after add-loop if new entries installed).
**Called by:** User manually (`python3 src/hooks/hook_setup.py` from Monitor_CC root). Never imported.
**Calls out:** stdlib only (`functools`, `json`, `os`, `pathlib`, `subprocess`, `sys`); `git` CLI (subprocess, not a package import).

**Fail-safe direction (git query unanswerable):** `_script_on_main()` returns `None` when `main` doesn't resolve, `git` is missing, or the subprocess errors/times out (5s timeout on both calls). `decide_entries()` treats `None` identically to a confirmed-absent `False` — SKIP, never install. Rationale: the incident this layer prevents is a machine-wide Bash outage from a dead absolute path; losing one hook's enforcement until the query can succeed again is categorically cheaper than risking that outage on an unverifiable script. Note: this `None` path is exercised only via stub in the smoke suite — not reproduced against a live git repo lacking a `main` ref.

**Event dimension (2026-08-29).** `_HOOK_SCRIPTS` entries are `(script, matcher)` — registering under `PreToolUse`, the `_DEFAULT_EVENT` — or `(script, matcher, event)` for any other hook event; `_unpack_entry()` normalises both shapes. The add-loop keys `hooks.setdefault(event, [])` and checks `_already_installed` within that event's list, so the same script may be registered under different events without collision. `decide_entries()` passes entries through in the SHAPE they arrived (a 2-tuple stays a 2-tuple), keeping the install gate agnostic of an event dimension it does not judge — which is also why its smoke suite needed no change. `_sweep_stale_hooks()` already iterated every event key, so dead PostToolUseFailure paths were swept correctly before this change existed.

**Usage:** `python3 src/hooks/hook_setup.py` — run once after clone or reinstall. Re-run any time to heal stale hook entries. Hooks are active immediately (no CC restart needed).

**Note:** Must be run from the MAIN REPO root, not a worktree. The guard enforces this — attempting to run from a worktree exits with exit code 2 and a stderr message before touching settings.json.

**Smoke:** `dev/hook_smoke/test_hook_setup_main_branch_gate.py` (10 cases, stub `git_query_fn` + `tree_query_fn`: all-present install, absent-from-main skip, git-query-fails skip, mixed set, multi-matcher script skips every entry, absent-from-tree-only skip, present-in-both install, absent-from-both reports the main-branch reason, skip-reason text distinguishes the two conditions).

---

## Gotchas

- **Hooks are the single source of truth for mechanical command rules — do NOT also state the rule in a skill or rule file.** A skill/rule loads its full text into every session (context cost + a maintenance surface that drifts) and carries that text whether or not it is relevant; a hook fires surgically only on the actual violation and costs nothing idle. Failure-case rules can therefore be added freely as hooks without bloating any always-loaded surface. When a rule can be a hook, make it a hook and keep skills/rules lean — never duplicate a hook-enforced rule as prose.
- **Auto-deploy via `.githooks/` (per-clone setup required).** The repo ships `.githooks/post-merge` and `.githooks/post-commit` — both fire `python3 src/hooks/hook_setup.py` automatically when a commit (merge or direct) touches `src/hooks/*`. This keeps `~/.claude/settings.json` in sync with the filesystem, preventing the stale-hook disaster class. Each clone must activate the hooks once:
  ```bash
  git config core.hooksPath .githooks
  ```
  This is a local config (not committed). Workers committing from worktrees are unaffected — `hook_setup.py`'s worktree guard (`_guard_not_worktree()`) exits 2, which the hook script swallows silently; settings.json is only updated when the hook fires from the main repo context (merge onto main, direct commit on main). Verification: after a commit touching `src/hooks/`, confirm `settings.json` under `~/.claude/` (user-level file, not in repo) has mtime fresher than the commit timestamp.

- **`log_fire` decision enum and API-impact semantics.** Three values are defined — only `"block"` and `"rewrite"` are live today; `"ui-notice"` is reserved for future hooks with no API impact:

  | decision | Mechanism | API impact | Record field |
  |---|---|---|---|
  | `"block"` | exit 2 + stderr | Agent sees error, may retry | `reason` (stderr text) |
  | `"rewrite"` | exit 0 + updatedInput JSON | Agent runs modified input silently | `rewritten` (change description) |
  | `"ui-notice"` | exit 0, UI-only side-effect | **None** — agent sees nothing | neither |

  Filter `"ui-notice"` from FP analysis: `jq 'select(.decision != "ui-notice")' src/logs/hook_firing.jsonl`.

- **Fail-open is mandatory.** All hooks exit 0 on any parse error or missing field — a hook must never block a legitimate tool call due to its own failure. A broken hook that blocks everything is a footgun.
- **Global registration.** Bash hooks fire for every Bash call; Edit hooks for every Edit call; Read hooks for every Read call — across all CC sessions on this machine (main sessions and workers). Keep hooks fast and narrowly scoped. Current timeout: 5s (set in `hook_setup.py`).
- **Absolute path in settings.json.** `hook_setup.py` writes the full resolved path of each hook script at install time. If the repo is moved, re-run `hook_setup.py` to update the paths. The sweep pass removes the old stale paths automatically on re-run.
- **Stale hooks block all Bash calls.** A stale `python3 <missing>.py` hook exits 2 (Python interpreter error for missing file), which CC treats as a block — every Bash command in every session fails globally. Recovery: re-run `hook_setup.py` from the main repo root (from a real terminal, not CC's Bash tool, since Bash is blocked). The sweep removes dead entries before the add-loop runs.
- **A feature-branch-only script must never reach settings.json in the first place.** Confirmed incident: a hook merged into `integration` was auto-registered by `.githooks/post-merge` using its absolute working-tree path; the tree later checked out `main` (script absent there) → the registered path went dead → every Bash call on every project, every session, failed globally until removed by hand. The sweep (previous bullet) only heals this AFTER `hook_setup.py` runs again — during the outage window Bash itself is dead, so nothing triggers a sweep. `hook_setup.py`'s Layer 3 (main-branch presence gate, see module entry above) closes this at registration time instead: a script not verifiably committed on `main` is never added.
- **A shared shell-region stripper (`_shell_strip.py`) is used across most Bash-scanning hooks.** Before regex matching, `_strip_non_shell_active()` replaces heredoc bodies, single/double-quoted strings, and ANSI-C `$'...'` quotes with spaces of the same length (position-preserving). Command substitutions `$(...)` and backtick expressions are kept shell-active. Hooks using this: `block_broad_find.py`, `block_broad_grep.py`, `block_busywait_loop.py`, `block_dangerous_kill.py`, `block_gh_cli_chained.py`, `block_gh_cli_local_path.py`, `block_manual_worker_cleanup.py`, `block_pipe_scraper_isolated.py`, `block_po_read.py`, `block_rag_cli_chained.py`, `block_rag_docs_layer.py`, `block_search_subreddits_limit.py`, `block_venv_no_redirect.py`, `block_worker_kill_while_working.py`, `block_worker_send_background.py`, `block_worker_spawn_placement.py`, `rewrite_chained_sleep.py`, `rewrite_gh_cli_read_noise.py`, `rewrite_rag_cli_search_noise.py`, `rewrite_websearch_scrape_noise.py`, `rewrite_worker_cli_capture_noise.py`, `rewrite_worker_cli_response_noise.py`. Fail-open: any parse error returns the original string unchanged — a malformed command is never incorrectly allowed by the stripper.
- **Cache-bust on settings.json edit.** Editing `~/.claude/settings.json` busts CC's prompt cache — full message rebuild on the next request. Hooks are active immediately after settings.json is written; no CC restart needed.
- **PreToolUse exit codes.** Exit 0 = allow, exit 2 = block (CC shows stderr to user as the block reason), exit 1 = hook error (CC logs but does not block). This hook uses exit 2 on block, exit 0 on allow and on hook-internal errors.
- **A failed tool call does NOT reach `PostToolUse` — the event is `PostToolUseFailure` (measured 2026-08-29).** With a stdin-dumping probe on `PostToolUse`/Bash: 4 payloads for 4 successful calls, **zero** for 3 failing ones (`cat <missing>`, `false`, `exit 3`). The failure lands on the sibling event `PostToolUseFailure`, whose payload carries `error` (`"Exit code N\n<output>"`) and `is_interrupt`, and NO `tool_response` at all. `ToolUseFailure`, `PostToolUseError` and `ToolError` are not real event names — probes registered under them never fired. Consequence for any future post-hoc hook: "only react to errors" needs no condition, it is what registering on this event already means. Also measured: on a success, `tool_response.stderr` was empty and stderr text arrived inside `stdout`, so `tool_response.stderr` is not a usable error signal either.
- **Feedback surfaces to the model through three channels; plain stdout is swallowed.** Measured on `PostToolUseFailure` (2026-08-29): exit 2 + stderr renders as `…hook blocking error from command: "<path>": [<path>]: <MSG>`; stdout `{"decision":"block","reason":MSG}` renders as `…hook blocking error from command: "<path>": <MSG>`; stdout `hookSpecificOutput.additionalContext` renders as `PostToolUseFailure:Bash hook additional context: <MSG>`; plain stdout produces nothing at all. All three arrive as a `<system-reminder>` after the error result. `additionalContext` is the one to use for post-hoc feedback — the other two frame a non-block as a "blocking error" and echo the hook's absolute path into context. Note `strip_hook_prefix.py` (proxy) strips the `PreToolUse:<Tool> hook error: [python3 <path>]:` prefix and does not cover these newer shapes.
- **Subprocess hooks must resolve plugin CLIs by absolute path.** CC's hook execution environment has a stripped PATH that does NOT include `~/.local/bin` or the plugin-cache `bin/` directories. A subprocess-hook invoking a plugin CLI by bare name (e.g. `subprocess.run(['worker-cli', ...])`) receives `FileNotFoundError` → catches it → returns the fail-open default → hook silently never fires. This was a confirmed live bug in `block_worker_kill_while_working`: the kill-guard let working-worker kills through until `_resolve_worker_cli()` was added (`shutil.which` + glob `~/.claude/plugins/cache/.../bin/worker-cli`). **Pattern for any future subprocess-hook:** resolve the binary via `shutil.which` first, then a hardcoded plugin-cache glob fallback; return `None` if unresolvable and fail-open. Never rely on bare PATH.
- **All active hooks log fires via `_fire_log.log_fire()`.** Called at the decision-point only — NOT at hook start and NOT on passthroughs. The shared log `src/logs/hook_firing.jsonl` is append-forever; fail-silent on write errors so logging never breaks hook behavior. New hooks must add a `log_fire()` call at their decision-point as part of the implementation. Use `MONITOR_CC_HOOK_FIRING_LOG` env var in smoke tests to redirect to a temp file and avoid polluting the real log.
