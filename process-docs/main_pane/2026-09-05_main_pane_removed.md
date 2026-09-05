# Main Pane Removed — Window 0 Becomes the Tokens Pane at Full Width (2026-09-05)

This entry closes the `main_pane` area: the main pane no longer exists in any form. It supersedes
`2026-09-05_tool_calls_only_req_numbering.md` in this same folder (a same-day redesign of a pane
that got deleted a few hours later) — that entry stays as a write-once historical record and is
not edited.

## Trigger

The main pane's own req-numbering/tool-calls-only redesign (see the superseded entry) was the
last significant investment in a pane whose displayed content — tool calls with `req N:` headers —
fully duplicated what the tokens pane already shows per-request, just without CR/CC/D/output
metrics. The decision was to delete the main pane rather than keep maintaining a strictly-smaller
subset of another pane's information.

## What changed

**tmux layout:** `_WINDOW_LAYOUT`/`launch_split_screen` in `src/tmux_launcher.py` — window 0 no
longer splits into main (0.0, 70%) + tokens (0.1, 30%). It is now a single pane running
`--mode tokens`, full width, renamed `tokens` (not `main`) since nothing else referenced the
window name — grepped `tmux_launcher.py` itself (the only place `_WINDOW_LAYOUT`'s `win_name` is
read, via `new-window -n`) before renaming, confirmed safe. Pane count drops from 9 to 8. Pane
title map, `M-m` keybinding (dropped, no pane left to copy), and `M-t` (now targets `0.0` instead
of `0.1`) updated to match. `restart_panes`'s self-heal walks the same `_WINDOW_LAYOUT`, so Ctrl+R
heals the 8-pane layout automatically — verified live (see Verification below).

**CLI modes:** `--mode main` removed from `startup.py`'s argparse choices. `--mode rules` and
`--mode hooks` were removed alongside it — both were never wired into any tmux window or given a
mode constant of their own; they fell through `run_monitor`'s catch-all `else` branch straight
into `run_main_loop()`, the exact code path being deleted. Keeping them would have meant either
reinventing a purpose for two modes that never had one, or leaving a CLI choice that crashes the
moment anyone used it — neither is "preserving a feature." `constants.MODE_MAIN` removed
(`MODE_ALL`/`MODE_WARNINGS`/`MODE_TOKENS`/`MODE_WORKERS`/`MODE_PROXY`/`MODE_WORKER_PROXY` stay,
all still real dispatch targets).

**`src/core/monitor.py`:** `run_main_loop` and every private helper that existed only to serve it
(`_main_ram_state`, `_handle_main_mouse`, `_handle_main_search_cancel`/`_input`/`_release`,
`_main_search_on_commit`, `_jump_search_match`, `_refresh_main_data`, `_build_main_output`) are
gone. So is the module-level state nothing else ever read: `tool_use_caches`,
`request_numbers_by_file`, `call_counter`, `agent_to_task`, `agent_to_type`,
`buffered_subagent_calls`, `task_requests_seen` — confirmed via grep that no file outside
`core/monitor.py`/`core/monitor_session.py` touched any of them. `filter_sessions_by_mode` also
died: with `MODE_MAIN` gone it was a permanent no-op wrapper (`mode == MODE_MAIN` never true,
always returned `sessions` unchanged). `monitor_sessions()` simplified to
`update_session_tracking(find_active_sessions(...))` — pure session-file bookkeeping, no more
`process_all_sessions`/`process_session_file` call. `get_file_end_position`/`get_initial_position`
moved in from the deleted `monitor_session.py` (their only remaining callers,
`initialize_file_positions`/`update_session_tracking`, both live here). `run_monitor`'s dispatch
`else` branch now raises `ValueError` for an unrecognized mode instead of silently falling into a
main-pane loop — every mode `workflow.py` can still route here (`workers`, `tokens`, `warnings`,
`proxy`, `worker-proxy`) is handled by an explicit `elif`, so the `else` is unreachable in normal
operation, matching the "fail fast" default rather than leaving a silent dead branch.
121 LOC, down from 379.

**Deleted modules (only caller was the main pane), confirmed via grep before deleting:**
- `src/core/monitor_display.py` — `main_event_buffer`, `render_main_buffer`, `display_tool_call`,
  `display_warning`, `print_session_status`, and all main-pane-only search/copy machinery. Zero
  callers outside `core/monitor.py` and the deleted `core/monitor_session.py`.
- `src/core/monitor_session.py` — `process_session_file`, `process_all_sessions`,
  `is_task_request`/`is_task_response`/`is_subagent_call`, `handle_task_request`/
  `handle_task_response`/`handle_subagent_call`, `load_historical_main`. Its only callers were
  `core/monitor.py`'s now-deleted main-loop dispatch and `core/__init__.py`'s re-export.
