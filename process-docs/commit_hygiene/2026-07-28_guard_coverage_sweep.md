# commit-msg Guard — Coverage Sweep + Inheritance Measurement (2026-07-28)

## Scope of the sweep

Earlier surveys searched `~/Documents` only and found 22 repos. Widening to the whole home
directory (`find ~ -name .git -maxdepth 8`, excluding `venv/`, `node_modules/`, `Library/`,
`.Trash/`, `site-packages/`, `.cache/`) returned **37**. The 15 extra repos were not new work —
they were structurally invisible to the narrower scope:

| Group | Count | Note |
|---|---|---|
| Own projects | 19 | the only group that can be unguarded |
| Worktrees | 9 | wohnung ×4, Mineru ×2, monitor-cc ×2, trading ×1 |
| Under `~/.claude/` | 7 | 5 auto-materialized plugin caches + marketplace + shared-rules |
| Foreign vendor source | 2 | `llama.cpp` (under rag-cli), `tmux` (under monitor-cc/repo) |

The `~/.claude/` group is the reason a `~/Documents`-scoped sweep is structurally insufficient:
plugin caches are git repos created by the plugin system, outside any project tree.

## Coverage result: 8 repos were running with NO hooks

All 8 carried a repo-local `core.hooksPath` pointing at a **non-existent** directory — a leftover of
the retired beads task system. Since `core.hooksPath` is a single value and not a stack, the setting
fully masked the global guard while resolving to nothing:

| Repo | stale hooksPath value |
|---|---|
| gh-cli, reddit-cli, websearch, iterative-dev, wise2627 | `.beads/hooks` (relative) |
| linkedin | `…/MCP/linkedin/.git/hooks` (absolute, foreign project) |
| rag-cli | `…/MCP/RAG/.beads/hooks` (absolute, foreign project) |
| ClaudeCode(-Suite) | `.beads/hooks` — repo itself retired, see below |

The two absolute-path cases are the same class of failure but harder to spot: they name a plausible
directory in a *different* project rather than an obviously missing local one.

Fix: `git config --local --unset core.hooksPath` on 7 repos. Post-check via
`git rev-parse --git-path hooks` → all 7 resolve to `/Users/…/.githooks`.

`monitor-cc` keeps its local `.githooks` (post-commit/post-merge run `hook_setup.py`) and its own
byte-identical copy of the guard — `diff -q` against the global file confirmed identical.

## Inheritance: measured, not assumed

The prior entry listed worktree/clone inheritance as an unverified gap. Measured in a throwaway repo
under `/tmp` (deleted afterwards), by attempting real commits:

| Context | hooks path resolved | `Co-Authored-By` commit |
|---|---|---|
| fresh `git init` | global `~/.githooks` | rejected |
| fresh `git clone` | global `~/.githooks` | rejected |
| `git worktree add` | global `~/.githooks` | rejected |

Guard behavior in the fresh repo, all four cases:

1. clean message → commit created
2. `Co-Authored-By:` trailer → rejected
3. `Generated with Claude Code` banner → rejected
4. `GIT_AUTHOR_NAME=Somebody Else` env override → rejected (`git var` catches it)

`git rev-list --count HEAD` = 1 afterwards — the three rejected commits genuinely did not enter the
history, so the guard aborts rather than warns. The monitor-cc copy was invoked directly on a
message file: rejects the trailer, exits 0 on a clean message.

## ClaudeCode-Suite repo retired

`~/Documents/ai/Meta/ClaudeCode` was a shell: **2 of 103 tracked files still existed on disk**, and
both were git's own config files (`.gitignore`, `.gitmodules`). Its content had long since moved into
the standalone repos under `cli/`. Last 3 commits (unpushed) were all beads backups, newest 2026-03.
`.gitmodules` referenced two submodules (`MCP/github`, `MCP/searxng`) whose directories no longer
exist. The GitHub remote was already gone — `gh repo view` could not resolve it.

Removed locally: `.git` (moved to `/tmp`, not deleted, for short-term recoverability), `.gitmodules`,
`.gitignore`. Preserved untouched: the 8 standalone repos under `cli/`, and `Project.md/` (a
directory of 11 active project notes that the repo never tracked).

## State as of this entry

37 repos on disk, 0 with a stale or masking `core.hooksPath`. Every repo either resolves to
`~/.githooks` or (monitor-cc only) to a local copy of the same guard.

## Residual gap

A future repo setting its own `core.hooksPath` still bypasses the guard silently — `hooksPath` has no
layering, so nothing detects this except a repeat sweep. The sweep must span the whole home
directory, not just `~/Documents`.
