# Excluding the Interleaved Sidecar Call From REQ Boundaries, and Its Write-Side Half, 2026-09-03

Continues this area's `msgs` sys/tool delta line work of the same day.
That entry's own Measurement 2 found `rag-chunking_1788333660`'s "restarts" were not restarts at
all: a second, structurally distinct sonnet call — system prompt "You are a security monitor for
autonomous AI coding agents…", `tools == 0`, always exactly 1 message — interleaved into the same
`sonnet` family bucket `infer_family` cannot tell apart from the real conversation. This entry is
two passes at removing it: a READ-side boundary exclusion, then a correction after that pass turned
out to be necessary but not sufficient.

## Pass 1 — excluding the sidecar from request_boundaries

`counts.tools == 0` on a non-haiku `forwarded_delta` line is the identifying signal: a real
conversation request always carries tools, the sidecar never does. Measured across the whole corpus
at the time: exactly 3 sessions carry this shape — `rag-chunking_1788333660` (35 of its lines),
`opus_jobscraper_1788347399` (57), `opus_monitor_cc_1788342698` (96) — and in every one of the 188
lines, checked by reconstructing the FULL cumulative system content from the delta chain rather than
trusting one line's own (often partial) delta, the signature text was present. Zero exceptions, so
the criterion is not over-broad.

