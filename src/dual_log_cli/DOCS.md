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
./venv/bin/python -m src.dual_log_cli sessions
./venv/bin/python -m src.dual_log_cli timeline <stem-or-substring> [--turn N [--full]]
./venv/bin/python -m src.dual_log_cli search <stem-or-substring> <term> [--case-sensitive]
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
`sessions` builds one inventory row per stem from that stem's `_forwarded` stream alone;
`timeline` and `search` resolve the stem, then `reader` reverse-seeks the last non-haiku
`_original` line and parses only that line → `timeline` builds turn rows via
`proxy.message_summary` plus request boundaries from `_forwarded.counts.messages`, or `search`
streams the same blocks through the matcher → `render` emits plain terminal text to stdout.

## Modules

### __main__.py (141 LOC)

**Purpose:** argparse dispatch for the three subcommands plus the `--turn` / `--full` / `--case-sensitive` variants, the shared `_load_for` session resolution, the process exit codes, and the broken-pipe guard.
**Reads:** `sys.argv`; the resolved dual_log directory via `discovery`.
**Writes:** stdout (rendered text), stderr (resolution, range and empty-term errors). Never touches the log directory.
**Called by:** the user, via `python -m src.dual_log_cli` or `bin/duallog`.
**Calls out:** `discovery`, `render`, `search`, `timeline` (all package-local).

---

### discovery.py (135 LOC)

**Purpose:** Log-directory resolution, stem grouping, context parsing, the session inventory, and stem/substring resolution with explicit ambiguity and unknown errors (`AmbiguousSessionError`, `UnknownSessionError`).
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

### timeline.py (177 LOC)

**Purpose:** Turn-row construction for one payload, `iter_block_texts` (the block-text generator both `search` and the full-turn dump build on), single-turn full extraction, request-boundary derivation from the `_forwarded` delta stream, and `load_timeline` as the one call that assembles everything a render needs.
**Reads:** The parsed last-request payload; the session's `_forwarded.jsonl`.
**Writes:** Nothing — returns row lists, a generator, and one data dict.
**Called by:** `__main__.py`, `search.py`.
**Calls out:** `src/proxy/message_summary.py` (`_summarize_message` — imported, not copied), `reader`.

---

### search.py (61 LOC)

**Purpose:** The literal-substring matcher over one session's deduplicated timeline. Returns one hit per matching (turn, block) with an occurrence count and a whitespace-collapsed context snippet, plus scope statistics.
**Reads:** The parsed payload, streamed block by block via `timeline.iter_block_texts`.
**Writes:** Nothing — returns `(hits, stats)`.
**Called by:** `__main__.py`.
**Calls out:** `timeline`.

---

### render.py (159 LOC)

**Purpose:** All terminal output. Session table, timeline with request markers, search results, full-turn dump, and the size/char/timestamp formatters.
**Reads:** The dicts produced by `discovery`, `timeline` and `search`.
**Writes:** Nothing — returns strings; `__main__.py` does the `sys.stdout.write`.
**Called by:** `__main__.py`.
**Calls out:** `timeline` (`boundaries_by_index`).

---

## State

None. Every command is a single pass with no caches, no module-level mutable state, and no files
written anywhere. Two invocations on an unchanged log directory produce identical output; on a
live session the output tracks whatever the proxy has appended by then.

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

**A search hit is one (turn, block) pair, never one occurrence.** A block containing the term N
times stays one hit carrying `×N`. Changing that granularity changes every reported hit count, so
it is a contract, not a formatting detail.
