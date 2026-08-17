# Background-Timer Hook Family — Migration to `worker-cli wait` (Pull)

The iterative-dev plugin's `worker-cli wait [project_path] [--timeout N]` (own area:
`process-docs/worker_wait/` in the iterative-dev repo) replaces the orchestrator's raw
`sleep 3300 && echo done` background timer + menubar-kill-on-idle push mechanism with a
pull: the command blocks in-process until all workers of the project go stably idle (or
`--timeout`), and its own exit IS the wake-up — no external killer, no ambiguity about
which timer got killed. The four hooks in `src/hooks/` built around the old raw-sleep
convention needed to follow.

## Changes

**`rewrite_background_sleep.py`** — rewrite target changed from `"sleep 3300 && echo done"`
to `"worker-cli wait"`. Dropped the old "already canonical" exemption: it existed only
because the target string itself could theoretically match `_SLEEP_ONLY_BG` (a sleep-form);
now the target is a different command entirely, so that branch was permanently unreachable
and removing it simplified the condition to "any sleep-only match + `run_in_background` →
rewrite, no exceptions." Consequence: the OLD canonical `sleep 3300 && echo done` is now
ALSO a stale habit and gets rewritten — every sleep-timer form converges on `worker-cli
wait`, with no privileged exact string anymore.

**`block_unauthorized_background.py`** — added a second canonical-form regex,
`_WAIT_FORM = ^\s*worker-cli\s+wait\b[^;&|\n]*$` (word-boundary after `wait`, same
shell-separator tail-guard style as `_SLEEP_ONLY_BG`), alongside the existing sleep-only
regex. Both are order-independent exemptions relative to `rewrite_background_sleep.py` — this
hook currently runs BEFORE the rewrite hook in `hook_setup.py`'s registration order, so a raw
sleep-timer habit must still be recognized as canonical here even before it gets normalized.
"No whitelist beyond these two forms" policy is unchanged — every other `run_in_background=true`
command is still foreground-forced without exception.

**Removed `block_timer_no_worker_working.py` and `block_timer_pending_bg.py` entirely**
(files, `hook_setup.py` `_HOOK_SCRIPTS` entries, `dev/hook_smoke/` smoke suites). Rationale —
both existed to compensate for properties the OLD push mechanism lacked, both now
structurally unnecessary:

- `block_timer_no_worker_working.py` blocked arming the timer when no worker was working, to
  avoid idling for nothing. `worker-cli wait` now handles "no worker yet" by continuing to
  poll internally (see its own area, `worker_wait`: "no worker visible at all -> keep
  waiting, never exit early, until timeout") — arming early is no longer wasted, just a
  longer wait; no separate blocking hook needed to teach the agent not to arm it.
- `block_timer_pending_bg.py` blocked arming a new timer while an earlier `sleep`-tracked
  background task (via `src/proxy/pending_bg_state.py`, milestone-3, `process-docs/timer-loop/`
  area) was still pending — preventing stacked timers and duplicate wakeups. `worker-cli
  wait` is independently concurrency-safe (verified: two concurrent `wait` invocations on the
  same project both converge and exit cleanly on the same idle transition, `worker_wait`
  area) and there is no external killer anymore to produce ambiguity about which arm "won" —
  the stacking failure mode this hook guarded against no longer exists in the pull design.

**Transitional state, explicitly accepted (negative scope — `src/proxy/` untouched this
milestone):** `src/proxy/pending_bg_state.py` keeps writing `pending_bg_tasks.json` on every
bg-launch-ack/completion sighting — it now has no reader. This is intentional: removing that
writer is a later milestone. Its module comments and `dev/timer-loop/
p3_project_scope_incident_probe.py` (a `dev/timer-loop/` incident-replay probe, not a
`dev/hook_smoke/` regression suite — subprocess-invokes the now-removed hook by absolute
path) both still name `block_timer_pending_bg.py` by design; the probe got a one-line
"superseded, hook removed" note at its top and is otherwise left as a historical record.

**`block_worker_send_background.py`** — block-message text only (no logic change): the
"dispatch any timer separately as..." clause now names `worker-cli wait` instead of the
stale `sleep N && echo done` phrasing.

## Verification

Ran the 2 directly-changed smoke suites plus 2 neighboring ones (unaffected logic, run as a
registration/order regression check since `hook_setup.py`'s `_HOOK_SCRIPTS` list and the two
background-command hooks were edited):

- `test_rewrite_background_sleep.py` — 11/11 passed (6 positive rewrite incl. the old
  canonical target now converting, 5 negative no-op incl. `worker-cli wait` passthrough).
- `test_block_unauthorized_background.py` — 14/14 passed (3 sleep-only ALLOW, 4 `worker-cli
  wait` ALLOW incl. `project_path`/`--timeout` combinations, 6 FORCE incl. a chained
  `worker-cli wait && rag-cli index` case proving the tail-guard and a `worker-cli waitfoo`
  case proving the word-boundary, 1 foreground PASS).
- `test_rewrite_chained_sleep.py` (neighboring, unaffected) — 31/31 passed.
- `test_hook_setup_main_branch_gate.py` (neighboring, unaffected — uses synthetic script
  lists, not the real `_HOOK_SCRIPTS`) — 10/10 passed.

`block_busywait_loop.py` and `block_worker_send_background.py` have no dedicated
`dev/hook_smoke/` suite to re-run (message-text-only change on the latter, verified by
reading the diff — no behavior change to test).

Confirmed via grep: no remaining references to `block_timer_no_worker_working` /
`block_timer_pending_bg` in `hook_setup.py` or `src/hooks/DOCS.md`; both hook files and both
smoke-test files removed from disk.
