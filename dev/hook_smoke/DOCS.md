# dev/hook_smoke/

## Role

Smoke-test suite for `src/hooks/` — one test script per hook, verifying positive (blocks/rewrites)
and negative (pass-through) cases via subprocess. Each script invokes the hook with a JSON payload
on stdin and checks exit code + stdout/stderr.

Touch this suite when: adding a new hook (add matching test script); changing hook logic (extend
or fix existing test script); verifying after merges that no hook regressed.

## Modules

### test_block_chained_sleep.py (67 LOC)

**Purpose:** 13-case smoke for the now-disabled `block_chained_sleep.py`. Preserved for regression
reference — the file still exists as `block_chained_sleep.py.disabled`.

**Usage:**
```bash
# From project root — references src/hooks/block_chained_sleep.py (disabled, skip if not restored)
python3 dev/hook_smoke/test_block_chained_sleep.py
```

---

### test_block_broad_grep.py (84 LOC)

**Purpose:** 16-case smoke for `block_broad_grep.py`. Verifies 5 blocked cases (broad recursive, piped to non-head), 5 head-bounded exemptions (piped to `head`/`head -N`, with redirect before head, further pipe after head), and 6 existing-exemption passes (--include, file-targeted, non-recursive, git grep, quoted, heredoc).

**Usage:**
```bash
python3 dev/hook_smoke/test_block_broad_grep.py
```

---

### test_block_gh_cli_chained.py (101 LOC)

**Purpose:** 21-case smoke for `block_gh_cli_chained.py`. Verifies 9 blocked cases (each of the 7 search/research tools piped/chained with a non-search command), 6 pass cases (two search tools chained together, standalone with tool-native args, redirect to file), 2 exempt issue-command passes (`list_issues` / `get_issue` piped to grep/head), 2 shell-strip passes (pattern inside single-quotes, pattern inside heredoc body), and 3 `repo_freshness`-as-legal-segment cases (2026-08, CC 2.1.223 websearch incident): `repo_freshness && index_issues && index_issues` PASS (the fixed retry), the same chain with `echo` segments interleaved still BLOCK (echo isn't a legal segment), `repo_freshness && git log` PASS (hook never triggers — `repo_freshness` alone is outside `_GH_SEARCH_RE`'s scope).

**Usage:**
```bash
python3 dev/hook_smoke/test_block_gh_cli_chained.py
```

---

### test_block_gh_cli_local_path.py (83 LOC)

**Purpose:** 15-case smoke for `block_gh_cli_local_path.py` (2026-08-07). Verifies 5 blocked cases
(`get_file_content` with `/Users/...` or `~/...` path, `download_files` with an absolute
positional or a `~/...` path among several, local path preceded by a `--limit` flag), 4 pass cases
(repo-relative path, **the `--dest` false-positive trap in both flag positions** — before and
after the repo-path positionals, `--metadata-only` flag present), 4 untouched-command cases
(`get_repo_tree`/`index_issues`/`repo_freshness`/non-gh-cli), and 2 shell-strip passes (pattern
inside single-quotes, pattern inside heredoc body).

**Usage:**
```bash
python3 dev/hook_smoke/test_block_gh_cli_local_path.py
```

**Report:** `md/block_gh_cli_local_path_smoke_report.md`.

---

### probe_gh_cli_repo_freshness_incident.py (121 LOC)

