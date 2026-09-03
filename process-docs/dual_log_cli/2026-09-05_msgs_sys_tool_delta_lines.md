# `msgs` Shows the System Blocks and Tools Each Request Sent, 2026-09-05

Continues this area's command line. The stated motivation: the most frequent cause of a
prompt-cache rebuild is a change in the system blocks or the tool list that precede the messages,
and `msgs` showed neither. `timeline.request_boundaries` already reads `_forwarded`'s
`system_delta`/`tools_delta` per request (via `_build_forwarded_delta` in `src/proxy/logging.py`) —
this reuses that data rather than re-reading the stream.

## Shape reused, tags computed here

The proxy's delta already decides WHICH indices to include (hash comparison against ITS own
`prev_hashes`, `src/proxy/logging.py`); `_delta_lines` only decides how to LABEL what is already
there — `changed` for an index below the previous request's own `counts.system`/`counts.tools`,
`new` for one at or beyond it, and no tag at all on the family's first request (`is_first`), which
lists every block regardless. System index 0 — the billing header, a hash plus the previous request
id that changes by construction and was already established (`process-docs/cache/`) as not
invalidating the cache — is dropped from that comparison on every request but the first, unconditionally,
regardless of what the raw `system_delta` says.

Chars are the wire size the request actually carried: a system block's `text` length, a tool's
`len(json.dumps(tool))` (default separators) — not `sig_chars` or any other summary figure the rest
of the module uses, since the point here is specifically "what changed on the wire," matching the
sys/tool line's stated purpose.

## A corpus wrinkle found while verifying the worked example

The task's own example (`rag-chunking_1788333660`, its 2nd and 3rd sonnet-family requests) matched
every chars value exactly, but 2 of 5 `changed`/`new` tags in that example did not match this
implementation's literal "compare to the immediately preceding request" output. Investigated fully
before accepting the discrepancy:

`rag-chunking_1788333660` interleaves a SECOND, structurally distinct API call into the exact same
`sonnet` family bucket — recurring, roughly every few real turns: `system=3` (not the real
conversation's 4), `tools=0`, always exactly 1 message, and a system prompt opening "You are a
security monitor for autonomous AI coding agents." `infer_family` only looks at the model string
(`claude-sonnet-5` for both), so `request_boundaries` cannot tell the two apart — and the existing
restart heuristic (`message_count` regressing) flags every one of these interleaved calls as a
restart, which is a documented-but-previously-"unexercised" divergence
(`src/dual_log_cli/DOCS.md`'s "REQ numbers match the pane's `#N`" Gotcha already named the sibling
case, `sys_chars == 0 and tools_chars == 0`, "measured at zero occurrences" as of `2026-08-30`).

Content check: hashed the 6 tools of the request right after one such interleave against the SAME 6
tools of the true previous REAL request — all 6 byte-identical (0 of 6 actually changed). All 6
still show up in `tools_delta` regardless, because the interleaved call's `tools == 0` reset the
PROXY's own bookkeeping, not because any tool's content changed. Several tag-source hypotheses were
tried against the target's specific tag pattern (a monotonic non-decreasing high-water mark instead
of the literal immediately-preceding count; per-index "ever seen" tracking seeded from the first
request) — the high-water-mark version reproduced 4 of the 5 example tags (better than the literal
version's 3 of 5) but still could not explain why the example tags exactly one of six
identically-situated, identically-unchanged tools `new` and the rest `changed`; no count- or
index-threshold rule can single out one interior index from an otherwise uniform block. Concluded
this is not a formatting question this feature's spec can settle — it is the same
boundary-detection question the existing restart Gotcha already scopes as future work — and kept
the literal, spec-stated rule (compare to the immediately preceding request of the family) rather
than inventing an unstated heuristic to chase one example. `DOCS.md` documents the wrinkle inline,
tied to the existing Gotcha.

## Measurements (as of 2026-09-05, 24 non-haiku sessions on disk)

**Incidence.** 69 non-first requests carry a sys/tool change once system block 0 is excluded — 68
in `rag-chunking_1788333660` (the interleave above; every restart round-trips one system block
between 1c and 110,550c, always tagged `changed`), 1 in `skill-help_1788343931`. Every other session
on disk shows zero — the system prompt and tool list are set once near session start and never
touched again, so a delta line is genuinely rare, which is what makes one worth noticing.

**CR-drop coincidence.** Of those 69, exactly 1 coincides with a `CR < previous CR + CC` prompt-cache
drop: `skill-help_1788343931`, where `tool[Skill]`/`tool[Write]` change and `CR` falls from
456,637 (plus `CC` 1,048) to 0 — a real, full rebuild, and a real example of the causal link this
feature exists to surface. The other 68 (all in `rag-chunking`) never coincide with a CR drop,
consistent with `process-docs/cache/2026-09-02_worker_start_double_rebuild_closed.md`'s finding that
a growing cache_read against the previous total is incremental caching, not a rebuild — these round
trips read the same prefix back every time.

**Timing**, largest session on disk (`opus_jobscraper_1788347399`, 385 MB `_original`, whole-session
`msgs`, 3 runs each): 0.13/0.13/0.13 s before, 0.14/0.15/0.15 s after — roughly 15-20 ms, negligible
next to the session load itself.

## Verification

`sessions`, `search`, `expand` confirmed byte-identical via `git stash`. `msgs` confirmed
line-count-correct with every PRE-EXISTING line byte-identical on two sessions
(`devproxy-docs_1788377950` msgs 0-4: 11/11 unchanged lines, 9 new; `rag-chunking_1788333660` msgs
0-12: 32/32 unchanged lines, 9 new) — filtering the new output down to everything except the new
`^        (sys\[|tool\[)` lines reproduces the pre-change output exactly. New regression suite
`dev/dual_log_cli/tests/test_msgs_sys_delta.py` (25 checks): first-request full listing incl. the
billing header, later-request exclusion of the billing header plus `changed`/`new` tagging on a
monotonically growing fixture, an all-billing-header delta producing no lines at all, `render_msgs`
placing the delta lines directly under the separator before the first msg line (column-aligned to
the parent's chars column), and a re-fire group showing only the owner boundary's own lines.
Existing suites (`test_msgs_blocks.py`, `test_msgs_overlay.py`, `test_msgs_usage.py`) re-run
unchanged, 13/13 each.

## Relevant Symbols / Paths

- `_delta_lines`, `_system_block_chars`, `_tool_chars`, `_BILLING_HEADER_SYS_INDEX`
  (`src/dual_log_cli/timeline.py`)
- `_req_delta_lines` (`src/dual_log_cli/render.py`)
- `_build_forwarded_delta` (`src/proxy/logging.py`) — read only, not modified
- Ground truth for the worked example: the corpus wrinkle above is visible directly in
  `src/logs/dual_log/api_requests_worker_25c51a2e_rag-chunking_1788333660_forwarded.jsonl`, its 2nd
  and 4th `forwarded_delta` lines of the `sonnet` family
- `process-docs/cache/` — why system block 0 is excluded
