# Global commit-msg Guard — 2026-07-28

## Trigger

Question raised while reviewing GitHub's repo page: the Contributors panel of `monitor-cc` lists a
second contributor ("claude") next to the owner. Audit of the actual commit objects: **all 2186
commits carry exactly one author identity** (`Bruno Winter <brunowinter8192@github.com>`), author and
committer identical throughout. The second contributor comes purely from `Co-Authored-By:` trailers
in commit message BODIES — GitHub counts those as contributors.

526 commits carry such a trailer, spread over 9 distinct spellings (`Claude`, `Claude Sonnet 4.6`,
`Claude Opus 4.6 (1M context)`, `Claude Haiku 4.5`, …). The newest is dated 2026-05-21; nothing
since. That break matches the codified commit rule ("no Co-Author footer for routine commits") taking
effect — the trailers stopped on their own, no cleanup was ever run.

## Decision: guard forward, do not rewrite history

Rewriting 526 commits to drop the trailers would change every hash on an already-pushed 2186-commit
history for a purely cosmetic panel entry. Rejected. Instead: a guard that makes it impossible for a
new trailer or a foreign identity to enter.

## Implementation

`~/.githooks/commit-msg`, wired machine-wide via `git config --global core.hooksPath ~/.githooks`.
Two checks, both **rejecting** rather than silently rewriting — a visible abort reveals that
something TRIED to write the trailer, which a silent scrub would hide:

1. **Message body** — `Co-Authored-By:` lines, and tool-attribution banners matching
   `(generated with|🤖 generated|created with).*(claude|copilot|cursor|codex)`.
2. **Identity** — author and committer compared against the expected name/email. Read via
   `git var GIT_AUTHOR_IDENT` / `GIT_COMMITTER_IDENT`, not `git config`: `git var` resolves the value
   git will ACTUALLY record, so an identity injected through `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL`
   env vars is caught too. Verified — a `GIT_AUTHOR_NAME=…` override is rejected.

Written for bash 3.2 (macOS system bash): no `${var,,}`, labels passed explicitly.

Verified on 5 cases before install: clean message passes; Co-Authored-By rejected; generated-with
banner rejected; env-var identity override rejected; real identity passes.

## hooksPath is a single value, not a stack

`core.hooksPath` does not layer — a repo-local value fully overrides the global one, so any repo with
its own setting is invisible to the global guard. Survey of the repos on disk at the time:

| Repo | hooksPath before | after |
|---|---|---|
| Mineru, trading_ai, waschmaschine, Watch, wohnung | unset | global |
| trading | `…/Trading/.beads/hooks` (stale — directory did not exist) | unset → global |
| monitor-cc | `.githooks` (2 live hooks: post-commit, post-merge) | unchanged + guard copied in |

The `trading` entry was a leftover from the retired beads task system, pointing at a deleted
directory — meaning that repo had been running with NO hooks at all. Note the path also carried a
capital-T spelling (`/Documents/ai/Trading/`) which resolves only because the filesystem is
case-insensitive (same inode as the lowercase path).

`monitor-cc` keeps its local hooksPath (its post-commit/post-merge hooks auto-run `hook_setup.py` on
`src/hooks/` changes) and received its own copy of the guard — otherwise the one repo where most
commits happen would have been the only unguarded one.

## Known gaps

- A future repo setting its own `core.hooksPath` silently bypasses the guard; only a periodic sweep
  catches that.
- Worktree / CI checkouts with independent config are unverified.
- Fresh clones inherit the global setting (not verified end-to-end, expected by config semantics).
