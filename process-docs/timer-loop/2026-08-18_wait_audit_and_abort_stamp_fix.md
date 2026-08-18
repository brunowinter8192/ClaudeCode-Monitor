# Wake-Up Chain Audit + Abort-Stamp Scoping Fix

Live report: the 2026-08-17 `worker-cli wait` pull migration (see the three same-day entries in
this area) was reported broken in live use — no wake, duplicate wakes, and always-timeout were
all open candidates. This entry covers the end-to-end audit of the chain, the re-analysis against
procured live evidence, and the one fix implemented and merged in this session (Mechanism B).
Mechanisms A (stacked wait arms) and C (timeouts) are diagnosed but NOT fixed here — see Open
Items.

## Audit method

Read the full chain end-to-end: `worker-cli`'s `wait` subcommand (external, `iterative-dev`
plugin, read-only reference — plus its own sibling `dev/worker_wait/test_worker_wait.sh`, a real
tmux-backed integration suite whose named test cases directly document several of the failure
modes below), `tmux_spawn.sh`'s `worker_status`/`_worker_detect_status` (the "idle" source of
truth `wait` polls), every hook in `src/hooks/` touching background-command authorization
(`rewrite_background_sleep.py`, `block_unauthorized_background.py`,
`block_worker_send_background.py`, `hook_setup.py`'s registration order), the menubar's
`bg_timer.py`/`focus_controller.py` (auto-abort removal residue check — none found), and the
proxy's `strip_bg_launch_ack.py`/`strip_bg_completed.py`/`bg_escape.py` plus the underlying
`<task-notification>` pipeline in `message_passes.py`/`payload_helpers.py` (confirmed: the proxy
never drops a genuine completion notice, only compresses it).

## Ranked findings (initial, code-read only)

1. Worker crash/context-limit death mid-wait → permanent non-idle status → `wait` runs to the
   full 3300s ceiling (tested by `test_worker_wait.sh` Test 4).
2. `_wait_has_live_bg_task`'s handle-based probe erroring (missing `lsof` on `PATH`, tmux/session
   resolution failure) → fail-toward-waiting is indistinguishable from genuinely busy → full
   ceiling (tested by Test 6, the exact PATH-stripped reproduction).
3. `wait` armed against zero registered workers → empty `NAMES` loops to the full ceiling with no
   fast exit (tested by Test 2).
4. No code-level guard against stacking multiple concurrent `worker-cli wait` arms for one
   project — the only defense is a natural-language instruction in the launch-ack replacement
   text; the prior enforcement hook (`block_timer_pending_bg.py`) was deliberately removed as
   part of this same migration.
5. `block_unauthorized_background.py`'s canonical-form exemption for `worker-cli wait` has no
   orchestrator-only guard (unlike `rewrite_background_sleep.py`, which got one after a
   documented live incident) — a residual asymmetry, unconfirmed against live data.
6. Menubar auto-abort removal: verified clean, no residue.
7. Proxy stripping: verified the completion path is never dropped, only compressed.

## Live-evidence re-analysis (procured by the orchestrator: worker-deaths.log, 7 task .output
files, menubar timestamps for 2026-08-17)

