# rewrite_background_sleep.py — Orchestrator-Only Guard (Live Incident)

## Incident

Twice in one day: a WORKER armed a background sleep (waiting on its own long test run — e.g.
`sleep 300 && echo done`). `rewrite_background_sleep.py` had zero cwd awareness and rewrote it to
`worker-cli wait` regardless of caller — the `worker-cli wait` rewrite-target migration (same area,
same day) didn't account for non-orchestrator callers. Run from the worker's own worktree cwd,
`worker-cli wait` resolves that
worktree path as the project, finds no workers registered there, and blocks up to the full default
timeout (3300s). That stray `worker-cli wait` process is then a live child under the worker's own
`claude` process — which `worker-cli wait`'s own background-task heuristic (see the `worker_wait`
area in the iterative-dev repo) correctly detects, so the ORCHESTRATOR's own `worker-cli wait`
ALSO refuses to finish (idle worker + live background task under it = not done, by design). One
misfire in a worker cascades into two stuck waits.

## Fix

Added the same `_WORKTREE_FRAGMENT = '.claude/worktrees/'` cwd exemption the (now-removed,
Milestone 2) `block_timer_no_worker_working.py`/`block_timer_pending_bg.py` hooks used —
`rewrite_background_sleep.py` is now orchestrator-only, checked first via a small `_in_worktree()`
helper before any input parsing. A worker's `sleep N` now genuinely stays `sleep N` in the
background, harmless for its own purpose.

`block_unauthorized_background.py` stays global, deliberately unchanged: it only ever flips
`run_in_background` (never rewrites command text), so a worker's sleep-only background command
staying background there was already correct and harmless — the bug was entirely in the OTHER
hook's command-text rewrite, not in this one's foreground-forcing decision.

**Fail-open direction chosen deliberately, opposite of most hooks in this file family:**
`_in_worktree()` defaults to `True` (skip rewrite) on any `os.getcwd()` failure, not `False`
(proceed to rewrite). Reasoning: a missed rewrite for the orchestrator on the rare occasion cwd
detection itself fails just means the old sleep-timer form persists that one time — harmless. The
opposite default would risk reproducing the exact incident being fixed, on precisely the call
where the guard meant to prevent it can't be evaluated reliably.

## Test-suite gotcha (real, hit while building the regression cases)

`dev/hook_smoke/test_rewrite_background_sleep.py`'s `_run_hook()` previously invoked the hook via
a relative path with NO explicit subprocess `cwd` — silently inheriting the test-runner's own cwd.
Since this repo's dev worktrees live under paths containing `.claude/worktrees/` themselves,
running the suite normally (from inside a worktree, the everyday case) would have made every
EXISTING positive case inherit a worktree cwd the moment the guard was added — flipping all of
them to unexpected no-rewrite and masking the very thing under test. Fixed by resolving `HOOK` to
an absolute path and forcing `cwd` explicitly per case: a plain `tempfile.TemporaryDirectory()`
(guaranteed no `.claude/worktrees/` fragment anywhere) for the 11 non-worktree cases, and a
`<tempdir>/.claude/worktrees/fake-worker` path (same construction pattern the deleted
`test_block_timer_pending_bg.py`'s worktree-exemption layer used) for 3 new negative cases proving
the guard actually fires.

## Verification

`dev/hook_smoke/test_rewrite_background_sleep.py` — 14/14 passed (11 existing cases re-verified
green under the now-explicit non-worktree cwd, 3 new worktree-cwd cases: bare `sleep 300`, the old
canonical `sleep 3300 && echo done`, and a foreground sleep — all correctly no-op from a
`.claude/worktrees/`-shaped cwd). Neighboring suites re-run for regression, unaffected as expected:
`test_block_unauthorized_background.py` (14/14) and `test_rewrite_chained_sleep.py` (31/31).
