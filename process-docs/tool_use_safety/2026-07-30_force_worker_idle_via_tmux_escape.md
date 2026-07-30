# 2026-07-30 — Forcing a worker idle via tmux Escape: feasibility research

Direction explored: rather than only protecting the orchestrator's timer from being aborted while a worker
has a pending background task, take the worker's escape route away entirely — send an Escape keystroke into
its tmux pane the moment one of its calls goes to background, forcing it idle so it CANNOT poll even if the
orchestrator prods it.

## Delivery path already exists

`iterative-dev/1.0.0/src/spawn/tmux_spawn.sh` (~lines 324-336) delivers orchestrator messages to a worker
as real key events:

```
printf '%s' "$message" | tmux load-buffer -
tmux paste-buffer -d -t "$pane_id"
sleep 0.2
tmux send-keys -t "$pane_id" Enter
```

The comment states why the trailing Enter must be a key event: the CC TUI ignores pasted newlines as
submit. An Escape is the same call with a different key name — `tmux send-keys -t <pane_id> Escape`.

## External confirmation that Escape into a CC TUI works

Searched GitHub for prior art. `EliasSchlie/sub-claude` runs a pool of CC sessions in tmux and drives them
entirely through send-keys. Two findings:

`lib/sub-claude/tmux.sh` separates literal text from named keys deliberately:

```sh
# send_special_key — send a named special key (Enter, Escape, Up, Down, …).
# Unlike send_keys, this does NOT use -l, so tmux interprets the key name.
send_special_key() {
  local slot="$1" key="$2"
  tmux_cmd send-keys -t "$(slot_target "$slot")" "$key"
}
```

`lib/sub-claude/offload.sh` uses exactly that to reset a session before reusing it, in both
`offload_to_new` and `offload_to_resume`:

```sh
# Send Escape — harmless no-op at the prompt, exits any open menus.
send_special_key "$slot" Escape
sleep 0.5
```

So Escape via send-keys is established practice for controlling a CC TUI from outside, and it is treated as
safe at an idle prompt.

One caveat carried in that same repo, worth keeping: a SECOND Escape on an empty input opens CC's quit menu
(`lib/sub-claude/tmux.sh`, in the C-u path: "A second Escape on an empty input opens the quit menu in
Claude Code"). A force-idle mechanism must therefore not fire repeatedly — one Escape per detected
background-launch, not per tick.

Other repos found doing the same thing for different ends: `tugcantopaloglu/openclaw-dashboard`
(`tmux send-keys -t "$SESSION" Escape` to dismiss CC's usage panel after capture-pane),
`liaohch3/claude-tap` (`Escape C-u` to clear a line and retry a key in an e2e harness).

## Detection side

The trigger signal is the one measured separately this session: an open write handle on
`<tasks_dir>/<id>.output` marks a live background task, and it holds for auto-backgrounded tasks too. The
menubar already ticks every 1.5s across all sessions and already resolves each session's tasks dir, so it
is the natural place to detect and to fire.

## Relationship to the timer-abort guard

These are two answers to the same failure, and both are wanted:

- guard: the orchestrator's timer is NOT aborted while a worker has a live background task → the
  orchestrator never wakes to prod
- Escape: the worker is forced idle → even if prodded, it has no running turn in which to poll

Escape is the stronger of the two because it removes the worker's ability to poll rather than removing the
orchestrator's occasion to prod. The guard is still needed: without it the orchestrator prods a
force-idled worker, which then starts fresh work while its background task is still running.

## Open question, unresolved

Escape aborts whatever the worker is mid-way through. If a call gets auto-backgrounded while the worker is
inside a reasoning chain, that chain is lost and the worker sits idle with a half-done task. Whether it
resumes cleanly when later prodded is not known and not measured.

## Scope note

The mechanism covers workers only. The orchestrator's own session is not driven through tmux, so no
equivalent lever exists there — the orchestrator side stays dependent on the timer-abort guard.