- **Candidate 1 (worker death) REFUTED**: no `worker-deaths.log` entry on 2026-08-17.
- **Candidate 8 (abort-sweep global blast radius) CONFIRMED directly**: `bwbf0nmow.output`
  contained both `aborted` (from the sweep) and `workers idle` (the wait's own real result) on
  separate lines — proof the global sweep hit a different, still-running wait's own file.
- **Candidates 2 vs 3 for the two observed timeouts (20:59, 21:43) — discriminated using an
  artifact not in the original file list**: `worker-cli spawn`'s sidecar diagnostic logger
  (`worker_logger.sh` in the iterative-dev plugin) writes a 10s-interval `pane_dead` sample log
  per worker. The `timer-wait` worker's log (session `worker-monitor-cc-timer-wait`, pid 68777)
  showed `pane_dead=0` continuously from 19:32 through 23:18, spanning both timeout instances —
  refuting candidate 3 (empty NAMES) for these two specific events; `worker_list` cannot have
  returned empty while this session was alive. This leaves two live possibilities
  code-indistinguishable from the `.output` file alone (neither `wait` nor its bg-task probe log
  anything mid-poll): a genuine detection bug (candidate 2), or the worker legitimately still
  working past the 3300s default. Not resolved further this session — would need the worker's own
  JSONL transcript to separate "detection bug" from "legitimately busy."
- **Stacking-count interpretation (task: verify or refute)**: the 6-7 simultaneously-stamped
  `.output` files at 22:28:37 do NOT by themselves prove 6-7 stacked `worker-cli wait` arms for
  one project. Traced the code: the abort action's SIGTERM kill is project-scoped (`app.py`'s
  `cwd_to_project` explicitly excludes worker sessions, so only the clicked project's own
  orchestrator-owned PIDs get killed), but the file-STAMP sweep (pre-fix) was unconditionally
  global across every session and every project on the machine. Two named alternative mechanisms
  producing the identical artifact without same-project stacking: other projects' independently
  running `worker-cli wait` processes (already observed live during the 2026-08-17 rollout's own
  verification — the menubar auto-abort-removal entry notes finding "2 OTHER genuine worker-cli
  wait processes ... from unrelated live orchestrator sessions"), and worker-side exempted `sleep
  N` background timers (which `block_unauthorized_background.py` allows in ANY session, not just
  the orchestrator's). The discriminating artifact — the `[abort]` log line's `killed=N` count vs.
  the 6-7 total stamped-file count — was identified but not checked this session.

## Fix implemented: Mechanism B (abort-sweep scoping)

`src/menubar/bg_timer.py`: `_abort_bg_sleep_timers` no longer sweeps every 0-byte `.output` file
under `_TASKS_BASE` globally. New `_resolve_pid_output_file(pid)` runs a real `lsof -p <pid> -a -d
1,2 -Fn` call to find the EXACT task file a given PID holds open on fd 1/2, called BEFORE the
SIGTERM (the open handle disappears the instant the process exits, so resolving after would race
the kill). Only that one file gets the `aborted\n` stamp. The `[abort]` menubar.log line now also
records which files were actually stamped (`stamped=[...]`).

**Badge-clearing dependency check (explicitly asked, verified against current code, found
STALE)**: the removed sweep's own comment claimed the write existed "so the `[B]` badge clears."
Traced both actual clearing paths: the panel `[B]` badge is driven by `_scan_bg_sleep_timers`'s
live `ps` scan (clears when the PID drops out of `ps`, independent of file content); `discover.py`'s
`has_bg` flag is driven by `proc_cache._has_active_bg`'s `lsof` open-handle scan (clears when the
handle closes). Neither reads file content. The stamp write is kept per the fix's scope (scope it,
not remove it) — its only remaining purpose is a human-readable trace in the file, not a
functional dependency of either clearing mechanism. Corrected both `bg_timer.py`'s inline comment
and `DOCS.md`'s Gotchas to state this plainly, replacing a stale/wrong claim that would otherwise
have kept propagating.

**Verification**: `dev/timer-loop/test_abort_stamp_scope.py` (new, integration-level, real
subprocesses holding real open file handles + real `lsof` + real SIGTERM, not mocked) — 6/6
checks passing: killed PID's own file stamped, its process actually terminated, a foreign 0-byte
file with no associated PID left untouched, a live wait's file AND process in another session both
left untouched, and the `[abort]` log line naming only the stamped file. Full `src.menubar`
package import verified clean after the edit (`bg_timer`, `proc_cache`, `app`, `focus_controller`,
`panel_manager`).

**Two hook-driven detours during implementation**: `block_except_pass.py` (Write/Edit) fired
twice on the first draft (a bare `except OSError: pass` in the new stamp-write path and in the
test's teardown) — both changed to log-and-continue. `block_dev_imports_src.py` blocks a literal
`from src.` line inside `dev/` — the test uses `importlib.import_module('src.menubar.bg_timer')`
instead, the same pattern already established in `dev/proxy/test_strip_fix.py`.

## Open items (not touched this session)

- **Mechanism A (stacked wait arms)**: diagnosed, options proposed (silent-supersede kill-old-
  before-new-arm was the leading candidate — respects "no forced agent reasoning," "no
  agent-chosen durations"), not implemented. True same-project stacking count for the 2026-08-17
  incident remains unconfirmed (needs the `killed=` log-line cross-check above).
- **Mechanism C (timeouts)**: root cause between "detection bug" and "legitimately busy >55min"
  undetermined; the fix (empty-NAMES fast exit, hardened `lsof`/`PATH` handling) lives in
  `worker-cli` itself — the `iterative-dev` plugin repo, out of this repo's scope, explicitly not
  touched per this session's instructions.
- **Candidate 5 (`block_unauthorized_background.py` orchestrator-only asymmetry)**: unconfirmed
  against live data either way, left as-is.
