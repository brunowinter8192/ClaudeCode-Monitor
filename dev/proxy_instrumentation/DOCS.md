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

- Both scripts import from `src/` — filename MUST carry the `pN_` prefix (project convention:
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
