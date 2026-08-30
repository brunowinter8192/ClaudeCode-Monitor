# src/dual_log_cli/

## Role

Read-only command-line inspector for the six-stream dual-log quartet in `src/logs/dual_log/`
written by `src/proxy/addon.py`. Turns ~15 GB of unreadable JSONL — every `_original` line
re-embeds the entire conversation history, so grep and head report every content hit once per
subsequent request — into a session inventory, a deduplicated search, a msg listing grouped by
request, and a full-content read of any msg window. The deduplicated msg timeline is the internal
data structure all four commands build on; it has no command that renders it whole, because the two
views worth having are the request-grouped classifier listing (`msgs`) and the full content of a
chosen range (`expand`). The
user-facing unit is the msg (one API message) and its blocks, matching the proxy pane's display
grammar.
Touch this package to add read-side views over the dual logs. Do NOT add anything here that
writes, creates or locks a path under `src/logs/dual_log/`: the logs are frozen evidence and the
proxy appends to them live during a session.

## Public Interface

`__init__.py` is a package marker only — no exports. The entry path is the module runner:

```bash
./venv/bin/python -m src.dual_log_cli sessions [CONTEXT] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
./venv/bin/python -m src.dual_log_cli msgs <stem-or-substring> [FROM] [TO]
./venv/bin/python -m src.dual_log_cli expand <stem-or-substring> <msg> [--before N] [--after N] [--only CLASSIFIER]
./venv/bin/python -m src.dual_log_cli search <term> [SCOPE] [--since D] [--until D] [--only CLASSIFIER] [--case-sensitive]
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
`project_map` resolving each worker stem's 8-hex project id once per run.
`msgs` and `expand` resolve one stem, then `reader` reverse-seeks the last non-haiku `_original`
line and parses only that line → `timeline` builds turn rows via `proxy.message_summary` plus
request boundaries from `_forwarded.counts.messages`. `msgs` prints those rows for an inclusive
index range, interleaving one REQ separator per request group (`timeline.request_markers` folds the
boundaries into `{msg_index: {number, timestamp, refires}}`); `expand` slices an anchor-centred
window out of the same rows and re-summarizes each selected msg for its full block content.
`search` selects a
SET of sessions the same way `sessions` does (scope + date window), repeats that per-session
reconstruction for each one and streams its blocks through the matcher, skipping any session whose
timeline will not load → `render` emits plain terminal text to stdout.

## Modules

### __main__.py (283 LOC)

**Purpose:** argparse dispatch for the four subcommands (`sessions`, `msgs`, `expand`, `search`) plus the optional `CONTEXT` / `SCOPE` / `FROM` / `TO` positionals and the `--since` / `--until` / `--before` / `--after` / `--only` / `--case-sensitive` variants, `expand`'s window arithmetic and bound validation (`_run_expand` / `_window`), `msgs`' inclusive-range defaulting and bound validation (`_run_msgs`), the shared `_reject_bad_days` validator, the per-session search loop with its skip-on-unloadable guard, day-flag validation via `strptime` (rejects impossible dates, not just wrong shapes), the shared `_load_for` session resolution, the process exit codes, and the broken-pipe guard.
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

### classifier.py (50 LOC, 2026-08-29)

**Purpose:** The `--only` vocabulary and its two operations, shared by `expand` and `search`. `ROLES` (3) and `TYPES` (9) are the BLOCK types a msg can carry — the real content blocks (text, thinking, tool_use, tool_result, image) plus the pseudo-types a str-content msg contributes as its single synthetic block; `parse_only` turns a spec into a `(role, type)` pair or raises `BadClassifierError`; `matches_only` applies it, matching the type side against ANY of a msg's block types. `ONLY_FORMS` is the accepted-forms sentence, interpolated into both `--help` texts so the syntax is documented where it is used.
**Reads:** Nothing — pure vocabulary and predicates.
**Writes:** Nothing.
**Called by:** `__main__.py` (validation once per run, then msg selection in `expand`), `search.py` (hit filtering).
**Calls out:** —

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

### timeline.py (235 LOC)

**Purpose:** Turn-row construction for one payload, `iter_block_texts` (the block-text generator `search` builds on), single-turn full extraction (`full_turn`, what `expand` dumps), request-boundary derivation from the `_forwarded` delta stream, `build_turn_times` (turn → timestamp of the request that first carried it), `request_markers` (boundaries → `{msg_index: {number, timestamp, refires}}`, what `msgs` draws its REQ separators from), and `load_timeline` as the one call that assembles everything a render needs. `request_markers` groups boundaries by the msg index they open and takes the LAST of each group as the owner — within a group every member shares one `prev_count`, so only the last can have raised `message_count`, which makes it the request that actually added those msgs; the earlier members are re-fires and are counted, not listed. Its `number` deliberately counts only msg-adding requests, which is what aligns it with the proxy pane's `#N` (see Gotchas). `load_timeline` returns `entry`, `family`, `line_bytes` and `haiku_lines_skipped` without readers today; `session`, `payload`, `turns`, `turn_times` and — since `msgs` grew separators — `boundaries` all have them.
**Reads:** The parsed last-request payload; the session's `_forwarded.jsonl`.
**Writes:** Nothing — returns row lists, a generator, and one data dict.
**Called by:** `__main__.py`, `search.py`.
**Calls out:** `src/proxy/message_summary.py` (`_summarize_message` — imported, not copied), `reader`.

