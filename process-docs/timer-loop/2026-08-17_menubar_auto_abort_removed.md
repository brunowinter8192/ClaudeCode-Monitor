# Menubar Auto-Abort Removed — Closing the Push-Mechanism Chapter

Final milestone of the `worker-cli wait` pull migration (the M2 hook-family conversion and M3
proxy-side `pending_bg_state.py` removal both live in this same area; the hook-family side of
the migration itself is `process-docs/tool_use_safety/` — cross-referenced, not duplicated
here). With the orchestrator's background command now `worker-cli wait` (iterative-dev
plugin — self-terminating: blocks in-process until all workers of the project go stably idle,
or `--timeout`; its own exit IS the wake-up), the menubar's AUTO-abort push mechanism — kill
the timer once all workers go idle, so the orchestrator wakes early — became actively wrong: it
would fight the self-terminating design rather than complement it. Removed entirely.

**Hard requirement preserved, unaffected by the removal:** the menubar still shows the running
wake-up process per project (badge + countdown) and still allows MANUAL abort via the panel
button — both live in `bg_timer.py`, never routed through the removed auto-abort logic.

## Changes

**`focus_controller.py`** — 114 LOC → 43 LOC. Removed the entire auto-abort block from `tick()`
(`_all_workers_idle_since_ts`, the `all_idle`/`will_abort`/5s-dwell computation, the
`abort_check` log line, the `_abort_bg_sleep_timers` call), module-level `_abort_log_write` and
`_has_recent_send_signal`, and the now-dead `_abort_bg_sleep_timers`/`_read_orchestrator_signals`/
`ORCHESTRATOR_SIGNAL_BUFFER_SECS` imports. Auto-focus logic (working→idle debounce, `_focus_session`)
kept byte-for-byte. `tick()`'s `bg_by_project` parameter dropped from the signature (unused once
auto-abort was gone) — `app.py`'s one call site updated to match (`self.focus.tick(sessions, now)`).

**`proc_cache.py`** — 207 LOC → 184 LOC. Removed `_read_orchestrator_signals`,
`_orchestrator_signal_cache`, `_orchestrator_signal_last_read`, and the exported
`ORCHESTRATOR_SIGNAL_BUFFER_SECS` constant — `focus_controller.py`'s auto-abort was their sole
reader. `paths.py:ORCHESTRATOR_SIGNALS_FILE` and the file itself are left UNTOUCHED: `worker-cli
send` (iterative-dev plugin, a separate repo, out of this milestone's scope) still writes to it
before every tmux send-keys. The file is now an orphaned write-only artifact from the menubar's
side — a future cross-repo cleanup could stop that write, but it costs nothing today since
nothing reads it anymore.

**`bg_timer.py`** — 138 LOC → 187 LOC. `_scan_bg_sleep_timers` extended (not replaced) to detect
TWO shapes in one `ps` scan: the canonical `worker-cli wait` process (new — matched via
`_worker_cli_wait_index`: any args token whose basename is `worker-cli` immediately followed by
`wait`, catching both `worker-cli wait ...` and `bash <path>/worker-cli wait ...`; remaining
time = parsed `--timeout N`/`--timeout=N` or the `_WORKER_CLI_WAIT_DEFAULT_TIMEOUT=3300` default,
minus `etime`) and the legacy `sleep N && echo done` pattern (kept — a timer armed before the
migration may still be in flight; dropping it would blind the panel to those with no compelling
reason). Both branches now share one ancestry-walk helper, `_resolve_ancestor_cwd` (factored out
of the pre-existing sleep-branch logic, walks up to 5 levels to find a CC process in
`_cc_proc_cache`) — the two call sites start at slightly different points (one hop apart) because
the two process shapes differ by one hop, but the helper's cache-membership-checked-before-advancing
loop makes both starting points converge correctly regardless. `_abort_bg_sleep_timers` needed
ZERO logic changes — it was already a generic SIGTERM-by-pid + global 0-byte-task-file sweep, never
inspecting what a pid actually was.

**`discover.py`** — comment-only fix. `SessionInfo.tmux_session_name`'s docstring cited
`app.py:_has_recent_send_signal` (now removed) as its consumer; updated to note the field's
original consumer is gone but the field itself stays — still the canonical worker-tmux-session
identifier for any future use.

## Verification

**Real live-spawn probe, three separate runs** (not synthetic `ps` fixtures — a genuine
`worker-cli wait <project> --timeout N` spawned from this worktree, kept as a direct child of
this session's own process tree so its ancestry genuinely resolves through a real `claude.exe`
pid, exactly the shape a CC-launched background process has):

1. **Detection + attribution + timing:** spawned `worker-cli wait /tmp/menubar-probe-... --timeout
   60`; `_scan_bg_sleep_timers` against real `ps -A` output correctly found it, attributed it to
   the mapped project (via the real `_cc_proc_cache` built by a real `_refresh_cc_proc_cache`
   call), and computed `min_remaining=57` (60s timeout, ~2-3s elapsed at scan time) — also
   incidentally found 2 OTHER genuine `worker-cli wait` processes already running on the machine
   from unrelated live orchestrator sessions, correctly bucketed under `'unknown'` since their
   cwd wasn't in the test's attribution map (proves the 'unknown' fallback still works and
   proves detection generalizes beyond the one process I controlled).
2. **Manual abort kills the real process:** spawned another `worker-cli wait`, confirmed alive via
   `ps`, called `_abort_bg_sleep_timers([pid])` directly — process confirmed gone via `ps` after,
   `menubar.log`'s `[abort]` line confirmed written (`killed=1 errors=0`).
3. **Full pipeline re-run after the doc/comment editing pass** (regression check that nothing broke
   during cleanup): spawn → detect (`min_remaining=42`, correct pid) → abort → confirmed killed,
   same result as run 1+2 combined, run last as the final gate before commit.

`--timeout`/`--timeout=` parsing and the `_worker_cli_wait_index` basename-match verified via a
standalone unit table (7 argv shapes: bash-prefixed with/without args, bare form, both `--timeout`
syntaxes, and 2 true-negative cases — a bare `sleep 300` and a same-named-`wait` non-worker-cli
script) — all resolved correctly.

Full `src/menubar` package import (`from src.menubar import app, bg_timer, focus_controller,
proc_cache, discover`) verified clean after every edit, including the final doc-comment pass.

**NOT verified from this worktree — explicitly out of reach:** the live NSPanel visual appearance
(badge text, countdown update, abort-button click) — requires a running GUI menubar instance
(py2app rebuild + human look). Per the task's own verification plan, this is the user's final
gate after merge. The task's own hard requirement (panel keeps showing the process + manual abort
keeps working) is verified at the DATA level (the exact dict/PID list the panel consumes is
correct, proven above) but not at the RENDERED level.
