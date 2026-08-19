# Hotkey/Menubar Latency Report

Source: `/Users/brunowinter2000/Library/Application Support/com.brunowinter.monitor-cc-menubar/menubar.log`
Generated: 2026-08-19T15:59:46+00:00

## Tick Latency (over-threshold ticks only)

Total-duration distribution: n=4 mean=1992.5 median=1742.0 p90=4433.0 p95=4433.0 max=4433.0

### Per-Phase Distribution (ms, over over-threshold ticks)

- `bg_task_lsof`: n=4 mean=68.8 median=68.5 p90=138.0 p95=138.0 max=138.0
- `bg_timer_scan`: n=4 mean=35.2 median=35.0 p90=39.0 p95=39.0 max=39.0
- `desktop_detection`: n=4 mean=1373.5 median=1119.5 p90=3255.0 p95=3255.0 max=3255.0
- `focus_tick`: n=4 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `ghostty`: n=4 mean=289.8 median=289.0 p90=581.0 p95=581.0 max=581.0
- `panel_rebuild_update`: n=4 mean=4.0 median=3.5 p90=9.0 p95=9.0 max=9.0
- `per_project_loop`: n=4 mean=18.0 median=18.5 p90=20.0 p95=20.0 max=20.0
- `proc_cache`: n=4 mean=197.8 median=196.5 p90=398.0 p95=398.0 max=398.0
- `queue_tick`: n=4 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `rag_tick`: n=4 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `sessions_refresh_total`: n=4 mean=1952.8 median=1700.5 p90=4390.0 p95=4390.0 max=4390.0
- `tmux_state`: n=4 mean=5.5 median=5.5 p90=6.0 p95=6.0 max=6.0

### Slowest 4 Ticks

- 2026-08-19T17:56:21 total=4433ms — sessions_refresh_total=4390ms desktop_detection=3255ms ghostty=581ms proc_cache=393ms bg_task_lsof=137ms bg_timer_scan=35ms per_project_loop=19ms panel_rebuild_update=7ms tmux_state=6ms focus_tick=0ms queue_tick=0ms rag_tick=0ms
- 2026-08-19T17:56:10 total=3422ms — sessions_refresh_total=3378ms desktop_detection=2239ms ghostty=578ms proc_cache=398ms bg_task_lsof=138ms bg_timer_scan=35ms per_project_loop=20ms panel_rebuild_update=9ms tmux_state=6ms focus_tick=0ms queue_tick=0ms rag_tick=0ms
- 2026-08-19T17:56:10 total=62ms — bg_timer_scan=39ms sessions_refresh_total=23ms per_project_loop=18ms tmux_state=5ms proc_cache=0ms ghostty=0ms bg_task_lsof=0ms desktop_detection=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T17:56:21 total=53ms — bg_timer_scan=32ms sessions_refresh_total=20ms per_project_loop=15ms tmux_state=5ms proc_cache=0ms ghostty=0ms bg_task_lsof=0ms desktop_detection=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms

## Hotkey Queue-Delay (queue_delay_ms = handler-entry time - Carbon event timestamp)

Overall: n=1 mean=12.3 median=12.3 p90=12.3 p95=12.3 max=12.3

### Per Hotkey

- `cmd+3`: n=1 mean=12.3 median=12.3 p90=12.3 p95=12.3 max=12.3

## Focus-Path Timing (_focus_session)

- `lookup_ms` (get_ghostty_terminal_id): n=1 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `osascript_ms` (osascript run): n=1 mean=87.1 median=87.1 p90=87.1 p95=87.1 max=87.1