---

### search.py (48 LOC)

**Purpose:** The literal-substring matcher over one session's deduplicated timeline. Returns one hit per matching (turn, block) with an occurrence count and a whitespace-collapsed context snippet.
**Reads:** The parsed payload, streamed block by block via `timeline.iter_block_texts`.
**Writes:** Nothing — returns the hit list.
**Called by:** `__main__.py`.
**Calls out:** `timeline`.

---

### render.py (153 LOC)

**Purpose:** All terminal output. Session table (START / CONTEXT / SESSION plus a count line), `msgs`' request-grouped classifier listing (`render_msgs` — a `── REQ n  HH:MM:SS ──` separator per request group via `_req_separator`, then one `[idx] role type chars` line per msg, and NOTHING else: no totals, no sub-rows; `_governing_marker` gives a mid-group FROM its separator back), search results (one term line overall, then a `session <stem>` line plus its hit lines per matching session, blank-line separated, with an optional skipped-sessions note), `expand`'s full-content window dump (`▶` anchor mark and an HH:MM:SS request-time column in each msg header, then one `── block i ──` header plus the raw text per block), and the char/timestamp formatters. Rendering only — selection and filtering happen before a list reaches this module.
**Reads:** The dicts produced by `discovery`, `timeline` and `search`.
**Writes:** Nothing — returns strings; `__main__.py` does the `sys.stdout.write`.
**Called by:** `__main__.py`.
**Calls out:** `timeline` (`request_markers`, for `msgs`' REQ separators).

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
walks backwards past them via a 512-byte model sniff and only parses the first non-haiku line.
The skipped count reaches `load_timeline`'s dict but no command prints it since the `timeline`
header was removed. Any new read path must reuse that function rather than taking the file's final
line.

**Never parse an `_original` line to decide whether you want it.** Lines reach 15 MB. The
top-level key order written by `addon.py` is `timestamp, flow_id, request_id, model, payload`, so
`model` always sits in the first few hundred bytes — that is what makes the sniff cheap and the
4.94 GB file answerable in 0.16 s.

**`_forwarded` is a line-for-line mirror of `_original`, and that is load-bearing.** Verified:
identical line count and identical per-line `(model, message_count)`. The whole 62-session
inventory therefore reads 108 MB of `_forwarded` instead of 14 GB of `_original`. If a future
proxy change breaks that 1:1 alignment, `sessions` silently reports wrong request counts and
`expand`'s time column drifts — re-verify the alignment before relying on it again.

**A message-count regression means CC restarted inside one log id.** Request boundaries before the
restart index into a message list that no longer exists, so `build_turn_times` stops trusting them
(see the `?` gotcha below). Since the `timeline` command was dropped there is no header left that
announces the regression in words — the only surviving signal is the `?` time column. Do not "fix"
the misalignment by clamping indices; it is real.

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

**`msgs` prints msg lines and REQ separators, and NOTHING else.** No header, no count line, no
block sub-rows, no previews, no per-msg time column — an agent pipes it into `grep`/`wc` or reads
it whole, and any further decoration would have to be filtered back out. The separator became part
of the contract on 2026-08-30 (it was absent for the command's first hours): every msg line sits
under the `── REQ n  HH:MM:SS ──` line of the request that added it, so `grep -v '^──'` recovers
the original separator-free listing exactly. `msgs <session>` is the whole session,
`msgs <session> F T` an inclusive range, and `msgs <session> F` runs from F to the last msg. A bad
bound exits 2 naming the offending side (`FROM 1417 out of range (0..1416)`,
`TO 2 is before FROM 5`). A NEGATIVE bound needs a `--` separator (`msgs <s> -- -1`), else argparse
reads it as a flag — the exit code is 2 either way.

**A FROM landing mid-group still prints that group's separator, and it is not the group's own
first line.** `_governing_marker` falls back to the nearest request opening at or before the first
printed msg, so `msgs <s> 178 178` shows `── REQ 60 ──` even though REQ 60's group starts at 176.
Only the FIRST printed msg gets that fallback; every later separator appears at its group's real
start. Without it a mid-group range would print msgs under no request at all, which is the one
thing the separator exists to prevent.

**`msgs`' REQ numbers match the proxy pane's `#N` for the same session — by construction, not by
luck.** The number counts only requests that ADDED msgs, which is exactly the pane's rule
(`format.py` numbers `#N` on `messages_added > 0` and renders a re-fire as `#N.M` without advancing
N). Measured: 971 of 971 requests across three sessions agree on number, timestamp AND message
count simultaneously. `timeline.request_boundaries`' own `request_no` does NOT match — it counts
every forwarded line, so the 3 re-fires in the gh_cli session push it out of step on 223 of 482
requests. Two divergences are possible but unexercised by any recorded session: a non-haiku sidecar
(`sys_chars == 0 and tools_chars == 0`, which the pane labels `S` and does not count, while these
boundaries would) and a session mixing model families (these boundaries keep only the last
request's family). Both measured at zero occurrences; if either appears, the numbers drift from
there on.

**A re-fire leaves its only trace on the separator.** A request that re-sent the same message list
added no msg, so it opens no group of its own; it is folded into the next separator as
`(+1 re-fire)`. Measured: 3 in 1417 msgs on the gh_cli session, 0 in the other two. Drop that
suffix and a re-fire becomes completely invisible in this view — the pane still shows it as a
`#N.M` row.

**`msgs`' columns are fixed-width, and two real cases exceed them by one character.** The line is
`[{idx:3d}] {role:.4} {type:<20}{chars:>6}`. An index of 1000+ widens the whole line by one
(measured: 417 of 1417 msgs in one session), and a chars value needing 7 characters — `68,021c` —
pushes its own line out by one (12 of 1417, 2 of them overlapping the first case). Right-alignment
means both still read correctly, they just sit one column off their neighbours. Widening the
columns would trade that for permanent extra padding on every short line; the narrow default was
chosen deliberately.

**`expand` dumps full content and nothing else, and its bounds default to 0.** A bare
`expand <session> <msg>` prints exactly the anchor msg with every block in full — the old
classifier-rows overview and its 30-row hard floor are gone (2026-08-30), and so is the `--full`
flag that used to select the content dump. `--before`/`--after` are optional, may be 0, and a
negative value exits 2. The caller pays for every dumped character, so widening a window on a
tool_result-heavy stretch costs megabytes of stdout — widen deliberately.

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
Do not "fix" it by falling back to the pre-restart requests.

**No view prints `── REQ n ──` markers any more.** `expand`'s overview dropped them 2026-08-29
because it navigates by msg index and a second numbering system is noise there, and the `timeline`
command that owned them was removed 2026-08-30. Request boundaries survive only as data:
`timeline.request_boundaries` feeds `build_turn_times`, so a request's send time still reaches the
reader through `expand`'s HH:MM:SS column. Anything reintroducing markers should first answer which
of the two indices the reader is supposed to follow.

**`--only` matches BLOCK types, not the aggregated message type (revised 2026-08-29).** It used to
compare against the msg's single aggregated type, so a msg labelled `tool_use` was invisible to
`--only thinking` even when it carried a thinking block. That is superseded: a msg is selected when
its role matches and ANY of its blocks matches the type, and a selected msg always shows ALL of its
blocks. Measured on one window: `--only thinking` went from 5 to 11 msgs, the six additions being
assistant msgs aggregated as `tool_use` that carry reasoning; `--only user/text` picked up two msgs
aggregated as `tool_result` and `task-notification` that carry text blocks. Accepted syntax is a
role, a type, or a `role/type` pair, case-insensitive; an unknown token exits 2 naming the accepted
forms rather than silently matching nothing.

**The user-facing unit is the msg, not the turn.** One msg is one API message; its parts are
blocks. Internal identifiers still say `turns` in places (`data["turns"]`, `hit["turn"]`), but no
output string or `--help` text does — that split is intentional, and new output should say msg.

**`--only` never narrows the WINDOW, only what is printed from it.** The `expand` header keeps
stating the full examined range (`msgs 38-41 of 0-1416, anchor #40, 2026-08-29, only user`), so a
filter that hides most of the window is visible in the output rather than silent. A window in which
nothing matches prints `no msg in the window matches --only <spec>` and still exits 0 — an empty
result is a finding, not an error.

**Three commands removed so far, all of them LOUD.** `timeline --turn N [--full]` went 2026-08-29;
`timeline` itself and `expand --full` went 2026-08-30. All three break with argparse exit 2 —
`invalid choice: 'timeline'` and `unrecognized arguments: --full` — because the command and the flag
were deleted rather than reinterpreted. Replacements: `expand <s> <msg>` for a single-msg read,
`search` for finding something across a session, and — since `msgs` arrived the same day — `msgs
<s>` for the whole-session listing the old `timeline` and the old expand overview both used to
serve. `msgs` is narrower than either: no block sub-rows and no previews. It DOES carry request
markers — since 2026-08-30 they are its default grouping — but they are the compact
`── REQ n  HH:MM:SS ──` form, not the old `timeline` marker with its running msgs total. Contrast
`search`'s argument flip below, which fails silently.

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
