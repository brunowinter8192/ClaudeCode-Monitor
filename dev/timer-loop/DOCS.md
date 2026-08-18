# dev/timer-loop/

## Role

Measurement + verification scripts for the (now-removed, Milestone 3) proxy-side
pending-background-task tracking design: what background-task completion/kill notices actually
look like in the recorded corpus (`p1_`, feeding the design — independent of the removed
mechanism, still runs), the proxy-side state mechanism that used to arm/clear a pending tombstone
from them (`p2_`, `src/proxy/pending_bg_state.py` — REMOVED, see `process-docs/timer-loop/`), and
the 2026-08-07 project-scoping fix spanning that writer and its enforcement hook,
`src/hooks/block_timer_pending_bg.py` (`p3_` — hook removed Milestone 2, writer removed Milestone
3; the whole chapter is closed, `p2_`/`p3_` kept only as historical record). `md/` holds every
script's report. `test_abort_stamp_scope.py` is a live regression-guard for the 2026-08-18
menubar-side abort-scoping fix (`src/menubar/bg_timer.py`) — a different mechanism in the same
wake-up chain, not related to the removed pending-state machinery above.

## Modules

### p1_scan_bg_completion_wordings.py (466 LOC)

**Purpose:** Inventories distinct background-task completion/kill notice wordings in the recorded
corpus (`src/logs/dual_log/*_original.jsonl`), split main vs worker session, dedups cumulative
dual-log duplication via a per-session exact-raw-text `seen` set (not a positional delta — robust
to the non-monotonic message-count resets observed in some worker sessions), evaluates the real
`payload_helpers._extract_task_notification_task_id` extraction against each wording.
**Reads:** `src/logs/dual_log/*_original.jsonl` (corpus dir overridable via `sys.argv[1]`).
**Writes:** `md/bg_completion_wordings_<date>.md`.
**Called by:** run manually — measurement only, not a regression guard.
**Calls out:** `src/proxy/strip_sn_notice.py`, `src/proxy/strip_bg_completed.py`,
`src/proxy/payload_helpers.py` (imports the real markers/regexes/extractors).

---

### p3_project_scope_incident_probe.py (243 LOC)

**SUPERSEDED (Milestone 2, 2026-08, hook family rework — updated Milestone 3):**
`src/hooks/block_timer_pending_bg.py` was removed in Milestone 2 (hook-subprocess sections
stopped running); `src/proxy/pending_bg_state.py` itself was removed in Milestone 3 (its own
probe, `p2_pending_bg_state_probe.py`, deleted with it), so this probe's writer-side sections are
ALSO non-runnable now — the whole script is a dead import. Left as-is, historical record only. See
`process-docs/timer-loop/` for the removal.

**Purpose:** Replays the 2026-08-07 ~01:10 cross-project false-block incident verbatim — the
websearch project's main session armed its canonical timer and was blocked by a POSTS-project
pending entry (task `b4z5fzzao`) in the one global `pending_bg_tasks.json`. Drives the REAL
`block_timer_pending_bg.py` hook via `subprocess` with a seeded state file and a real named cwd
directory (`.../Websearch`, `.../Posts`) — not injected strings — so `_current_project_slug()`'s
actual cwd-basename derivation runs end-to-end: foreign-project pending → now ALLOWS (the incident
itself); same-project pending → still BLOCKS; legacy no-project entry → still BLOCKS regardless of
cwd (backward compat); expired same-project entry → ALLOWS (expiry independent of project match).
Also verifies the writer side directly — real `ProxyAddon.request()` stamps the project slug from
`PROXY_PROJECT_PATH`.
**Reads:** Nothing persistent — seeds its own state file per case under a `tempfile.TemporaryDirectory()`-scoped `MONITOR_CC_ROOT`.
**Writes:** `md/p3_project_scope_incident_probe_report.md`.
**Called by:** does not run — historical incident record only (see SUPERSEDED note above; both the
hook-subprocess sections and the writer-side sections are now dead imports).
**Calls out:** `src/hooks/block_timer_pending_bg.py` (removed, path now dead),
`src/proxy/pending_bg_state.py` (removed, path now dead), `src/proxy/addon.py` (`ProxyAddon`,
`_derive_worker_context` — still live).

---

### test_abort_stamp_scope.py (122 LOC)

**Purpose:** Integration regression guard for the 2026-08-18 abort-stamp scoping fix
(`src/menubar/bg_timer.py:_abort_bg_sleep_timers`/`_resolve_pid_output_file`). Spawns two REAL
subprocesses (`sleep 20`) with stdout+stderr redirected straight to fake `.output` files —
mirrors CC's own background-launch fd shape — plus one plain 0-byte file with no associated
process. Calls the REAL `_abort_bg_sleep_timers` with only one of the two PIDs, asserts: (1) the
killed PID's own file gets stamped `aborted\n`; (2) the killed PID's process actually terminates;
(3) the foreign 0-byte file (no associated PID) is untouched; (4) the OTHER live process's file
AND its process are both untouched (still running) — the exact "a live wait's file in another
session" shape from the confirmed 2026-08-17 incident; (5) the `[abort]` menubar.log line lists
only the stamped file, not the untouched ones. `importlib.import_module` used for the
`src.menubar` imports (`block_dev_imports_src.py` forbids a literal `from src.` line in `dev/`).
**Reads:** nothing persistent — spawns its own subprocesses + tempdir.
**Writes:** tempdir under system temp (removed in `finally`); appends to the REAL
`APP_SUPPORT/menubar.log` (same file the live menubar app uses — append-only, no isolation
needed, verified via before/after size diff rather than a fresh file).
**Called by:** run manually — `python3 dev/timer-loop/test_abort_stamp_scope.py`.
**Calls out:** `src.menubar.bg_timer` (`_abort_bg_sleep_timers`, dynamic import),
`src.menubar.paths` (`_APP_SUPPORT`, dynamic import); `subprocess`, `lsof` (via the module under
test), `sleep` (fixture processes).

---

## Gotchas

**p1's corpus is a moving target — counts are a lower bound, not final.** Same caveat as
`dev/bg_wakeup_id_line`'s p1: `src/logs/dual_log/*_original.jsonl` keeps growing from concurrent
live sessions while the scan runs; a rescan can only add deduped occurrences, never remove them.
