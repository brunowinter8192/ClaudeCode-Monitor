# dev/proxy_instrumentation/

## Role

Reconstructs/measures the proxy's real strip/inject pipeline output straight from recorded
dual-log payloads or `src/logs/dual_log/*_original.jsonl`, through the REAL production code
(`src/proxy/message_passes.py`, `rule_ops.py`, `diff_engine.py`, `proxy_display/render_messages.py`)
— no live proxy required. Touch when validating a pane-render or span-computation change against
real recorded data; not for live-session debugging (see `dev/proxy_dual_log/` for the dual-log
invariant/verification suite instead).

## Modules

### render_recorded_request.py (129 LOC)

**Purpose:** Reconstructs the pane render for one specific recorded request (by `request_id`)
straight from the on-disk dual-log, verifying a span-render fix for block-less messages.
`_render` takes `entry_idx` as of 2026-08-28 (thinking-expander milestone bumped
`render_messages`'s signature to `(entry_idx, entry, ...)`) — passes `target_line`/`control_line`,
mechanical update only, no behavior change to this script's own checks.
**Reads:** `src/logs/dual_log/api_requests_opus_posts_1785266871_{forwarded,stripped,injected}.jsonl`
(hardcoded stem/request_id — one-off verification, not parameterized).
**Calls out:** `src.proxy_display.{forwarded_parser,parser,render_messages}`.

### p2_badge_words_probe.py (109 LOC)

**Purpose:** Verifies the REQ-header `strip`/`inject` word badge (replacing the old numeric
`Nstrip Ninj`) end-to-end — `accumulate_dual_log` -> pane-style entry attach ->
`_build_req_header_line` — against 4 recorded requests, including the "."-filler injection
case (empty `fn_map`, non-empty `messages_delta`) that must still render `inject`.
**Reads:** `src/logs/dual_log/api_requests_{opus_monitor_cc_1785364138,opus_monitor_cc_1785347492}_{forwarded,stripped,injected}.jsonl`.
**Writes:** `md/badge_words_probe_report.md`.
**Calls out:** `src.proxy_display.{forwarded_parser,parser,render_turn}`.

### p3_badge_inline_probe.py (244 LOC)

**Purpose:** Verifies the per-flow msg-index tracking + inline out-of-window span rendering
and the neighbor-bleed fix end-to-end — `accumulate_dual_log` -> pane-style entry attach ->
`_build_req_header_line` + `render_messages` — against the CC 2.1.223 recorded session with
mid-conversation system messages (deferred-tools notice, task-tools nag, bg-notification), plus
a synthetic fields-only delta line (`fields_delta` must not badge) and a full-session
collapsed-header sweep (`⚠S` badge must never render). `_render_body`'s `render_messages()` call
passes `idx` as `entry_idx` as of 2026-08-28 (thinking-expander milestone signature bump),
mechanical update only.
**Reads:** `src/logs/dual_log/api_requests_opus_websearch_1786052022_{forwarded,stripped,injected}.jsonl`.
**Writes:** `md/badge_inline_probe_report.md`.
**Calls out:** `src.proxy_display.{forwarded_parser,parser,render_turn,render_messages,format}`.

### p4_blocklist_223_probe.py (140 LOC)

**Purpose:** Verifies the CC 2.1.223 `TOOL_BLOCKLIST` extension (Artifact, ReportFindings,
DeferredToolPlaceholder) end-to-end — runs the real `proxy.tools._strip_unused_tools` on the
session's actual original-log payload, asserts the post-strip set is exactly
`{Bash, Edit, Read, Write, Skill}` + any MCP-injected names present in the forwarded log; sanity
check for a live `tool_use` invocation of any newly-blocked name (would 400 the API if stripped);
confirms `Agent` (pre-existing blocklist entry) is absent from the forwarded tools list — the
drill-down's "Agent" sighting is the intentional whole-stripped yellow row
(`render_sections.py`), not a strip-path bug.
**Reads:** `src/logs/dual_log/api_requests_opus_websearch_1786052022_{original,forwarded}.jsonl`.
**Writes:** `md/blocklist_223_probe_report.md`.
**Calls out:** `proxy.tools` (`_strip_unused_tools`), `constants` (`TOOL_BLOCKLIST`),
`src.proxy_display.forwarded_parser` (`_parse_forwarded_log`).

### p5_mid_turn_user_msg_preserve_probe.py (132 LOC)

**Purpose:** Verifies the CC 2.1.223 mid-turn-user-message preserve-guard in
`src/proxy/message_passes.py::_apply_role_system_strip` (issue #61) — drives the REAL function on
the REAL recorded message list, not a synthetic fixture. Preserve case: session
`api_requests_opus_posts_1786051932`, flow `4b4d396b...`, msg 274 — the live incident itself (a
role='system' mid-turn user message body "jetzt") must survive byte-for-byte. Regression: session
`api_requests_opus_websearch_1786052022`, three unrelated role='system' noise messages
(deferred-tools, task-tools-nag, date-changed) must still strip to `"."` exactly as before.
**Reads:** `src/logs/dual_log/api_requests_opus_{posts_1786051932,websearch_1786052022}_original.jsonl`.
**Writes:** `md/mid_turn_user_msg_preserve_probe_report.md`.
**Calls out:** `src.proxy.message_passes` (`_apply_role_system_strip`).

### p6_no_flow_extra_prepend_probe.py (250 LOC)

**Purpose:** Verifies that an expanded request body is the request's payload delta and nothing
else, after the out-of-window prepend was removed entirely (2026-08-30). Replaces
`p6_flow_extra_suppress_probe.py`, which verified the earlier PARTIAL suppression of the same
mechanism by rendering each entry twice (once with the suppression disabled) — impossible now that
the mechanism is gone, so these invariants are self-contained instead: no entry's body carries a
`[N]` header below its own delta-window start (the window start is recomputed here from
`prev_msg_count`/`diff_start` rather than imported, so the probe cannot agree with the renderer by
construction); `_render_flow_extra_messages`/`_own_msgs` are absent from `render_messages`, the
parser no longer mentions `_msg_idx_sub_by_flow_id` and no entry carries a sub-lookup attachment
(reintroduction guard — a partial revert would otherwise pass the first check silently); every
entry whose out-of-window touch is SUBSTANTIAL still badges, substantiality read off the raw
dual-log lines via `parser._msg_delta_entry_is_substantial` because a total_tokens-only touch
deliberately badges nothing; and at least one entry still renders an in-window olive/green span, so
a regression that killed span rendering outright cannot pass as "no prepend". Reports, without
asserting, how many entries have an out-of-window touched index whose stripped original is
therefore invisible in the pane — the accepted cost, recoverable only from the `_stripped` stream.
**Reads:** `src/logs/dual_log/api_requests_{opus_monitor_cc_1788091735,opus_gh_cli_1787995963}_{forwarded,stripped,injected}.jsonl` (override via argv).
**Writes:** `md/no_flow_extra_prepend_report.md`.
**Calls out:** `src.proxy_display.{forwarded_parser,parser,render_messages,render_turn}`.

### p1_measure_full_replacement_blast_radius.py (536 LOC)

**Purpose:** Measurement script (dev/ M1 "bg-ack-shapes" milestone, 2026-07-29) — drives real
recorded payloads through the real `message_passes.py` pass functions in `rules.py`'s actual
order, classifies each `_ops_from_content_change` call site as FULL (whole-block-independent
replacement) vs PARTIAL (excise-and-keep-remainder) vs STRUCTURAL (index-shift artifact) by
reading the underlying strip function — NOT by any ratio threshold — and quantifies how many
FULL-class ops are today recorded as a trimmed/split span due to `_extract_block_op`'s
prefix/suffix-trim. Report: `md/full_replacement_blast_radius_20260729.md`.
**Reads:** `src/logs/dual_log/api_requests_{opus_monitor_cc_1785336796,opus_posts_1785338463,
opus_wise2627_1785324012,worker_25c51a2e_tn-role-system_1785344818}_original.jsonl`.
**Writes:** `md/full_replacement_blast_radius_20260729.md`.
**Calls out:** `src.proxy.{message_passes,rule_ops,diff_engine,payload_helpers,content_strip}`,
`src.proxy_display.render_messages`.

---

## Gotchas

- `pN_*.py` scripts import from `src/` — filename MUST carry the `pN_` prefix (project convention:
  only `pN_*.py` dev scripts may `from src...`/`import src...`; unprefixed dev scripts must copy
  the logic or import from an existing `pN_` module).
- `proxy_display` has an internal `from ..constants` (2-level relative import in `pane.py`, pulled
  in transitively by `proxy_display/__init__.py`) — it must be imported with the project ROOT on
  `sys.path` (not `src/` directly, which is what the plain `src/proxy/*` imports use). Mixing both
  roots on `sys.path` in the same script is safe (verified in `p1_measure_full_replacement_blast_radius.py`)
  since `src.proxy_display` and the flat `proxy` package never collide.
- `p1_measure_full_replacement_blast_radius.py` feeds each pass function only the NEW-message
  delta per dual-log request (not the full cumulative message list) — safe because none of the
  11 pass functions read any OTHER message's content (verified by reading `message_passes.py`),
  so this reproduces the same per-message ops as the real pipeline without the dual-log's
  cumulative-snapshot duplication inflating counts. The 2026-07-29 corpus itself was NOT static
  during the scan — see `process-docs/proxy_instrumentation/2026-07-29_full_replacement_blast_radius_measurement.md`
  for the moving-snapshot caveat.
