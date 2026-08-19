# Hotkey/Menubar Latency Report

Source: `/Users/brunowinter2000/Library/Application Support/com.brunowinter.monitor-cc-menubar/menubar.log`
Generated: 2026-08-19T16:15:46+00:00

## Tick Latency (over-threshold ticks only)

Total-duration distribution: n=206 mean=636.1 median=213.0 p90=1142.0 p95=3611.0 max=4577.0

### Per-Phase Distribution (ms, over over-threshold ticks)

- `bg_task_lsof`: n=206 mean=28.8 median=0.0 p90=103.0 p95=106.0 max=138.0
- `bg_timer_scan`: n=206 mean=40.5 median=36.0 p90=52.0 p95=55.0 max=135.0
- `desktop_detection`: n=206 mean=343.2 median=0.0 p90=715.0 p95=2239.0 max=3643.0
- `focus_tick`: n=206 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `ghostty`: n=206 mean=156.6 median=153.0 p90=169.0 p95=174.0 max=776.0
- `panel_rebuild_update`: n=206 mean=0.2 median=0.0 p90=0.0 p95=1.0 max=9.0
- `per_project_loop`: n=206 mean=23.0 median=14.0 p90=19.0 p95=20.0 max=1763.0
- `proc_cache`: n=206 mean=40.7 median=0.0 p90=136.0 p95=143.0 max=398.0
- `queue_tick`: n=206 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `rag_tick`: n=206 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `sessions_refresh_total`: n=206 mean=595.2 median=177.0 p90=1085.0 p95=3548.0 max=4515.0
- `tmux_state`: n=206 mean=2.8 median=4.0 p90=6.0 p95=6.0 max=14.0

### Slowest 10 Ticks

- 2026-08-19T18:14:14 total=4577ms — sessions_refresh_total=4515ms desktop_detection=3544ms ghostty=665ms proc_cache=160ms bg_task_lsof=111ms bg_timer_scan=53ms per_project_loop=22ms tmux_state=14ms panel_rebuild_update=8ms focus_tick=0ms queue_tick=0ms rag_tick=0ms
- 2026-08-19T17:56:21 total=4433ms — sessions_refresh_total=4390ms desktop_detection=3255ms ghostty=581ms proc_cache=393ms bg_task_lsof=137ms bg_timer_scan=35ms per_project_loop=19ms panel_rebuild_update=7ms tmux_state=6ms focus_tick=0ms queue_tick=0ms rag_tick=0ms
- 2026-08-19T18:14:24 total=4067ms — sessions_refresh_total=4013ms desktop_detection=3630ms ghostty=133ms proc_cache=130ms bg_task_lsof=101ms bg_timer_scan=54ms per_project_loop=13ms tmux_state=5ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:15:27 total=4048ms — sessions_refresh_total=4001ms desktop_detection=3643ms proc_cache=127ms ghostty=117ms bg_task_lsof=103ms bg_timer_scan=47ms per_project_loop=11ms tmux_state=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:14:55 total=4031ms — sessions_refresh_total=3982ms desktop_detection=3605ms ghostty=136ms proc_cache=121ms bg_task_lsof=103ms bg_timer_scan=48ms per_project_loop=12ms tmux_state=5ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:15:37 total=4010ms — sessions_refresh_total=3958ms desktop_detection=3594ms proc_cache=141ms ghostty=113ms bg_task_lsof=99ms bg_timer_scan=52ms per_project_loop=10ms tmux_state=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:14:45 total=3973ms — sessions_refresh_total=3925ms desktop_detection=3554ms proc_cache=143ms ghostty=120ms bg_task_lsof=93ms bg_timer_scan=48ms per_project_loop=10ms tmux_state=5ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:15:16 total=3971ms — sessions_refresh_total=3921ms desktop_detection=3544ms proc_cache=133ms ghostty=127ms bg_task_lsof=100ms bg_timer_scan=50ms per_project_loop=12ms tmux_state=5ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:14:34 total=3927ms — sessions_refresh_total=3878ms desktop_detection=3523ms proc_cache=126ms ghostty=121ms bg_task_lsof=97ms bg_timer_scan=49ms per_project_loop=12ms tmux_state=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:15:06 total=3897ms — sessions_refresh_total=3846ms desktop_detection=3484ms proc_cache=135ms ghostty=117ms bg_task_lsof=100ms bg_timer_scan=51ms per_project_loop=11ms tmux_state=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms

## Hotkey Queue-Delay (queue_delay_ms = handler-entry time - Carbon event timestamp)

Overall: n=63 mean=0.4 median=0.2 p90=0.4 p95=0.5 max=12.3

### Per Hotkey

- `cmd+2`: n=1 mean=0.1 median=0.1 p90=0.1 p95=0.1 max=0.1
- `cmd+3`: n=2 mean=6.2 median=6.2 p90=12.3 p95=12.3 max=12.3
- `cmd+k`: n=49 mean=0.2 median=0.2 p90=0.3 p95=0.5 max=1.0
- `cmd+l`: n=11 mean=0.3 median=0.2 p90=0.5 p95=1.2 max=1.2

## Focus-Path Timing (_focus_session)

- `lookup_ms` (get_ghostty_terminal_id): n=4 mean=0.0 median=0.0 p90=0.1 p95=0.1 max=0.1
- `osascript_ms` (osascript run): n=4 mean=83.8 median=88.8 p90=91.8 p95=91.8 max=91.8
