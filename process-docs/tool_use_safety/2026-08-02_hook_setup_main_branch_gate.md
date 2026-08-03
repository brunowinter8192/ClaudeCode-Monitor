# hook_setup.py: two-condition install gate (main-branch + working-tree presence)

## Incident

A hook file added on `integration` was merged via `worker-cli merge`; the repo's
`.githooks/post-merge` auto-ran `src/hooks/hook_setup.py`, which registered it into the GLOBAL
`~/.claude/settings.json` using its absolute working-tree path. The repo was later switched to
`main`, where that file did not exist. The registration stayed. From that moment EVERY Bash tool
call on the whole machine, every project, every session, failed with `can't open file '<path>':
[Errno 2] No such file or directory` until the entry was removed by hand.

`_sweep_stale_hooks()` already removes entries whose script path no longer exists on disk — but
only when `hook_setup.py` itself runs, which cannot happen during the outage window because Bash
is already dead and nothing triggers a re-run.

## Design: `decide_entries()` — two-condition gate before the add-loop

`hook_setup.py`'s install loop was preceded by a new pure partition step:
`decide_entries(hook_scripts, git_query_fn, tree_query_fn) -> (installable, skipped)`. A script
installs only when BOTH:

1. **Committed on `main`** — `_script_on_main(script)`: `git cat-file -e
   main:src/hooks/<script>`, gated behind a cached `_main_branch_resolves()` check
   (`git rev-parse --verify --quiet main`). Returns `True`/`False`/`None` (`None` = query
   unanswerable: no git, no `main` ref, subprocess error/timeout).
2. **Present in the CURRENT working tree** — `_script_in_worktree(script)`:
   `os.path.exists(_HOOKS_DIR / script)`, i.e. present at the exact path about to be written into
   settings.json, right now.

Fail-safe direction for condition 1's `None`: treated identically to a confirmed `False` — SKIP.
Rationale: the outage this gate prevents is categorically worse than losing one hook's
enforcement until the query can succeed again. This `None` path was not reproduced against a live
git repo lacking a `main` ref (two throwaway-repo setups were tried and abandoned) — it is
verified by stub only in the smoke suite, not live.

Both conditions route to skip because BOTH are the same failure class (dead absolute path in the
global settings.json) — condition 1 alone was the first-round implementation; condition 2 (the
"mirror-image hole") was caught in review, not by the initial implementation:

> A script that IS committed on `main` but is absent from the CURRENT working tree (a branch
> deleted or renamed it while its `_HOOK_SCRIPTS` entry stayed) passes a main-only gate and gets
> registered as a dead absolute path — the exact same outage, entering from the other side. Made
> worse by ordering: `_sweep_stale_hooks()` runs BEFORE the install loop, so it would remove that
> exact dead entry and the install loop would immediately put it back.

Main-branch presence is checked first; a script failing it never reaches the tree check, so
"missing from both" reports the main-branch reason (a deliberate, documented tie-break — not
significant for the install outcome, only for the stderr wording a maintainer sees).

Decision cached per script filename — `_HOOK_SCRIPTS` entries with multiple matchers for the same
script (`block_path_typo.py` × 4, `block_dev_imports_src.py` × 2, `block_except_pass.py` × 2)
query git/filesystem once and share the verdict; skipping one script never blocks the other 42.

## Verification

- Smoke: `dev/hook_smoke/test_hook_setup_main_branch_gate.py`, 10 cases, stub `git_query_fn` +
  `tree_query_fn` — all pass. Covers both conditions independently, the mixed set, multi-matcher
  scripts, and reason-text distinguishability between the two failure modes.
- Real repo-state run against actual `_HOOK_SCRIPTS` (43 entries at the time): `installed=43,
  skipped=0`. A fabricated script name: correctly skipped, reason names "not committed on
  'main'".
- **Mirror-image condition reproduced live** (not stubbed): temporarily deleted the real,
  main-committed `src/hooks/block_dangerous_kill.py` from disk mid-session, ran the gate —
  `_script_on_main` → `True`, `_script_in_worktree` → `False`, `decide_entries` skipped it with
  the tree-specific reason, `installed=[]`. File restored immediately after; `git status --short`
  on it came back clean, confirming a lossless round-trip and that the gate's skip decision was
  based on a genuine transient absence, not a stub.
- `hook_setup.py` itself was never run directly during this work — it refuses to run from a
  worktree by design, and mutates the live global `~/.claude/settings.json`; deployment onto that
  file happens via the repo's `.githooks/post-merge` automation after merge onto `main`.
