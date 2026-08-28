# Milestone 3 follow-up — the fifth hardcode site, and why only a real call caught it

2026-08-28

## The load-bearing fact of this entry

**Milestone 3's own file list was wrong.** It named four hardcode sites (`spawn.py:114`,
`tmux_spawn.sh:518/628/715`), all inside `src/spawn/`. A fifth site existed outside that
directory, in the plugin repo's `bin/worker-cli` (git-tracked, at the repo root, not under
`src/`) — and it sat **upstream** of all four listed sites, silently shadowing every one of them
for the actual command real users and orchestrators run:

```bash
# bin/worker-cli, spawn) case, before this fix
MODEL="${4:-claude-sonnet-5}"
...
cd "$PLUGIN" && python3 -m src.spawn.spawn "$NAME" "$PROMPT_FILE" "$PROJECT" "$MODEL" $WORKTREE_FLAG
```

This resolved "no model argument" to the hardcoded literal **before** `spawn.py` ever ran, so
`spawn.py`'s `args.model` was never actually `None` on that path (the whole point of milestone
3's `default=None` change), and `spawn.py` in turn always handed `tmux_spawn.sh` a concrete
value, so `tmux_spawn.sh`'s own `_resolve_worker_model()` never fired either. Every piece
milestone 3 built — `spawn.py`'s Python-side resolution, `tmux_spawn.sh`'s shared bash function,
all 3 of its call sites — was individually correct and individually verified, **and the whole
assembled path for a real `worker-cli spawn <name> <prompt> <path>` call was still dead code.**
The config's `"worker"` key had zero effect on the command that matters.

## How this was found, and why it wasn't found sooner

It was NOT found by the milestone's own grep sweep — that grep was scoped to `src/`
(`grep -rn "claude-sonnet-5" --include="*.py" --include="*.sh" .` effectively limited to the
package the milestone's file list already named), and `bin/worker-cli` sits outside `src/`
entirely. It was found because the reviewer asked a direct tracing question — "which resolution
actually runs for `worker-cli spawn <name> <prompt> <path>` with no model argument" — that forced
following the REAL call path end-to-end instead of trusting that four fixed sites meant the
feature worked. The lesson generalizes past this one milestone: a file list handed to an
implementer is a hypothesis about where the behavior lives, not a fence, and grepping only inside
that hypothesis's boundary reproduces its blind spot exactly.

## Whole-repo grep after the fix — confirming no sixth site

`git grep -n "claude-sonnet-5"` (all git-tracked files, not `src/`-scoped) after the fix, full
hit list with disposition:

| File:line | What it is | Disposition |
|---|---|---|
| `bin/worker-cli:32` | User-facing `--help` text describing the model precedence | Updated to describe the real chain (was stale, describing only the old hardcoded default) |
| `bin/worker-cli:686` | `MODEL="${4:-}"` | The fix itself — passes an empty string through instead of pre-resolving |
| `src/spawn/spawn.py:17` | `_DEFAULT_WORKER_MODEL = "claude-sonnet-5"` | Intentional — the single, correct last-resort fallback constant |
| `src/spawn/tmux_spawn.sh:507,525` | `_resolve_worker_model`'s doc comment + its own `echo "claude-sonnet-5"` fallback line | Intentional — the bash-side mirror of the same last-resort fallback |
| `src/spawn/DOCS.md` (2 entries) | Documentation of the resolution + the fix | Left as accurate documentation |
| `dev/model_selector/DOCS.md`, `verify_worker_model_precedence.sh`, `verify_spawn_model_resolution.md` | Test assertions and docs referencing the fallback string, and documentation of the bug/fix itself | Left — these are what's testing/describing the intentional fallback and its history |
| `process-docs/worker_spawn/spawn_architecture_2026-07.md:12` | Historical process-doc describing the pre-milestone-3 architecture | Left untouched — write-once, describes the state as of 2026-07, not maintained forward |

No sixth site. Both hardcoded-fallback occurrences that remain (`spawn.py`'s constant,
`tmux_spawn.sh`'s echo) are the deliberate, single source-of-truth fallback each language side
needs — not additional hardcode sites competing with the config.

## Why the original 12/12 test suite didn't catch it, and what closes that gap

The original `verify_worker_model_precedence.sh` (12/12 passing before this fix) drove
`_resolve_worker_model()` directly and the real `${4:-...}`/revive expansion **patterns** — real
code, not reimplemented, but exercised in isolation via `source tmux_spawn.sh`. That proves each
piece is internally correct; it says nothing about whether the pieces are actually wired together
along the path a user's command takes. `bin/worker-cli` was never in that call chain at all.

Fix: extended the same script with a real-entry-point section that invokes the actual
`bin/worker-cli spawn` binary via subprocess — no sourcing, no direct function calls, the literal
command an orchestrator runs. First run (before realizing a second issue) failed exactly where it
should: got `claude-sonnet-5` instead of the config's `claude-e2e-verify-9999` for the no-model-arg
case, proving the bug live. Investigating the failure surfaced a **second**, purely
environmental gap: `bin/worker-cli` resolves its own `$PLUGIN` path from `CLAUDE_PLUGIN_ROOT`,
falling back to the **installed plugin cache** (`~/.claude/plugins/cache/.../iterative-dev/1.0.0/`)
when unset — confirmed live that the installed copy still carried the pre-fix code. A real-call
test that doesn't override `CLAUDE_PLUGIN_ROOT` silently exercises the wrong `spawn.py`, passing
or failing for a reason unrelated to the worktree's actual changes. Fixed by exporting
`CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT"` (this worktree) before the real call. After both fixes:
16/16, including 2 new real-subprocess cases (no model arg → config wins end-to-end through both
the generated runner script's `--model` and the tmux `WORKER_MODEL` env var; explicit arg → still
wins).

## Verification, precisely stated

- Real subprocess call to `bin/worker-cli spawn <name> <prompt> <path> "" --no-worktree` (no
  model arg, `CLAUDE_PLUGIN_ROOT` pointed at this worktree, `MODEL_SELECTION_FILE` pointed at a
  temp config, `CLAUDE_BIN` pointed at a mock that never runs a real Claude process,
  `WORKER_REGISTRY_DIR` pointed at a temp dir, `PROXY_PROJECT_PATH` unset): the config's
  `"worker"` value (`claude-e2e-verify-9999`) was confirmed present in BOTH the generated
  runner script's `--model` argument and the real tmux session's `WORKER_MODEL` environment
  variable (the same value `worker_revive` would later read back).
- Same real entry point with an explicit model argument: the explicit value won, config never
  consulted.
- Whole-repo (`git grep`, all tracked files) sweep for `claude-sonnet-5` — full hit list above,
  no sixth site.
- All tmux sessions, runner scripts, and `.done` marker files created by the real-call test were
  killed/removed after each case; the real `~/.claude/shared-rules/model_selection.json`,
  `~/.claude/.worker-registry`, and plugin cache were never touched.

## Cross-reference

See `process-docs/model_selector/2026-08-28_milestone3_launcher_and_worker_readers.md` for the
rest of milestone 3 (launcher config reader, Hook 17 retirement) — that entry's own "Finding"
section first surfaced the fifth site; this entry is the follow-up fix and the fuller accounting
the reviewer asked for. See `2026-08-28_milestone1_queue_removal.md` for the standing
`setup_py2app.py` hazard, unrelated to this fix and not exercised here.
