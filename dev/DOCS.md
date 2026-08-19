# Dev Scripts

Development and testing scripts for Monitor_CC pipeline components.

## Working Directory

**CRITICAL:** All commands assume CWD = `Monitor_CC/` (project root)

```bash
cd Monitor_CC/
```

## Documentation Tree

- [display/DOCS.md](display/DOCS.md) — Display layer tests + format_cache_tracker differential proof
- [jsonl/DOCS.md](jsonl/DOCS.md) — extract_cache_turns differential proof harness
- [hook_error_correlation/DOCS.md](hook_error_correlation/DOCS.md) — Hook-caused tool-error overlay analysis (`hook_firing.jsonl` × `tool_errors.jsonl`); `md/` also holds the historical 2026-05-22 hook block-event snapshot
- [pipeline/DOCS.md](pipeline/DOCS.md) — Pipeline evaluation suite (memory, I/O, parsing, format stability)
- [session_analysis/DOCS.md](session_analysis/DOCS.md) — Forensic session JSONL + proxy log analysis (cache behavior, rebuild detection, token attribution)
- [tool_injection/DOCS.md](tool_injection/DOCS.md) — MCP tool schema extraction for proxy-side tool injection
- [tool_use_analysis/DOCS.md](tool_use_analysis/DOCS.md) — Tool-use input size extraction (Proxy JSONL) + zero-result detection (Session JSONL)
- [tool_use_errors/DOCS.md](tool_use_errors/DOCS.md) — Empirical audit of `src/logs/tool_errors.jsonl` — cluster analysis + strip_hook_prefix.py cross-check (2026-05-30)
- [cursor_edges/DOCS.md](cursor_edges/DOCS.md) — NSPanel cursor-rect investigation probe — edge hover ↔/↕ blockers (NonactivatingPanel, subview coverage, mask conflicts)
- [menubar_nspanel/DOCS.md](menubar_nspanel/DOCS.md) — NSPanel sticky-toggle probe suite — persistent menubar panel replacing NSMenu auto-dismiss behavior
- [cc_internals/DOCS.md](cc_internals/DOCS.md) — CC binary + source research artifacts — env-var inventory from npm binaries, cross-referenced against community decompiles
- [ToolsSystemPrompts/DOCS.md](ToolsSystemPrompts/DOCS.md) — Captured CC built-in tool definitions + sys[3] segment — char-count corpus for proxy tool-injection/stripping budget analysis
- [ram_audit/DOCS.md](ram_audit/DOCS.md) — Pane RAM snapshot investigation — SIGUSR1 dump handler + `dump_all.sh` for live RSS/allocator capture across all panes
- [sleep_pattern_analysis/DOCS.md](sleep_pattern_analysis/DOCS.md) — Empirical audit of `block_chained_sleep` firing events; classifies cmd_before tokens as trivial-sync / load-bearing / mixed to inform `rewrite_chained_sleep.py` design
- [hook_smoke/DOCS.md](hook_smoke/DOCS.md) — Hook blocking/rewrite smoke tests — one test script per hook (block_dangerous_kill, block_read_worktree, rewrite_chained_sleep; block_chained_sleep preserved for reference; test_fire_log added 2026-05-24); also holds `test_bg_task_detection.py` + `probe_bg_task_live.py` for `proc_cache.py::_has_active_bg` (menubar background-task predicate, not a hook — added 2026-07-30)
- `bead_tracker/` — `smoke.py`: end-to-end smoke for `bead_tracker_hook` per-subcommand processing (4 cases: single, chained `;`, cross-project skip, pipe non-split); creates/deletes real test beads; no own DOCS.md
- [strip_fp_tool_result/DOCS.md](strip_fp_tool_result/DOCS.md) — Audit: which strip passes remove content from inside `tool_result` blocks, split SR strip family vs. unrelated non-SR passes; measurement only
- [proxy_instrumentation/DOCS.md](proxy_instrumentation/DOCS.md) — Reconstructs/measures the proxy's real strip/inject pipeline from recorded dual-log payloads through the real production code, no live proxy required
- [bg_wakeup_id_line/DOCS.md](bg_wakeup_id_line/DOCS.md) — CC background-launch-ack wording inventory (`p1_`) + tmux-Escape-on-launch-ack mechanism verification (`p2_`, `src/proxy/bg_escape.py`); `md/` holds both scripts' reports
- [pane_error_log/DOCS.md](pane_error_log/DOCS.md) — Regression coverage for the shared exception-safe pane-error sink (`src/pane_error_log.py`) and the exception guard on all 9 pane event loops — catch+log+continue, `KeyboardInterrupt`/`SystemExit` passthrough, failing-log-write safety, sink size-capping
- [click_ui/DOCS.md](click_ui/DOCS.md) — Click-UI milestone series (every pane control mouse-clickable) — Milestone 1: worker-selection click-region parity vs. digit keys, worker-proxy header + workers pane
- [hotkey_latency/DOCS.md](hotkey_latency/DOCS.md) — Menubar hotkey-lag investigation tooling: `GetEventTime`/`GetCurrentEventTime` probe + `menubar.log` `[latency]` line parser/report generator; measurement only, no `src/` behavior change

## session_analysis/

See [session_analysis/DOCS.md](session_analysis/DOCS.md).

6 standalone analysis scripts (01–06) + `md/` for `05_req_breakdown.py` output. No pipeline mapping.
