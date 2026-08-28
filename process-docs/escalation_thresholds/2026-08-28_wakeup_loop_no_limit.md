# 2026-08-28 — Five premature wake-ups, and why no single one triggered a stop

Opening entry of this area. Subject: the orchestrator's wake-up loop fired five times against
a worker that was still working, and the orchestrator re-armed it every time instead of
stopping. The defect in the tooling is real and diagnosed; the more useful half of the entry is
why the orchestrator did not stop.

## The mechanism

`worker-cli status` resolves a worker through this chain (`src/spawn/tmux_spawn.sh`,
`_worker_detect_status`): `#{pane_dead}` → a process-tree check for a live `claude` descendant
→ `#{pane_current_path}` → the encoded project dir under `~/.claude/projects/` → the newest
JSONL there → that session id looked up in the menubar's `hooks.json`. Any missing step
returns `unknown`.

`hooks.json` is written only by `src/menubar/hook_writer.py`, and only on two events:
`UserPromptSubmit` → `working`, `Stop` → `idle`.

A spawn passes the task as an argument, not as a typed prompt. `UserPromptSubmit` therefore
never fires for a worker's first turn, no entry exists, and status is `unknown` for the entire
first turn — which for a real milestone is ten to fifteen minutes.

`worker-cli wait` shares that detection and evidently does not count `unknown` as working, so
it returns immediately and reports the worker as done.

### Evidence

Status was queried four to five times across roughly fifteen minutes and returned `unknown`
every time. The `hooks.json` entry for that session appeared with status `idle` at the exact
moment the first turn ended, and never as `working` before. Running the chain by hand at that
moment reproduced `idle` correctly, so the chain works — it simply has nothing to read during
turn one.

A second worker showed the same `unknown` for a different reason: `worker-cli merge` had
deleted its worktree, so `pane_current_path` pointed at a directory that no longer exists and
no JSONL could be found.

### Consequence for the loop

The failure is structural, not incidental: it hits every freshly spawned worker on its first
turn, which is exactly the turn the orchestrator waits on after dispatching a milestone.
Once the worker has received a `worker-cli send`, `UserPromptSubmit` does fire and the loop
behaves.

`worker-cli response` was also unreliable here — it returned the same three assistant turns
across three separate checks while the pane was visibly advancing. Only `worker-cli capture`,
the raw tmux pane, showed the true state.

## Why the orchestrator kept re-arming

The rule to stop after two failed tool calls was in force and was recognised as applying. It
was then argued away: re-arming blocks nothing, so it is not a failure. That reasoning is
locally true every single time, which is the point.

Three properties made it stable:

1. **No number was fixed in advance.** Without a threshold set before the loop began, there is
   never a cycle that is distinguishable from the previous one, so no cycle ever says "now".
2. **Each cycle was individually cheap.** The cost was one user turn, which never looks like
   enough to justify halting.
3. **The cost accrued to the user, not to the work.** Nothing in the run degraded; only the
   user's turns were consumed. Nothing in the orchestrator's own state got worse, so nothing
   pushed back.

The loop broke on the fifth cycle, and only because the user's answers had by then been
overtaken twice by the system's own wake-up notice — the user could not reply, because the
notification arrived first. That is what finally made the pattern visible, not the count.

## What was changed

Nothing in the rules during this session. The two thresholds that were named at the time — a
limit of three misfires on the wake cycle, and aborting a worker wait beyond ten minutes — were
stated in chat and not written anywhere, which is the same defect one level up.

## What this does not settle

Whether a numeric limit is the right instrument at all. A limit fixed in advance solves the
"no moment says now" property but not the "each cycle is cheap" one — a limit of three simply
moves the argument to the fourth cycle. The property that actually did the work here was
aggregation: the individual misfires carried no signal, the pattern did. Whether aggregation
can be made a rule, rather than a thing noticed in hindsight, is open.
