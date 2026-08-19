# Trigger worker-cli janitor on main-session start, 2026-08-19

## Problem

Worker tmux sessions (spawned via `worker-cli spawn`, iterative-dev repo) accumulate: workers
die (context limit) or the registry loses track of them, and their tmux sessions + worktrees +
branches linger for days with nothing to prompt cleanup. `worker-cli janitor` (iterative-dev,
`bin/worker-cli`) implements the sweep itself; it needed a trigger point that fires on its own,
without a human remembering to run it.

## Decision

`src/claude_proxy_start.sh` is the confirmed chokepoint every main session starts through
(mitmproxy + Claude Code launch script). Added a `command -v worker-cli`-guarded, fully detached
(`nohup worker-cli janitor >/dev/null 2>&1 & disown`) trigger right after the `MITMPROXY_CA`
constant, before argument parsing — earliest point with zero dependency on the script's own
parsed state (project path, model flags), unambiguously before the `claude` launch at the bottom
of the script. No new function — a bare guarded block, deliberately not folded into the script's
own pre-existing (and unrelated) `_janitor_cleanup_live_copies`/`_janitor_cleanup_jsonl_logs`
functions, which manage proxy live-copies and dual-log rotation, a different concern that
happens to share the "janitor" name coincidentally.

Detach pattern (`nohup ... & disown`) matches the existing idiom already used in this codebase
family for background sidecars (iterative-dev's `tmux_spawn.sh` `_start_worker_logger`) — chosen
so the sweep can never delay or block session start regardless of `worker-cli janitor`'s own
runtime (a full sweep across N stale sessions, each doing tmux/git/lsof calls).

## Verification (2026-08-19)

- `bash -n src/claude_proxy_start.sh` — syntax valid.
- Extracted the exact 5-line trigger snippet, ran it standalone (not via the full script, which
  would launch Claude Code) — confirmed a fresh `event=start dry_run=0 max_age_hours=12` /
  `event=end` pair appeared in `${WORKER_LOGGER_DIR:-$HOME/Documents/ai/Meta/blank/src/logs}/janitor.log`
  immediately after.
- `git diff src/claude_proxy_start.sh` — only the 8-line trigger block added; rest of the script
  byte-identical.
- NOT verified: the full script's own entry-point path end-to-end (i.e. an actual `claude`
  session launch observing the sweep fire in the background) — out of scope, would require
  launching a real Claude Code session.
