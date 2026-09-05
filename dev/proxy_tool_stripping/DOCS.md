# dev/proxy_tool_stripping/

## Purpose

Regression coverage and measurement probes for the proxy's strip/inject display area — how a
whole-stripped tool shows up in the tools drill-down (`TOOL_BLOCKLIST`, `src/constants.py` +
`src/proxy/tools.py`), and the REQ-header `strip`/`inject` badge's noise filters
(`src/proxy_display/parser.py`). Shares its name with `process-docs/proxy_tool_stripping/`, the
broader area covering both the write-side strip mechanism and the read-side display/logging of
what got stripped — not limited to the tool blocklist specifically, despite the directory name.

## Scripts

### tests/test_whole_stripped_tool_expand.py (216 LOC)

**Purpose:** Verifies the whole-stripped tool row expand feature (Milestone 2, 2026-09) — a
`TOOL_BLOCKLIST`-stripped tool's yellow drill-down row is now expandable, showing the original
description/schema sourced from the same session's `_original` dual-log (the last request's own
`tools` list), instead of a static non-expandable name-only row.
- `_render_whole_stripped_tool` (`src/proxy_display/render_sections.py`): collapsed-row bytes and
  key shape (`('stripped_tool', entry_idx, name)`), expanded body with a resolved `tool_def`
  (description lines + `name[*]: type — desc` params, all `DIM_YELLOW_BG`), expanded fallback
  (`(original definition unavailable)`) when `tool_def` is `None`.
- `render_tools`'s `use_dual` whole-stripped loop: wires `entry['_original_tools_by_name']`
  through to the new function; a forwarded-tool row (no whole-stripped tools present) renders
  identically to the pre-milestone shape.
- `parser._find_original_log_path` / `parser.accumulate_original_tools`: path derivation
  (`dual_dir / f'{stem}_original.jsonl'`), per-family latest-snapshot overwrite behavior
  (`_original` is NOT delta-encoded, so no merge — always the newest tools-bearing line wins),
  reference-preservation across incremental reads, missing-file no-op.
Placed under `tests/` (pytest-shaped filename) so `src.hooks.block_dev_imports_src`'s regression-
suite exemption applies — this file needs literal `from src.proxy_display....` imports, which the
hook otherwise blocks for any other `dev/` script (see that hook's own module for the exact rule).
**Reads:** Nothing from disk (synthetic fixtures only) except a `tempfile.TemporaryDirectory()`
JSONL file it writes itself for the `accumulate_original_tools` incremental-read tests.
**Writes:** Nothing persistent — prints PASS/FAIL to stdout.
**Usage:** `python3 dev/proxy_tool_stripping/tests/test_whole_stripped_tool_expand.py`

### probe_trailing_message_shapes.py (121 LOC)

**Purpose:** Measurement probe (2026-09-05) backing the claude-f trailing-nudge badge-widening —
scans every `_stripped.jsonl` line's `messages_delta` in the three current corpus stems, collects
every individual stripped text ending with the `<total_tokens>N tokens left</total_tokens>` tag,
normalizes by replacing the digit run with `N`, and reports distinct shapes with counts per
session plus a union total. Pure text/regex measurement — no `src/` import needed (does not touch
the `from src.` block-dev-imports-src hook at all), so it lives at the top level of this directory
rather than under `tests/`. This is what established the 24-distinct-shapes finding and the
3-sentence nudge catalog now in `src/proxy_display/parser.py`'s `_TOTAL_TOKENS_NUDGE_PARAGRAPHS` —
re-runnable against the live corpus to check whether a NEW, uncatalogued nudge shape has appeared
(by design it would show up here as a new distinct shape with real content mixed in, or as a
growing "ending-with-tag but never matches any catalogued shape" bucket over time).
**Reads:** `src/logs/dual_log/api_requests_opus_{wise2627_1788612045,websearch_1788611995,
monitor_cc_1788611156}_stripped.jsonl` (hardcoded stems — measurement was run against a specific
corpus snapshot, not parameterized).
**Writes:** `md/trailing_message_shapes_report.md`.
**Usage:** `python3 dev/proxy_tool_stripping/probe_trailing_message_shapes.py`

## Gotchas

- The byte-identical regression for this milestone was NOT run from this directory — it reuses
  the existing `dev/proxy_dual_log/A_render_refactor_proof.py` harness (capture-before /
  implement / verify-after). 13 of its 14 fixture cases stayed byte-identical; the 14th
  (`expand_fixpoint`) legitimately gained one new line once its whole-stripped `read_file` row's
  new key got iterated to `True` by the fixpoint loop — inspected manually via `difflib`, confirmed
  the diff is exactly the new expanded content and nothing else. The refreshed baseline is
  `dev/proxy_dual_log/A_render_refactor_proof_reports/baseline_20260905.json`.
