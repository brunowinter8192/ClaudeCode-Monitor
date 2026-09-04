# Claude Code cross-session messaging — evaluated, not adopted (2026-09-04)

## What the feature is (as of the docs captured 2026-09-04 into `monitor-cc-reference`)

- Shipped in Claude Code 2.1.224 (macOS/Linux), idle notice in 2.1.236, Windows in 2.1.239.
- Each session binds a Unix-domain inbox socket. `ListAgents` lists reachable sessions on the
  machine; `SendMessage` delivers plain text (no files, no history) to a session by name.
- Delivery: read between tool calls during an active turn, or a new turn when the receiver is
  idle. The receiving Claude is told the message came from another Claude session, not the user.
- `crossSessionInbound` per session: accept / hold / refuse. Rate limits, 50-message queue,
  dedup of identical repeats.
- `notify_when_idle` on `SendMessage`: the main conversation subscribes to one one-shot notice
  when a same-machine session next goes idle; no turn and no tokens in the watched session; the
  notice starts a new turn in the asking session if it is idle; 12 h expiry.

## Hands-on on this machine

- `ListAgents` from this session (monitor-cc-34, CC 2.1.258) listed the three other main
  sessions (websearch, jobscraper, wise2627) and NONE of the three running workers.
- Cause: workers are spawned through `~/.local/bin/claude-223` (CC 2.1.223), one version before
  the feature. They bind no inbox socket, so they are neither reachable nor able to send a notice.

## Fit against the orchestrator-worker workflow

Requirements stated by the user: pull principle only (orchestrator initiates every exchange;
workers never send on their own), worker sessions visible in tmux/Ghostty, no overhead in the
worker, and as few tool calls per round as possible.

- The only piece that fits the pull principle is `notify_when_idle` (the orchestrator subscribes;
  the worker's harness, not its Claude, emits one line). It would replace `worker-cli wait` plus
  the `worker-cli status` re-check, i.e. it saves one to two tool calls per round.
- `SendMessage` as the send channel would merge send and wait into one call, but delivers
  mid-turn (which `block_worker_send_while_working` deliberately forbids since today) and marks
  the text as coming from another Claude session rather than the user.
- Reading worker output through the inbox would depend on the worker actively sending, which is
  exactly what capture/response exist to avoid: when a worker stalls or dies, `worker-cli capture`
  is the lever, and it needs no cooperation from the worker.

## Decision

Not adopted. The gain is one saved `status` call per round; the cost is a dependency on a
harness feature whose socket, version gates and inbound rules change with every CC release and
whose source is not available. The plugin-owned path (tmux keystrokes in, session JSONL and hook
state files out) stays. The observed failure that `worker-cli wait` sometimes did not return
while a worker was idle is a defect in that path and is to be fixed there, not by switching the
channel.

## Open

- Why workers are pinned to CC 2.1.223 while the main session runs 2.1.258 was not investigated
  here; a `pin-bump-258` worker ran on 2026-09-03, so a bump is apparently in flight elsewhere.
