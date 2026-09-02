# Worker Status — first-turn status verified live, reader rules aligned (2026-09-02)

Follows the three-state vocabulary entry of the same day in this area. Code lives in the
iterative-dev repo (`bin/worker-cli`, `src/spawn/tmux_spawn.sh`).

## First turn of a fresh spawn

Before the vocabulary change, a freshly spawned worker had no hooks.json entry for its whole
first turn (the spawn prompt arrives as a CLI argument, so `UserPromptSubmit` never fires) and
`status` returned `unknown`; the 2026-08-28 trace showed 40 of 195 arms with `unknown` on the
first poll. Under the new vocabulary `working` is the default for everything without a dead or
idle signal, which covers that gap by construction.

Verified in the prod path after `plugin-publish` (the cached `tmux_spawn.sh` was byte-identical
to the repo at the time of checking). Two real spawns in the monitor-cc session, first poll of
the armed `wait` in `wait_trace.log`:

| Spawn | First poll | Exit |
|---|---|---|
| 18:33:08 capture worker | `status=working saw_working=1` | `workers_idle` after 21s, a real transition to the worker's cull gate |
| 18:38:45 fix worker | `status=working saw_working=1` | `workers_idle` after 180s |

No `unknown` and no immediate return.

## "Worktree removed by merge" no longer exists as a case

The 2026-08-28 observation was a worker reading `unknown` because `worker-cli merge` had
removed its worktree and `pane_current_path` pointed nowhere. As of this date only `kill`
removes worktrees (`bin/worker-cli`, kill branch, plus the cross-project sidecar loop); `merge`
leaves them in place, confirmed on a cross-project worker whose two worktrees both survived the
merge. With `unknown` gone there is also no "cannot be read" state left to distinguish from; a
probe failure inside `wait` stays internal (`probe-error`) and the display commands fall back to
`tmux has-session`.

## What `response` actually depends on

`response` never touches tmux. It derives the worktree path from the registry and the name,
requires that directory to exist, encodes the path into the `~/.claude/projects/<encoded>/`
folder name and reads the newest JSONL there. So it reads a dead worker's completed turns just
as well as a live one's; what it cannot show is a turn that died mid-generation, because that
turn never reached the JSONL. That is the one case where the pane is the only source, and it is
the case the rules now name.

The directory-exists check is stricter than needed (the encoded name is computed from the
string alone), but the only path that removes the directory is `kill`, after which the worker is
gone by definition. No observed failure, so no change.

## Rules

`shared-rules/main/workers.md` lost the line "use capture only for a dead or force-stopped
worker, because response needs a live session" (wrong reason). `shared-rules/main/tool-use.md`
now says `capture` is the reader when `status` shows `dead`. The wake-up loop keeps only the
working and idle branches on purpose; `dead` is handled by the death-recovery section, not the
loop.
