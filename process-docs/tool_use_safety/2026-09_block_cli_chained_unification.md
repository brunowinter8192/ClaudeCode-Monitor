# block_cli_chained.py: unifying 7 per-CLI chained/isolated hooks into one rule set (2026-09)

**Topic:** `block_gh_cli_chained.py`, `block_rag_cli_chained.py`, `block_worker_cli_read_chained.py`,
`block_websearch_scrape_chained.py`, `block_duallog_chained.py`, `block_linkedin_cli_isolated.py`,
`block_penny_cli_chained.py`, and `block_bd_cli_worker.py` (bd retired) deleted; replaced by one
`src/hooks/block_cli_chained.py` driven by a `PROTECTED_SUBCOMMANDS` table in `_known_cli.py`.

## Motivation

The 7 hooks each carried the same idea (some CLI subcommands return bounded, context-destined
output that a pipe or file-redirect defeats) plus an extra, unintended rule: any "foreign" chain
segment — one that was neither a known CLI call, a `cd`/`test` guard, `echo`/`printf`, nor
for/while loop scaffolding — blocked outright, even when nothing about that segment touched the
protected CLI's output. Measured on `src/logs/hook_firing.jsonl` (main checkout) at the start of
this task: 115 blocks total across the 7 hooks since 2026-08-29 (31 `block_gh_cli_chained`, 66
`block_rag_cli_chained`, 13 `block_worker_cli_read_chained`, 0 `block_websearch_scrape_chained`, 2
`block_duallog_chained`, 1 `block_linkedin_cli_isolated`, 2 `block_penny_cli_chained`) — matching
the number given in the task prompt exactly, which grounded the rest of the design in that same
log rather than a fresh assumption.

## The actual rule, as stated in the task prompt

Chaining any CLI with `;`/`&&`/`||`/newline/background-`&` and ANY other command is always fine —
no allowlist of chain segments. Exactly 3 conditions block:
1. A pipe (`|`) after a CLI segment (any of 8 tools, any subcommand), into ANY command.
2. A redirect (`>`, `>>`, `2>&1`, `&>`, `<`) on a segment invoking a PROTECTED subcommand.
3. A same-Bash-call readback (`head`/`tail`/`cat`/`sed`/`awk`/`grep`/`less`/`more`/`wc`) of a file
   a CLI segment in that same call redirected into — protected or not.

## Design decisions

**Protected-set proposal for `reddit-cli` and `linkedin`** (task explicitly asked for this, no
existing hook had settled it): read `~/Documents/ai/Meta/ClaudeCode/cli/reddit-cli/cli.py` and its
`search_subreddits_workflow`/`index_subreddits_workflow` — `search_subreddits` returns a bounded
(`--limit`-capped, and `block_search_subreddits_limit.py`, untouched, already forbids capping it
further) subreddit list meant to land in context whole; `index_subreddits`/`deep` are long-running
fetch+index operations returning only a final summary, the same shape as `rag-cli index` (which
stays unprotected — redirect is how its progress log works). So only `search_subreddits` joined
the protected set. For `linkedin`, read `~/.local/bin/linkedin` → `jobscraper/cli.py`: all 5
subcommands (`get_company_info`, `get_company_posts`, `get_messages`, `get_thread`,
`get_notifications`) are bounded read/query calls (`--count`/`--days`/`--date`-capped) with no
write/index-type subcommand at all — every invocation protected, matching how the deleted
`block_linkedin_cli_isolated.py` already treated the whole CLI as one undifferentiated unit (no
subcommand split). `duallog` and `penny-cli` keep the "every invocation protected" shape their own
deleted hooks already established (no unprotected subset exists for either).

**Rule 1 (pipe) scoped to ANY of the 8 CLIs, not just protected subcommands.** The task's wording
distinguishes "a CLI segment" (rule 1, unqualified) from "a PROTECTED subcommand" (rule 2,
explicitly qualified) — read literally, piping ANY invocation of any of the 8 tools blocks,
protected or not. This also matches the OLD hooks' own behavior: `block_gh_cli_chained.py`'s
7 unprotected search/research tools were never redirect-policed but WERE already blocked when
piped (the pipe target became a "foreign" trailing segment under the old mechanism). Verified
against real historical commands: `gh-cli get_file_content ... | head -80` (unprotected subcommand,
piped) and `worker-cli kill name 2>&1 | tail -5` (unprotected subcommand, piped) both still block
under the new hook — consistent with this reading.

