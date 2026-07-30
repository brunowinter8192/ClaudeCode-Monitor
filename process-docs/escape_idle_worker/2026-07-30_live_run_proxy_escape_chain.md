# 2026-07-30 — Live run of the proxy-triggered Escape chain

## Setup

Worker `esc-live2` was dispatched with a pure behavior task, no code changes: delete + re-index
`GuKellyXiu2020EmpiricalAssetPricingMachineLearning.md` (216 KB) from the `trading-reference` collection
as a plain FOREGROUND call, then immediately start unrelated work (read `src/menubar/` modules and write a
structural summary), with an explicit instruction not to poll and a note that being interrupted was the
expected outcome.

## Escape fired, once, on the real signal

`src/logs/bg_escape_events.jsonl`, the only event in the test window:

```json
{"ts":"2026-07-30T16:27:29.064279+00:00Z","event":"fired","worker_context":"worker:esc-live2",
 "task_id":"b3wlvypku","tmux_session":"worker-monitor-cc-esc-live2","send_result":true}
```

Nothing before it. The worker verified backups, ran the delete, copied the `.md` back, and issued the
index call — all without a fire. Only the actual backgrounding triggered. That is the distinction the
previous filesystem-handle trigger could not make: it fired on the worker's very first call.

Session name derivation held for a hyphenated worker name: `PROXY_LOG_ID=worker_25c51a2e_esc-live2_…`
plus `PROXY_PROJECT_PATH=/Users/…/monitor-cc` → `worker-monitor-cc-esc-live2`.

## The worker stopped — and then stalled for the wrong reason

The worker's own account after the interruption:

> Re-index was auto-backgrounded immediately after the foreground call returned (task ID `b3wlvypku`) …
> I was interrupted right at the point of pivoting to Step 2 — before opening any of
> `src/menubar/discover.py`, `proc_cache.py`, `focus_controller.py`, or `bg_timer.py`. No files were read
> … Waiting for the orchestrator's next instruction.

Stopping was correct. Waiting for an instruction was not: CC records the Escape in the conversation as a
block containing exactly `[Request interrupted by user]`, and the worker reads that as a human having
stopped it. Visible in the pane as the 3-block shape: injected launch-ack replacement (green) / marker /
injected wake-up replacement (green).

That marker is what the same-day `strip_interrupt_marker.py` pass removes. Corpus scan behind it: 1791
occurrences across 4 dual-log files, every one `role='user'`, `type='text'`, text exactly the marker,
never embedded in longer text.

## Timer was aborted anyway — the gate was missing at the time

The `has_bg` abort gate had been rolled back earlier the same day, so with the worker idle the menubar
killed the orchestrator's timer:

```
18:28:43.975 abort_check project=monitor-cc bg_pids=[48575]
  workers=[esc-live2:idle:has_bg=True:sig_age=207.3] all_idle=True since_idle=5.9 decision=ABORT
18:28:43.976 abort_action pids=[48575] killed=1 errors=0
```

`idle:has_bg=True` while the re-index was still running — exactly the sequence that makes the orchestrator
wake, prod the worker, and set off polling. This observation is what prompted reinstating the gate.

## State at the end of the run

- Escape trigger: proxy-side, launch-ack driven — verified live
- interrupt-marker strip: merged, verified against fixtures only (143/143 + 28/28), NOT yet live
- `has_bg` abort gate: reinstated, bundle rebuilt, NOT yet re-run live

The remaining live verification of the last two is one scenario, not two: the same worker + re-index run
exercises both.
