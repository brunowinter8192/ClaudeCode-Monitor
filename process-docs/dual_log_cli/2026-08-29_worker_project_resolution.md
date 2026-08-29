# 2026-08-29 — Making worker sessions selectable by project

Fifth entry of this area. Worker sessions rendered as `worker/<name>`, so the context filter could
find `worker/discovery` but had no way to answer "everything that happened in the websearch
project". The project exists in a worker stem only as `md5(project_path)[:8]`
(`addon.py::_derive_session_id`), e.g. `api_requests_worker_52fce57c_discovery_…`. Goal: render
`worker/<project>/<name>` by resolving that id, without a hardcoded per-project map in code.

## Where the mapping comes from

**CC's own session transcripts.** `~/.claude/projects/` holds one directory per project cwd, and
the records inside carry the real absolute path in a `cwd` field. The directory *names* encode the
path lossily — `-Users-…-cli-gh-cli` cannot be decoded without knowing whether a `-` is a separator
or a literal hyphen — but the `cwd` value needs no decoding at all.

Mechanism: per project dir, open the newest transcript and scan the first ~40 lines for the first
record carrying `cwd`. Scanning only line 1 returns nothing — the opening records are `mode` and
`permission-mode` entries without the field, which is what made the first attempt yield zero paths.

Measured: **166 distinct cwd values from 175 project dirs in 0.03 s**, **0 hash collisions**.

Hashing reuses `_proxy_session_id_for_project()` from `src/proxy_display/forwarded_parser.py` —
the helper whose own comment calls it the single source, byte-identical to `addon.py`'s
`_derive_session_id`. Re-deriving `md5(path)[:8]` locally would have been a second definition of a
value that must never drift.

## Result

All five worker ids in the corpus resolved, and the worker names corroborate each mapping
independently:

| sid8 | project | workers |
|---|---|---|
| `52fce57c` | websearch | discovery, hookfix, lane-choice, lane-judge, lane-metrics, steal-probe, watchdog-removal, … |
| `25c51a2e` | monitor-cc | model-selector, rule-injection, thinking-pane, tt-delta-skip, verbosity-k2 |
| `64b2ab20` | jobscraper | portal-sweep, state-relocate, stepstone-probe |
| `79b52c8d` | wise2627 | anhaenge, chore-*, tracker, tunnel, localtime, … |
| `e5917974` | gh-cli | buildlog, duallog |

`sessions websearch --since 2026-08-28 --until 2026-08-28` went from 2 sessions to 4 — both opus
sessions plus the `hookfix` and `discovery` workers. Unfiltered, `sessions websearch` went from 6
to 15.

## Sources evaluated and rejected

- **`~/.claude/.worker-registry/<name>`** — one file per worker holding its project path: exactly
  the right data, but only for LIVE workers (4 at the time). Nothing for historical logs.
- **Decoding the `~/.claude/projects/` directory names** — needs `-`-vs-`/` disambiguation by
  probing the filesystem. Workable, but a heuristic where the `cwd` field is ground truth.
- **The dual logs themselves** — `_original` payloads do carry the cwd in CC's env block, but
  reading it means parsing a multi-MB line per session, turning a 0.23 s inventory into minutes.
- **`src/logs/.proxy_live_<id>_…/`** — the directory name carries the id, the contents are only a
  frozen copy of the proxy package. No path anywhere.
- **tmux session names** (`monitor_cc_<hash8>`) — `tmux_launcher.py` hashes the NORMALISED path,
  not the raw one, so those hashes are not interchangeable with the proxy's. Recorded because the
  two look identical at a glance.

## Decisions

**The label is sanitised to match the main-session spelling.** Main stems already carry
`opus_gh_cli_…` / `opus_monitor_cc_…`, so the resolved path's basename gets the same treatment
(`-` → `_`). Without that, `websearch` would match the opus sessions and `worker/websearch/...`
would need a different term — which is the entire feature. Cross-checked: every main label in the
logs (`gh_cli`, `jobscraper`, `linkedin`, `monitor_cc`, `websearch`, `wise2627`) matches a real cwd
basename under this rule.

**The map is injected, not looked up.** `context_for_stem(stem, project_map)` stays a pure string
transform, testable without a filesystem; `list_sessions` builds the map once and shares it. The
alternative — resolving inside the renderer — would have made every unit test depend on the machine's
transcript store.

**Unresolvable ids render `worker/<sid8>/<name>`.** Still filterable, by the id itself: under a
forced-empty map, filtering `52fce57c` returns that project's 9 sessions. This path is real, not
theoretical — two ids present in this area's opening entry have since rotated out of both the logs
and the transcript store.

## Verification

- Pure-renderer unit cases with an injected map: **8/8** — resolved, fallback, empty map, `None`
  map, main sessions untouched.
- Forced fallback (`build_project_map` pointed at an empty dir): workers render
  `worker/25c51a2e/rule-injection`, sid8 filtering still returns 9 sessions, and `websearch` falls
  back to the 6 opus-only matches — i.e. exactly the pre-change behaviour.
- Nonexistent projects root: fail-open, empty map, no error.
- Regressions: `opus/` 31 + `worker/` 30 = 61 (exact partition), `gh_cli` 4, `duallog` 1,
  `monitor_cc` on 08-28 5; `timeline`/`search` headers show the new context; `search milestone`
  unchanged at 26 hits in 23 turns.
- Runtime 0.23 s → **0.27 s** for 61 sessions; the map costs ~0.03 s and is not cached to disk.

## What this costs

The command's output is now a function of TWO stores, not one. Pruning `~/.claude/projects/` flips
worker contexts to the sid8 fallback while the dual logs are untouched — the package's State
section was rewritten to say so, since it previously claimed a run depends on the log directory
alone.

One spelling asymmetry worth knowing: one project directory is literally named `Posts` while its
main-session stems say `posts`. Context matching is case-insensitive, so a `posts` filter catches
both — but that is the only reason they meet.
