# Hotkey/Menubar Latency Report

Source: `/Users/brunowinter2000/Library/Application Support/com.brunowinter.monitor-cc-menubar/menubar.log`
Generated: 2026-08-19T16:49:25+00:00

## Main-Thread Tick Latency (over-threshold ticks only)

Total-duration distribution: n=861 mean=835.8 median=215.0 p90=2863.0 p95=2910.0 max=4577.0

### Per-Phase Distribution (ms)

- `bg_task_lsof`: n=853 mean=27.8 median=0.0 p90=103.0 p95=105.0 max=138.0
- `bg_timer_scan`: n=853 mean=40.7 median=36.0 p90=54.0 p95=57.0 max=135.0
- `desktop_detection`: n=853 mean=565.8 median=0.0 p90=2432.0 p95=2472.0 max=3724.0
- `focus_tick`: n=861 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `ghostty`: n=853 mean=150.8 median=152.0 p90=167.0 p95=173.0 max=776.0
- `panel_rebuild_update`: n=861 mean=0.1 median=0.0 p90=0.0 p95=1.0 max=9.0
- `per_project_loop`: n=853 mean=17.3 median=15.0 p90=20.0 p95=21.0 max=1763.0
- `proc_cache`: n=853 mean=37.7 median=0.0 p90=136.0 p95=143.0 max=398.0
- `queue_tick`: n=861 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `rag_tick`: n=861 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `sessions_refresh_total`: n=853 mean=802.4 median=178.0 p90=2806.0 p95=2858.0 max=4515.0
- `snapshot_consume`: n=8 mean=0.0 median=0.0 p90=0.0 p95=0.0 max=0.0
- `tmux_state`: n=853 mean=3.1 median=0.0 p90=7.0 p95=7.0 max=14.0

### Slowest 10 Entries

- 2026-08-19T18:14:14 total=4577ms — sessions_refresh_total=4515ms desktop_detection=3544ms ghostty=665ms proc_cache=160ms bg_task_lsof=111ms bg_timer_scan=53ms per_project_loop=22ms tmux_state=14ms panel_rebuild_update=8ms focus_tick=0ms queue_tick=0ms rag_tick=0ms
- 2026-08-19T17:56:21 total=4433ms — sessions_refresh_total=4390ms desktop_detection=3255ms ghostty=581ms proc_cache=393ms bg_task_lsof=137ms bg_timer_scan=35ms per_project_loop=19ms panel_rebuild_update=7ms tmux_state=6ms focus_tick=0ms queue_tick=0ms rag_tick=0ms
- 2026-08-19T18:44:51 total=4154ms — sessions_refresh_total=4097ms desktop_detection=3724ms proc_cache=133ms ghostty=117ms bg_task_lsof=103ms bg_timer_scan=56ms per_project_loop=20ms tmux_state=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:43:37 total=4071ms — sessions_refresh_total=4012ms desktop_detection=3627ms proc_cache=144ms ghostty=124ms bg_task_lsof=100ms bg_timer_scan=59ms per_project_loop=17ms tmux_state=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:14:24 total=4067ms — sessions_refresh_total=4013ms desktop_detection=3630ms ghostty=133ms proc_cache=130ms bg_task_lsof=101ms bg_timer_scan=54ms per_project_loop=13ms tmux_state=5ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:44:09 total=4062ms — sessions_refresh_total=4012ms desktop_detection=3603ms ghostty=156ms proc_cache=128ms bg_task_lsof=105ms bg_timer_scan=49ms per_project_loop=20ms tmux_state=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:45:01 total=4054ms — sessions_refresh_total=3999ms desktop_detection=3554ms ghostty=160ms proc_cache=135ms bg_task_lsof=123ms bg_timer_scan=54ms per_project_loop=19ms tmux_state=9ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:15:27 total=4048ms — sessions_refresh_total=4001ms desktop_detection=3643ms proc_cache=127ms ghostty=117ms bg_task_lsof=103ms bg_timer_scan=47ms per_project_loop=11ms tmux_state=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:43:58 total=4044ms — sessions_refresh_total=3990ms desktop_detection=3589ms proc_cache=140ms ghostty=132ms bg_task_lsof=109ms bg_timer_scan=53ms per_project_loop=20ms tmux_state=0ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms
- 2026-08-19T18:44:30 total=4037ms — sessions_refresh_total=3985ms desktop_detection=3614ms ghostty=127ms proc_cache=125ms bg_task_lsof=94ms bg_timer_scan=52ms per_project_loop=17ms tmux_state=7ms focus_tick=0ms queue_tick=0ms rag_tick=0ms panel_rebuild_update=0ms