- `src/format/formatter.py` — `format_tool_call` and everything it composed
  (`format_request`/`format_response`/`combine_request_response`/`format_todo_list`/
  `format_parameters`/`format_task_parameters`/`format_output`/`format_error_output`/
  `format_value`/`get_status_icon`/`get_status_color`) had exactly one caller,
  `monitor_display.py`. `shorten_tool_name` did NOT die with it — grep found a second real caller,
  `format/token_format.py:139` (`mcp__` tool name shortening for the tokens pane's own render) —
  moved there instead, `format/__init__.py`/`format/DOCS.md` updated.
- `src/jsonl/jsonl_extractors.py` and the tool-call-classification half of
  `src/jsonl/jsonl_parser.py` (`extract_tool_calls`, `create_tool_use_entry`,
  `update_request_numbers`, `parse_new_tool_calls`/`parse_new_tool_calls_isolated` + its
  subprocess worker, `is_tool_result`, `get_progress_content`, `extract_spawned_agent_id`,
  `extract_result_content`, `filter_excluded_tools`, `sort_by_timestamp`,
  `build_malformed_warnings`) — grepped for every symbol individually across `src/` AND `dev/`
  before deleting; the only real caller of the higher-level `parse_new_tool_calls*` functions was
  `monitor_session.py` (confirmed also by the already-existing `jsonl/DOCS.md` note recording this
  same finding from the 2026-09-05 req-numbering milestone). Survivors — `read_new_lines`,
  `get_current_position`, `parse_jsonl_lines`, `get_message_content`, `is_tool_use`,
  `extract_cache_turns` — are read directly by `panes/token_pane.py` and `workers/worker_format.py`,
  confirmed still wired after the cut (302 LOC → 56 LOC in `jsonl_parser.py`).
- Dead constants: `MODE_MAIN`, `TOOL_TASK` (only `monitor_session.py`'s task-classification used
  it), `MAIN_EVENT_BUFFER_CAP` (only `monitor_display.py`), `EXCLUDED_TOOLS` (only the deleted
  `filter_excluded_tools`).

## Warnings-pane finding

`monitor_session.py::process_session_file` returned *before* calling `display_warning` whenever
`active_mode in (MODE_WARNINGS, MODE_TOKENS)` — malformed-JSON warnings from the session-parse
pipeline never reached the warnings pane's own display, only the now-deleted main pane's buffer.
The warnings pane's real `tool_errors` come entirely from the proxy's `_errors` dual-logs
(`find_errors_log_path`/`scan_worker_errors_logs` in `proxy_display/parser.py`), a completely
independent path. **Conclusion: malformed-JSON warnings had zero surface once the main pane was
gone, and were dropped along with `display_warning`.** The warnings pane keeps calling
`monitor.monitor_sessions()` on startup and every poll tick — this is session-tracking bookkeeping
only (`file_positions` add/remove), which the milestone's own instructions required
`monitor_sessions` to keep serving as pane-facing API; nothing currently reads its side effect for
warnings-pane content.

## Log janitor relocation

The 24h JSONL sweep (`log_janitor.cleanup_old_jsonl` over `log_janitor.sweep_eligible_specs`)
moved from `core/monitor.py::run_main_loop` into `panes/token_pane.py::run_tokens_loop`, same
guard (`now - last_janitor_ts >= 86400`, threaded through `_refresh_tokens_data`'s return tuple
exactly like the old code threaded it through `_refresh_main_data`) and same path resolution
(`Path(__file__).parent.parent / 'logs'` — `token_pane.py` sits at the same depth under `src/` as
`monitor.py` did, `src/panes/` vs `src/core/`, so the two-`.parent` climb resolves to the same
`src/logs/`). Per `process-docs/logging/log_janitor.md`, the janitor must run from a pane that is
(a) always active whenever Monitor_CC runs and (b) resolves its own `__file__` from the main
checkout, not a frozen bundle — the tokens pane satisfies both exactly as the main pane did.

## dev/ cleanup

- `dev/main_pane/` deleted entirely (`probe_req_numbering.py`, its report, and
  `tests/test_req_numbering_and_format.py` — all main-pane-only).
- `dev/pane_search/p4_main_pane_parity_test.py` deleted (100% main-pane search-bar parity guard)
  plus its 11 `md/` reports; its `DOCS.md` section and intro-paragraph mention removed.
- `dev/click_ui/p2_copy_click_probe.py` (shared file covering 4 panes) — `test_main_pane_copy_click`
  and its `mod_main_display`/`mod_monitor` imports removed; the other 3 panes' tests untouched.
  `dev/click_ui/DOCS.md` updated to match.
- `dev/pane_error_log/p1_pane_loop_survives_exception_probe.py` — not in the milestone's named
  scope, but it directly imported `src.core.monitor` and called `run_main_loop()` as one of its 9
  pane-survival cases; this breaks the moment `run_main_loop` is deleted, so it's a caused-behavior
  change per the testing rule (a broken caller belongs to the task that broke it), not optional
  cleanup. `test_main_pane`/`mod_main` removed, "9 pane loops" → "8" throughout (docstring,
  print banner, the two "shared by all N panes"/"MRO relationship for all N" comments). `DOCS.md`
  updated to match (9→8, "8 previously unguarded"→"7").
- `dev/pane_search/p6_tokens_pane_parity_test.py`'s one call to `_refresh_tokens_data` (now 4 args
  after the `last_janitor_ts` threading) updated — passed `last_janitor_ts=10_000_000.0` (equal to
  `now`) so the unrelated search-state test never incidentally triggers a real janitor sweep.

