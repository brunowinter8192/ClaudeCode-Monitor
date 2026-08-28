# Milestone 3 — launcher + worker readers for model_selection.json, Hook 17 retired

2026-08-28

## Scope

Third milestone of the model-selector line of work, cross-repo (monitor-cc + the iterative-dev
plugin). Milestone 2 gave the menubar a Models tab that writes
`~/.claude/shared-rules/model_selection.json` (`{"main": ..., "worker": ...}`); nothing read it.
This milestone adds the two readers and retires a hook whose policy the new config contradicts.

**Part A (monitor-cc, `src/claude_proxy_start.sh`):** added the config file as a third,
lowest-precedence tier below explicit `--model` and the `--fable`/`--opus` shortcuts. Read via
`jq -r '.main // empty'` — chosen over hand-parsing because `jq` is already a real, working
dependency of the sibling plugin script (`tmux_spawn.sh`) that reads this same file, and because
JSON malformation handling is exactly the place hand-rolled parsing gets fragile. Guarded with
`command -v jq` (same idiom the script already uses for `worker-cli`), so a missing binary
degrades to "nothing injected," never a launcher failure.

**Part B (iterative-dev plugin, `src/spawn/`):** added a shared `_resolve_worker_model()` in
`tmux_spawn.sh` (same `jq ... 2>/dev/null || true` fail-open idiom already used for the
`hooks.json` read in `_worker_detect_status` — this file runs under `set -euo pipefail`), wired
into `spawn_claude_worker`'s and `spawn_claude_worker_from_file`'s `${4:-...}` defaults and into
`worker_revive`'s WORKER_MODEL-absent fallback. `spawn.py`'s `model` argparse default changed from
the hardcoded literal to `None`, with `args.model or _resolve_worker_model()` (Python-side,
stdlib `json`) resolving before anything reaches bash.

**Part C (monitor-cc, hooks):** deleted `block_worker_spawn_opus.py` (Hook 17 — blocked `opus` as
a worker-cli spawn model argument), removed its `hook_setup.py` registration entry and all 3
`DOCS.md` mentions (dedicated section, `_shell_strip.py`'s user list, the Gotchas shared-list).
No manual `~/.claude/settings.json` edit — `.githooks/post-merge` (confirmed active via `git
config core.hooksPath` = `.githooks`) re-runs `hook_setup.py` automatically on any merge touching
`src/hooks/`, and `hook_setup.py`'s own `_sweep_stale_hooks()` removes the now-dead path entry on
that run.

Verified: launcher precedence — 12/12 checks (`dev/model_selector/verify_launcher_model_precedence.sh`,
monitor-cc) covering all 4 tiers plus the 3 degradation cases, against a temp config path.
Worker-model resolution — 12/12 (`dev/model_selector/verify_worker_model_precedence.sh`, plugin)
driving the real sourced `_resolve_worker_model()` and the real `${4:-...}`/revive-fallback
expansion patterns; 1 Python probe (`verify_spawn_model_resolution.py`, plugin) confirming
`args.model` is real `None` (never the string `"None"`) when omitted and the resolved model
passed onward is always a concrete non-empty string. Hook removal — file gone, registration entry
gone, `_sweep_stale_hooks()` verified correct on a synthetic in-memory dict (never the real
settings file). `setup_py2app.py` was not run (standing constraint, unrelated to this milestone's
files anyway). NOT verified: an actual live `worker-cli spawn`/`claude_proxy_start.sh` run against
a real config file — that's a user check after merge.

## Finding — `bin/worker-cli` shadows BOTH new resolution paths for the primary spawn command

Traced the real, complete call path for `worker-cli spawn <name> <prompt> <path>` (no model
argument) end-to-end, past what the milestone's four listed hardcode sites covered. `bin/worker-cli`
itself — a fifth site, not in the original list of four, git-tracked at the plugin repo root — has
its own pre-existing line in the `spawn)` case:

```bash
MODEL="${4:-claude-sonnet-5}"
...
cd "$PLUGIN" && python3 -m src.spawn.spawn "$NAME" "$PROMPT_FILE" "$PROJECT" "$MODEL" $WORKTREE_FLAG
```

This resolves the "no model argument" case to the hardcoded literal `claude-sonnet-5` BEFORE
`spawn.py` is ever invoked, and always passes a concrete, non-empty string as `spawn.py`'s model
argument. Consequence: for the actual `worker-cli spawn` command — the real, primary entry point
orchestrators use — `spawn.py`'s `args.model` is never `None` in practice, so its own
`_resolve_worker_model()` never fires; and since `spawn.py` in turn always hands `tmux_spawn.sh` a
concrete value, `tmux_spawn.sh`'s own `_resolve_worker_model()` at the `spawn_claude_worker`/
`spawn_claude_worker_from_file` sites never fires either. **As shipped, the config's `"worker"`
key has no effect on a `worker-cli spawn` call with no model argument** — the worker always gets
`claude-sonnet-5`, exactly as before this milestone, because `bin/worker-cli` intercepts upstream
of both new resolution paths.

**What IS load-bearing today:**
- `worker_revive`'s fallback (`tmux_spawn.sh`) — genuinely reachable; revive never goes through
  `bin/worker-cli`'s `spawn)` case at all. A worker revived after a death with no stored
  `WORKER_MODEL` in its tmux environment WILL pick up the config.
- `spawn.py`'s own resolution — reachable only by a caller that invokes
  `python3 -m src.spawn.spawn <name> <prompt> <path>` directly, bypassing `bin/worker-cli`
  entirely (a real but narrow case, e.g. a script or a future different entry point).
- `tmux_spawn.sh`'s bash-side resolution at the other two sites — reachable only by a direct
  source-and-call of `spawn_claude_worker`/`spawn_claude_worker_from_file` with the model argument
  actually omitted or empty, likewise bypassing `bin/worker-cli`.

**Not fixed here** — `bin/worker-cli` was not in this milestone's approved scope (four sites,
all in `src/spawn/`), and unilaterally editing a fifth, unlisted site was judged out of bounds
without explicit sign-off. Flagged as the deciding follow-up: a future milestone (or an amendment
to this one) needs to change `bin/worker-cli`'s own `MODEL="${4:-claude-sonnet-5}"` line to
`MODEL="${4:-}"` (or otherwise stop pre-resolving there) so the argument actually reaches
`spawn.py` as empty/unset and its `_resolve_worker_model()` gets a chance to run for the primary
`worker-cli spawn` path.

## Cross-reference

See `process-docs/model_selector/` for milestones 1 (Queue-tab removal) and 2 (Models tab). The
`setup_py2app.py` deploy-from-worktree hazard flagged in milestone 1's entry still stands and was
not tested against in this milestone.
