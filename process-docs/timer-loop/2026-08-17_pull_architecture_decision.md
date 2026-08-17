# Push → Pull: The Architecture Decision Behind the `worker-cli wait` Migration

Decision record for the 2026-08-17 session that replaced the orchestrator's raw background
sleep-timer + menubar auto-abort (push) with `worker-cli wait` (pull). The per-milestone
implementation entries live in this area and in `process-docs/tool_use_safety/` (hook family)
and the iterative-dev repo's `worker_wait` area; this entry records the reasoning that produced
the design, which existed only in the orchestrator↔user discussion.

## Why the block-hook line was abandoned entirely

As of 2026-08-17, the enforcement approach had a consistent failure history: the 2026-07-20/21
clock-based `block_concurrent_timer.py` (removed after false blocks), the 2026-08-07
cross-project false block (project-scoping fix), and — decisive — duplicate timers kept
appearing in live sessions even after the 2026-08-06/07 event-driven hook stack was deployed.
The judgment reached: timer discipline is something the orchestrator agent structurally cannot
be taught reliably; every block message forces extra agent reasoning, and each new enforcement
layer added a new false-positive surface.

## The design principles (user-set, they drove every subsequent choice)

1. **No forced agent reasoning when the outcome is identical.** A hook that blocks and explains
   is worse than silently accepting, but ONLY when the flow ends in the same state without the
   agent having to think about it. Swallow errors whose downstream effect is just "the agent
   wakes up anyway."
2. **Workers are a cut-off cosmos; strict pull.** Nothing on the worker side may push the main
   session awake. The main is woken only by its own child processes.
3. **The agent has no sense of time.** Any design requiring the agent to choose durations
   (short-poll intervals, timeout values) fails — it will improvise numbers. The agent gets ONE
   instruction: arm `worker-cli wait` after every dispatch. No timer concept in the rulebook at
   all.

## Alternatives weighed

- **Level-triggered abort fixes** (stamp timers as killable/unkillable at arm time,
  edge-triggered menubar abort): rejected — too many unknowns (spawn-detection latency, signal
  grace, menubar restart state), each a new fragile surface on top of the existing push design.
- **Naked short-interval polling** (`sleep 300` + status check per wake): rejected via
  principle 3 — up to 5min wake latency, ~12 poll turns/hour, and the agent choosing intervals.
- **`worker-cli wait` (chosen):** the waiting logic moves INTO the background command. It polls
  worker status in-process and exits on stable all-idle or its built-in 3300s ceiling; its exit
  IS the wake notification. All failure modes collapse into one direction — waking LATE, capped
  by the ceiling. Early or wrong wakes are constructively impossible; duplicates and no-worker
  arms become ignorable noise instead of enforcement targets.

## What the rollout surfaced (both fixed same-day, own entries exist)

- The rewrite hook initially applied to ALL sessions: worker-armed background sleeps were
  rewritten to `worker-cli wait`, producing stray 55min waits inside worker sessions that in
  turn held the orchestrator's wait open. Fix: orchestrator-only worktree exemption
  (`tool_use_safety` area).
- `wait`'s first bg-task detection counted any child under the worker's claude process as a
  live task; persistent tooling (pyright-langserver) made idle-transition wakes structurally
  impossible. The initial live verification had sampled before any tooling existed — a false
  pass. Fix: handle-based detection mirroring the menubar's proven lsof scheme (iterative-dev
  `worker_wait` area).

## End state as of 2026-08-17

Arming is unrestricted (no worker-state hooks, no pending-state machinery, no menubar
auto-abort); the only remaining hook roles are rewriting stale sleep habits to `worker-cli
wait` (orchestrator-only) and authorizing it as the background form. The menubar keeps display
+ manual abort only. Live end-to-end proof in this session: worker went idle with
pyright-langserver still running → `wait` exited within seconds → orchestrator woke on the
notice. The orchestrator rulebook (`shared-rules/opus/workers.md`) carries the Wake-up Loop
with no timer vocabulary.