## Background Discovery-Worker Cycle Latency (over-threshold cycles only)

Total-duration distribution: n=33 mean=1328.8 median=1133.0 p90=3935.0 p95=4425.0 max=4544.0

### Per-Phase Distribution (ms)

- `bg_task_lsof`: n=33 mean=74.3 median=104.0 p90=125.0 p95=130.0 max=139.0
- `desktop_detection`: n=33 mean=846.0 median=698.0 p90=3265.0 p95=3267.0 max=3303.0
- `ghostty`: n=33 mean=157.4 median=120.0 p90=576.0 p95=577.0 max=676.0
- `per_project_loop`: n=33 mean=72.0 median=17.0 p90=19.0 p95=19.0 max=1831.0
- `proc_cache`: n=33 mean=132.5 median=143.0 p90=404.0 p95=406.0 max=483.0
- `tmux_state`: n=33 mean=3.4 median=5.0 p90=6.0 p95=6.0 max=13.0

### Slowest 10 Entries

- 2026-08-19T18:42:56 total=4544ms — desktop_detection=3303ms ghostty=576ms proc_cache=483ms bg_task_lsof=125ms per_project_loop=17ms tmux_state=5ms
- 2026-08-19T18:48:45 total=4530ms — desktop_detection=3293ms ghostty=600ms proc_cache=439ms bg_task_lsof=139ms per_project_loop=17ms tmux_state=6ms
- 2026-08-19T18:43:31 total=4425ms — desktop_detection=3265ms ghostty=577ms proc_cache=404ms bg_task_lsof=123ms per_project_loop=17ms tmux_state=6ms
- 2026-08-19T18:44:33 total=3935ms — desktop_detection=2792ms ghostty=559ms proc_cache=406ms bg_task_lsof=120ms per_project_loop=17ms tmux_state=5ms
- 2026-08-19T18:48:55 total=3706ms — desktop_detection=3267ms bg_task_lsof=130ms ghostty=129ms proc_cache=121ms per_project_loop=14ms tmux_state=5ms
- 2026-08-19T18:46:30 total=3588ms — per_project_loop=1831ms desktop_detection=725ms ghostty=676ms proc_cache=181ms bg_task_lsof=116ms tmux_state=13ms
- 2026-08-19T18:48:40 total=1270ms — desktop_detection=732ms proc_cache=161ms ghostty=158ms bg_task_lsof=136ms per_project_loop=24ms tmux_state=7ms
- 2026-08-19T18:47:12 total=1197ms — desktop_detection=743ms proc_cache=164ms ghostty=117ms bg_task_lsof=104ms per_project_loop=17ms tmux_state=5ms
- 2026-08-19T18:47:45 total=1193ms — desktop_detection=706ms ghostty=154ms proc_cache=147ms bg_task_lsof=117ms per_project_loop=17ms tmux_state=0ms
- 2026-08-19T18:48:18 total=1174ms — desktop_detection=711ms proc_cache=145ms ghostty=145ms bg_task_lsof=105ms per_project_loop=16ms tmux_state=5ms

## Hotkey Queue-Delay (queue_delay_ms = handler-entry time - Carbon event timestamp)

Overall: n=89 mean=0.4 median=0.2 p90=0.3 p95=0.5 max=12.3

### Per Hotkey

- `cmd+1`: n=3 mean=0.2 median=0.2 p90=0.2 p95=0.2 max=0.2
- `cmd+2`: n=3 mean=0.2 median=0.2 p90=0.3 p95=0.3 max=0.3
- `cmd+3`: n=4 mean=3.2 median=0.2 p90=12.3 p95=12.3 max=12.3
- `cmd+k`: n=67 mean=0.2 median=0.2 p90=0.3 p95=0.5 max=1.0
- `cmd+l`: n=12 mean=0.3 median=0.2 p90=0.5 p95=0.5 max=1.2

## Focus-Path Timing (_focus_session)

- `lookup_ms` (get_ghostty_terminal_id): n=11 mean=0.0 median=0.0 p90=0.1 p95=0.1 max=0.1
- `osascript_ms` (osascript run): n=11 mean=88.3 median=87.1 p90=112.0 p95=120.4 max=120.4
