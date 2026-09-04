# Fix: block_duallog_chained.py path-substring false positive (2026-09-04)

**Topic:** `block_duallog_chained.py`'s trigger anchor blocked commands that merely mentioned a
path containing `duallog` as a substring (e.g. `iterative-dev-duallog`), with no `duallog` CLI
invocation anywhere in the command — fixed by adopting `block_rag_cli_chained.py`'s existing
segment-first anchor shape.

## The bug

`_DUALLOG_RE = re.compile(r'\bduallog\b')` was the hook's fast-path trigger, searched over the
WHOLE stripped command before any segment splitting. `\b` treats a hyphen as a word boundary, so
this matched `duallog` inside `iterative-dev-duallog` — a real path segment
(`~/Meta/iterative-dev/skills/iterative-dev-duallog/SKILL.md`), not a CLI invocation. Reproduced
live: `cat ~/Meta/iterative-dev/skills/iterative-dev-duallog/SKILL.md | grep -n msgs` blocked with
the piping message, even though no `duallog` call exists anywhere in that command — the trigger
fired, then the per-segment loop correctly found no segment starting with `duallog`, but the
foreign `cat`/`grep` segments still failed `is_allowed_chain_segment` and blocked.

Found by accident while investigating an unrelated `dual_log_cli` milestone (reading that exact
SKILL.md path) — flagged via `SendFeedback` at investigation time, fixed in this same-day pass once
scoped as its own deliverable.

## The fix

Exactly `block_rag_cli_chained.py`'s own 2026-08 fix for the identical bug class on `rag-cli`:
split into segments FIRST (the same `_SEPARATOR_RE` split the per-segment loop already needs), then
trigger on `any(_DUALLOG_SEGMENT_RE.match(seg) for seg in segments)` — a segment START match, never
a substring search anywhere in the raw command. `_DUALLOG_SEGMENT_RE` itself also gained an
optional env-var-assignment prefix (`_ASSIGN_PREFIX`, the same shape `_known_cli.py`'s
`_KNOWN_CLI_RE` and `block_rag_cli_chained.py`'s `_RAG_CLI_SEGMENT_RE` already use), which it had
not carried before — a `duallog`-prefixed segment with a leading env assignment now anchors
correctly too, matching every sibling chained-CLI hook.

## Verification

- New case in `dev/hook_smoke/test_block_duallog_chained.py`: the exact reproducing command now
  PASSes (exit 0). Full suite: 8/8 (was 7/7 before the new case).
- Sibling chained-CLI suites re-run unchanged: `test_block_gh_cli_chained.py` 34/34,
  `test_block_rag_cli_chained.py` 24/24, `test_block_websearch_scrape_chained.py` 21/21,
  `test_block_worker_cli_read_chained.py` 23/23 — confirming the fix touched only
  `block_duallog_chained.py`.
- Real invocation of the literal reproducing command against the hook script directly: exit 0.

## Relevant Symbols / Paths

- `_DUALLOG_SEGMENT_RE`, `block_duallog_chained_workflow` (`src/hooks/block_duallog_chained.py`)
- `_RAG_CLI_SEGMENT_RE` (`src/hooks/block_rag_cli_chained.py`) — the precedent this fix copies
- Area: `process-docs/tool_use_safety/` — see `2026-09-04_block_duallog_chained.md` in this same
  area for the hook's original design (same-day, earlier in the day)
