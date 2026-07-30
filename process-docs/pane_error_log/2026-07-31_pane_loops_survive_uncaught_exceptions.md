# 2026-07-31 — Pane loops survive uncaught exceptions (window `1:proxy` vanishing)

## Problem

User-reported symptom: tmux window `1:proxy` disappears from the status bar; Ctrl+R
(`restart_panes()` in `src/tmux_launcher.py`) brings it back. tmux destroys a window when its
last pane's process exits (`remain-on-exit` off globally) — window 1 holds exactly one pane, so
the disappearance means that pane's Python process died. `src/proxy_display/pane.py:run_proxy_loop`
had no exception guard around its `while True:` body — any uncaught exception silently kills the
process, leaving no log file, no macOS crash report, no tmux pane-died record. The proxy crash's
own root cause was ruled un-diagnosable from available evidence this session (no jetsam entries,
no `kill-pane`/`kill-window` call sites in `src/`, RSS flat across session ages, and 40 replayed
`_refresh_proxy_data`/`_build_proxy_output` calls against this repo's real logs reproduced nothing)
— this work does not attempt to fix that unknown crash, only to stop it from taking the pane
process down and to capture it if/when it recurs.

Of the 8 pane event loops, only `src/workers/worker_pane.py::run_workers_loop` had a guard: an
exception handler inside the `while True:`, writing a timestamped traceback to
`/tmp/monitor_cc_error.log` via an inline `open(...)` call, then continuing. The other 7
(`proxy_display/pane.py`, `proxy_display/worker_proxy_pane.py`, `panes/token_pane.py`,
`panes/warnings_pane.py`, `gpu_pane/pane.py`, `news_pane/pane.py`, `core/monitor.py`) had none.

## Fix

**Shared sink, not copy-paste.** New `src/pane_error_log.py::log_pane_error(pane_name)` —
root-level module (same shallow-import-path rationale as `constants.py`/`utils.py`: imported by
every pane package via `from ..pane_error_log import log_pane_error`). Writes
`\n[<iso timestamp>] [<pane_name>] error:\n<traceback>` to `/tmp/monitor_cc_error.log`
(same path the pre-existing worker_pane.py guard already used — kept for continuity, no reason to
move it). All 8 loops (`workers`, `proxy`, `worker_proxy`, `tokens`, `warnings`, `gpu`, `news`,
`main`) now share this one function, so a future 9th pane inherits the same sink for free.

**Per-loop wiring:** each `while True:` body now wraps in its own exception handler around
`log_pane_error('<pane>')` followed by `wait_for_input(INPUT_POLL_INTERVAL)` (or
`time.sleep(...)` for `core.monitor.run_main_loop`, which doesn't use `wait_for_input`), nested
inside the existing outer `try/finally: disable_mouse(); restore_terminal()`. The handler is
scoped to `Exception` specifically — `KeyboardInterrupt`/`SystemExit` both derive from
`BaseException`, not `Exception`, so they fall outside that scope and still propagate out of the
loop, still hitting the outer `finally:`.

**Size-capped, not left to grow unbounded.** `PANE_ERROR_LOG_MAX_BYTES = 2_000_000`,
`PANE_ERROR_LOG_KEEP_BYTES = 500_000` (both in `constants.py`, alongside `PANE_ERROR_LOG_PATH`).
`_cap_log_size()` checks the file size before every write and, once over the cap, truncates to
its last `KEEP_BYTES` (seek from EOF, no line/timestamp parsing). Chosen over
`menubar_log.py`'s 7-day-retention line-prune (the other exception-safe-sink precedent in this
repo) because that shape reads the WHOLE file and re-parses every line's timestamp on every
write — fine for a menubar tick, too expensive for a sink that can be hit repeatedly in a tight
exception-retry loop (an unguarded pane crashing every tick would have re-parsed a multi-MB file
on every single iteration under the old shape). A pure byte-offset check + tail-copy bounds the
per-write cost to a fixed read/write regardless of how the file got large.

**Worker_pane.py's pre-existing guard had its own bug, fixed as part of this milestone
(deliverable 3's audit target):** the inline `open('/tmp/monitor_cc_error.log', 'a')` +
`traceback.print_exc(file=_f)` sat directly inside the exception handler with nothing wrapping
it — a failing write (disk full, permissions, concurrent truncation from another pane process now
sharing the same file) would raise a NEW exception from inside that handler, which nothing
catches, killing the loop from inside its own crash-recovery path. Delegating to
`log_pane_error()` (whose body is itself wrapped end to end, swallowing any failure from
`open`/`write`/`_cap_log_size`) closes this for all 8 loops uniformly, not just worker_pane.py.

## Verification

`dev/pane_error_log/p1_pane_loop_survives_exception_probe.py`, 48/48 checks passed. Cannot use a
live tmux session (no pane process exists to kill and observe); instead each `run_*_loop()` is
invoked directly (package-qualified via `importlib.import_module` — these modules need `..constants`
double-dot relative imports resolved, which rules out the path-inserted bare-top-level-module
import style some other dev probes use for self-contained packages like `proxy`) with
`read_keypress` patched to raise a distinctive marker exception on its first call only, and the
tick function (`wait_for_input`, or `time.sleep` for `core.monitor`) patched to raise a
`BaseException` stand-in after 3 calls — bounding runtime and doubling as a second, independent
check that a `BaseException` (same MRO relationship as `KeyboardInterrupt`) is never swallowed.
For every one of the 8 loops: the injected exception is caught, logged with the correct pane
identifier and a full traceback, the loop survives past the crash iteration, and
`disable_mouse()`/`restore_terminal()` still run on exit. Separately verified with the REAL
`KeyboardInterrupt`/`SystemExit` classes on one representative loop (proxy pane): both propagate
out uncaught, `finally:` cleanup still runs. `log_pane_error` itself verified against an
unwritable path (nonexistent parent dir) and a forced `_cap_log_size` seek-underflow (`OSError`
from seeking past a 5-byte file's start) — neither raises out of the function. Sink-capping
verified directly: an oversized file truncates below its pre-cap size and keeps the tail, not
the head.

Not verified this session: the actual unknown proxy crash recurring in production and being
captured by this guard — that requires the crash to happen again on the live machine, out of
scope for worktree-only verification (and explicitly not this milestone's goal — the point was to
stop it from killing the pane, not to reproduce or diagnose it).
