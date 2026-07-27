# Cross-project worker merge — silent no-op, rules gap closed, 2026-07-27

## Symptom

`worker-cli merge sn-textblock-strip` returned `=== Merging sn-textblock-strip into main === Already
up to date` and exited 0. The worker's two commits sat unmerged on the target repo's branch; nothing
was lost, nothing was merged, and the output read like success.

## Mechanism

The worker was spawned into `trading` (spawn is always the current project) and then given a
cross-project worktree in `monitor-cc` via `worker-cli worktree`. Both repos end up with a branch of
the same name; all commits go to the `monitor-cc` one.

`resolve_worker_project` reads the registry, which holds two entries — `<name>` (spawn project) and
`<name>.worktrees` (target repo + branch). It resolves to the spawn project. The merge therefore ran
in `trading`, against `trading`'s empty same-named branch, on whatever branch `trading` happened to
have checked out (`main` at that moment, post session-recap). The identical branch name is what makes
the failure silent — a differing name would have errored out.

## What was already there

`bin/worker-cli` (iterative-dev) already accepts the override: `merge <name> [project_path]`, same for
`kill`, `status`, `capture`, `response`. Only `spawn`'s usage line documents a project path; the
others show `<name>` alone. So the capability existed and was invisible at every surface the
orchestrator reads.

`worker-cli merge sn-textblock-strip /Users/brunowinter2000/Documents/ai/monitor-cc` merged correctly
on the first try — 9 files onto `integration`.

## Rules changed (`~/.claude/shared-rules/`, outside both repos)

- `opus/workers.md` § Worker Project Scope: new rule — `merge`, `kill`, `status`, `capture`,
  `response` take `[project_path]` as their LAST argument; without it they resolve to the SPAWN
  project.
- `opus/workers.md` § Step 6 — Merge: `project_path` marked MANDATORY for a cross-project worker.
  The post-merge check previously read `Already up to date` → worker did not commit; it now splits
  the two cases (cross-project → re-run with the path; otherwise → investigate via `capture`).
- `opus/tool-use.md` § Worker CLI: `[project_path]` added to the five affected table rows; the
  auto-resolve note now says which project it resolves to.

Same pass: all 8 `§` cross-references across `shared-rules` normalised to `§ Section (Rule)` — four
had the whole reference wrapped in parentheses.

## Open

`~/.claude/shared-rules/` is not inside any repo touched here; whether it is versioned elsewhere was
not established. The rule text above is the record of what changed.
