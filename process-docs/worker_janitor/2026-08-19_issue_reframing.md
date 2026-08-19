# Worker-State Issue Reframed to the Janitor — Decision Trail (2026-08-19)

Chat-level decision record for how the original three-defect worker-state issue became the
`worker-cli janitor` feature (implementation + trigger entries: this area and the
iterative-dev repo's `worker_janitor` area).

## Original framing (as of the issue's creation, 2026-08-18)

Three state-detection defects bundled: (1) menubar showed a context-dead worker as idle while
worker_status returned a terminal status; (2) the worker-cli registry lost a live tmux session
(present for days, absent from `worker-cli list`); (3) "silent worker deaths" leave no
`worker-deaths.log` entry when the pane survives.

## User decisions that reframed it (2026-08-19, chat only)

- **Defect 1 dropped:** the menubar is a display for the user; whether a dead worker renders
  as idle or dead is cosmetically secondary. Also, the process history
  (`menubar_session_status` area) shows dead→idle demote was a DELIBERATE crash-safety fix,
  not a bug — the menubar has no third "dead" state by design.
- **Defect 3 dropped as a concept:** the only regular death cause is the context limit.
  Crash and quota-out exist in the historical record (`menubar_worker_death_detection`) but
  are irregular cases where the user intervenes personally — no tooling built for them.
- **Defect 2 generalized into the janitor:** instead of repairing registry bookkeeping,
  sweep ALL worker tmux sessions older than 12h at every main-session start, cross-project.
  Key consequence of the registry-loss lesson: the sweep enumerates tmux `worker-*` sessions
  directly (registry-lost sessions are invisible to a registry-only sweep by definition);
  the registry is a resolution aid, not the source of truth.
- **Working-skip guard** (orchestrator proposal, user-approved): a worker with status
  `working` is never killed regardless of age — the cost of killing a mid-turn worker
  outweighs the delay of catching it on the next sweep.

## Outcome pointers

Implementation (subcommand, resolution chain, isolated smoke test): iterative-dev repo,
`process-docs/worker_janitor/`. Trigger wiring in `src/claude_proxy_start.sh`: this area.
Live verification at build time: a 22.6h-old registry-lost session (`worker-repro1b58790-w1`)
was the sole sweep candidate and was removed in the first real run; live workers were spared.
