# dev/proxy_tool_stripping/

## Purpose

Regression coverage for the display side of the `TOOL_BLOCKLIST` mechanism (`src/constants.py` +
`src/proxy/tools.py`) — how a whole-stripped tool shows up in the proxy pane's tools drill-down.
Shares its name with `process-docs/proxy_tool_stripping/`, the area covering both the write-side
strip (per-CC-version blocklist follow-ups) and the read-side display of what got stripped.

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

## Gotchas

- The byte-identical regression for this milestone was NOT run from this directory — it reuses
  the existing `dev/proxy_dual_log/A_render_refactor_proof.py` harness (capture-before /
  implement / verify-after). 13 of its 14 fixture cases stayed byte-identical; the 14th
  (`expand_fixpoint`) legitimately gained one new line once its whole-stripped `read_file` row's
  new key got iterated to `True` by the fixpoint loop — inspected manually via `difflib`, confirmed
  the diff is exactly the new expanded content and nothing else. The refreshed baseline is
  `dev/proxy_dual_log/A_render_refactor_proof_reports/baseline_20260905.json`.