`timeline.request_boundaries` now skips a sidecar entry entirely, before `prev_count` or anything
else is touched — it seeds no REQ, no restart, no turn time. `discovery.build_session` applies the
identical exclusion to its `requests`/`requests_main`/`messages` inventory figures.
`reader.load_last_request` was checked too: could a sidecar ever be the LAST non-haiku `_original`
line (the one `load_timeline` treats as "the conversation")? Measured: no, in 0 of 24 sessions on
disk. Extended anyway, cheaply — the check happens AFTER the parse this function already does for
its return value (checking `tools` cheaply via a sniff is not possible: it can sit well past the
model sniff's 512-byte window, behind a system block up to 110 KB), so the extension costs nothing
on the common path and is a true guarantee rather than a documented gap.

Effect on `rag-chunking_1788333660`: 124 raw boundaries (58 of them the sidecar's own restarts) down
to 89 clean REQs, 0 restarts. Usage-join coverage (owners resolved / owners total) went from 89/124
(71.8%) to 89/89 (100%) — the resolved count did not change, only the denominator stopped counting
entries that could never resolve, because the sidecar's request id genuinely never appears in CC's
transcript (it is not a conversation turn). The other two sessions' coverage (99.4%, 99.6%) was
unchanged by this pass, because their sidecar already sat in a DIFFERENT family bucket
(`claude-sonnet-5` sidecar vs. the conversation's `claude-fable-5-1` → `opus`) and was never in
their boundary list to begin with.

## Pass 2 — the write-side half this alone did not fix

Pass 1 fixed which request a delta gets ATTRIBUTED to. It did not fix what the delta itself
CONTAINS. Review caught this: `rag-chunking_1788333660`'s sys[1] was reported "changed" 34 times
after Pass 1, always at a constant 1 char — but the recorded content, `{"type": "text", "text":
"."}`, was byte-identical across all 35 occurrences. The tag was wrong; nothing about that block
ever changed.

Root cause, found by reading (not editing) `src/proxy`: `addon.py` keeps one
`prev_delta_hashes_by_model` dict, keyed by `model_family` — the exact same family bucket
`infer_family` reproduces read-side — and hands the matching entry into
`logging.py`'s `_build_forwarded_delta` to decide `system_delta`/`tools_delta`. Since the sidecar
shares that family key, the request immediately after an interleaved sidecar call gets diffed on the
WRITE side against the SIDECAR's own system/tools, not the real conversation's previous request —
so every real block comes back looking "changed" regardless of whether its content moved. Verified
directly: hashed `rag-chunking_1788333660`'s REQ 2 tools (`tools_delta` from the raw JSONL) against
REQ 1's — all 6 byte-identical, yet all 6 were present in the raw delta and, under Pass 1's
count-based tagging, all showed `new` or `changed`.

Excluding the sidecar from the boundary WALK cannot fix this by itself, because the pollution is
baked into the delta dict at write time, before dual_log_cli ever reads the line. The fix has to be
read-side content comparison, not a smarter count: `_delta_lines` now takes a `hash_by_index` map
(one for system, one for tools, threaded through the whole `request_boundaries` walk) holding the
CONTENT hash last seen at each index across REAL (non-sidecar) requests only. An index present in
the raw delta whose hash matches what is stored is dropped outright — no line, no tag — rather than
shown as `changed`. Hashing reuses `src/proxy/logging.py`'s own `_delta_hash` (imported, not
re-implemented) specifically so the read-side equality test can never disagree with what the proxy
itself would compute if it were diffing against the right previous request — cache_control is
stripped by the same function, so a cache_control move (a cache-boundary shift with no content
change) is never mistaken for a real one either.

## Measurements (as of 2026-09-03, corpus on disk)

**Measurement 1 — `rag-chunking_1788333660`.** After BOTH passes: **89 REQs, 0 restarts, 0
re-fires** (89 separator groups, 1:1 with boundaries — no group has more than one member). sys[1]:
`1c` untagged at REQ 1, then dropped entirely at every subsequent request — not shown even once
after REQ 1, matching the expectation exactly. (After Pass 1 alone it was still reported `changed`
34 times at a constant 1c — the exact write-side artifact Pass 2 removes.)

**Sys/tool lines removed corpus-wide, content comparison vs. the Pass-1 count-based version, per
session** (24 non-haiku sessions swept): **21 of 24 sessions show 0 removed** — their delta was
never touched by a sidecar interleave and stayed byte-for-byte identical.
`rag-chunking_1788333660`: 282 lines → 10, **272 removed**. Every other session, including the two
whose sidecar never shared a family bucket (`opus_jobscraper_1788347399`, `opus_monitor_cc_1788342698`)
and `skill-help_1788343931`: 0 removed.

**`skill-help_1788343931` REQ 196 (`tool[Skill]`/`tool[Write]`) survives, and its content genuinely
differs.** `counts.tools` drops from 6 (REQ 195) to 5 (REQ 196) — a real tool, `SendFeedback`, left
the list between those two requests. That shifted every tool after it down one index, so index 3
held `SendFeedback` at REQ 1 and holds `Skill` at REQ 196 (hash `4e81aa4008` → `7f5d2a9538`) and
index 4 held `Skill` at REQ 1 and holds `Write` at REQ 196 (hash `7f5d2a9538` → `99a890965a`) — two
genuinely different tool definitions occupying those positions, not a false positive from reusing an
index. This is also the session's one real, corpus-verified prompt-cache rebuild: `CR` collapses
from 456,637 (+ `CC` 1,048) to 0 at exactly this request.

**Corpus-wide count of non-first requests carrying a sys/tool change, before vs. after Pass 2**
(same sweep the first entry in this area ran): **69 → 1**. The one survivor is `skill-help_1788343931`
REQ 196 above, and it is also the corpus's only CR-drop coincidence — 1 flagged change, 1 real
rebuild, exact agreement. All 68 of `rag-chunking_1788333660`'s previously-flagged "changes" are
gone, confirmed as write-side noise, not incremental caching this time — genuinely nothing to see.

## Follow-up for the proxy area (not fixed here, `src/proxy` untouched)

The write-side root cause remains in `src/proxy/addon.py`: `prev_delta_hashes_by_model` should key
on conversation identity, not bare `model_family`, or a sidecar sharing a family with its
conversation will keep polluting every write-side delta immediately following it — this read-side
fix only prevents dual_log_cli from ACTING on that pollution, it does not stop the proxy from
recording spurious `system_delta`/`tools_delta` entries in the first place (harmless for the wire
payload itself, since the delta is a LOG artifact, not what is sent to the API — but it does inflate
the dual log and would mislead any other future reader of `system_delta`/`tools_delta` that does not
apply this same read-side correction). Out of scope for dual_log_cli; no existing `process-docs/proxy_*`
area matches this specific mechanism (family-keyed delta-hash state), so this paragraph is the
record until one is opened.

## Verification

Both passes verified against `gcommit-umlaut_1788367120`, `devproxy-docs_1788377950` and the largest
session `opus_jobscraper_1788347399` via `git stash`: `sessions`, `search`, `expand` and `msgs`
byte-identical (line counts unchanged: msgs 183/234/1463, search 50/78/342, expand 125/782/128,
sessions 33). `reader.load_last_request` confirmed byte-identical across all 24 sessions
(`skipped == 0` everywhere, unchanged before/after). Regression suites: `test_sidecar_exclusion.py`
(new, 13 checks — boundary exclusion, `build_session` count exclusion, `load_last_request` skip-and-
recover) and `test_msgs_sys_delta.py` (extended to 26 checks — an index present in the delta with
IDENTICAL content across two requests is now asserted to be DROPPED, not tagged `changed`; one
fixture needed correcting because it accidentally used a genuinely zero-tool boundary, which the
Pass-1 sidecar filter now correctly swallows). `test_msgs_blocks.py`, `test_msgs_overlay.py`,
`test_msgs_usage.py` re-run unchanged, 13/13 each.

## Relevant Symbols / Paths

- `_is_sidecar`, `_delta_lines`, `request_boundaries` (`src/dual_log_cli/timeline.py`)
- `build_session` (`src/dual_log_cli/discovery.py`)
- `load_last_request` (`src/dual_log_cli/reader.py`)
- `_delta_hash`, `_strip_cache_control` (`src/proxy/logging.py`) — read and imported, not modified
- `prev_delta_hashes_by_model` (`src/proxy/addon.py`) — the write-side state behind the follow-up,
  read-only
- Ground truth: `src/logs/dual_log/api_requests_worker_25c51a2e_rag-chunking_1788333660_forwarded.jsonl`
  (the interleave itself), `..._skill-help_1788343931_forwarded.jsonl` (the one real change, REQ 195→196)
