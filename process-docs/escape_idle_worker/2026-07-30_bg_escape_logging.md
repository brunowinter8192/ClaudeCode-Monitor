# 2026-07-30 — bg_escape.py gained a trace log; it had none

Follow-up in this area: `src/proxy/bg_escape.py` (the launch-ack-triggered Escape mechanism)
shipped with zero logging — a fire or a skip left no trace, so a live check could only guess
whether the mechanism did anything. This mattered concretely: the rolled-back `has_bg`-based
predecessor was diagnosed via its own log (`menubar.log`), and that log is exactly what exposed
its failure the same day it shipped. Without an equivalent trace, this replacement mechanism would
have been harder to debug than the one it replaced.

## Sink chosen — JSONL file, not stderr

`src/claude_proxy_start.sh` runs production `mitmdump` with `2>/dev/null` (line ~302) — stderr is
discarded entirely in the live proxy. A comment in the same script's janitor
(`# Remove legacy proxy_errors_*.log files (mitmdump uses 2>/dev/null since 2026-05-28)`) confirms
this was a deliberate, already-made decision: stderr-based proxy diagnostics were replaced by
structured JSONL files under `src/logs/` before this session. Following that existing convention
(not inventing a new one): `bg_escape.py` writes `bg_escape_events.jsonl` — same
`MONITOR_CC_ROOT`-scoped, `/tmp`-fallback path resolution and the same flat-top-level-file shape
`addon.py` already uses for `api_errors.jsonl`.

## What gets logged, and the hot-path constraint

One JSONL line per fire (`event="fired"`, `task_id`, `tmux_session`, `send_result`) and per
meaningful skip (`event="skipped"`, `reason` — `main_context`, `already_escaped`, `no_task_id`,
`no_tmux_session`). The logging call sits strictly inside the branch already gated on
`_is_bg_launch_ack(chunk)` matching — a request whose `stripped_msg_removed` carries no
bg-launch-ack chunk at all never reaches a logging call, so the ordinary per-request hot path (the
overwhelming majority of requests, which carry no ack) stays log-free; only requests that already
contain a genuine ack pay the one JSONL write.

## Verification reached (`dev/bg_wakeup_id_line/p2_bg_escape_probe.py`, 29/29 checks, up from 21)

Added Test 5b: a real fire (through `_trigger_bg_escape`, `MONITOR_CC_ROOT` scoped to a
`tempfile.TemporaryDirectory()`) produces exactly one JSONL line with the expected `task_id`,
`tmux_session`, and `send_result=True`; a main-context call with a genuine ack logs
`reason="main_context"` instead of silently no-op'ing; a request with no ack chunk at all creates
no log file. All 21 previously-passing checks (dedup, two-id, both-wordings, main-never-fires,
tmux-session-derivation, real-tmux-roundtrip, failure-isolation) still pass unchanged — this
session added a new consumer of the existing fire/skip decision points, it did not alter them.

## What is still not known

Whether the log is actually readable/tail-able from a live worker proxy process during a real
session was not exercised this session — verification stayed at the level of a real function call
writing to a real temp-scoped file path, not a live mitmdump process's own `MONITOR_CC_ROOT`.
