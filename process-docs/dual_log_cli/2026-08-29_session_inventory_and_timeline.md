# 2026-08-29 — Making the dual logs readable: session inventory and deduplicated timeline

Opening entry of this area. Subject: `src/logs/dual_log/` had grown to 369 files / 15.1 GB across
62 sessions and was effectively unreadable. Each `_original` line is one complete API request that
re-embeds the whole conversation, so a grep for any phrase returns it once per subsequent request,
and `head` returns half of one JSON line. The goal of this milestone was two read-only commands —
`sessions` and `timeline` — not a viewer and not a search.

## What the corpus actually looks like

Measured by walking the directory and parsing only line prefixes:

- 369 files, **15.1 GB**, 62 distinct session stems, six streams per stem
  (`_original`, `_forwarded`, `_stripped`, `_injected`, `_response`, `_errors`;
  `_errors` exists for 57 of 62 — it is only written when a tool error occurred).
- Largest `_original`: **4.94 GB** (`api_requests_opus_wise2627_1787903678`). Its last
  conversation request is a single **14.3 MB** line carrying 1367 messages.
- Total `_forwarded` across all 62 sessions: **107.8 MB**, fully scannable in **0.28 s**.

The pre-work estimate of "largest session ≈ 235 MB `_original`" was low by a factor of 21. Nothing
in the design depended on the estimate, but the reverse-seek approach became mandatory rather than
merely nice: the file cannot be streamed per invocation.

## The three findings that shaped the implementation

**1. Every session file interleaves two model families.** All 62 stems contain haiku requests
(1 message, ~0.5–2 KB — CC's title, quota and classifier sidecars, see `process-docs/haiku_traffic/`)
alongside exactly one real family: 32 sessions opus, 30 sonnet. So the naive "read the last line"
rule lands on a 500-byte sidecar call in any session that happened to end on one. Measured on the
4.94 GB file: 1 trailing haiku line; on `api_requests_opus_gh_cli_1787939513`: 1. The reader walks
backwards past them, deciding per line from a 512-byte prefix.

**2. `_forwarded` is a line-for-line mirror of `_original`.** Verified on two sessions by parsing
both files completely: identical line count (137/137 and 213/213) and identical per-line
`(model, message_count)` sequence. This is what makes `sessions` cheap — the inventory reads
108 MB of `_forwarded` plus `stat()` instead of 14 GB of `_original`. All 62 rows render in
**0.23 s**.

**3. The "last line holds the full conversation" assumption holds, but had to be proven.** Checked
across all 62 sessions using `_forwarded.counts.messages` per non-haiku request: the final
request's message count equals the session maximum in **62 of 62**. Exactly one session
(`api_requests_opus_gh_cli_1787939513`) has an internal regression — request 6 drops from 14
messages to 2 — and the reconstructed timeline shows why: turn #0 of that session contains
`<command-name>/clear</command-name>`. A `/clear` restarts the conversation while the proxy log id
stays the same. Even there the last line is the fullest (506 messages), so the rule survives; what
does not survive is the request-boundary alignment before the restart, which is why the renderer
prints a WARNING instead of silently drawing markers that point into a message list that no longer
exists.

## Reverse seek — the measurement that settled the approach

Backwards chunked scan (1 MB chunks) yielding line offsets from EOF, with a 512-byte read plus
`"model":"…"` regex per candidate. The top-level key order written by `addon.py` is
`timestamp, flow_id, request_id, model, payload`, so the model is always in the first few hundred
bytes and no rejected line is ever parsed.

On the 4.94 GB file: locating the last conversation line costs **0.05 s** and 15 chunk reads.
End-to-end `timeline` on that session, three consecutive runs: **0.16 / 0.15 / 0.16 s**. Smoke run
over all 62 sessions: every timeline renders without exception, worst case 0.12 s.

## Request boundaries came free

The brief allowed request-boundary markers "if cheap". They cost one extra read of the already-open
`_forwarded` stream: `counts.messages` per request gives the message index at which each request's
new messages begin. No second pass over `_original`, no diffing of 100+ requests — the property
that made the whole task tractable (one line contains everything) applies to the boundaries too,
just from the delta log instead.

## Decisions taken

- **Entry mechanism: `python -m src.dual_log_cli`.** The repo's convention is `src/<pkg>/` packages
  driven by a module entry (`workflow.py --mode X`, `mitmproxy -s src/proxy_addon.py`). A `-m` entry
  adds no root file and no PATH install, and it makes `from ..proxy.message_summary import
  _summarize_message` a plain relative import — the `block_dev_imports_src` restriction that forces
  `dev/` scripts into `importlib`/`sys.path` gymnastics (see `dev/proxy_dual_log/`) does not apply
  inside `src/`.
- **Reuse `_summarize_message` rather than re-deriving block metadata.** It already yields role,
  type, chars, per-block `{type, chars, preview, full_text}` plus `tool_use.name`/`id`,
  `tool_result.is_error`, `thinking.sig_chars`. `full_text` is dropped while building rows and only
  the requested turn is re-summarized for `--full`, so peak memory stays near the parsed payload.
- **Inventory from `_forwarded` only.** Correctness rests entirely on finding 2 above; the risk is
  recorded in the package's Gotchas so a future alignment break is diagnosable rather than silent.
- **Read-only proven, not asserted.** `st_mtime_ns` + size of all 369 files snapshotted before and
  after a full test run: 364 identical. The 5 that differed were the running worker's own session,
  appended by the live proxy while the tests ran, and all 5 only grew.

## Deliberately out of scope in this milestone

No search command, no `_stripped`/`_injected` drilldown, no HTML or viewer output. `_response` and
`_errors` are inventoried (their bytes count toward session size) but not rendered.
