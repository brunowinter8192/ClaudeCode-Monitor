# Background-task detection probe — real rag-cli index run + synthetic writer + cost bench

Run: 2026-07-30, this machine. Verifies `src/menubar/proc_cache.py::_has_active_bg` (handle-based)
against the old 0-byte-file predicate it replaces.

## Required comparison table

| case | old 0-byte predicate | new handle predicate |
|---|---|---|
| real `rag-cli index` run, mid-flight, output file already non-empty (175 bytes, 3/12 progress lines written, task still running — completion arrived ~9 min later) | **False (wrong)** | **True** |
| same run, after completion (457 bytes, target file's own handle confirmed closed via `lsof <file>`) | False | False |
| session with no background task at all (`wise2627` main session — 0 `*.output` files ever written in its tasks dir) | False | False |
| synthetic writing loop, >0 bytes, still running (18 bytes after 3s, real subprocess holding the fd open) | **False (wrong)** | **True** |

Bonus real-world finding (not required by the table, found while sourcing the control case): the
`monitor-cc` main CC session's tasks dir carries a stale 0-byte `*.output` file left over from a
prior no-output task. Old predicate: **True** (falsely "busy", forever, until someone manually
deletes the file). New predicate: **False** (correct — no process holds it open). This is the
mirror-image failure mode of the required table's rows: old is 0-byte-file-existence, which is
wrong in BOTH directions (false-negative while a real writer is active with `size>0`; false-positive
forever after a no-output task leaves a stale empty file behind).

## Methodology note — real rag-cli run required two corrections before it reproduced the target scenario

1. **Self-referential confound (first 2 attempts).** Running the measurement tool itself as a
   backgrounded/auto-backgrounded process *inside the same CC session* being measured makes the
   session permanently show `has_bg=True` — the tool's own tracked wrapper output file IS an open
   handle in that session's tasks dir for as long as the tool runs. A dedicated Python probe script
   run via `run_in_background=true` (or auto-backgrounded by CC because it ran >~60s) got stuck for
   14 minutes waiting for `new=False`, which could never happen while it was itself the open handle.
   Fix: issue short, individually-fast checks (each completes in well under CC's auto-background
   threshold) rather than one long-lived observer process. This is a probe-methodology artifact only
   — the real menubar process lives outside every CC session it monitors and never hits this.
2. **`rag-cli`'s progress printer is fully block-buffered (2 attempts confirmed this empirically,
   then confirmed via source read).** `src/rag/indexer.py:122` (`_embed_store_batches`) does
   `print(f"Indexed {chunks_done}/{total} chunks{suffix}")` with no `flush=True`, and no module
   reconfigures stdout to line-buffering. Two full real `rag-cli index` runs of the 547 KB
   `BreimanFriedmanOlshenStone1984CART.md` document (382 chunks, ~9-10 min end-to-end against a warm
   local `llama-server` embedding model) showed the tracked `.output` file sitting at 0 bytes for
   the entire run, jumping to the full 457-byte completed log in one flush at process exit — the
   real-world case this milestone assumes ("prints incremental progress, writes continuously") does
   NOT hold for this document/build without forcing unbuffered output. Fix: prefixed the third
   attempt with `PYTHONUNBUFFERED=1`, which produced genuine incremental writes (confirmed: file at
   175 bytes / 3 of 12 progress lines while the indexing process was still ~6-7 minutes from
   completion) — this is the run reported in the table above.

## Per-tick cost (batched `lsof` scan, TTL-cached)

- Refresh tick (1 global `lsof +D /tmp/claude-<uid> -Fn` scan, TTL expired): **106.2 ms**
  (covers every session's tasks dir at once — this machine had 20+ historical session dirs under
  `_TASKS_BASE` at measurement time; cost does not scale with session count, confirmed against the
  issue's own ~100ms single-directory `lsof` measurement).
- Cache-hit tick (20 synthetic sessions, `_has_active_bg` string-prefix match only, no subprocess
  call): **0.015 ms** total for all 20.
- TTL: 10s (`_PROC_REFRESH_INTERVAL`, shared with `_refresh_cc_proc_cache` — same "expensive
  ps/lsof" budget class). Net effect: the ~106ms cost is paid once per 10s window regardless of how
  many live sessions the menubar is tracking, not once per session per 1.5s tick. A naive
  per-session-per-tick design with N=5 concurrent sessions would cost ~500ms every 1.5s tick;
  the batched+cached design costs ~106ms every ~7 ticks (10s / 1.5s) plus a negligible per-tick
  lookup — a ~500x reduction in steady-state lsof-call volume.

## Restoration verification (`trading-reference` collection)

- `rag-cli delete --collection trading-reference --document BreimanFriedmanOlshenStone1984CART.md`
  reported `Deleted 382 chunks` on every one of the 4 delete/reindex cycles run during this probe.
- Final `.md` (546667 bytes) and regenerated `.json` sidecar (740179 bytes) are byte-identical to
  the pre-test backups at `/tmp/BreimanFriedmanOlshenStone1984CART_backup.{md,json}` (`diff -q`
  reported no differences).
- `rag-cli progress trading-reference` reports `BreimanFriedmanOlshenStone1984CART.md 382 / 382
  100.0% done`.
- `rag-cli search "classification and regression trees" trading-reference --document
  BreimanFriedmanOlshenStone1984CART.md` returns 12 ranked hits (top score 0.999) from the restored
  document.

## Test suite (regression guards)

`dev/hook_smoke/test_bg_task_detection.py` — 6/6 passing:

- 3 pure-function regression guards (monkeypatched `_bg_task_open_paths` snapshot): open-path match
  → True; no match → False; session-id prefix-collision boundary (`sess1` vs `sess12`) → no
  false-positive.
- 1 integration case: real subprocess (`bash` loop) holds a real file open under a scratch tasks
  dir; real `lsof` scan (`_refresh_bg_task_cache`, TTL bypassed) detects it while open, and its
  absence after the writer's process group is killed.
- 1 fail-open case: `subprocess.run` raising leaves the prior `_bg_task_open_paths` snapshot in
  place and `_has_active_bg` still returns a plain `bool`, no exception escapes.
- 1 TTL-gate case: a second `_refresh_bg_task_cache` call inside `_PROC_REFRESH_INTERVAL` does not
  re-invoke `lsof` (call-count assertion on a monkeypatched `subprocess.run`).

## Entry-point verification

`src.menubar.discover.list_alive_sessions()` — the real orchestrator function called every 1.5s
tick from `app.py:CCMenuBarApp._tick` — was invoked directly (via `./venv/bin/python -c`, project
venv, real `rumps`/AppKit imports resolved) while the real `rag-cli index` background task was
running in this very worktree's CC session. Result: the `bg-detect` worktree session's `SessionInfo`
showed `has_bg=True`, `status=working`; all 4 other live sessions on this machine showed
`has_bg=False`. This is entry-point-level, not just unit-level — routing, caching, and the real
`lsof`/`ps` calls all executed for real. NOT verified at this level: the panel-render badge itself
(`panel.py`/`panel_manager.py` consuming `has_bg` to draw the UI) — that needs a running menubar
app instance and a human visual check, out of scope for this milestone (predicate only).
