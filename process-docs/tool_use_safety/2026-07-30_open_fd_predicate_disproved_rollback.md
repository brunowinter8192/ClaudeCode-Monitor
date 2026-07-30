# 2026-07-30 — Open-FD predicate disproved by live test; escape + abort-gate rolled back

## What was built on the assumption

Two mechanisms were built on `has_bg` (`proc_cache._has_active_bg`: does any process hold an open handle
on a `*.output` file in a session's tasks dir):

1. **Escape-on-bg-launch** (`focus_controller.tick`) — on the `has_bg` False→True edge for a worker, send
   one `tmux send-keys -t <session> Escape` to force it idle so it cannot poll a backgrounded task.
2. **Auto-abort gate** — `all_idle` additionally required `not w.has_bg`, so a worker with a live
   background task would not let the orchestrator's sleep timer be aborted.

Both shipped in the installed bundle and both were removed again the same day.

## The live test that disproved the premise

Worker `esc-live` was told to: delete + re-index a 327 KB document (`Silverman1986DensityEstimation.md`)
as a plain FOREGROUND call, then immediately start unrelated work (read `src/proxy/` modules and write a
structural summary) — explicitly instructed not to poll, and told that being interrupted was the expected
success case.

Observed:

- `17:11:55 [escape] escape_idle worker=esc-live tmux=worker-monitor-cc-esc-live sent=True`
- the worker's pane stops right after "Now issuing the index call as a normal foreground call"
- its tasks dir contained ZERO `*.output` files afterwards, and no `rag-cli index` process was running
- every subsequent `abort_check` line reported `has_bg=False` for that worker

So the Escape fired on the worker's very first Bash call and killed it before any indexing began.

## Root cause — the predicate measures the wrong thing

Direct check, run as a plain foreground Bash call with no backgrounding whatsoever:

```
lsof +D <own tasks dir>
zsh  45482  .../tasks/br9roxcfa.output
zsh  45482  .../tasks/br9roxcfa.output
awk  45490  .../tasks/br9roxcfa.output
head 45491  .../tasks/br9roxcfa.output
head 45491  .../tasks/br9roxcfa.output
```

EVERY Bash call — foreground included — gets a `tasks/<id>.output` file and holds open handles on it for
its whole runtime. `has_bg` therefore means "some call is currently running", not "a task was moved to the
background".

Consequences for both mechanisms:

- the Escape fires on the first call a worker makes, at which point the running turn IS that call — it
  kills the very work it was meant to protect
- the abort gate holds the timer for any busy worker, which `status == 'working'` already covers; it adds
  nothing and obscures the real condition

## Where the earlier measurement went wrong

The 2026-07-30 open-handle measurements were correct as measurements: a backgrounded task does hold open
handles, and the handle disappears exactly at process exit. The error was the missing control: a
FOREGROUND call was never measured. Without that control, "backgrounded tasks hold handles" was read as
"holding a handle means backgrounded" — the converse, which does not follow and is false.

## Rollback performed

- `focus_controller.py`: escape block, `_send_escape_key`, `_escape_log_write`, `_bg_escaped_workers`,
  and the `not w.has_bg` term in `all_idle` all removed; `has_bg` is still printed per worker in the
  `abort_check` log line for diagnosis only
- deleted: `dev/hook_smoke/test_escape_idle_worker.py`, `probe_escape_real_tmux_roundtrip.py`,
  `test_focus_controller_bg_gate.py`, `md/2026-07-30_escape_real_tmux_roundtrip.md`
- `src/menubar/DOCS.md` and `dev/hook_smoke/DOCS.md` updated
- `proc_cache._has_active_bg` itself was KEPT — as a "session is busy" signal it is accurate, and it is
  still an improvement over the 0-byte predicate it replaced (which was wrong in both directions)

The rollback was done by the orchestrator directly rather than by a worker: with the escape mechanism live
in the installed bundle, every spawned worker was killed on its first call.

## The signal that actually works

The proxy injects a launch-ack replacement exactly when Claude Code has backgrounded a call — the
three-line "Command is running in the background… / Output: … / ID: <id>" text, verified across all three
backgrounding paths earlier the same day. That text exists if and only if a task was backgrounded; it is
not a side effect of anything else. The proxy also already knows which worker a request belongs to
(`addon.py::_derive_worker_context()` → `worker:<name>`), from which the tmux session name is derivable.

Open question for that design, unresolved here: the proxy sees the launch-ack on the worker's NEXT
request, i.e. after the call was backgrounded. Whether the worker is then still mid-turn or already
waiting determines what an Escape at that moment would hit.
