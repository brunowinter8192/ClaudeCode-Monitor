# 2026-08 — chained-CLI hooks: loop scaffold + echo/printf relax

## Problem

Real case wrongly blocked (via `block_gh_cli_chained.py`):

```bash
for n in 62 61 59; do echo "===== #$n ====="; gh-cli get_issue brunowinter8192 wise2627 $n; done
```

The four chained-CLI hooks (`block_gh_cli_chained.py`, `block_rag_cli_chained.py`,
`block_websearch_scrape_chained.py`, `block_worker_cli_read_chained.py`) split a Bash command on
separators (`&&`, `||`, `;`, `|`, newline) and require every segment to be a known-CLI call
(`is_known_cli_segment`) or a leading `cd`/`test`/`[ ... ]` guard (`is_guard_segment`). A
for-loop produces segments `for n in 62 61 59`, `do echo "===== #$n ====="`, `gh-cli get_issue
... $n`, `done` — three of the four match neither predicate, so a batch loop that filters
nothing and returns each `get_issue` call's output in full to context (the exact intent the
hooks protect) gets blocked outright. This is the same failure shape as the msg118 echo-variant
incident recorded in `2026-08-07_gh_cli_repo_freshness_segment_and_message_clarity.md` (echo
separators between chained gh-cli calls) — that entry's fix made `repo_freshness` a legal
segment but left bare `echo`/loop scaffolding blocking, because at the time only
`repo_freshness`-as-known-CLI was in scope, not the general echo/loop case.

## Decision

Rather than adding loop-awareness separately to all four hooks, the allowance lives once in the
shared `src/hooks/_known_cli.py` helper (already the shared home of `is_known_cli_segment`/
`is_guard_segment`) as two new predicates plus a composed entrypoint:

- `is_echo_segment(segment)` — `^(?:echo|printf)\b`. A pure echo/printf segment produces
  separator/label output only; it can never filter or truncate another segment's output
  elsewhere in the same Bash call, so it carries none of the risk the hooks exist to prevent.
- `is_loop_scaffold_segment(segment)` — a `for ...`/`while ...` header (whole segment, any
  content — loop headers are iteration control, never a CLI call themselves), a bare `do`/`done`
  (own segment when the loop spans newlines/semicolons), or `do <segment>` where `<segment>`
  (everything after `do `) is itself a known-CLI call, a guard, or echo/printf. The recursive
  check on `do <segment>` is what keeps a foreign command inside a loop body blocked: `do curl
  ...` fails `is_known_cli_segment`/`is_guard_segment`/`is_echo_segment` on the inner `curl ...`,
  so `is_loop_scaffold_segment` returns `False` and the segment blocks exactly as before.
- `is_allowed_chain_segment(segment)` — ORs all four predicates (`is_known_cli_segment`,
  `is_guard_segment`, `is_echo_segment`, `is_loop_scaffold_segment`). Each of the four hooks now
  imports only this one function and checks `if is_allowed_chain_segment(seg): continue` in
  place of the old `is_known_cli_segment(seg) or is_guard_segment(seg)` check — no
  hook-specific logic changed, only the shared allow-set grew.

Alternatives considered and rejected:
- Per-hook loop detection — rejected, duplicates the same for/while/do/done parsing four times
  and risks the four hooks drifting out of sync, which the shared-helper design already exists
  to prevent.
- Allowing arbitrary segments inside `do ...`/`while ...` bodies unconditionally — rejected, that
  would let a foreign command (e.g. `curl`) ride through the loop body unpoliced, defeating the
  hooks' purpose. The recursive check on the `do <segment>` inner content is deliberate.

## Side effect: msg118 incident now resolved

The msg118 echo-variant from the repo_freshness incident (previously a documented
"still blocks" regression case in `dev/hook_smoke/probe_gh_cli_repo_freshness_incident.py`) now
passes under this relax — echo is a legal separator segment. The probe and
`dev/hook_smoke/test_block_gh_cli_chained.py`/`test_block_rag_cli_chained.py`/
`test_block_websearch_scrape_chained.py`/`test_block_worker_cli_read_chained.py` were updated:
every case that asserted BLOCK purely because of a bare `echo`/`printf` segment (six cases across
the four suites) now asserts PASS, with the case description updated to note the 2026-08
loop-scaffold relax. The probe's `_BLOCK_MESSAGE`-content assertion, which used to run against
the msg118 echo-variant's stderr, was retargeted to the still-blocking `index_issues | head`
case, since msg118 no longer produces a block at all.

## Verification (as of 2026-08)

- `dev/hook_smoke/test_block_gh_cli_chained.py`: 34/34 pass (4 new: real-world for-loop PASS,
  while-loop-with-echo PASS, foreign-curl-in-for-loop-body BLOCK, plus the msg118 case flipped
  to PASS; two standalone "echo chained" cases flipped to PASS in place).
- `dev/hook_smoke/test_block_rag_cli_chained.py`: 20/20 pass (3 new: for-loop-with-echo PASS,
  while-loop-with-echo PASS, foreign-curl-in-for-loop-body BLOCK; one "echo chained" case
  flipped to PASS in place).
- `dev/hook_smoke/test_block_websearch_scrape_chained.py`: 21/21 pass (4 new: for/while-loop
  PASS cases, foreign-curl-in-for-loop-body BLOCK; two "echo chained" cases flipped to PASS in
  place).
- `dev/hook_smoke/test_block_worker_cli_read_chained.py`: 23/23 pass (4 new: for/while-loop PASS
  cases, foreign-curl-in-for-loop-body BLOCK; two "echo chained" cases flipped to PASS in
  place).
- `dev/hook_smoke/probe_gh_cli_repo_freshness_incident.py`: 6/6 case checks + 3/3 message-content
  checks pass; report at `dev/hook_smoke/md/gh_cli_repo_freshness_incident_probe_report.md`.
- Manual run of the exact real-world command through all four hook scripts via subprocess: all
  four exit 0.
- Manual run of `gh-cli get_issue owner repo 5 | grep foo` through `block_gh_cli_chained.py`:
  exit 2 (unchanged — a piped foreign segment still blocks).
