# CR/CC Transcript Search Scoped to the Session's Own Project, 2026-09-03

Follows this area's usage-join entry of the same day directly: same feature, same join, but the
transcript lookup changed completely after review. The first version shelled out to `grep -rlF`
over the WHOLE `~/.claude/projects/` store (316 files, 1.3 GB at the time) for every `msgs`
invocation. That cost 6.97 s on the largest session, against 0.113 s before the feature — a
measured loss on every call, not a hypothetical one, and the review identified the CAUSE as scanning the
whole store rather than the `grep` binary itself. The fix scopes the search to the one or few
directories the session's own stem can possibly resolve to, in Python, no subprocess.

## The scoping insight

`project_map.py` already walks every `~/.claude/projects/*/` directory once per run and reads each
one's real `cwd` out of a transcript record — that walk is exactly what a stem needs to locate its
OWN directory, it was just being thrown away after collapsing straight to `{sid8: label}`.

- A **worker** stem (`worker_<sid8>_<name>_<ts>`) carries the sid8 = `md5(project_cwd)[:8]` of its
  MAIN project (proxy hashes the main path, never the worktree — an existing Gotcha). Reversing
  that hash-to-cwd direction gives the main project's cwd; the worker's OWN cwd is that same path
  plus `/.claude/worktrees/<name>`, the layout every worker actually runs under. Looking THAT cwd
  up in the cwd→directory map (the other half of the same walk) gives the one directory to search.
- A **main** stem (`opus_<label>_<ts>`) carries only the sanitised label, which is lossy (multiple
  cwds can share a basename), so every cwd whose `project_label` matches is kept as a candidate —
  plural on purpose.

`project_map.build_project_index` now exposes both shapes from ONE walk (`cwd_to_dir`,
`sid_to_cwd`) instead of the label-only map `build_project_map` returns; `build_project_map` itself
is now a one-line projection of the same index; `discovery.stem_identity` gives `usage.py` the raw
`(kind, sid_or_head, name_or_label)` tuple `context_for_stem` already computed for rendering,
without touching that rendering path.

Within the resolved directory (or directories), only `.jsonl` files whose mtime is at or after the
session's own start (the first boundary's timestamp) are read at all — a transcript predating the
session cannot contain it — and the search itself is a plain `fragment in file_text` check, first
match wins, no subprocess.

## The dropped ambiguity branch

The first version treated 2+ matching transcript files as unresolvable (`None`, same as zero
matches) — a defensive branch built without ever observing the case. The same-day sweep of the
whole corpus (this area's usage-join entry) found **zero** sessions where the anchor
request id appeared in more than one transcript, in the WHOLE store, not just within scope. There
is no observed failure to defend against, so the branch is gone: `_find_transcript` now takes the
first candidate (name order) that contains the fragment and stops. Scoping directories per stem
also makes a genuine collision far less likely than the store-wide version ever risked, since a
worker's OWN worktree directory and a main project's directory(ies) rarely — in the corpus, never —
overlap with another project's.

## Re-verification after the change

- **Timing**, same largest session as before (`opus_jobscraper_1788347399`, 368 MB `_original`):
  0.148 s (scoped) vs. 6.97 s (store-wide) vs. 0.113 s (pre-feature, no join at all). `gcommit-umlaut_1788367120`
  dropped from 0.07 s (with the store-wide grep already warm) to 0.104 s total run time — the search
  itself is now negligible relative to loading the session.
- **Correctness**, same session: separator lines byte-identical to the store-wide version's output
  (`diff` clean on the `^──` lines), confirming the scoped search resolves the exact same 306/308
  owners the unscoped search did.
- **Corpus-wide owner coverage**, re-run after the change: 1705/1720 owners resolved (99.13%) across
  22 sessions (the corpus grew live between sweeps, including this very work session's own dual
  log growing from 105 to 137 owners mid-task) — consistent with the store-wide version's 1637/1647
  (99.39%) on its own snapshot; the same handful of sessions carry the same residual shortfalls
  (the two fully-errored jobscraper sessions, the "200 status but absent from the transcript"
  sessions, and live-session lag), none of them newly introduced by the scoping change.
- **Byte-identity of the unrelated commands**: `sessions`, `expand` and `msgs`' msg/sub-lines
  re-confirmed identical via `git stash` against the previous commit (the store-wide version), not
  just against the pre-feature baseline — this change touched `discovery.py` and `project_map.py`,
  both used by `sessions`/`search`/`expand`, so their outputs needed re-checking, not just `usage.py`'s.
- New regression coverage replaces the old subprocess-dependent test: `_find_transcript` is
  exercised against fixture directories directly (in-scope hit, out-of-scope miss, mtime-cutoff
  miss), and `build_usage_by_flow` end to end for BOTH a main stem (label match) and a worker stem
  (sid8 → cwd → worktree cwd), all against a fixture `projects_root` — no dependency on a `grep`
  binary or the real store.
