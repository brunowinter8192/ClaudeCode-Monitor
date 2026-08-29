# src/dual_log_cli/

## Role

Read-only command-line inspector for the six-stream dual-log quartet in `src/logs/dual_log/`
written by `src/proxy/addon.py`. Turns ~15 GB of unreadable JSONL — every `_original` line
re-embeds the entire conversation history, so grep and head report every content hit once per
subsequent request — into a session inventory and a deduplicated per-session turn timeline.
Touch this package to add read-side views over the dual logs. Do NOT add anything here that
writes, creates or locks a path under `src/logs/dual_log/`: the logs are frozen evidence and the
proxy appends to them live during a session.

## Public Interface

`__init__.py` is a package marker only — no exports. The entry path is the module runner:

```bash
./venv/bin/python -m src.dual_log_cli sessions [CONTEXT] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
./venv/bin/python -m src.dual_log_cli timeline <stem-or-substring>
./venv/bin/python -m src.dual_log_cli expand <stem-or-substring> <turn> [--before N] [--after N]
./venv/bin/python -m src.dual_log_cli expand <stem> <turn> --full --before N --after N [--only CLASSIFIER]
./venv/bin/python -m src.dual_log_cli search <term> [SCOPE] [--since D] [--until D] [--case-sensitive]
```

Run from the project root. `bin/duallog` (repo root, mode 755) is the PATH-facing form: it cds to
the hardcoded repo root and execs the same module, so `duallog <command>` works from any cwd once
symlinked into PATH. Hardcoded on purpose — a symlink must always run the main checkout, never
whatever worktree the script was copied into.

The log directory is resolved from `MONITOR_CC_ROOT`, else the repo root, else the main checkout
when running inside `.claude/worktrees/<name>/` — the log directory is gitignored and exists only
in the main checkout.

## Flow

`__main__` parses argv → `discovery` resolves the log dir and groups `*.jsonl` by session stem →
`sessions` builds one inventory row per stem from that stem's `_forwarded` stream alone, with
`project_map` resolving each worker stem's 8-hex project id once per run;
`timeline` resolves one stem, then `reader` reverse-seeks the last non-haiku `_original` line and
parses only that line → `timeline` builds turn rows via `proxy.message_summary` plus request
boundaries from `_forwarded.counts.messages`. `search` selects a SET of sessions the same way
`sessions` does (scope + date window), then repeats that per-session reconstruction for each one
and streams its blocks through the matcher, skipping any session whose timeline will not load.
`expand` reuses the timeline of one session and slices an anchor-centred window out of its turn
rows — classifier lines by default, full block content with `--full` → `render` emits plain
terminal text to stdout.

## Modules

### __main__.py (271 LOC)

**Purpose:** argparse dispatch for the four subcommands plus the optional `CONTEXT` / `SCOPE` positionals and the `--since` / `--until` / `--before` / `--after` / `--full` / `--only` / `--case-sensitive` variants, `expand`'s two-mode argument rules (`_run_expand` / `_run_expand_full` / `_window`), the shared `_reject_bad_days` validator, the per-session search loop with its skip-on-unloadable guard, day-flag validation via `strptime` (rejects impossible dates, not just wrong shapes), the shared `_load_for` session resolution, the process exit codes, and the broken-pipe guard.
**Reads:** `sys.argv`; the resolved dual_log directory via `discovery`.
**Writes:** stdout (rendered text), stderr (resolution, range and empty-term errors). Never touches the log directory.
**Called by:** the user, via `python -m src.dual_log_cli` or `bin/duallog`.
**Calls out:** `discovery`, `render`, `search`, `timeline` (all package-local).

---

### project_map.py (77 LOC, 2026-08-29)

