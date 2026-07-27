# Background-timer stacking on an auto-backgrounded task — confusion pattern + hook feasibility, 2026-07-27

## Symptom (observed live, trading session)

`rag-cli index` was launched as a FOREGROUND Bash call. CC auto-backgrounded it (its own
terminal-freeze protection). The orchestrator then armed a `sleep 600` background timer on top —
the worker-timer reflex, applied to a self-backgrounding command that already reports its own
completion.

Consequence chain, measured over ~20 minutes of wall time:
1. The timer's wake-up notice arrived almost immediately (no worker was running), so it did not
   pace anything.
2. Each wake produced a status probe of the index run. Three probes landed within seconds of each
   other while the orchestrator believed ~20 minutes had passed between them.
3. Identical chunk counters across those probes (96/700 each time) were read as "the process is
   stalled" instead of "these samples are seconds apart".
4. The index run's `Error: server returned HTTP 400 … exceeds the available context size` sat in
   the FIRST line of its output file the entire time, unread — the orchestrator diagnosed process
   liveness via `ps` on a reported PID instead of reading the output.
5. Diagnosis was wrong twice in a row (first "hung process", then a fabricated "coarse-grained
   progress counter" theory), and the real cause (an OCR digit-run of 16,364 chars in one MinerU
   markdown, unsplittable → over the embedding context limit) was only found after reading the
   output file.

## Two separate defects, both real

**A — skill gap (fixed, out of this area):** the PDF skill's Phase-2 audit had no oversized-span
class, and its Phase-3 gave no instruction to read the index run's output file. Both were closed in
`websearch-pdf/SKILL.md` (new class J + Phase-3 read-the-output rule) the same session.

**B — timer stacking (open, this entry):** nothing prevents arming a background timer while
something is already running in the background. That is the defect this entry scopes.

## Current hook state — what exists, what it does NOT do

Two hooks touch background Bash calls, both stateless and per-call:

- `block_unauthorized_background.py` — `run_in_background=true` is allowed ONLY for a sleep-only
  command; every other background command is rewritten to foreground.
- `rewrite_background_sleep.py` — normalizes any sleep-only background command to
  `sleep 600 && echo done`.

Neither knows whether anything is already running. A concurrency guard existed once
(`block_concurrent_timer.py`) and was removed 2026-07-21 after false-blocking the legitimate
"worker went idle before the 600s window expired → arm a fresh timer" path. That removal rationale
still stands and constrains any redesign.

## Feasibility measured this session

**Detection of a live background task — WORKS for explicitly-backgrounded commands.** Each
background task writes `<session-tmp>/tasks/<task-id>.output`; while it runs, its processes hold
that file open. Measured: a live `sleep 600` timer showed 4 open handles
(`zsh` + `sleep`, fds 1w/2w); every completed task's output file showed 0. No separate state file
needed — no staleness risk, unlike the removed hook's `timer_state.jsonl`.

**Hook input surface — only the explicit flag is visible.** A PreToolUse hook receives
`tool_input.command`, `tool_input.run_in_background`, `session_id`. Auto-backgrounding happens
mid-execution, after the hook has already passed the call through; there is no hook event for it.
A hook can therefore only ever gate the EXPLICIT background flag — which, given
`block_unauthorized_background`, means exactly one command shape: the sleep timer.

**The unresolved question:** does an AUTO-backgrounded task get a `tasks/<id>.output` file held open
the same way an explicit one does? Not measured — during the session only timer-held files were
observed live. This is the load-bearing unknown: if auto-backgrounded runs are invisible to the
handle check, a guard built on it would NOT have caught the very pattern that motivated it.

## Design sketch (NOT implemented, NOT decided)

Block (hard, exit-2 + message), do not rewrite-to-foreground: a foreground 600s sleep would hold
the terminal for 10 minutes, i.e. exactly the condition CC's auto-backgrounding exists to prevent.
Message would name the running task and instruct: go idle, wait for the completion notice, do not
arm a second background call.

Open risks to weigh before building:
- The 2026-07-21 false-block path (worker idle before timeout) must not reappear.
- Whether "anything holds a handle in `tasks/`" is the right predicate, or too broad — any
  session-scoped background writer would block a legitimate timer.
- Whether auto-backgrounded runs are detectable at all (above).

## Sources

Internal: `src/hooks/block_unauthorized_background.py`, `src/hooks/rewrite_background_sleep.py`,
`src/hooks/hook_setup.py`; the 2026-07-21 removal entry and the 2026-07-20 concurrent-redesign
entry in this area (historical constraints on any new guard).