## DOCS.md updates

`src/DOCS.md` (package table: `core/` 121 LOC/1 module, `panes/` 1037 LOC/4, `format/` 324 LOC/2,
`jsonl/` 206 LOC/2; Flow/Shared-State sections rewritten; `log_janitor.py`'s root-file description
updated to point at `token_pane.py`), `src/core/DOCS.md` (full rewrite — dispatcher-only role),
`src/format/DOCS.md` (`formatter.py` entry removed, `token_format.py` entry updated for the
`shorten_tool_name` move), `src/jsonl/DOCS.md` (full rewrite — no more tool-call classification
pipeline), `src/panes/DOCS.md` (`token_pane.py` entry: LOC + new janitor blurb + `log_janitor` in
Calls-out). `src/hooks/DOCS.md` checked — contains zero main-pane references (the "hooks" it
documents are CC safety hooks, unrelated to the deleted `--mode hooks` CLI vestige), not touched.

## Verification

Real launch from the worktree (`env -u TMUX -u TMUX_PANE python3 workflow.py --project <worktree>`
— the Bash tool's own shell runs inside a host tmux session, so `TMUX`/`TMUX_PANE` had to be
unset for the child process or `is_inside_tmux()` correctly refused to nest):

```
0.0 TOKENS 0
1.0 PROXY 0
2.0 WORKERS 0
2.1 WORKER-PROXY 0
3.0 WARNINGS 0
4.0 GPU 0
5.0 NEWS 0
5.1 NEWS-LOG 0
```

8 panes, none dead, window 0 exactly one pane, window 0 renamed `tokens`. Pane 0.0's start command
confirmed `--mode tokens` (not `main`). Captured pane 0.0's live output — real tokens-pane
rendering (REQ #158-175 with CR/CC/D/output columns), not a crash loop.

`--mode restart-panes --session monitor_cc_7304bf84` re-run against the live session: pane list
identical afterward (8 panes, none dead, same layout) — Ctrl+R's self-heal walks
`_WINDOW_LAYOUT` and found nothing missing, respawned all 8 panes in place, all PIDs alive after a
3s settle.

Session killed by exact name (`tmux kill-session -t monitor_cc_7304bf84`), confirmed gone via
`tmux has-session` (exit 1) and `ps aux | grep worktrees/nomain` (no output — no leftover child
processes).

Test suites re-run (all pre-existing failures excluded as environment-only, not regressions):

| Suite | Result |
|---|---|
| `dev/click_ui/p1_worker_selection_click_probe.py` | 35/35 |
| `dev/click_ui/p2_copy_click_probe.py` | 25/25 (was 34/34 before the main-pane case removal — 9 main-pane-only checks gone) |
| `dev/click_ui/p3_button_click_probe.py` | 32/32 |
| `dev/click_ui/p4_gpu_news_button_probe.py` | 53/53 |
| `dev/pane_search/p1_full_sweep_cost_probe.py` | pre-existing environment failure (gitignored forwarded-log fixture absent from this worktree — unrelated to this change, confirmed by its own DOCS.md) |
| `dev/pane_search/p2_search_feature_regression_test.py` | 48/48 |
| `dev/pane_search/p3_drag_select_regression_test.py` | 62/62 |
| `dev/pane_search/p5_worker_proxy_pane_parity_test.py` | 77/77 |
| `dev/pane_search/p6_tokens_pane_parity_test.py` | 78/78 |
| `dev/pane_search/p7_workers_pane_parity_test.py` | 76/76 |
| `dev/pane_search/p8_warnings_gpu_news_parity_test.py` | 82/82 |
| `dev/pane_error_log/p1_pane_loop_survives_exception_probe.py` | 47/47 (was 9-pane-loop probe, now 8) |
| `dev/hook_smoke/test_log_janitor.py` (untouched, sanity check on `log_janitor.py` itself) | 4/4 |

## Relevant Symbols / Paths

- `_WINDOW_LAYOUT`, `launch_split_screen`, `restart_panes` (`src/tmux_launcher.py`)
- `run_monitor`, `monitor_sessions`, `get_main_session_files` (`src/core/monitor.py`)
- `run_tokens_loop`, `_refresh_tokens_data` (`src/panes/token_pane.py`) — new janitor host
- `shorten_tool_name` (`src/format/token_format.py`) — moved from the deleted `formatter.py`
- `process-docs/logging/log_janitor.md` — why the janitor needs an always-active, main-checkout pane
- `process-docs/pipeline/pipe01_entry_startup.md` — write-once prior-state snapshot of the
  9-pane/6-window layout this milestone replaced; not edited, left as historical record
