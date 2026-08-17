# pending_bg_state.py Removal — Closing the Timer-Loop Chapter

Milestone 3 of the `worker-cli wait` migration (`process-docs/tool_use_safety/` area — the M2
hook-family side of this same migration removed `block_timer_pending_bg.py`, the last reader of
the state this module wrote). With that reader gone, `src/logs/pending_bg_tasks.json` had no
consumer left — `pending_bg_state.py` (the writer — original design and the later
project-scoping fix are both earlier entries in this area) became dead code and is removed.
`bg_escape.py` — the OTHER mechanism on the same launch-ack detection (forces a worker idle via
tmux Escape) — is untouched; it never depended on `pending_bg_state.py`.

## Changes

- Deleted `src/proxy/pending_bg_state.py` (270 LOC).
- `src/proxy/addon.py`: removed the import and the `try/except _update_pending_bg_state(...)`
  call site in `request()`. `bg_escape`'s call site is the only per-concern side-effect call left
  there.
- `src/proxy/strip_bg_launch_ack.py`: one comment fix (no logic change) — the main-context
  sharpened wording (`_BG_LAUNCH_ACK_MSG_MAIN`) no longer cites `pending_bg_state.py` as its
  rationale; it now cites the actual current one (avoiding a stacked/duplicate `worker-cli wait`
  arm, the M2 hook-family side of this migration).

## `dev/timer-loop/p2_pending_bg_state_probe.py` — deleted, one case folded elsewhere first

Different treatment than `p3_project_scope_incident_probe.py` got at M2. p3's still-valid section
stayed independently runnable after M2 (only its hook-subprocess part died — `pending_bg_state.py`
itself still existed then). p2's very first import (`from proxy import pending_bg_state`) crashes
the ENTIRE script the moment the module is gone — a superseded-note alone would have stranded
every one of its 12 test groups, not just the pending_bg_state-specific ones.

11 of 12 groups were 100% pending_bg_state subject matter (arm/clear/prune/failure-isolation/
project-scoping) — zero value once the module is gone, straight deletion. But Test 12
(`test_wording_main_vs_worker`) tested `strip_bg_launch_ack.py`'s `is_main` replacement-wording
split — unrelated to pending_bg_state, and grep confirmed zero other coverage of it anywhere in
`dev/`. Folded that one case into `dev/proxy_dual_log/proxy_176_bg_launch_ack_tests.py` (the live
suite already covering `strip_bg_launch_ack.py`) as `test_wording_main_vs_worker`, adapted to that
file's own convention (`_apply_bg_launch_ack_strip(messages, is_main=...)` on a messages list,
matching its other tests, rather than p2's lower-level direct `_strip_bg_launch_ack(...)` call) —
6 new checks, all passing (suite went from 51 to 57 PASS lines). Then deleted p2 outright.

`p3_project_scope_incident_probe.py`'s SUPERSEDED note (written at M2) is updated: its
"writer-side sections still run" claim is now false too — the whole script is a dead import as of
this milestone. Left in place otherwise, historical record of the resolved 2026-08-07 incident.

`p1_scan_bg_completion_wordings.py` is untouched — it measures the raw corpus independently of
`pending_bg_state.py` (never imported it), still a valid standalone measurement tool.

## Runtime files (not touched here)

`src/logs/` is fully gitignored — `pending_bg_tasks.json` and `pending_bg_state_events.jsonl` are
untracked runtime artifacts, absent from this worktree. Orchestrator deletes the live file(s) in
the main repo at merge time.

## Verification

Baseline (before removal) vs. after, all subprocess/direct-call suites, no regression:

- `dev/proxy/test_strip_fix.py` — 159/159 passed, before and after.
- `dev/proxy_dual_log/proxy_176_bg_launch_ack_tests.py` — 51 PASS lines before, 57 after (the 6
  folded-in checks), 0 FAIL either run.
- `dev/bg_wakeup_id_line/p2_bg_escape_probe.py` — 29/29 passed, before and after (confirms
  `bg_escape.py` is genuinely independent, as expected).
- Post-merge proxy import-smoke check (`src/proxy/DOCS.md` Gotchas — mandatory after any
  `addon.py` edit): `mitmdump -s proxy_addon.py --set flow_detail=0 -q -p 0`, process stayed alive
  2s+ with an empty log (clean import, no startup traceback) before being killed.
- Grep-confirmed: zero remaining `pending_bg_state`/`pending_bg_tasks` references in `src/` or
  `dev/` `.py`/`.md` files outside write-once `process-docs/` entries, `dev/timer-loop/md/` report
  outputs (historical, never retroactively edited), and the two intentional historical-context
  mentions left in `p3_project_scope_incident_probe.py`'s docstring (per its established
  leave-otherwise-untouched treatment) and this suite's own folded-in-case comment.
