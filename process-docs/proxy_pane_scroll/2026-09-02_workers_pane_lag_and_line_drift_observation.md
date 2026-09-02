# Workers pane — lag and line drift while scrolling, observation only (2026-09-02)

User-reported on the workers pane (tab 2, left pane, `src/workers/worker_pane.py`) with five
workers listed, two of them expanded with their request tables (one with 29 requests). Not
investigated in this session; recorded for the follow-up.

## Symptom

- The pane reacts to wheel scrolling with a noticeable delay, described as "generell total
  laggy", and no usable scrolling is possible.
- While scrolling, rows shift against each other, the same symptom class the user recalls from
  earlier work in this area. The screenshots show a selected-row highlight sitting on a request
  row inside an expanded worker (REQ #22 of devproxy-docs) while the `>>` cursor marks the worker
  header line above it, and a second capture where the highlight bar spans two request rows
  (REQ #1 and REQ #2 of spawn-placement-msg) with the row highlight offset by one line against
  the left-edge marker.

## State of the pane at the time

Five workers alive and idle: capture-git-status (11 requests shown), devproxy-docs (29 requests,
expanded), gcommit-umlaut, spawn-placement-msg (6 requests, expanded in one capture),
verifier-retire (7+ requests, expanded in one capture). The pane was in SCROLL mode per the
status line. The monitor process had been running since the morning.

## Prior work in this area that a follow-up should read first

The three clamp entries of 2026-07-21, 2026-07-28 and 2026-08-04 cover state-versus-display
scroll drift in the proxy, worker-proxy and main panes; the workers pane itself has per-worker
scroll offsets (`worker_scroll_offsets`) plus a pane-level bottom-anchored offset, documented in
the pane_search rollout entry of 2026-08-18 in `process-docs/pane_search/`. Whether the workers
pane ever received a write-back clamp of the same shape is the first thing to check. The lag is a
separate question from the drift and may be render cost with five expanded request tables.
