# Timer guard: block canonical bg sleep-timer when no worker is working

## Problem

Orchestrator ends a turn by arming a canonical background sleep-timer
(`run_in_background=true`, `sleep 3300 && echo done`) and going idle. Legitimate only while a
worker of the SAME project is actively working (the timer's sole purpose is to wake the
orchestrator when that worker finishes). When the project's worker set is empty or every worker
is idle, arming the timer idles the orchestrator for nothing.

## Design

New PreToolUse Bash hook, `src/hooks/block_timer_no_worker_working.py` (129 LOC), registered in
`_HOOK_SCRIPTS` (42→43 entries) immediately before `rewrite_background_sleep.py` so it fires
before the rewrite/normalization hooks — order-independence achieved by reusing the exact
`_SLEEP_ONLY_BG` regex shape already shared between `rewrite_background_sleep.py` and
`block_unauthorized_background.py`.

**Block condition (both):** (1) `run_in_background=true` + sleep-only command form; (2) project
worker set empty OR every worker's first status token (`status.split()[0]`) == `idle`.
`unknown`/`working`/`limit reached` never contribute to a block by construction — `unknown`
specifically must never block since it covers the fresh-spawn window right after `worker-cli
spawn` returns, before the new worker's CC instance has written its first status file.

**`decide(command, run_in_background, project_path, status_fn)`** kept pure with an injectable
`status_fn`, mirroring `block_worker_kill_while_working.py`'s pattern — the real entrypoint wires
`_live_worker_statuses` (subprocess `worker-cli status --all <project>`, 3s timeout, resolved via
duplicated `_resolve_worker_cli()` helper: `shutil.which` then plugin-cache glob fallback), smoke
tests inject a stub returning raw `worker-cli status --all` stdout text directly.

**Worktree exemption:** hook is orchestrator-only — `.claude/worktrees/` fragment in `os.getcwd()`
→ exit 0 immediately, same shape as `block_cd_drift.py`.

## Broken-probe class found during review (not by initial implementation)

Reviewer measured: with a PATH lacking the tmux-containing directory, `worker-cli status --all
<project>` prints `(no active workers)` and exits 0 EVEN THOUGH a worker is live and registered —
`worker-cli` shells out to bare `tmux` internally and swallows the failure. The hook's own
fail-open handling already covered "worker-cli binary unresolvable" and "subprocess/non-zero-exit"
as broken-probe classes routing to allow — this is the same class one level deeper: worker-cli's
own dependency silently missing rather than worker-cli itself.

Fix: `_live_worker_statuses` checks `shutil.which('tmux') is None` and raises before invoking
`worker-cli`, so `decide()`'s status_fn try/except routes to allow instead of misreading the
degraded output as a genuine empty worker set.

**Live verification** (real payload, real project dir `monitor-cc` root with a genuinely
registered live worker at the time — `timer-guard: limit reached`, PATH stripped to
`~/.local/bin:/usr/bin:/bin`, confirmed via `shutil.which`: `worker-cli` still resolves, `tmux`
does not):
- Pre-guard code (`git show HEAD~1` at review time): exit 2 — false block.
- Post-guard code: exit 0 — correct allow.
- Independently confirmed `worker-cli status --all` itself: `(no active workers)` exit 0 under
  stripped PATH vs. `timer-guard: limit reached` exit 0 under the real PATH — proves the
  degradation lives in worker-cli's tmux dependency, not in this hook's output parsing.

Not covered by the stub-based smoke suite: the tmux check lives inside `_live_worker_statuses`,
below the `status_fn` boundary the smoke suite stubs — a stub-based case would just re-exercise
the already-covered generic "status_fn raises → allow" path in `decide()`. Live drive above is
the evidence for this specific class instead.

## Block message iteration

First version ("Skip the timer, or arm it after a worker starts.") didn't tell the orchestrator
to go idle, only that the timer shouldn't be armed — a real instruction gap since the whole point
of blocking the arm is that the orchestrator should stop the turn now. Reviewer traced this to a
requirement carried over from a removed predecessor hook (`block_background_sleep_nonworker.py`,
no longer in the tree) that opened with "Go idle immediately." Final message: `"Go idle
immediately. No worker of this project is working — this timer may not be armed.\n"`.

## Verification summary

- Smoke: `dev/hook_smoke/test_block_timer_no_worker_working.py`, 10/10 (pure `decide()` + stub
  `status_fn`, no real workers).
- Entry-point: real subprocess drive (`echo <payload> | python3
  block_timer_no_worker_working.py`) for both block and allow cases, plus the tmux-guard
  before/after drive above.
- Not verified: a live scenario where a real worker of the project is actually mid-`working` at
  hook-fire time (all live drives happened to catch the worker in `idle`/`limit reached`).
