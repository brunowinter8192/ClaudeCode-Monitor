# Reddit survey: which Claude Code features the community values, and how cross-session messaging is received (2026-09-04)

Indexed into `reddit-cli-posts` on 2026-09-04: r/ClaudeCode, r/ClaudeAI, r/ClaudeCodeTLDR, r/claude
(queries "best feature" hot, "favorite feature game changer", "cross-session messaging" hot,
"agent teams subagents workflow" hot; 46 new posts). Read as a first pass only; a closer reading
is deferred to a follow-up session.

## Features the community celebrates, and the stated reason

- A short CLAUDE.md, plan mode before code, `/clear` or `/compact` after each task: output stops
  being random, context bloat degrades quality (multiple high-scoring workflow posts).
- Hooks: Boris Cherny's own list (SessionStart loads context, PreToolUse logs every bash command,
  PermissionRequest routed to WhatsApp, a Stop hook that keeps Claude going). "The Stop hook alone
  is worth it."
- A verification path for Claude (Chrome extension, test suite, simulator): "2-3x the quality of
  the final result" (Boris, tip 13).
- Parallelism as one task per agent, one git checkout per agent (Boris: 5 terminal + 5 web, same
  repo, separate checkouts). Top comment on his thread: "Notice how he doesn't have 17 parallel
  subagents" (382 points).
- `/loop` and `/schedule`: turn workflows into skills, then loop them.
- Official plugins typescript-lsp, security-guidance, context7, playwright (1362-point post);
  `/simplify` before review; an end-of-session retrospective.

## Reception of cross-session messaging (shipped 2.1.224, 2026-08-07)

- Highest-scoring substantive comment (10 pts): "the real problem was never the transport. It was
  always coordination: which agent owns which files, who waits on whom."
- Months-long multi-session user: "they dont coordinate. they snitch on each others bugs."
- Implementer/reviewer pair over messaging: "at least twice or three times as inefficient",
  arguing over sentences in documentation; replies call the design a red flag, multi-agent mainly
  pays when cheap orchestrates expensive.
- Agent Teams thread (2026-09-02): messages queue while a teammate is mid-task; the lead assumed
  teammates had frozen and spawned duplicates; delayed replies caused token churn. The poster's
  wish: "agents need to be able to see when each other are busy and how many messages are queued."
- One enthusiastic post (6 pts) about two sessions coordinating commits on one branch.
- A coordinator pattern close to ours appears in a comment: coordinator session spawns headless
  sessions, communicates via files, monitors their context and retires them; "I can't directly
  monitor their progress, but I just want to know when it's done."

## What this says about the monitor-cc orchestrator-worker setup

The celebrated patterns are the ones already in place: worktree per worker, hooks as hard rules,
one task per worker, the orchestrator reading worker state itself. The Agent Teams pain (queued
messages misread as a frozen teammate) is exactly what `block_worker_send_while_working`
(tool_use_safety, 2026-09-04) forecloses structurally. This survey did not change the decision in
this area's evaluation entry of the same day.
