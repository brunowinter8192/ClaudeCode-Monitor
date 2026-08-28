# Milestone 1 — Queue tab removal (menubar)

2026-08-28

## Scope

First milestone of the model-selector line of work: retire the message-queue feature
from the menubar app entirely, in both halves — UI (tab, controller, render module, data
module) and delivery (the queue-delivery half of `hook_writer.py`) — leaving a correct
two-tab Sessions ↔ RAG ring. A later milestone adds a Models tab into the vacated ring slot;
this milestone was removal only, no new tab.

Deleted: `src/menubar/queue_controller.py`, `queue_panel_render.py`, `queue.py`.
Split `hook_writer.py` into its two always-separate jobs: kept the hook-state half
(`_write_state`/`_load_state`/`_HOOK_STATE_FILE`/`_WORKING_EVENTS`/`_IDLE_EVENTS`) byte-for-byte
unchanged, removed the queue-delivery half (`_maybe_deliver_queue` and its 8 helper functions +
3 constants). Removed `QUEUE_FILE`/`QUEUE_LOCK` from `paths.py`. Rewired `panel_lifecycle.py`'s
Cmd+→/← wiring from a 3-element ring (Sessions→RAG→Queue→Sessions) to a 2-element ring
(Sessions↔RAG, either arrow crosses). Full trail is in the commit diff; DOCS.md was updated
in the same commit as the code (module sections, State table, Module Import Graph, Gotchas).

Verified: syntax (`ast.parse`) + integration-level import of every touched module; hook script
tested with real synthetic `UserPromptSubmit`/`Stop` stdin payloads against a tempdir-isolated
`_APP_SUPPORT` (`dev/model_selector/verify_hook_writer_split.py`) — both status transitions
correct, zero queue-file side effects. `setup_py2app.py py2app` build completed clean. NOT
verified: interactive Cmd+→/←/Cmd+K behavior in the live running app — visual check, not
self-verifiable from a worktree.

## Hazard — `setup_py2app.py py2app` deploys from wherever it runs, including a worktree

`setup_py2app.py` is not a build-only script: `_install_bundle` runs unconditionally after
`setup()` and copies the freshly-built bundle to `~/Applications/monitor-cc-menubar.app`,
codesigns it, and does a `launchctl bootout` + `bootstrap` cycle that relaunches the app —
all in the one `py2app` invocation used for the "does the build succeed" check.

Running it from a worktree therefore does not just prove the build works — it **installs and
relaunches the live, user-facing menubar app with whatever code is checked out in that
worktree**, merged or not. This milestone's build-verification step had exactly that effect:
the user's live menubar was left running this milestone's unmerged worktree code, not the
integration branch. The change was accepted as wanted in this case, but it was an unrequested
production side effect of a verification step, and it will recur for any future milestone that
runs the same command from a worktree for the same reason.

**Consequence for future milestones:** build verification of a worktree change must be aware
that `setup_py2app.py py2app` is a deploy, not a dry-run compile — confirm with the user before
running it from a worktree if unmerged code reaching the live app is a concern for that change.

## Finding — worker-cli status reads 'unknown' for a freshly spawned worker's entire first turn

While reviewing this milestone's diff, a separate pre-existing defect was traced to code this
milestone touches: a freshly spawned worker (this session's own `model-selector` worktree
session, spawned via the model-selector project's own iterative-dev spawn) showed status
`unknown` in `hooks.json` for the entirety of its first turn, only flipping to `idle` at the
exact moment the first turn ended — never `working` beforehand.

**Root cause chain:** `proc_cache.py`'s hook-state signal is populated exclusively by
`hook_writer.py`, which writes an entry only on `UserPromptSubmit` (→`working`) or
`Stop`/`StopFailure` (→`idle`). A spawned worker receives its first prompt as a CLI argument
at process start, not as a `UserPromptSubmit` hook event — that hook only fires for prompts
typed into an already-running session. So no `hooks.json` entry exists at all for a freshly
spawned worker until its first `Stop` fires, at which point the entry appears directly as
`idle` — `working` is never observed for that worker's first turn.

**Consequence:** `worker-cli wait` (and anything else keying off hook state to decide
working-vs-idle) treats a missing/`unknown` entry as not-working and returns immediately for a
worker still on its first turn — the wait exits before the worker has done anything.

**Verification of this finding:** manual, single-instance — observed by hand that this
session's own `hooks.json` entry appeared with `status: "idle"` at the exact wall-clock moment
this milestone's first turn ended, with no prior `working` entry at any point beforehand. Not
verified across multiple spawns or written up as a regression test — this is a root-cause
report for a follow-up fix, not a fix itself, and stays out of this milestone's scope (menubar
delivery/UI removal only).

**Not fixed here** — flagging for whichever area owns spawn-prompt-delivery semantics
(`worker-cli`/iterative-dev plugin) or a future `hook_writer.py` change (e.g. treating an
absent hook-state entry as "assume working within N seconds of process start" instead of
"not-working") to pick up.
