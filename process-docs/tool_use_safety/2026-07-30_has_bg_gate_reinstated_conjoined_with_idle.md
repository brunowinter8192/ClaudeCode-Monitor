# 2026-07-30 — has_bg abort gate reinstated: the rollback was an overcorrection

## What happened

Earlier the same day two mechanisms built on `has_bg` (open handle on a `tasks/<id>.output` file) were
rolled back together after a live test disproved the predicate:

1. Escape-on-bg-launch in the menubar — fired on the `has_bg` False→True edge
2. the auto-abort gate — `all_idle` additionally required `not w.has_bg`

The disproof: EVERY foreground Bash call also holds such a handle. So `has_bg` means "some call is
running", not "a task was backgrounded". Mechanism 1 fired on a worker's very first call and killed it
before it did anything.

The rollback applied that disproof to BOTH mechanisms because they read the same field. That was wrong for
the second one.

## Why the gate is sound and the trigger was not

The two use `has_bg` in different positions:

- **Trigger (unsound):** `has_bg` alone, on a rising edge. A worker executing an ordinary foreground call
  satisfies it. Escaping then destroys live work.
- **Gate (sound):** `status == 'idle' AND has_bg`. A foreground call keeps the worker `'working'` — the
  status is derived from CC's hook state, not from the handle. So idle + a live handle means a call
  outlived the turn that started it, which is what backgrounding is.

The conjunction with `idle` removes exactly the false-positive class that killed the trigger.

## The live observation that forced the correction

With the gate removed, worker `esc-live2` was driven through a real auto-backgrounded `rag-cli index` run.
The abort log at 18:28:43:

```
abort_check project=monitor-cc bg_pids=[48575] workers=[esc-live2:idle:has_bg=True:sig_age=207.3]
  all_idle=True since_idle=5.9 decision=ABORT
abort_action pids=[48575] killed=1 errors=0
```

`idle:has_bg=True` — worker waiting, index still running — and the orchestrator's timer was killed anyway
after the 5s dwell. That is precisely the sequence that leads to the orchestrator waking, prodding the
worker, and the worker polling its own background process. The gate would have held it.

## Reinstated

`src/menubar/focus_controller.py`, one term back in the `all_idle` predicate:

```python
w.status == 'idle' and not w.has_bg and not _has_recent_send_signal(w, signals, now)
```

The Escape mechanism stays out of the menubar — it now lives in the proxy, triggered by the launch-ack
replacement (`src/proxy/bg_escape.py`), which is unambiguous. Verified live the same session: one `fired`
event at 16:27:29 for task `b3wlvypku`, worker `esc-live2`, correct tmux session, and no spurious fire on
any of the worker's earlier calls.

## Consequence for the start/end pairing idea

Pairing the proxy's launch-ack and completion messages by task id (start seen, end not yet → task still
running) was the planned "clean" replacement for the gate. With `idle AND has_bg` covering the same case
at the cost of one term and no new data path between proxy and menubar, that pairing is not currently
needed. It stays available if a case turns up where the conjunction is insufficient.

## Method note

The failure here was applying one disproof to two consumers of the same field without checking whether the
disproof survives the surrounding condition. The measurement was right both times; the second inference
from it was not.
