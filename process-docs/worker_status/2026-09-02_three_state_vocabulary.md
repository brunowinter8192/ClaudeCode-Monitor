# Worker Status — working / idle / dead (2026-09-02)

Code lives in the iterative-dev repo (`src/spawn/tmux_spawn.sh`, `bin/worker-cli`); its own
`process-docs/worker_status/` and `process-docs/worker_wait/` areas carry the earlier history.
This entry records the decision and the evidence gathered in the monitor-cc session.

## Problem

`worker-cli status` returned four values: `working`, `idle`, `limit reached`, `unknown`.

- `limit reached` covered both a real death and a user ESC-interrupt. The classifier demoted
  `working` with a pane quiet for more than 10s to `limit reached`. On 2026-08-25 two
  ESC-interrupted workers were killed and re-spawned with full handover because the status
  said `limit reached`, although both were alive and resumable.
- `unknown` was a "no data yet" placeholder (no JSONL, no hooks.json entry, unreadable pane).
  Every consumer had to special-case it; `worker-cli wait` folded it into "terminal" on
  2026-08-19 because a silently dead worker reported `unknown` forever.

## Decision

The orchestrator needs to know one thing: can the worker take a message. That gives three
states and nothing else.

- `dead`: cannot accept a message. Positive signals: tmux session gone, `#{pane_dead}=1`, no
  `claude` process under the pane pid, or the context-limit marker in the session JSONL.
- `idle`: waiting for input. hooks.json `idle` (Stop hook fired), or hooks.json `working` /
  absent with `#{window_activity}` older than 10s. The second form is the ESC case and must
  never read as dead.
- `working`: the default, everything without a dead or idle signal, including a fresh spawn
  before its first JSONL.

The menubar's own derivation (`src/menubar/discover.py`) already worked this way: session
exists or the worker is gone, hook status, `working` with a quiet pane becomes `idle`, no hook
entry becomes `idle`. worker-cli had drifted from it by naming the demoted state `limit
reached`.

## How the context limit is detected

Two questions had to be answered first.

Can the pane still be read after a crash? Yes. Worker sessions run with `remain-on-exit`, so a
killed process leaves the pane content plus a "Pane is dead (signal ...)" line; reproduced with
a throwaway session and `kill -9`. `worker-cli capture` reads that pane. `worker-cli response`
reads the session JSONL from disk and needs no tmux at all, but a crash usually lands mid-turn,
so the pane is the useful source.

How does the context limit show up? Not as an API error: `src/logs/api_errors.jsonl` (59
entries since May) holds no "prompt is too long" at all, only auth, rate-limit, model-version
and thinking-block errors. Claude Code blocks the turn client-side. Issue 90113 in
anthropics/claude-code (v2.1.251) documents the exact footprint: the screen shows
"Context limit reached · /compact or /clear to continue", and the transcript receives a
synthetic assistant entry with `message.model: "<synthetic>"`, text `Prompt is too long`,
`error: "invalid_request"`, `isApiErrorMessage: true`, all usage fields 0. Issue 23377 confirms
every later input fails the same way until /compact or /clear. That JSONL entry is the dead
signal; no pane text parsing needed. The check reads only the last 200 lines of the JSONL,
because `wait` polls every 5s and a session file grows to tens of megabytes.

## Consumers

`worker-cli wait` classifies `dead` as non-blocking terminal, exit line `worker dead`, trace
`class=dead` / `reason=worker_dead`. A failed status probe inside `wait` yields the internal
value `probe-error`, which stays blocking and never arms the transition gate. The display
commands (`list`, `status`, `status --all`) and `janitor` recover from a probe failure with a
direct `tmux has-session` check: gone means `dead`, otherwise `working`.

## Tests

`dev/worker_status/test_worker_status.sh` (new, iterative-dev): 11 cases against real tmux
sessions and a scoped hooks.json, including the ESC case (hook `working`, pane quiet, process
alive gives `idle`), the synthetic marker (gives `dead`), a normal aborted assistant message
(gives `idle`), and grep proof that `limit reached` and `echo "unknown"` are gone. All pass.

`dev/worker_wait/test_worker_wait.sh`: 22 checks, all pass. Two fixtures changed meaning under
the new vocabulary and were fixed rather than relabelled: a deleted hook entry alone is now
`idle` after 10s, not dead, so the dead test pairs it with a killed claude child; the
"stuck unknown forever" case now self-heals from `working` to `idle`.

## Verification status

Suites verified by the worker. The prod path is only partly live: `bin/worker-cli` is a symlink
into the repo, but it sources `tmux_spawn.sh` from the plugin cache, which still returns the
old vocabulary until `plugin-publish` runs. Between merge and publish, a dead worker would read
as busy in `wait` and run to the timeout ceiling. Live check of the three values happens after
publish.

## Rules

`shared-rules/main/workers.md` still names `limit reached` as the signal for a successor. The
rules update is a separate step done with the user.
