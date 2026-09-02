# `worker-cli wait` — Exit on a Transition, Not on a State (2026-09-02)

Continuation of the pull architecture from 2026-08-17. The pull design made every wake-up the
exit of the orchestrator's own `worker-cli wait` process; this entry changes WHEN that process
may exit.

## Problem

`wait` was level-triggered: poll every 5s, exit once all workers of the project were
non-blocking (`idle` without a live bg task, or terminal) for 3 consecutive samples, or once 3
consecutive polls saw zero workers (`"no workers"`, added 2026-08-18). It judged only the current
state, never the history of the invocation.

Observed consequence, recorded on 2026-08-25 as a bug: a `wait` armed while the worker was
already idle, or while no worker existed, exited after 15-60s, waking the orchestrator for
nothing, repeatedly. The orchestrator also had no way to sleep through a long detached job,
because every background sleep is rewritten to `worker-cli wait` and that exited on the idle
state at once.

## Specification (set by the user)

How background commands come into existence stays untouched (rewrite to `worker-cli wait`,
foreground-forcing of everything else). Only the termination condition changes:

- worker idle at arm time, or no worker at all: the wait stays alive
- worker idle but holding a live background task of its own: stays alive
- worker transitions from working to idle with no background task of its own: the wait ends,
  and every wait that is alive at that moment ends together

## Decision

One flag per invocation, `SAW_WORKING`, set the first time any poll classifies a worker as
verbatim `working`. The existing 3-sample stability exit for `workers idle` and `worker
terminal` additionally requires the flag. The `"no workers"` exit is removed; zero workers is a
non-exiting state like idle-at-arm. `timeout` (3300s ceiling) is unchanged. The terminal exit
stays, gated the same way, because a worker dying mid-task is a working-to-terminal transition
and the orchestrator must react to it; a worker already dead at arm time is a state.

Concurrent waits need no coordination: each polls the same worker, each sees the same working
phase, each exits in the same stability window.

This keeps the area's invariant, "wake late, never wrong": a missed transition ends at the
ceiling, never in a spurious wake.

## Evidence from the live trace before the change

`wait_trace.log` held 195 arms with a first-poll status. First poll saw `working` 129 times,
`unknown` 40 times (fresh spawns), `idle` 26 times. Of the 26 idle-first arms, 25 ran on for
22-534s, i.e. the `send` landed after the first poll and the working phase was observed later;
only 1 exited at 11s, a genuine idle-at-arm. Of 134 `workers_idle` exits overall, 1 was under
20s. So the send-versus-first-poll race is real (~13% of arms) and the transition gate absorbs
it, because the wait simply keeps polling until the working phase shows up. The one genuine
idle-at-arm case is exactly the one that now runs to the ceiling, as specified.

Residual risk: a worker turn shorter than one poll interval (5s) is invisible as a transition;
the wait then runs to the ceiling. Minimum observed elapsed for a working-first arm was 11s.

## Test suite

`dev/worker_wait/test_worker_wait.sh` in iterative-dev. The fixture could not produce a real
`working` status, because `_worker_detect_status` demotes `working` to `limit reached` when tmux
`#{window_activity}` is older than 10s. Added a chatty mode to the existing claude-dummy (prints
to the pane every 1-2s until a quiet file appears), plus `go_quiet` and `kill_claude_child`
helpers. Six new or reshaped cases: idle-from-start runs to timeout, no-worker runs to timeout,
working-then-idle exits `workers idle` 11s after the edge, working-then-child-killed exits
`worker terminal` 12s after the edge, two waits armed during working both exit on the edge,
armed-while-idle survives 18s of idle and exits only after a later working-to-idle edge. Tests
that modelled idle or terminal from the start got a working phase first or flipped to a timeout
expectation. Full run: 22 checks, all pass, ~5-6 minutes.

## Verification in the prod path

After merge, `worker-cli wait --timeout 20` against the real project with one idle worker: the
trace shows `stable_count=3` and `4` with `saw_working=0` and no exit, then `reason=timeout` at
22s. The working-to-idle transition is verified by the suite; the next real dispatch shows it in
the trace with `saw_working=1`.

## Side observation

Trace lines now carry `saw_working=` on every poll and exit line, so a wait that ran to the
ceiling is explainable from the log alone. An orphan registry entry (`rag-chunking`, status
`unknown`) was visible in the same trace; `worker-cli janitor` covers that, not this change.
