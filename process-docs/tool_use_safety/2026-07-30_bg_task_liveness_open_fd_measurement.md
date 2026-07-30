# 2026-07-30 — Background-task liveness: open file handles beat the 0-byte predicate

Measured on this machine against real auto-backgrounded `rag-cli index` runs plus a synthetic writer.

## The predicate on file at the time

`src/menubar/proc_cache.py::_has_active_bg(encoded_dir, session_id)` answered "does this session have a
background task in progress" with: is any `*.output` file in `<tasks_dir>` zero bytes.

## Measurement 1 — auto-backgrounded task holds open write handles

`rag-cli index --collection trading-reference --document HansenLundeNason2011ModelConfidenceSet.md`
(127 KB doc) was auto-backgrounded by CC as task `btxonl8af`. Immediately after the launch-ack, `lsof` on
`<tasks>/btxonl8af.output` showed FOUR open write handles:

```
zsh     99656  1w, 2w  → .../tasks/btxonl8af.output
Python  99659  1w, 2w  → .../tasks/btxonl8af.output
```

The `zsh` wrapper and the `Python` process doing the indexing each hold stdout and stderr on the file.
File size at that moment: **0 bytes** — the run had not flushed anything yet.

After completion: **zero** open handles, file 254 bytes, containing the finished `Indexed 96/96 chunks`
report. The transition is sharp — no lingering handle, no delay.

This answers the open question that was on file for the timer-stacking guard: an AUTO-backgrounded task is
detectable the same way an explicitly-backgrounded one is. Same measurement had already been done for the
explicit path; both hold handles.

## Measurement 2 — the 0-byte predicate fails on any task that writes

```
for i in 1..10; do echo "progress $i"; sleep 2; done > /tmp/fake_task.output
```

After 3 seconds: file **22 bytes**, still 2 open handles, loop still running. The 0-byte predicate returns
False here — a live task reported as finished. A `rag-cli index` run behaves exactly like this: it prints
`Indexed N/M chunks` continuously, so it stops being 0 bytes within seconds while running for minutes.

So file size is not a liveness signal; an open write handle is.

## Measurement 3 — cost

`lsof +D <tasks_dir>`: 101 / 102 / 97 ms across three runs. With `-w` (suppress warnings): 93 / 92 / 93 ms.

`_has_active_bg` is called once per session per menubar tick, and the tick is 1.5s
(`src/menubar/DOCS.md` Flow step 2). A naive per-session call is therefore too expensive with several live
sessions — a cache/batch layer is required. The module already carries a TTL-cache pattern
(`_refresh_cc_proc_cache` + `_PROC_REFRESH_INTERVAL`).

## Task-dir resolution per worker

A worker's tasks dir is derivable from its worktree path, no search needed: the path is encoded with `/`
→ `-`, then the session UUID, then `tasks/`. Example — worker `badge-words` in worktree
`/Users/…/monitor-cc/.claude/worktrees/badge-words`:

```
/private/tmp/claude-501/-Users-…-monitor-cc--claude-worktrees-badge-words/<session-uuid>/tasks/
```

`_TASKS_BASE` (`/tmp/claude-<uid>`) plus `encoded_dir` plus `session_id` is exactly the shape
`_has_active_bg` already takes.

## Where the predicate is (and is not) consumed

`discover.py::_process_project_dir` (~line 147) → `SessionInfo.has_bg`. Only consumer of `has_bg` is
`focus_controller.py:50` — the auto-FOCUS debounce. The auto-ABORT check in the same file (~lines 65-97)
does NOT look at it: it kills the orchestrator's `sleep 600` timer as soon as every worker of a project is
`idle`, whatever those workers still have running.

## The failure pattern this enables

1. orchestrator dispatches a worker
2. inside its task, one of the worker's calls gets auto-backgrounded
3. the worker goes idle correctly — the injected launch-ack tells it to wait
4. all workers idle → auto-abort kills the orchestrator's timer
5. orchestrator wakes, sees `idle`, cannot see the pending background task, and prods the worker
6. the worker has nothing to do but poll its own background process
7. worker goes idle again → timer aborted again → repeat

Polling that is blocked at the hook level re-enters through orchestration. Observed live this session with
worker `bg-detect`: its own probe script sat in a wait-until-non-empty loop for >10 minutes
("Still 0 bytes. Let's launch the probe now — it will poll until non-empty"). Contributing cause was the
task prompt asking to "record the answers over time", which invites a loop; the no-polling rules cover
timers and worker-status reads, not a worker's own probe script.

Side observation from that run: the worker's long-running foreground probe was NOT auto-backgrounded by CC
even though it ran >10 minutes. Auto-backgrounding is therefore not a reliable function of runtime — single
observation, not a rule.
