# dev/pane_error_log/

## Role

Regression coverage for `src/pane_error_log.py` (shared exception-safe sink) and the
per-loop exception guard wrapping all 8 pane `run_*_loop()` functions
(`src/workers/worker_pane.py` + the 7 other modules retrofitted 2026-07-31, in two passes — 6 found
in the initial sweep, `news_pane/log_pane.py` found in a follow-up: it was missed because window 5
has two panes, so this one dying silently leaves pane 5.1 blank rather than killing the whole
tmux window, unlike the single-pane windows that motivated the original sweep). **(2026-09) The
main pane's `run_main_loop` (`src/core/monitor.py`) was removed along with the main pane itself**
— see `process-docs/main_pane/` — dropping the pane-loop count from 9 to 8; `test_main_pane` and
its `mod_main` import were removed from `p1_pane_loop_survives_exception_probe.py` accordingly.
Verifies catch+log+continue end to end without a live tmux session — cannot be tested by killing a
real pane process, so each loop is invoked directly with its I/O primitives monkeypatched. `md/`
holds every run's report.

## Modules

### p1_pane_loop_survives_exception_probe.py (429 LOC)

**Purpose:** For 7 of the 8 pane loops (all but `news_pane/log_pane.py`): injects a marker
exception on the loop's first `read_keypress()` call, forces a bounded exit after 3 ticks via a
`BaseException` stand-in (`_ProbeStop`), and asserts the injected exception was caught + logged
with the correct pane identifier + full traceback, that the loop survived past the crash
iteration, and that `finally: disable_mouse(); restore_terminal()` still ran. For the 8th
(`news_pane/log_pane.py::run_news_log_loop`, pane id `news_log`) — no keyboard/mouse and no
`finally:` (never had one, none invented) — the marker exception is injected via `find_log_file()`
instead, `time.sleep` is the tick counter, and only catch+log+continue is asserted, not cleanup.
Also verifies real `KeyboardInterrupt`/`SystemExit` still propagate (not swallowed by
`except Exception:`), that a failing log write (unwritable path, `_cap_log_size` seek-underflow
on an artificially tiny file) cannot raise out of `log_pane_error`, and that the sink truncates
to its tail once it exceeds the size cap.
**Reads:** Whatever real session/tmux/RAG state exists on the machine (each loop's real
data-refresh/render path runs unmocked past the injected first-call crash — any exception it
raises is caught by the same new guard and logged, harmless to the assertions, which only check
for the specific injected marker).
**Writes:** `md/p1_pane_loop_survives_exception_probe_<timestamp>.md`; redirects
`pane_error_log.PANE_ERROR_LOG_PATH` to `/tmp/_pane_error_log_probe.log` for the run (never
touches the real `/tmp/monitor_cc_error.log`).
**Called by:** run manually — regression guard for `pane_error_log.py` and all 8 pane-loop
guards; re-run after any change to a pane loop's `while True:` shape or to `pane_error_log.py`.
**Calls out:** `src.pane_error_log`, `src.workers.worker_pane`, `src.proxy_display.pane`,
`src.proxy_display.worker_proxy_pane`, `src.panes.token_pane`, `src.panes.warnings_pane`,
`src.gpu_pane.pane`, `src.news_pane.pane`, `src.news_pane.log_pane` — loaded
via `importlib.import_module` (package-qualified; these modules use `from ..constants import ...`
double-dot relative imports, so they cannot be path-inserted as bare top-level modules the way
self-contained packages like `proxy` can).
