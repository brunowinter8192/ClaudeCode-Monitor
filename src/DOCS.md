# src/ — Monitor_CC

## Role

Real-time monitor for Claude Code sessions. Reads Claude Code's JSONL output files and the mitmproxy API log, formats tool calls and events to a terminal, and drives 8 dedicated tmux panes (tokens, warnings, workers, worker-proxy, proxy, gpu, news, news-log). The `src/` tree is the entire application — `workflow.py` at the project root is just a 25-line entry point.

## Entry Points

- `workflow.py` → `src.startup`, `src.tmux_launcher`, `src.core.monitor`
- mitmproxy → `src.proxy_addon` (thin shim, loaded via `mitmproxy -s src/proxy_addon.py`)
- tmux panes → `workflow.py --mode <pane>` (each pane is a separate process)

## Directory Map

| Subdir | Role | LOC | Modules |
|---|---|---|---|
| `core/` | Session polling orchestrator + main-pane output | 911 | 3 |
| `panes/` | Tmux pane event loops (tokens, warnings) + warnings scan/render/parse helpers | 701 | 3 |
| `format/` | ANSI string rendering (tool calls, events, cache tracker) | 506 | 4 |
| `input/` | Keyboard/mouse stdin handling | 150 | 1 |
| `jsonl/` | JSONL parsing + tool call extraction | 580 | 3 |
| `workers/` | Workers pane (tmux session discovery + status display) | 658 | 3 |
| `proxy_display/` | Proxy pane TUI (two-level expand, delta rendering, subprocess-parse, copy-button) | 2310 | 8 |
| `proxy/` | mitmproxy addon (payload modification + JSONL logging) | 3074 | 18 |
| `ram_audit/` | SIGUSR1 RAM-dump helper, gated by MONITOR_CC_RAM_AUDIT env | 101 | 1 |
| `menubar/` | macOS status-bar app showing live CC sessions (rumps/AppKit) | 3481 | 18 |
| `gpu_pane/` | GPU server monitor pane (cross-project, reads RAG state) | 613 | 3 |
| `news_pane/` | CoinDesk news pipeline control (left) + live log tail (right) | 388 | 3 |
| `hooks/` | Global CC safety hooks (PreToolUse scripts + hook_setup) | 1674 | 22 |
| `ccwrap/` | Standalone PTY wrapper with diagnostic ANSI logging for CC (Phase 1 diagnostic tool) | 254 | 4 |

## Root-Level Files

