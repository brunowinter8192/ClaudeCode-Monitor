# Background-task liveness via open file handle, replacing 0-byte-file check — 2026-07-30

## Question this entry answers

The 2026-07-27 entry in this area left one unresolved question open: does an AUTO-backgrounded
task (CC's own terminal-freeze protection moving a running foreground call to background, as
opposed to an explicit `run_in_background=true`) get a `tasks/<id>.output` file held open the same
way an explicit background task does? If not, a liveness guard built on open-handle detection would
miss exactly the pattern that motivated the investigation.

Measured this session, on `src/menubar/proc_cache.py::_has_active_bg` (the menubar's own
background-task badge predicate, unrelated to the hook-based concurrency-guard sketch from
2026-07-27 but built on the same open-handle signal): YES for both. An auto-backgrounded
`rag-cli index` run and an explicitly-backgrounded synthetic writer loop both showed the wrapper
`zsh` process AND the worker process holding open write handles (`fd 1w, 2w`) on the task's
`.output` file for the task's entire real duration.

## Why file size was the wrong signal

`_has_active_bg` previously asked: is any `*.output` file in the session's tasks dir exactly 0
bytes? Two independent failure directions, both reproduced with real processes this session:

- **False negative.** A task that writes progress (`rag-cli index` on a 547 KB document, 382
  chunks) goes non-zero once its writes flush, while the process is still running for minutes. A
  synthetic writer loop (`for i in 1..10; do echo progress; sleep 2; done > out`) was 18 bytes and
  still had 2 open fds after 3s — the 0-byte predicate returned `False` (reported "finished") while
  the process ran for another ~17s.
- **False positive.** A real, unrelated CC main session's tasks dir had accumulated a stale 0-byte
  `*.output` file left over from a prior task that produced no output. The 0-byte predicate reads
  that as "busy" — forever, since nothing ever cleans up an empty completed task file. The
  handle-based predicate correctly read `False` (no process holds it open).

## Root cause of a measurement snag: rag-cli's own output buffering

Reproducing the "real rag-cli run, mid-flight, non-empty output" case required 3 attempts. Two real
re-index runs of the 547 KB `BreimanFriedmanOlshenStone1984CART.md` (382 chunks, ~9-10 min against a
warm local `llama-server` embedding model, restored from `/tmp/*_backup.{md,json}` before each run)
showed the tracked `.output` file sitting at 0 bytes for the ENTIRE run, then jumping to the full
457-byte completed log in one write at process exit. Source read confirmed why:
`src/rag/indexer.py:122` (`_embed_store_batches`, in the separate rag-cli repo) does
`print(f"Indexed {chunks_done}/{total} chunks{suffix}")` with no `flush=True` and no stdout
reconfiguration — default Python block-buffering on a non-tty stream holds every progress line
until the process exits. Prefixing the third attempt with `PYTHONUNBUFFERED=1` produced genuine
incremental writes (175 bytes / 3 of 12 progress lines while ~6-7 minutes from completion),
confirming the task WAS actually running (not just paused) when the 0-byte predicate would have
already reported it finished.

## A second measurement snag: self-referential confound when checking a session from within itself

A dedicated Python probe script, run via `run_in_background=true` against the SAME CC session it
was measuring, got stuck for 14 minutes: the script's own tracked wrapper `.output` file IS an open
handle in that session's tasks dir for as long as the script runs, so the handle-based predicate
could never read `False` for that session while the observer was itself alive — self-confounding
the very measurement. Real production impact: none — the menubar runs as an independent process
outside every CC session it monitors, so it never observes its own check. Mitigation used for
further measurement: short, individually-fast checks (each completes before CC's own
auto-backgrounding heuristic can wrap it) driven from an external shell `until`-loop, rather than
one long-lived Python observer process; for a "handle is now closed" claim specifically, `lsof`
scoped to the single target file rather than the whole session directory eliminates the self-entry
noise entirely.

## Design landed: batched lsof scan + existing TTL-cache pattern, not per-session calls

`lsof +D <tasks_dir>` on this machine costs ~95-110 ms per call — but a SINGLE `lsof +D
/tmp/claude-<uid> -Fn` scan over the entire tasks-base directory (all sessions at once, `-Fn` for
reliable name-field parsing) costs the same ~95-110 ms regardless of how many session dirs exist
underneath (measured against 20+ historical session dirs on this machine: 106.2 ms). This turns an
O(N sessions) per-tick cost into O(1) per refresh window. Implementation follows the
`_refresh_cc_proc_cache` TTL-cache shape already in `proc_cache.py`: a new `_refresh_bg_task_cache`
gated by the SAME `_PROC_REFRESH_INTERVAL` (10s, the module's existing "expensive ps/lsof" budget
class), populating a global `_bg_task_open_paths` set; `_has_active_bg` itself does a pure
string-prefix check against that snapshot — no subprocess call on the per-session query path.
Measured cache-hit cost for 20 sessions: 0.015 ms total. Fail-open preserved: an `lsof` error leaves
the previous snapshot in place rather than resetting to empty or escalating to "always busy".

## Verification reached

Entry-point level: `src.menubar.discover.list_alive_sessions()` (the real per-tick orchestrator
call) invoked directly under the project venv (real `rumps`/AppKit resolved), while a real
`rag-cli index` background task ran in this repo's own worktree session — `has_bg=True` for that
session, `False` for 4 other live sessions on the machine, one of which (`wise2627`) had zero
`*.output` files ever written (clean real-world negative case) and one of which (`monitor-cc` main)
carried the stale-0-byte-file real-world positive case described above. NOT reached: the panel
badge rendering that consumes `has_bg` — needs a running menubar app instance and a human visual
check.

## Deferred to a later session

Using this predicate in `focus_controller.py`'s auto-abort check (today: the orchestrator's
`sleep 600` timer is killed as soon as all workers of a project go idle, regardless of whether a
worker still has a background task running) — the condition the 2026-07-27 entry originally scoped
this investigation around. Not touched this session; `focus_controller.py` untouched.
