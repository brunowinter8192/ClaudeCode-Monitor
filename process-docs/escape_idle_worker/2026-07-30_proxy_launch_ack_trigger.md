# 2026-07-30 — Escape trigger moved to the proxy's launch-ack replacement, not `has_bg`

Continuation of this area's driving question (force a worker idle via tmux Escape the moment a
Bash call goes to background) with a different trigger: the earlier `has_bg`-based mechanism
(open write-handle on a `tasks/<id>.output` file) was disproved and rolled back the same day it
shipped — every foreground Bash call also holds such a handle, so the Escape fired on a worker's
very first call. This entry only records what replaced it.

## The signal used instead

The proxy already replaces a genuine CC background-launch ack with a 3-line hold message
(`src/proxy/strip_bg_launch_ack.py::_is_bg_launch_ack`) — that replacement fires if and only if
Claude Code actually backgrounded a call, on either of the two known wordings ("Command running
in background with ID: …" / "Command was manually backgrounded by user with ID: …"). Unlike
`has_bg`, this signal cannot false-positive on an ordinary foreground call: there is no ack text
to replace unless CC genuinely backgrounded something.

## Design decision — the proxy sends the Escape directly, not via a signal file

Considered: (a) `ProxyAddon.request()` sends the Escape itself (a `tmux send-keys` subprocess
call inline in the request hook), vs. (b) it writes a signal (file/IPC) that a separate poller
acts on later.

Chosen: (a), direct send. Reasoning: the entire point of this mechanism is to beat the worker's
next turn — a signal-file design needs an external poller to notice the file and act, and the
only continuously-ticking process on this machine (the menubar's `FocusController`) is explicitly
off-limits for this change (it is the file the rolled-back mechanism lived in, and touching it
again risks resurrecting exactly the disproved coupling). Any new poller would either need its own
tick loop (added complexity, added latency equal to its poll interval) or ride on the menubar's
existing tick (forbidden here). A direct send has no such window: it fires in the same request
that revealed the ack, before the worker's next message exists. `addon.py` already performs
blocking I/O synchronously in this exact hook (six dual-log JSONL writes, one per concern, each in
its own `try/except`) — one more bounded, exception-wrapped subprocess call is the same risk class,
not a new one. The subprocess calls carry an explicit 2s timeout each so a hung `tmux` cannot block
a request indefinitely, and the dedup gate (below) means the call only ever actually reaches
`tmux` once per background task id, not once per request.

## Fire-once-per-task-id — why, and where it lives

Measured this session on a real worker proxy log: the raw ack text (unlike the proxy's own
replacement of it) persists in Claude Code's own conversation history and is resent on nearly
every subsequent request in that session — 142 of 169 requests in the sampled session carried it,
because each request re-sends full history and the proxy re-detects + re-replaces it fresh every
time. A naive fire-on-detection would send an Escape on almost every one of those 142 requests.
Worse than wasteful: a SECOND `tmux send-keys ... Escape` into an already-idle Claude Code TUI can
open its quit menu (`EliasSchlie/sub-claude`'s `lib/sub-claude/tmux.sh` notes the first Escape at
an empty prompt is a no-op, implying nothing guarantees a second one stays a no-op) — so an
un-deduped trigger is an active hazard, not just noise.

Dedup store: `src/proxy/bg_escape.py::_escaped_task_ids`, a module-global `set` of task ids
already escaped, keyed on the id CC assigns to the backgrounded call (recovered from the ack text
via the same `_ACK_ID_RE` the strip pass already uses to build its replacement — reused unchanged,
not re-implemented). Lives in-memory for the mitmproxy process's lifetime; wiped on hot-reload
(any edit under `src/proxy/`, the same trigger every other cache in this package already resets
on) or a full process restart. A restart can cause at most one *extra* Escape per task id whose
ack is still being resent — never a repeat storm, since the set re-populates from the process's
own first sighting of each id going forward.

## Targeting — reusing addon.py's existing worker/main derivation

`addon.py::_derive_worker_context()` (unchanged, pre-existing) already distinguishes
`"worker:<name>"` from `"main"` from `PROXY_LOG_ID`. `bg_escape.py::_derive_tmux_session_name`
builds `worker-{basename(PROXY_PROJECT_PATH)}-{name}` from that plus `PROXY_PROJECT_PATH` — the
same iterative-dev convention `discover.py::_worker_tmux_session` uses on the menubar side, just
derived from proxy-visible env vars instead of a session's JSONL cwd. A `"main"` context is
rejected structurally (empty string returned, caller treats empty as no-op) before any tmux
command is attempted.

## Verification reached (2026-07-30, `dev/bg_wakeup_id_line/p2_bg_escape_probe.py`, 21/21 checks)

- Dedup: 169 simulated requests, 142 carrying the same ack (real 142/169 shape) → exactly 1
  Escape. Two distinct task ids across repeated calls → exactly 2.
- Both CC wordings trigger independently; a `main`-context call with a genuine ack fires 0.
- tmux session name derivation verified against the two example ids given for this task
  (`worker_25c51a2e_esc-live_1785424292` → `worker-monitor-cc-esc-live`,
  `worker_25c51a2e_bg-ack-shapes_1785359201` → `worker-monitor-cc-bg-ack-shapes`) — the second
  specifically exercises a hyphenated worker name against the underscore-joined log-id parsing.
- Real tmux round trip: throwaway session running a raw-mode 1-byte reader, the PRODUCTION
  `_send_escape_key` called against it, `capture-pane` confirms the reader received `'\x1b'`.
- Failure isolation: a dead/missing tmux session and a missing `tmux` binary both return `False`
  without raising, at the unit level; additionally, a real `ProxyAddon.request()` call with the
  `tmux` binary simulated absent still completes — `flow.request.content` is set, i.e. the request
  still forwards.
- Existing proxy regression suites (bg-launch-ack strip semantics, composition/span invariants,
  header capture) all still pass unchanged — this session touched no detection/replacement logic
  in `strip_bg_launch_ack.py` itself, only added a new consumer of its already-detected ack text.

Not verified: a live Claude Code TUI actually being interrupted mid-turn by this exact path —
verification this session was scoped to the tmux-mechanics + dedup + failure-isolation proof; no
live worker session was driven end-to-end.

## Open question, still unresolved

Escape aborts whatever the worker is mid-way through. Whether a worker resumes cleanly once
force-idled by this launch-ack-triggered path, when later prodded, is not known and not measured
here.