| File | LOC | Why at root |
|---|---|---|
| `constants.py` | 152 | Imported by ~all subpackages — shallow path avoids deep `...constants` chains |
| `utils.py` | 148 | Same — `format_timestamp` + `visual_line_count` used everywhere; also `append_copy_symbol` (right-align a ⎘/✓ symbol, width-guarded — shared by `core.monitor_display`, `format.token_format`, `panes.warnings_render`, `workers.worker_format`, and `proxy_display`'s own reference implementation stays independent), `compute_header_rule_len` (shrinking-decoration header layout, shared by `gpu_pane`/`news_pane`), and `highlight_query_in_line` (2026-08, browser-find-style inline substring BG highlight, ANSI-safe; `restore_bg` param defaults to `\033[49m` for callers with no per-row background — `core.monitor_display` still keeps its own identical private copy, not yet migrated; `proxy_display.render_turn` passes a caller-owned sentinel instead, substituted for the real row background once known — see `proxy_display/DOCS.md`) |
| `pane_error_log.py` | 35 | `log_pane_error(pane_name)` — shared exception-safe sink all 8 pane `run_*_loop()` functions call from their `except Exception:` guard (2026-07-31); imported by every pane module the same shallow-path way as `constants.py`, so it belongs at the same level |
| `log_janitor.py` | 160 | `LogSpec` registry (11 entries) + `sweep_eligible_specs()` + `cleanup_old_jsonl(path)` — authoritative log inventory; 7-day JSONL sweep triggered from `core/monitor.py` every 24h |
| `session_finder.py` | 85 | Single module, no subpackage warranted |
| `startup.py` | 48 | Single module; only called by `workflow.py` |
| `tmux_launcher.py` | 287 | Single module; only called by `workflow.py` (mode `all` → `launch_split_screen`; mode `restart-panes` → `restart_panes`, the Ctrl+R self-heal handler) |
| `proxy_addon.py` | 31 | Thin shim — `claude_proxy_start.sh` copies it to `src/logs/.proxy_addon_live_<id>.py` for per-session isolation. Shim has sys.path logic that finds `src/proxy/` from both root and live-copy locations. Move would break live-copy pattern. |
| `claude_proxy_start.sh` | 402 | Shell script — launches mitmproxy + Claude Code with proxy env; version-aware purge (Phase 0: hash proxy source, delete stale >60min logs on change) + count-30 quartet-aligned dual-log rotation; per-project marker (src/logs + /tmp) with PID+identity liveness guard + 10s heartbeat reclaim; `--fable`/`--opus` shortcut flags (2026-08-06) map to `--model claude-fable-5`/`claude-opus-5` so the main session starts natively on the chosen model (workers already did via a separate spawn script) — an explicit `--model` always wins over either shortcut regardless of argument order, no flag at all leaves `CLAUDE_ARGS` byte-identical to before |

## Flow (Main Session)

1. `workflow.py` → `run_monitor(project_filter, mode="all")` → `tmux_launcher.launch_split_screen()` spawns 9 panes each running `workflow.py --mode <X>`.
2. The main pane runs `run_main_loop()` (in `core/monitor.py`): every 0.5s discover sessions → for each session read new JSONL lines → classify tool calls → append to `main_event_buffer` (list in `core/monitor_display.py`) → render via `render_main_buffer()` → `print()` to stdout in `run_main_loop()`.
3. Each dedicated pane runs its own event loop (e.g. `run_tokens_loop()`): poll data source → handle mouse/keyboard → render full screen.
4. mitmproxy (started by `claude_proxy_start.sh`) intercepts API traffic, strips/modifies payloads, logs to `src/logs/api_requests_<id>.jsonl`.
5. Panes that need proxy data (proxy_display, warnings) tail that JSONL file independently.

## Shared State

Most runtime state lives in `core/monitor.py` as module-level variables; display-side buffer state lives in `core/monitor_display.py`. Every pane that needs session state imports via `from ..core import monitor as _monitor` (lazy, inside the run function to avoid circular imports).

| State | Owner | Readers |
|---|---|---|
| `file_positions`, `call_counter` | `core/monitor.py` | `core/monitor_session.py` |
| `agent_to_task`, `agent_to_type` | `core/monitor.py` | `core/monitor_session.py`, pane loops |
| `active_project_filter` | `core/monitor.py` | all pane loops |
| `main_event_buffer`, `main_scroll_offset`, `main_hover_row`, `main_line_map` | `core/monitor_display.py` | `core/monitor.py` (`run_main_loop`) |
| Pane scroll/expand state | each pane module | that pane only |

## Subdir DOCS

- [core/DOCS.md](core/DOCS.md) — polling loop, session processing, main-pane display
- [panes/DOCS.md](panes/DOCS.md) — token, warnings pane loops
- [format/DOCS.md](format/DOCS.md) — formatter, formatter_events, token_format
- [input/DOCS.md](input/DOCS.md) — click_handler
- [jsonl/DOCS.md](jsonl/DOCS.md) — jsonl_parser, jsonl_extractors, jsonl_cache_turns
- [workers/DOCS.md](workers/DOCS.md) — worker_pane, worker_format, worker_tmux
- [proxy_display/DOCS.md](proxy_display/DOCS.md) — proxy pane TUI (8 modules)
- [proxy/DOCS.md](proxy/DOCS.md) — mitmproxy addon (18 modules)
- [ram_audit/DOCS.md](ram_audit/DOCS.md) — SIGUSR1 RAM-dump helper (env-gated tracemalloc)
- [menubar/DOCS.md](menubar/DOCS.md) — macOS menubar app (rumps, session discovery, background-task badge)
- [gpu_pane/DOCS.md](gpu_pane/DOCS.md) — GPU monitor pane (status, errors, toggle)
- [news_pane/DOCS.md](news_pane/DOCS.md) — CoinDesk news pipeline control pane + live log pane
- [hooks/DOCS.md](hooks/DOCS.md) — Global CC PreToolUse safety hooks (block scripts + hook_setup)
- [ccwrap/DOCS.md](ccwrap/DOCS.md) — PTY wrapper with diagnostic ANSI logging (Phase 1 diagnostic tool)
