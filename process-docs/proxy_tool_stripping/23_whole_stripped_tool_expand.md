# Whole-Stripped Tool Rows Become Expandable (Milestone 2, 2026-09)

## Problem

The tools drill-down's forwarded-tool rows (Bash, Edit, Read, Skill, Write) were expandable and
showed their description via `_render_tool_dual`, sourced from the `_forwarded` log's own
`tools_defs`. A `TOOL_BLOCKLIST`-stripped tool (Agent, Artifact, AskUserQuestion,
DeferredToolPlaceholder, ReportFindings, ScheduleWakeup, ToolSearch, Workflow, and — after the
CC 2.1.258 follow-up in this area — SendFeedback, ListAgents) rendered as a static yellow
name-only row: `render_tools`'s whole-stripped loop appended `keys.append(None)`, so no
`expand_states` key existed and clicking the row did nothing. The stripped stream itself only ever
records `{"whole": true}` for a fully-removed tool — no description, no schema — so there was no
in-pane way to read what CC actually sent for one of these tools.

## Where the original content lives

`dual_log_cli/overlay.py`'s `_tools_overlay` already had to solve the identical problem for the
`duallog msgs` CLI view, and the `process-docs/dual_log_cli/` measurement backing it
(2026-09-04) gave the answer directly: the same session's `_original` dual-log — the raw
pre-strip payload, logged before `apply_modification_rules` ever runs — carries the full tool list
on every non-haiku request. That measurement found 336/336 whole-stripped tool name-instances
across 42 sessions resolvable there, and 0 hash mismatches comparing any earlier request's
tool-by-name content against the last request's across 45 sessions — CC's own tool defs never
change mid-session. That made "look up the name in the LATEST `_original` line's own tools list"
both sufficient and safe to reuse for the pane, without needing any write-side log format change
(explicitly out of scope — writing tool text into the stripped stream would grow it by tens of KB
per request for content that's already on disk elsewhere).

## Design

`_original.jsonl` is structurally different from `_forwarded`/`_stripped`/`_injected`: it is NOT
delta-encoded. Every line whose `payload.tools` is non-empty carries the FULL 15-entry list (main
requests only — a haiku sidecar line has no `tools` key at all). That meant the read-side
accumulator needed is much simpler than `accumulate_dual_log`'s merge machinery: just overwrite
the per-model-family `{tool_name -> tool_def}` map with whatever the newest tools-bearing line
says, in place (same reference-preservation convention as the existing dual-log accumulators, so
entries created before the first `_original` line is read still see the definition once it lands).

Three files changed:
- `src/proxy_display/parser.py` — new `_find_original_log_path` (mirrors `_find_dual_log_paths`)
  and `accumulate_original_tools` (the overwrite-only accumulator above).
- `src/proxy_display/pane.py` — new `_proxy_original_pos` / `_proxy_acc_original` state, tailed
  every 0.5s poll tick alongside the stripped/injected accumulators, reset on session-change and
  hourly reparse. Each newly-created entry gets `entry['_original_tools_by_name'] =
  _proxy_acc_original.setdefault(family, {})` — a live reference, so no lazy-load-on-click
  machinery was needed (unlike message reconstruction, which only happens on demand).
- `src/proxy_display/render_sections.py` — new `_render_whole_stripped_tool`, mirroring
  `_render_tool_legacy`'s expanded body (description + per-param lines) but entirely
  `DIM_YELLOW_BG` and defaulting to a `(original definition unavailable)` line when the lookup
  returns `None`. `render_tools`'s `use_dual` whole-stripped loop now calls this instead of
  appending a static line; the collapsed-row bytes are unchanged from before (same `▶ {name}`
  text/background), only the `keys` entry changed from `None` to `('stripped_tool', entry_idx,
  name)`.

`worker_proxy_pane.py` was deliberately left untouched, per the milestone's scope. It shares
`render_sections.render_tools` (unavoidable — one render function, both panes), so its
whole-stripped rows also became clickable, but since it never attaches
`_original_tools_by_name`, expanding one there always shows the fallback line. This degrades
gracefully rather than crashing or diverging in the collapsed state, which is what "every other
pane section renders as before" required.

## Verification

Reused the existing `dev/proxy_dual_log/A_render_refactor_proof.py` byte-identical harness (14
fixture cases covering `render_tools`/`render_messages`/`render_turn`/`format_proxy_block`)
rather than trusting the new unit tests alone for the no-regression claim: captured a baseline
before the change (`git stash` + capture), implemented, captured again, and diffed. 13 of 14
cases were byte-identical. The 14th, `expand_fixpoint` (a kitchen-sink fixture iterated to a
fixpoint of fully-expanded keys, which happens to carry a `tools: {'read_file': {'whole': True}}`
stripped span), legitimately grew by one line once its whole-stripped row's now-real key got
iterated to `True` — inspected the diff manually via `difflib`: exactly one `▶`→`▼` flip plus one
new `(original definition unavailable)` line (the fixture never attaches
`_original_tools_by_name`), nothing else changed. Kept as the new baseline
(`dev/proxy_dual_log/A_render_refactor_proof_reports/baseline_20260905.json`).

New suite `dev/proxy_tool_stripping/tests/test_whole_stripped_tool_expand.py` (37 checks): direct
assertions on `_render_whole_stripped_tool` (collapsed-row bytes/key, expanded body with a
resolved def, expanded fallback), on `render_tools`'s wiring (a whole-stripped row with an
available original def shows it; one without falls back cleanly; a forwarded-only entry with no
whole-stripped tools at all renders its Bash row exactly as `_render_tool_dual` always has), and
on `parser.accumulate_original_tools`/`_find_original_log_path` (family split via
`_infer_model_family`, latest-snapshot overwrite behavior, in-place reference preservation across
incremental reads, missing-file no-op). Placed under `dev/proxy_tool_stripping/tests/` (pytest-
shaped filename) specifically so `src.hooks.block_dev_imports_src`'s regression-suite exemption
applies — the file needs literal `from src.proxy_display....` imports (two-level relative imports
inside those modules require it), which that hook otherwise blocks for any `dev/` script outside
a `tests/` directory.

Re-ran `dev/proxy/test_strip_fix.py` (217/217, unchanged) and the two proxy-pane search
regression suites that also exercise `pane.py`'s `_refresh_proxy_data` directly —
`dev/pane_search/p2_search_feature_regression_test.py` (48/48) and
`dev/pane_search/p3_drag_select_regression_test.py` (62/62) — as caller-safety checks, since
`_refresh_proxy_data` was the one function touched that many other pane mechanics also depend on.

## Relevant Symbols / Paths

- `_render_whole_stripped_tool`, `render_tools` (`src/proxy_display/render_sections.py`)
- `_find_original_log_path`, `accumulate_original_tools` (`src/proxy_display/parser.py`)
- `_proxy_original_pos`, `_proxy_acc_original`, `entry['_original_tools_by_name']`
  (`src/proxy_display/pane.py`)
- `_tools_overlay` (`src/dual_log_cli/overlay.py`) — the sibling mechanism this design borrowed
  the "look up in the last `_original` request's own tools list" approach from
- `process-docs/dual_log_cli/` — the corpus measurement backing that lookup's safety