**Purpose:** Replays the exact commands from the websearch-session `repo_freshness` incident
(`src/logs/dual_log/api_requests_opus_websearch_1786052022_original.jsonl`, messages [118]-[129])
through the real `block_gh_cli_chained.py` hook via subprocess — asserts exit code AND stderr
shape (BLOCK cases carry stderr, PASS cases carry none), plus 3 content checks on the rewritten
`_BLOCK_MESSAGE` (combine example present, "always full context" wording, "repo_freshness may
join" wording). Distinct from the smoke suite above: pins the literal incident commands
verbatim rather than minimal synthetic variants, and asserts message CONTENT, not just exit code.
**Reads:** none (commands are inlined verbatim from the incident log, not re-read from disk).
**Writes:** `md/gh_cli_repo_freshness_incident_probe_report.md`.

**Usage (from project root):**
```bash
python3 dev/hook_smoke/probe_gh_cli_repo_freshness_incident.py
```

**Expected output:** `ALL PASS` (exit 0).

---

### test_block_rag_cli_chained.py (79 LOC)

**Purpose:** 11-case smoke for `block_rag_cli_chained.py`. Verifies 4 blocked cases (rag-cli followed via `;`, `&&`, `|` by tail/echo/grep/head), and 7 allow cases (redirect to file, file-guard before rag-cli, cd before rag-cli, two rag-cli calls chained, no rag-cli at all, rag-cli inside single-quotes, rag-cli inside heredoc body).

**Usage:**
```bash
python3 dev/hook_smoke/test_block_rag_cli_chained.py
```

---

### test_block_rag_cli_index_isolated.py (146 LOC)

**Purpose:** 37-case smoke for `block_rag_cli_index_isolated.py`. Verifies 20 blocked cases (the observed poll-then-index incident: `tail` + `echo` + `cd` + index across newlines; noise before/after index via `&&`/`;`; a second `rag-cli delete` command alongside index; index piped to `tee`; the 2026-08-01 holes — env-prefixed index preceded by `tail`, env-prefixed index followed by `echo`, multi-assignment-prefixed index piped to `tee`, standalone assignment line + `tail` + `cd` + env-prefixed index; the 2026-08-02 holes — command/backtick substitution in an assignment value, substitution in the `--collection` argument, process substitution on a redirect target and as input, arithmetic expansion in an assignment, substitution nested inside a double-quoted `cd` target, backtick in a redirect filename, bare `&` smuggling with and without surrounding whitespace) and 17 allow cases (bare index, index with redirect, cd-before-index with/without redirect, env-prefixed bare index, the real HOLE-2 command verbatim — assignment line + cd + env-prefixed index + backslash line-continuation before the redirect, assignment line + cd + bare index + redirect, bare index with a backslash-continued redirect, quoted semicolon in an assignment value, plain `$VAR` expansion in a `cd` target, `&>` redirect not mistaken for the bare-`&` separator, three out-of-scope rag-cli subcommands (`search_hybrid`/`list_documents`/`delete`), no rag-cli at all, index inside single-quotes, index inside heredoc body).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_block_rag_cli_index_isolated.py
```

**Expected output:** `All 37 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_block_dangerous_kill.py (90 LOC)

**Purpose:** 18-case smoke for `block_dangerous_kill.py` — pkill -f patterns, pipe-kill chains, heredoc/quote exemptions, and allowlist cases.

**Usage:**
```bash
python3 dev/hook_smoke/test_block_dangerous_kill.py
```

---

### test_block_git_destructive.py (107 LOC)

**Purpose:** 21-case smoke for `block_git_destructive.py`. Verifies 2 FP-regression ALLOW cases (minimal: `git push -u origin main\n[ -f .env ]`; actual recap command with push + echo + `[ -f .rag-docs.json ]` across lines), 13 BLOCK cases (force-push `--force`/`--force-with-lease`/`-f`, push with `-C` flag, `--amend`/`--amend --no-edit`, `--no-verify` on commit and push, `--allow-empty`, `git config` write and write-with-`-C`), and 6 ALLOW cases (plain push, `push -u`, normal commit, `config --list`/`--get`/`--show-origin`, force-push phrase inside quoted message).

**Usage (from project root):**
```bash
./venv/bin/python dev/hook_smoke/test_block_git_destructive.py
```

**Expected output:** `All 21 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_block_read_worktree.py (74 LOC)

**Purpose:** Smoke test for `block_read_worktree.py` — foreign worktree reads blocked, own-worktree
reads allowed.

**Usage:**
```bash
python3 dev/hook_smoke/test_block_read_worktree.py
```

---

### test_log_janitor.py (75 LOC)

**Purpose:** 4-case smoke for `src/log_janitor.cleanup_old_jsonl`. Verifies: old record >7 days dropped,
recent record <7 days kept, empty `ts` kept (fail-safe), naive-ts without TZ kept (TypeError on
aware/naive comparison → fail-safe keep).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_log_janitor.py
```

**Expected output:** `All 4 tests passed.` (exit 0). Uses `sys.path.insert` on `src/` + `from log_janitor import` to avoid the `from src.` import restriction.

---

### test_rewrite_rag_cli_search_noise.py (139 LOC)

**Purpose:** 15-case smoke for `rewrite_rag_cli_search_noise.py`. Verifies 9 positive-strip cases (`| head`, `| tail`, `| grep`, `> redirect`, `2>&1`, `2>&1 | head`, `cd &&` chain, trailing `; bd list` chain, `|| echo fail` chain) and 6 negative no-op cases (bare search_hybrid, cd chain no noise, trailing chain no pipe, `list_collections | head` out of scope, `read_document | head` out of scope, search_hybrid inside quoted echo).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_rewrite_rag_cli_search_noise.py
```

**Expected output:** `All 15 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_rewrite_worker_cli_capture_noise.py (152 LOC)

**Purpose:** 17-case smoke for `rewrite_worker_cli_capture_noise.py`. Verifies 5 positive-strip cases (`| tail -40`, `| grep bar`, `| head -20 | sed`, `cd && ... | tail ; echo done` chain, `| wc -l`), 1 `--raw`-survives case (`--raw | tail -40` → `--raw` preserved), 3 redirect-preserved no-op cases (`> /tmp/x.txt`, `>> /tmp/x.txt`, `2>&1` all UNCHANGED), and 8 negative no-op cases (bare capture, `--raw` no-pipe, `response | tail` out-of-scope, wrong subcommands, chains without noise, quoted capture inside send-message).

**Critical assertions:** `> /tmp/x.txt` UNCHANGED (redirect preserved), `--raw | tail -40` → `--raw` (flag survives), `worker-cli send w "... capture foo | tail"` UNCHANGED (shell-strip blanks quoted region).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_rewrite_worker_cli_capture_noise.py
```

**Expected output:** `All 17 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_rewrite_gh_cli_read_noise.py (127 LOC)

**Purpose:** 12-case smoke for `rewrite_gh_cli_read_noise.py`. Verifies 5 positive-strip cases (`get_issue | tail -40`, `2>&1 | tail -40` with `2>&1` preserved, `list_issues | head`, `| tail ; echo done` chain, `cd && get_issue | tail` chain prefix), 2 redirect-preserved no-op cases (`> /tmp/x`, `>> /tmp/x` both UNCHANGED), 2 out-of-scope-command no-op cases (`create_issue | tail`, `update_issue | tail` — writes, not covered), 2 bare no-op cases (`get_issue`/`list_issues` with no pipe), and 1 quoted-string no-op case (`worker-cli send w "... gh-cli get_issue x | tail"` UNCHANGED).

**Critical assertions:** `> /tmp/x` UNCHANGED (redirect preserved), `create_issue`/`update_issue` UNCHANGED (anchor excludes writes), quoted send-message UNCHANGED (shell-strip blanks quoted region).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_rewrite_gh_cli_read_noise.py
```

**Expected output:** `All 12 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_rewrite_worker_cli_response_noise.py (144 LOC)

**Purpose:** 16-case smoke for `rewrite_worker_cli_response_noise.py`. Verifies 9 positive-strip cases (`| head`, `| tail`, `| grep`, `> redirect`, `2>&1`, `2>&1 | head`, `cd &&` chain, trailing `; bd list` chain, `|| echo fail` chain) and 7 negative no-op cases (bare response, **`worker-cli capture X | tail -40` critical pass-through**, `worker-cli status`, `worker-cli list`, cd chain no noise, trailing chain no pipe, response inside quoted echo).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_rewrite_worker_cli_response_noise.py
```

**Expected output:** `All 16 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_rewrite_websearch_scrape_noise.py (139 LOC)

**Purpose:** 15-case smoke for `rewrite_websearch_scrape_noise.py`. Verifies 9 positive-strip cases (`| head`, `| tail`, `| sed`, `2>&1`, `2>&1 | head`, `> redirect`, `cd &&` chain, trailing `; echo done` chain, `|| echo fail` chain) and 6 negative no-op cases (bare `scrape_url`, cd chain no noise, trailing chain no pipe, `search_web | head` out of scope, `search_engine_drilldown | head` out of scope, `scrape_url` inside quoted echo).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_rewrite_websearch_scrape_noise.py
```

**Expected output:** `All 15 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_rewrite_background_sleep.py (138 LOC)

**Purpose:** 11-case smoke for `rewrite_background_sleep.py`. Verifies 5 positive-rewrite cases
(`sleep 300`, `sleep 5`, `sleep 1200` with `run_in_background=true`; bare `sleep 300` alone;
`sleep 45 && echo "bg-ack-probe done"` custom echo; `sleep 3300 && echo "custom text"` N=3300 non-canonical
→ all rewritten to `sleep 3300 && echo done`) and 6 negative no-op cases (foreground flag; exact target
`sleep 3300 && echo done`; non-canonical non-sleep command; wrong chain target `&& rag-cli`).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_rewrite_background_sleep.py
```

**Expected output:** `All 8 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_block_unauthorized_background.py (84 LOC)

**Purpose:** 9-case smoke for `block_unauthorized_background.py`. Verifies 4 ALLOW cases (no foreground-force): original `sleep N && echo done`, bare `sleep N`, custom echo `sleep 45 && echo "bg-ack-probe done"` (fire-log actual), normalized `sleep 3300 && echo done`. Verifies 4 FORCE cases (foreground-forced): `reddit-cli index_subreddits`, `workflow.py index-dir` (former whitelisted, now forced), `./venv/bin/python script.py`, `rag-cli update_docs .` (original triggering incident). Verifies 1 PASS case (already foreground → no output): `./venv/bin/python script.py` with `run_in_background=false`.

**Usage (from project root):**
```bash
./venv/bin/python dev/hook_smoke/test_block_unauthorized_background.py
```

**Expected output:** `All 9 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_rewrite_chained_sleep.py (226 LOC)

**Purpose:** 8-case smoke for `rewrite_chained_sleep.py`. Verifies 3 positive-strip cases (`echo`
and `true` cmd_before → sleep stripped) and 5 negative no-op cases (load-bearing: `kill`, `launchctl`;
loop body; sleep-first; canonical timer).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_rewrite_chained_sleep.py
```

**Expected output:** `All 8 tests passed.` (exit 0). HOOK path in the script is relative
(`src/hooks/rewrite_chained_sleep.py`) — must be run from project root.

---

### test_version_purge.sh (140 LOC)

**Purpose:** 8-assertion smoke for the version-aware dual-log purge (`_janitor_version_purge_jsonl_logs` + `_compute_proxy_hash` in `src/claude_proxy_start.sh`). Runs in a temp dir; never touches real `src/logs/`. Four cases: (a) version change purges stale (>60min) logs; (b) same version leaves stale files untouched; (c) fresh (<60min) logs survive a version-change purge; (d) absent marker triggers first-run cleanup and creates the marker. Mirrors the production functions inline — keep in sync with `src/claude_proxy_start.sh` when editing either.

**Usage (from project root):**
```bash
bash dev/hook_smoke/test_version_purge.sh
```

**Expected output:** `All 8 assertions passed.` (exit 0).

---

### test_header_capture.py (179 LOC)

**Purpose:** 13-case smoke for the proxy header-capture additions in `src/proxy/addon.py`. Tests two
independent surfaces: (1) beta-flags extraction logic (split/strip/drop-empty on `anthropic-beta`
header value); (2) `_filter_response_headers()` — exact-name and prefix-based filter with lowercase
normalization. Does NOT require a live mitmproxy process — uses minimal mock headers objects.

**Usage (from project root):**
```bash
./venv/bin/python dev/hook_smoke/test_header_capture.py
```

**Expected output:** `13/13 passed` (exit 0). Imports `_filter_response_headers` directly from
`src/proxy/addon` via `sys.path.insert` on `src/`.

---

### test_bg_task_detection.py (145 LOC)

**Purpose:** 6-case smoke for `src/menubar/proc_cache.py::_has_active_bg` (open-file-handle predicate, replacing the old 0-byte-file check). 3 unit cases via a monkeypatched `_bg_task_open_paths` snapshot (match, no-match, session-id prefix-collision boundary), 1 integration case (real subprocess holds a real file open under a scratch tasks dir, real `lsof` scan detects it while open and its absence after the writer is killed), 1 fail-open case (`lsof` raising leaves the prior snapshot in place, does not crash), 1 TTL-gate case (second refresh call inside `_PROC_REFRESH_INTERVAL` does not re-invoke `lsof`).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_bg_task_detection.py
```

**Expected output:** `All 6 tests passed.` (exit 0). Creates/removes a scratch dir under the real `_TASKS_BASE` (`/tmp/claude-<uid>/__test_bg_probe__/`) for the integration case only; cleaned up in a `finally` block.

---

### probe_bg_task_live.py (n/a — live measurement tool, not a smoke test)

**Purpose:** Live probe comparing the old 0-byte predicate against the new handle-based predicate against a REAL running background task (e.g. a `rag-cli index` run), a synthetic writer loop, and a no-background-task control session; also benchmarks the per-tick cost of the batched `lsof` cache (refresh-tick cost vs. N-session cache-hit-tick cost). `--snapshot` mode prints one JSON measurement and exits. `probe_bg_task_detection_workflow` (no `--snapshot`) runs the full poll-loop + synthetic-writer + cost-bench + report-write in one process. Not CI-safe (depends on a live external task being supplied) — kept for future re-verification if the predicate regresses. **Gotcha:** any Bash-tool-invoked check running INSIDE the same CC session it targets can itself become a transient open `*.output` handle in that session's tasks dir for the duration of the check (CC's own tracked-wrapper mechanism, not specific to this script) — a long-lived process built this way (the original `probe_bg_task_detection_workflow` loop, run via `run_in_background=true` against its own session) got stuck for 14 minutes waiting for `new=False`, which could never arrive while it was itself the open handle. Mitigations used: (1) drive repeated measurements via `--snapshot` from an external shell `until`-loop (each invocation is independent and short) rather than one long-lived Python loop; (2) for a "handle is now closed" claim, scope `lsof` to the SPECIFIC target file (`lsof <path>`), not the whole session directory, to avoid the self-entry noise entirely.

**Usage (from project root):**
```bash
# repeated snapshots, driven by an external loop (safe even when target == own session)
until [ -s <tasks_dir>/<task_id>.output ]; do sleep 5; done
python3 dev/hook_smoke/probe_bg_task_live.py --encoded-dir=<encoded_dir> --session-id=<session_id> --task-id=<task_id> --snapshot

# full workflow — only when the target session is NOT the one this script runs in
python3 dev/hook_smoke/probe_bg_task_live.py --encoded-dir=<encoded_dir> --session-id=<session_id> --task-id=<task_id> --poll-secs 4 --max-polls 100
```

---




### test_block_po_read.py (94 LOC)

**Purpose:** 16-case smoke for `block_po_read.py`. Verifies 9 blocked cases (`head`/`tail`/`grep`/`cat`/`sed`/`rg` each on a `~/.claude/.../tool-results/<id>.txt` persisted-output path, the piped `cat <path> | head -20` case, and the `split -l 400 <path> /tmp/x` / `dd if=<path> of=/tmp/x` partitioning-escape cases) and 7 no-op cases (reader on a normal file, reader on a `.log` file, reader on `/tmp/foo.txt` not under `.claude/`, reader on a `.claude/` path not ending `.txt`, redirect-write to a PO path, PO path only inside a quoted string, malformed-JSON stdin fail-open).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_block_po_read.py
```

**Expected output:** `All 14 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_block_linkedin_cli_isolated.py (114 LOC)

**Purpose:** 25-case smoke for `block_linkedin_cli_isolated.py`. Verifies 11 blocked cases (piped to grep/head/tail/sed/awk/wc, two `linkedin` calls chained via `&&`/`;`, chained with an unrelated command both after and BEFORE the `linkedin` call, env-prefixed call then piped) and 13 pass cases (standalone with `--count`/`--days`, redirect-to-file, env-prefixed standalone, bare `linkedin` with no subcommand — a pinned decision, not accidental — non-`linkedin` command untouched, and 5 false-positive-avoidance cases: "linkedin" as a `cd` path segment, as a `cli/linkedin/cli.py` path, as a `grep` argument, as a different tool's name prefix (`linkedin-web`), and as text inside quotes), plus 1 malformed-stdin fail-open case.

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_block_linkedin_cli_isolated.py
```

**Expected output:** `All 25 tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_block_rag_cli_document_repeat.py (193 LOC)

**Purpose:** 7-case smoke for `block_rag_cli_document_repeat.py`. Verifies: a single `--document` call passes (exit 0); a 2nd `--document` call to the same collection+subcommand within the window blocks (exit 0 then exit 2); collection-wide calls (no `--document`) always pass, 3x in a row; a different session's `--document` call does not count toward another session's counter (session A #1 = 0, session B #1 = 0, session A #2 = 2); `rag-cli delete --document` is covered by the same threshold as `index`; malformed stdin fails open (exit 0). Each case uses `MONITOR_CC_RAG_DOC_REPEAT_STATE` set to a fresh `tempfile` per case — no shared/leftover state across cases.

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_block_rag_cli_document_repeat.py
```

**Expected output:** `All rag-cli document-repeat tests passed.` (exit 0). HOOK path is relative — must be run from project root.

---

### test_block_timer_no_worker_working.py (104 LOC)

**Purpose:** 10-case smoke for `block_timer_no_worker_working.py`. Calls `decide()` directly with a stub `status_fn` (raw `worker-cli status --all` stdout text, or `raises` sentinel — no real workers). Verifies 3 BLOCK cases (empty worker set / `(no active workers)`; all-idle including `'idle 59%'` suffix form; bare `sleep N` background with no worker working) and 7 ALLOW cases (one `working` among idle; single `unknown`; `unknown` mixed with idle; `limit reached`; foreground call; non-sleep background command; `status_fn` raises — fail-open). Does NOT cover the `tmux`-unresolvable broken-probe guard in `_live_worker_statuses` — that check sits below the `status_fn` injection boundary; verified instead by a live PATH-stripped subprocess drive (see `process-docs/tool_use_safety/`).

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_block_timer_no_worker_working.py
```

**Expected output:** `10/10 passed` (exit 0).

---

### test_block_timer_pending_bg.py (283 LOC, 2026-08-06 milestone-3; project-scoping cases added 2026-08-07)

**Purpose:** 36-check, 4-layer smoke for `block_timer_pending_bg.py`. **Layer 1 (18 cases):** `decide()` called directly with a stub `state_fn` returning a crafted `pending_bg_tasks.json`-shaped dict — fresh pending → block; cleared-only (incl. the "no prior arm" orphan tombstone shape) → allow; stale (2h) pending → allow; the exact-3600s boundary → allow (strictly-younger-than semantics); 3599s (1s under) → block; `state_fn` raising / non-dict / non-timer command / `run_in_background=False` / unparseable `armed_at` → allow; multiple entries → only fresh-pending ones returned, sorted; **project scoping (6 cases, 2026-08-07):** foreign-project pending → allow (the incident class), same-project pending → block, legacy no-project entry → blocks regardless of `current_project` (backward compat), foreign/same-project pending but EXPIRED → allow either way (expiry checked independently), mixed own+foreign+legacy entries → only own+legacy returned. **Layer 2 (12 cases):** real stdin entry-point via `subprocess`, a genuine `pending_bg_tasks.json` seeded under a `MONITOR_CC_ROOT`-scoped `tempfile.TemporaryDirectory()`, `cwd` forced to a SEPARATE tempdir outside any `.claude/worktrees/` path — this worktree's own filesystem path contains that fragment, so a subprocess launched with the default cwd would always hit the hook's own worktree exemption and mask every block/allow case; asserts exit code, that the block message names the id and states an age (`"ago"`) and an idle instruction, and exit-0-no-stderr for every allow path (cleared, stale, missing file, corrupt file, non-timer command, foreground); **3 project-scoping cases via a REAL named cwd directory** (`Path(outer) / "Websearch"`, not a random tempdir basename) — foreign-project (posts) pending + cwd=Websearch → exit 0; same-project pending + cwd=Websearch (normalizes to `"websearch"`) → exit 2; legacy no-project entry → exit 2 regardless of cwd — exercises the REAL `_current_project_slug()` cwd-basename derivation end-to-end, not just the injected `current_project` string Layer 1 uses. **Layer 3 (1 case):** dedicated worktree-exemption check — `cwd` deliberately INSIDE a `.claude/worktrees/`-fragment path WITH a fresh-pending state file that would block if not exempted — asserts exit 0, proving the exemption itself fires (not just that it's never triggered by accident in Layer 2). **Layer 4 (4 cases):** static `hook_setup._HOOK_SCRIPTS` check — entry present exactly once, immediately after `block_timer_no_worker_working.py`, immediately before `rewrite_background_sleep.py`, registered under the `Bash` matcher — same verification method used to confirm the 2026-07-21 `block_concurrent_timer.py` removal, applied in reverse for an addition.

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_block_timer_pending_bg.py
```

**Expected output:** `36/36 passed` (exit 0).

---

### test_hook_setup_main_branch_gate.py (135 LOC)

**Purpose:** 10-case smoke for the two-condition install gate in `hook_setup.py` (`decide_entries()`). Stub `git_query_fn` (script → `True`/`False`/`None`, on-`main` presence) and stub `tree_query_fn` (script → bool, working-tree presence), both defaulting to present so cases only name the interesting scripts — no real git or filesystem calls. Verifies: all-present → all installed; one absent from `main` → skipped, rest installed; `git_query_fn` returns `None` (query unanswerable) → fail-safe skip; mixed present/absent/query-error set resolved independently; a multi-matcher script (e.g. `block_path_typo.py`-shaped) absent from `main` has EVERY entry skipped; **on `main` but missing from the working tree → skipped** (the mirror-image condition — a script can be genuinely committed on `main` yet absent from the CURRENT tree if a branch deleted/renamed it while its `_HOOK_SCRIPTS` entry stayed); on `main` AND in the tree → installed (mirror-image positive); missing from BOTH → skipped, reporting the main-branch reason (checked first); skip-reason text distinguishes "not committed on main" from "missing from the current working tree" so a maintainer knows which condition failed.

**Usage (from project root):**
```bash
python3 dev/hook_smoke/test_hook_setup_main_branch_gate.py
```

**Expected output:** `10/10 passed` (exit 0).