**Purpose:** Resolves the proxy's `md5(project_path)[:8]` session id — the only trace of a worker's project in its stem — to a project label. Scans `~/.claude/projects/*/`, takes the first `cwd` record out of the newest transcript per directory, and hashes those real paths with the production helper. Reads CC's transcript store, never the dual logs.
**Reads:** `~/.claude/projects/<encoded>/<uuid>.jsonl` (first ~40 lines of up to 3 newest transcripts per project dir).
**Writes:** Nothing — returns `{sid8: label}`; `{}` on any failure, which degrades rendering to the `<sid8>` fallback rather than erroring.
**Called by:** `discovery.list_sessions` (once per run, shared across all sessions), `__main__._load_for`.
**Calls out:** `src/proxy_display/forwarded_parser.py` (`_proxy_session_id_for_project` — the single source shared with `addon.py`'s `_derive_session_id`, never re-derived here); stdlib (`json`, `os`, `pathlib`).

---

### discovery.py (190 LOC)

**Purpose:** Log-directory resolution, stem grouping, context rendering (`context_for_stem`, pure — the project map is injected, not looked up), the session inventory, all session selection in one place (`filter_sessions` — a `context` substring for `sessions`, a broader `scope` substring matching context OR stem for `search`, plus an inclusive start-day window, all ANDed), and stem/substring resolution with explicit ambiguity and unknown errors (`AmbiguousSessionError`, `UnknownSessionError`).
**Reads:** `MONITOR_CC_ROOT`; the dual_log directory listing; each stem's `_forwarded.jsonl` in full; `stat().st_size` of all six streams.
**Writes:** Nothing — returns dicts.
**Called by:** `__main__.py`, and indirectly by `timeline.load_timeline` through the session dict it is handed.
**Calls out:** `reader` (`infer_family`, `iter_jsonl`).

---

### reader.py (102 LOC)

**Purpose:** The read-only file primitives. Reverse chunked line-offset scanner, cheap model sniff, last-conversation-request loader, small-file JSONL iterator, and `infer_family` (the haiku/sonnet/else→opus rule shared with `addon.py` and `dev/proxy_dual_log/`).
**Reads:** `_original` (byte ranges only, never whole-file) and any small stream line by line.
**Writes:** Nothing.
**Called by:** `discovery.py`, `timeline.py`.
**Calls out:** stdlib only (`json`, `re`, `pathlib`).

---

### timeline.py (205 LOC)

**Purpose:** Turn-row construction for one payload, `iter_block_texts` (the block-text generator both `search` and the full-turn dump build on), single-turn full extraction, request-boundary derivation from the `_forwarded` delta stream, `build_turn_times` (turn → timestamp of the request that first carried it), and `load_timeline` as the one call that assembles everything a render needs.
**Reads:** The parsed last-request payload; the session's `_forwarded.jsonl`.
**Writes:** Nothing — returns row lists, a generator, and one data dict.
**Called by:** `__main__.py`, `search.py`.
**Calls out:** `src/proxy/message_summary.py` (`_summarize_message` — imported, not copied), `reader`.

---

### search.py (43 LOC)

**Purpose:** The literal-substring matcher over one session's deduplicated timeline. Returns one hit per matching (turn, block) with an occurrence count and a whitespace-collapsed context snippet.
**Reads:** The parsed payload, streamed block by block via `timeline.iter_block_texts`.
**Writes:** Nothing — returns the hit list.
**Called by:** `__main__.py`.
**Calls out:** `timeline`.

---

### render.py (206 LOC)

**Purpose:** All terminal output. Session table (START / CONTEXT / SESSION plus a count line), timeline with request markers, search results (one term line overall, then a `session <stem>` line plus its hit lines per matching session, blank-line separated, with an optional skipped-sessions note), `expand`'s two renderers (classifier-only overview with a `▶` anchor mark, an HH:MM:SS request-time column and NO request markers, and the full-content window dump whose turn headers carry the same time), and the size/char/timestamp formatters. Rendering only — selection and filtering happen before a list reaches this module.
**Reads:** The dicts produced by `discovery`, `timeline` and `search`.
**Writes:** Nothing — returns strings; `__main__.py` does the `sys.stdout.write`.
**Called by:** `__main__.py`.
**Calls out:** `timeline` (`boundaries_by_index`).

---

## State

No mutable state — every command is a single pass with no caches, no module-level state, and no
files written anywhere.

Two inputs decide the output, though, and only one of them is the log directory. Worker contexts
are resolved through `~/.claude/projects/` (see `project_map.py`), so a run is reproducible only
while BOTH are unchanged: pruning CC's transcript store flips a worker's context from
`worker/<project>/<name>` to the `worker/<sid8>/<name>` fallback without the dual logs changing at
all. On a live session the output additionally tracks whatever the proxy has appended by then.

## Gotchas

**The last line of `_original` is usually NOT the conversation.** Every session file interleaves
haiku sidecar requests (1 message, ~0.5–2 KB) with the real family. `reader.load_last_request`
walks backwards past them via a 512-byte model sniff and only parses the first non-haiku line;
the timeline header reports how many were skipped. Any new read path must reuse that function
rather than taking the file's final line.

**Never parse an `_original` line to decide whether you want it.** Lines reach 15 MB. The
top-level key order written by `addon.py` is `timestamp, flow_id, request_id, model, payload`, so
`model` always sits in the first few hundred bytes — that is what makes the sniff cheap and the
4.94 GB file answerable in 0.16 s.

**`_forwarded` is a line-for-line mirror of `_original`, and that is load-bearing.** Verified:
identical line count and identical per-line `(model, message_count)`. The whole 62-session
inventory therefore reads 108 MB of `_forwarded` instead of 14 GB of `_original`. If a future
proxy change breaks that 1:1 alignment, `sessions` silently reports wrong request counts and the
timeline's request markers drift — re-verify the alignment before relying on it again.

**A message-count regression means CC restarted inside one log id.** The renderer prints an
explicit WARNING and stops trusting the earlier markers, because request boundaries before the
restart index into a message list that no longer exists. Do not "fix" this by clamping the
indices — the misalignment is real and must stay visible.

**`_summarize_message` returns `blocks == []` for string content.** CC delivers `role='system'`
messages as plain strings, so `timeline.build_turns` and `timeline.iter_block_texts` synthesize a
single pseudo-block from `content_preview`. A renderer or matcher that assumes a non-empty block
list will drop every system turn.

**A broken pipe can surface at two places, and catching only the first is not enough.** With
`| head`, EPIPE hits either the `sys.stdout.write` inside `main()` or the interpreter's shutdown
flush after `main()` returned cleanly — which output size lands where is not predictable, so both
must be handled. `__main__.py` flushes INSIDE the guard and, on failure, `dup2`s the stdout fd to
`/dev/null` so the shutdown flush has nothing left that can fail. Dropping either half brings back
`Exception ignored while flushing sys.stdout: BrokenPipeError` on stderr — measured, not
theoretical, and it only reproduces on some sessions.

**The date filter compares ISO string prefixes, which only works because the format is fixed.**
`filter_sessions` slices `YYYY-MM-DD` off the `_forwarded` timestamp and compares lexicographically
— identical to calendar order for that exact format, and no timezone maths. If the timestamp source
ever changes shape or width, the filter keeps running and silently returns wrong sets.

**The two `sessions` filters treat a missing start timestamp differently, on purpose.** A DATE
filter drops such a session — it cannot be placed on a calendar. A CONTEXT filter keeps it, because
its context is known either way. Collapsing both into one "skip incomplete sessions" rule would
silently hide sessions from a context query.

**The context filter matches the RENDERED context value, family prefix included.** That is what
makes `opus/` and `worker/` usable as selectors, and they partition the corpus exactly (measured:
31 + 30 = 61). Matching only the name part would break both.

**A worker's project label must be spelled exactly like the main sessions' label, or the whole
point is lost.** Main stems carry a sanitised label (`opus_gh_cli_…`, `opus_monitor_cc_…`), so
`project_map.project_label()` applies the same rule to the resolved path — basename with `-`
collapsed to `_`. That is what lets ONE filter term (`websearch`) return a project's main sessions
AND its workers. Change either side's spelling and they silently stop meeting.

**The proxy hashes the MAIN project path, never the worktree.** Workers of one project therefore
share a single `sid8` (measured: 9 websearch workers all on `52fce57c`). The map does contain
worktree paths too — 157 of 166 entries — but those ids never appear in a worker stem, and there
are zero hash collisions across all 166 paths. Do not "fix" the map by filtering worktrees out; it
costs nothing and would only remove a harmless superset. Related near-miss: `tmux_launcher.py`
hashes the NORMALISED path, so its `monitor_cc_<hash8>` session names are not interchangeable with
these ids.

**A search hit is one (turn, block) pair, never one occurrence.** A block containing the term N
times stays one hit carrying `×N`. Changing that granularity changes every reported hit count, so
it is a contract, not a formatting detail. Since 2026-08-29 the header no longer states the totals,
so hits, turns and occurrences are read off the lines — the `×N` markers are the only place the
occurrence count survives.

**`expand`'s 30 is a FLOOR in overview mode, not a default.** An explicitly smaller `--before 5`
or `--before 0` is raised to 30; only values above it are honoured. The mode exists to show what
surrounds a turn, and a reader who narrows the window defeats that without noticing. Read mode
(`--full`) is the opposite: both bounds are REQUIRED explicit numbers with no floor, because there
the caller is paying for every dumped character.

**`expand`'s time column is the REQUEST's time, not a per-message time.** A turn shows when the
request that FIRST carried it was sent — derived by walking `_forwarded`'s `counts.messages` chain,
where turn N belongs to the earliest request whose count exceeds N. Turns that arrived in the same
request therefore share one timestamp, which is why the column typically repeats in threes
(assistant / user / system). It is a send time, not a per-turn duration, and nothing in the dual
logs offers the latter.

**A `?` in the time column means a restart discarded the chain, not that data is missing.**
`build_turn_times` walks only the chain from the LAST restart onward and leaves every turn below
that restart's message count unmapped — the requests that first carried those messages described a
different message list and cannot be walked against the final one. Measured: 766/766 turns mapped
in a restart-free session, 504/506 in the `/clear` session with exactly turns 0 and 1 unmapped.
Same conservative stance as the timeline's WARNING; do not "fix" it by falling back to the
pre-restart requests.

**Request markers belong to `timeline`, not to `expand`.** The overview used to interleave the
same `── REQ n ──` lines; they were dropped 2026-08-29 because `expand` navigates by turn index and
a second numbering system in the same block is noise. `timeline` keeps them unchanged — it is the
view where request boundaries ARE the structure. Anything reintroducing them here should first
answer which of the two indices the reader is supposed to follow.

**`--only` matches the MESSAGE-level classifier, not block types.** A turn whose message type is
`tool_use` typically also carries `thinking` and `text` blocks, yet `--only thinking` will not
select it — the filter compares against the turn's role and its message type, the same two values
the overview lines print. That keeps overview and read mode talking about the same units; a
block-level filter would need a different flag and a different output shape.

**`timeline --turn N [--full]` no longer exists** (removed 2026-08-29). `expand <s> <t> --full
--before 0 --after 0` is the replacement for a single-turn read. Unlike `search`'s argument flip,
this break is LOUD — argparse rejects `--turn` as an unrecognized argument with exit 2 — because
the flag was deleted rather than reinterpreted.

**`search` takes the TERM FIRST, and the old order fails silently.** The 2026-08-29 redesign
flipped `search <session> <term>` to `search <term> [scope]`. Both arguments stay structurally
valid under the new signature, so an old-style call is not rejected — it searches for the stem as
a literal term and scopes by the intended term, printing `no match` with exit 0. Anything that
calls this command (a script, a skill, a habit) has to be updated deliberately; there is no error
to trip over.

**`scope` and `context` are different selectors on purpose.** `sessions <CONTEXT>` matches the
rendered context only; `search <term> <SCOPE>` matches context OR stem, so one argument covers both
"the whole websearch project incl. its workers" and "this one session id". Both live in
`filter_sessions` and are ANDed with the date window.

**An unscoped `search` reconstructs every session, and that is the entire cost.** Measured: 1.42 s
over 61 sessions, unchanged between a common and a rare term — the matching is free, the per-session
last-request reconstruction is not. Scope or date flags are what make it fast, not a cheaper search.

**An empty search term matches nothing, deliberately.** `str.count("")` counts positions, so a
blank needle would report every block of the session as a hit. `find_matches` returns `[]` for it,
and `__main__` rejects a whitespace-only term with exit 2 before that ever matters.
