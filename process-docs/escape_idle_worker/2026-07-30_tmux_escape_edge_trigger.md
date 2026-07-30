# Forcing a worker idle via tmux Escape on auto-backgrounded Bash calls, 2026-07-30

New area — driving question: how to stop a worker from re-entering orchestration by polling its
own auto-backgrounded Bash call after the menubar's idle-based auto-abort has already killed the
orchestrator's wait timer. Distinct from the orchestrator-signal grace mechanism (worker-liveness
staleness during prompt-send) — this is a different failure surface: a worker whose CURRENT Bash
call silently went to background, which the hook-status layer alone cannot see, since the CC TUI
itself reports idle correctly while the underlying process is still running.

## Failure pattern (as observed 2026-07-30, live)

1. orchestrator dispatches a worker
2. one of the worker's Bash calls gets auto-backgrounded by Claude Code
3. worker goes idle correctly (proxy-injected launch-ack tells it to wait) — hook status genuinely
   reads idle, this is not a staleness bug
4. menubar's auto-abort sees "all workers of this project are idle" and kills the orchestrator's
   `sleep 600` timer
5. orchestrator wakes on the dead timer, sees `idle`, cannot see the pending background task, prods
   the worker
6. worker has nothing to do but poll its own background process
7. it goes idle again → timer aborted again → repeat

The loop is invisible to hook-status alone: the worker really is idle by CC's own definition
(no active turn), yet a live background process still exists that the orchestrator has no visibility
into. Blocking the poll at the hook level (an available lever) does not prevent the re-entry —
the orchestrator still prods and the worker still has to respond somehow.

## Chosen mechanism — Escape as a forced-idle signal

`tmux send-keys -t <target> Escape` (no `-l`, so tmux interprets the key name) interrupts a live
Claude Code TUI turn. Sending it the moment `has_bg` transitions to True forces the worker into an
unambiguously idle state that cannot itself trigger a new poll turn — the interrupt happens before
the worker's next message, not after. Detection (`proc_cache.py::_has_active_bg`, open-file-handle
based, already existed and needed no change) and addressing (`SessionInfo.tmux_session_name`,
already existed) were both already available; the only new surface is the send itself and its
edge-trigger gating, both added to `FocusController.tick()` (the same per-tick controller that
already owns the idle-based auto-abort logic, for locality — one place reads `has_bg` per worker
per tick already).

## Edge-trigger design — set-diff, not a per-worker boolean flag

Rejected: a `dict[str, bool]` of last-seen `has_bg` per worker, checked each tick. Chosen instead:
`self._bg_escaped_workers: set` holding the tmux names currently believed `has_bg=True`.
Each tick: `current_bg_workers = {tmux_name for worker with is_worker and tmux_session_name and
has_bg}`; the rising edges this tick are exactly `current_bg_workers - self._bg_escaped_workers`;
after firing on those, `self._bg_escaped_workers = current_bg_workers` unconditionally. This single
assignment does double duty — it both prevents re-fire while `has_bg` stays True across ticks (the
worker is simply already a member of the set) and resets the trigger the instant `has_bg` drops
back to False (the worker leaves the set, so a future True is a fresh rising edge). No separate
reset branch needed, no risk of the two states drifting out of sync with each other.

This mattered because of an external, pre-confirmed failure mode: a SECOND Escape sent into an
already-idle Claude Code TUI opens the quit menu (confirmed via `EliasSchlie/sub-claude`'s own
comment on the same key, "harmless no-op at the prompt, exits any open menus" — implying the FIRST
Escape at an empty prompt is a no-op, but nothing guarantees a SECOND one stays a no-op once a menu
state is already open). A per-tick send (bare `if has_bg: send()`), which would have been the naive
first draft, would have escaped an already-idle worker on every single 1.5s tick for as long as the
background task kept running — for a multi-minute task that is 40+ redundant Escapes, dropping the
worker into the quit menu on the second one. The set-diff design was chosen specifically to make
that failure structurally impossible rather than something to guard against with a cooldown timer.

## Fail-safe wrapping

`_send_escape_key` wraps both the `tmux has-session` liveness check and the `tmux send-keys` call
in one try/except returning `False` on any exception — a dead/missing tmux session, a missing
`tmux` binary, or any other subprocess error degrades to a logged no-op. This runs inside the
AppKit tick (`FocusController.tick()` is called from `CCMenuBarApp._tick`, a Carbon/AppKit-adjacent
callback per the file's existing `_abort_log_write`/`_escape_log_write` convention) where an
uncaught exception would be far more disruptive than a missed Escape.

## Real-tmux verification — an execvp pane-death gotcha

Verifying the actual `tmux send-keys ... Escape` mechanics (not the edge-trigger logic, which is
pure-Python and tmux-free) required a throwaway tmux session running something that visibly reacts
to the Escape byte. First attempt: `tmux new-session -d -s <name> python3 <path>` with the reader
script's path as a separate trailing argv element — the pane died before `send-keys` could reach it
(`tmux capture-pane` returned empty both before and after, and `tmux has-session` failed once
attempted a second time). Cause: multiple trailing argv words after `-s <name>` make tmux `execvp`
the command directly rather than routing it through `$SHELL -c`, and whatever caused the immediate
exit (session teardown timing, not a script bug — the identical script ran fine standalone) left no
window for the keystroke. Fix: pass a SINGLE shell-string trailing argument
(`f'python3 {path}; sleep 30'`), which tmux hands to `$SHELL -c`, keeping the pane alive well past
the point where `send-keys` fires regardless of how fast the reader script itself exits. The reader
script (a `tty.setcbreak` + `sys.stdin.read(1)` one-byte read, printing `repr()` of what arrived)
then confirmed `GOT_BYTE:'\x1b'` on the pane after `_send_escape_key(<session>)` was called — the
production send function, not a re-implementation. Full report:
`dev/hook_smoke/md/2026-07-30_escape_real_tmux_roundtrip.md`.

## Verification summary (as of 2026-07-30)

- `dev/hook_smoke/test_escape_idle_worker.py`, 6 cases, all passing: edge-trigger sequence
  (`False,True,True,False,True` → exactly 2 sends), 5 consecutive `True` ticks → exactly 1 send,
  main session with `has_bg=True` → 0 sends, worker with empty `tmux_session_name` → 0 sends, dead
  tmux session name → real call returns `False` without raising, missing `tmux` binary → same.
  Drives `FocusController.tick()` directly with synthetic `SessionInfo`-shaped objects; no tmux, no
  AppKit involved for these 6.
- `dev/hook_smoke/probe_escape_real_tmux_roundtrip.py`: one real tmux round trip, described above,
  passing (`exists_before=True sent=True arrived=True`).
- Not verified: the full `CCMenuBarApp._tick` → `FocusController.tick` wiring running live inside
  the actual packaged menubar app, and no live Claude Code TUI was driven end-to-end (the milestone
  scoped the tmux-mechanics proof to NOT require CC — a bare byte-reader stood in for it).