**Rule 2 deliberately excludes bare `2>`.** The task's protected-redirect list is exactly
`>`, `>>`, `2>&1`, `&>`, `<` — bare `2>` (stderr-only, e.g. `2>/dev/null` noise suppression) is
conspicuously absent from that list, and it never touches the actual bounded output (only
suppresses error text), so excluding it is not an oversight. Implemented via
`(?<![0-9])>(?!>)` — a lone `>` not immediately preceded by a digit and not immediately followed by
another `>` — which correctly lets `2>&1` still match via its own alternative while a bare
`2>/dev/null` matches nothing.

**Segment mechanics: chain-level split first, then per-chain-segment pipe-stage split.** Chain
separators (`&&`/`||`/`;`/newline/space-bounded `&`) deliberately exclude `|` — a chain segment
carrying a pipe is split a SECOND time, within itself, into pipe stages. Rule 1 checks every stage
except the last in each pipe run; rule 2 checks only the last stage (a CLI segment piped further is
already rule 1's territory, checked first); rule 3 does two full passes — collect every last-stage
CLI segment's own `>`/`>>`/`&>` redirect target, then scan every stage for a readback-tool first
token whose text contains one of those targets as a substring. Both splits are position-preserving
(spans computed against the shell-stripped copy, sliced from the original for block messages) so a
quoted argument like `"x"` in `rag-cli search "x" coll | head -40` shows up correctly in the
`Blocked segment:` line rather than as blanked whitespace.

**No allowlist predicates carried over.** The old `_known_cli.py`'s `is_guard_segment`/
`is_echo_segment`/`is_loop_scaffold_segment`/`is_allowed_chain_segment` existed solely to decide
whether a "foreign" segment was actually fine — the new rule has no such concept (chaining with
`;`/`&&` is unconditionally fine for anything), so all 4 were deleted rather than kept unreachable.
Confirmed via import grep that only the 7 deleted hooks (plus a comment-only mention in
`block_rag_corpus_read.py` and the deleted gh-cli smoke test) ever referenced them — no other hook
in `src/hooks/` imports from `_known_cli.py` besides `block_cli_chained.py` itself.

## Verification

New smoke suite `dev/hook_smoke/test_block_cli_chained.py`, 36 cases across all 3 rule classes for
all 8 CLIs, all passing. Re-ran the 5 untouched CLI-adjacent hook suites named in the task
(`block_rag_docs_layer` 11/11, `block_gh_cli_local_path` 15/15, `block_rag_cli_document_repeat` all
pass, `block_rag_corpus_read` 29/29, `block_rag_cli_index_isolated` 37/37) plus
`test_hook_setup_main_branch_gate.py` (10/10) — none regressed.

**Replay probe** (`dev/hook_smoke/probe_replay_cli_chained.py`, report at
`dev/hook_smoke/md/block_cli_chained_replay_report.md`): fed all 115 historical `block` fires
from the 7 old hooks (main checkout's `hook_firing.jsonl`) through the new hook. As of this task:
49 still block, 66 now pass (per-hook: gh-cli 12/19, rag-cli 32/34, worker-cli 3/10, websearch 0/0,
duallog 0/2, linkedin 1/0, penny-cli 1/1). This is a noticeably larger pass-share than the task
prompt's own pre-implementation estimate ("about 83 block, about 32 pass"). Each now-passing
command was spot-checked by hand against the literal rule text (e.g. `gh-cli list_issues ... 2>/dev/
null || true` passes because bare `2>` doesn't count and there is no pipe; `rag-cli search "x" ...;
echo ...; ls ...` passes because `search` carries no redirect and no pipe, only `;`-chaining) — the
larger-than-estimated pass count traces to how much of the historical 115 was actually "protected
CLI chained via `;`/`&&` with unrelated commands, no pipe, no redirect at all" or "bare `2>/dev/
null` suppression," both of which the literal rule allows. Not re-derived from a different reading
of the rule text — the discrepancy is reported as-is in the replay report rather than resolved by
loosening or tightening the implementation to chase the estimate.

## What was not changed

`block_rag_cli_index_isolated.py` and `block_pipe_scraper_isolated.py` stay untouched — they exist
to make CC auto-background a long-running call standing alone in its Bash invocation, a different
concern from output-boundedness. `hook_setup.py` was not run in this worktree (its own worktree
guard refuses this, and the repo's `.githooks/post-commit` confirmed the refusal automatically on
commit) — going live happens on merge into `main`, per the established pattern already documented
for `block_linkedin_cli_isolated.py`'s own registration in `process-docs/tool_use_safety/`.
