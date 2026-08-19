# Menubar Worker Rows Clickable — Click Focuses Viewer Window (2026-08-19)

New feature in the hotkey-lag investigation's area (`process-docs/hotkey_latency/`): worker rows
in the main panel (`panel_manager.py:_rebuild_inner`) were previously built as inert buttons — no
tag, no target, no action. This entry adds click-to-focus: clicking a worker row focuses its
Ghostty viewer window (a Ghostty window running `tmux attach -t <worker's tmux session>`).

## Core Assumption — Verified Live Before Writing Any Code

Assumption: `ghostty.py`'s OSC2 title-marker probe maps ALL Ghostty child ttys to UUIDs,
including worker-viewer ttys (not just main-session ttys). Verified with real live data, no
mocks:

- `ps -A -o pid=,ppid=,tty=,args=` at verification time showed 3 real worker-viewer clients:
  `ttys064` (`tmux attach -t worker-linkedin-keep-filters`), `ttys071` (`tmux attach -t
  worker-monitor-cc-janitor`), `ttys072` (`tmux attach -t worker-monitor-cc-hotkey-latency`).
- Traced ancestry: each client's parent chain is `Ghostty(pid 1072) → /usr/bin/login (direct
  Ghostty child, same tty) → zsh → tmux attach`. `ghostty.py:_ghostty_child_ttys` collects ttys
  from any process with `ppid==ghostty_pid` — the `login` process qualifies, so the viewer's tty
  is included in the probe scope exactly like a main session's tty.
- Ran a real, completely unmodified `_refresh_ghostty_tty_to_id` cycle (forced past its TTL):
  all 3 viewer ttys resolved to real UUIDs (`ttys064→811FA26A-...`, `ttys071→E2B8F7AD-...`,
  `ttys072→14AF8F08-...`). **Zero code changes needed for this part** — the existing mechanism
  already covers worker-viewer ttys; the feature only needed a way to go from `tmux_session_name`
  → tty → that same existing UUID map.

## Design

- **`panel_manager.py`**: worker rows (`_rebuild_inner`'s `else` branch) now allocate a tag from
  the same `next_tag` counter main rows use (safe — dispatched by a different Cocoa action,
  `focusWorker:` vs `focusSession:`, so tag-value overlap between the two groups is harmless) and
  set `setTag_`/`setTarget_`/`setAction_(b'focusWorker:')` on `name_btn`+`dot_btn` (the only two
  rendered worker columns). New `_worker_tag_map[tag] = s.tmux_session_name`, reset each rebuild
  alongside `_cwd_map`.
- **`app.py:_PanelController.focusWorker_`**: mirrors `focusSession_` exactly — reads
  `panel._worker_tag_map.get(sender.tag())`, calls `system.py:_focus_worker(tmux_session_name)`
  if non-empty.
- **`system.py:_find_worker_viewer_tty(tmux_session_name)`**: one `ps -A -o pid=,tty=,args=`
  scan; matches `tokens[0]=='tmux' and tokens[1] in ('attach','attach-session') and '-t' in
  tokens and tokens[tokens.index('-t')+1] == tmux_session_name` — EXACT match on the `-t` value,
  not substring (verified live: `'worker-monitor-cc'` (prefix) and
  `'worker-monitor-cc-janitor-x'` (superstring) both correctly return `None` against the real
  live process table, while the exact session names correctly resolve).
- **`system.py:_focus_worker(tmux_session_name)`**: on a tty miss OR an unmapped tty
  (`ghostty.py:get_ghostty_terminal_id_for_tty` returns `None`), logs ONE
  `log_menubar('latency', 'focus_worker ... NO-OP reason=no_attach_client|tty_unmapped')` line and
  returns — deliberate no-op, no fallback (closed-viewer case is a user decision, not an error).
  On a hit: identical `focus terminal id "<uuid>"` AppleScript to `_focus_session` — **no
  `activate`** (`process-docs/ghostty_foreground/` — app-level activate brings Ghostty forward on
  every space, confirmed root-caused and fixed there 2026-06). Logs `log_menubar('latency',
  'focus_worker ... lookup_ms=... osascript_ms=... id=...')`.
- **`ghostty.py:get_ghostty_terminal_id_for_tty(tty)`**: new accessor, `_ghostty_tty_to_id.get(tty)`
  — single-key `.get()`, GIL-safe cross-thread read (no lock needed, consistent with the M3
  threading-model note on `get_ghostty_terminal_id`'s own read).

**Decisions made explicit and confirmed:** distinct `focus_worker` log-line prefix (not reused
`focus`) — different lookup mechanism and NO-OP semantics from `_focus_session`, kept separate
for unambiguous log parsing; no write to `/tmp/monitor-cc-menubar_focus.log` for the worker path
(that file predates the `[latency]` instrumentation, not extended here); all new subprocess calls
use `text=True, encoding='utf-8', errors='replace'` (launchd ASCII-locale gotcha, established
package-wide convention).

## Verification

**Integration-level, real data, real process table — but NOT the actual click/osascript path**
(explicit instruction: the visual click-and-window-jumps confirmation is the user's job, not
mine — I have no GUI input capability and was told not to press-test):

- `_find_worker_viewer_tty` + `get_ghostty_terminal_id_for_tty` run for real against the live
  process table for all 3 real worker sessions: all 3 resolved to their real tty and real UUID
  (matching the pre-implementation verification numbers exactly).
- Same pair run for a non-existent session name (`worker-monitor-cc-menubar-remote`, standing in
  for a closed-viewer case): correctly returned `tty=None` — the NO-OP path.
- False-positive guard: `_find_worker_viewer_tty('worker-monitor-cc')` (prefix of a real session
  name) and `_find_worker_viewer_tty('worker-monitor-cc-janitor-x')` (superstring) both correctly
  returned `None` against the real process table — confirms exact-match, not substring-match.
  A completely unrelated real tmux session name (`monitor_cc_cbc9195b`, a main-session viewer,
  not a worker) also resolved correctly via the same exact-match logic, showing the function
  generalizes correctly.
- I deliberately did NOT call `_focus_worker()` end-to-end (would trigger a real, visible
  osascript window-focus) — only the pure-lookup half was exercised by me.

**Production build + restart** (same `setup_py2app.py` procedure as M2/M3): build succeeded
first try (`bootstrap retry in 1s (rc=5)... bootstrap: ok` — the documented expected pattern),
PID changed (restart confirmed), no stderr/stdout errors post-restart, `bg_refresh`/`hotkey`
`[latency]` lines continued flowing normally (real concurrent user hotkey activity observed
during/after the restart) — no regression in the M1-M3 instrumentation or M3's threading fix.
Confirmed via grep that the built bundle's `app.py`/`system.py`/`panel_manager.py`/`ghostty.py`
contain the new `focusWorker`/`_focus_worker`/`get_ghostty_terminal_id_for_tty` symbols.

## What's Left for the User

Click-test each worker row in the live panel: `keep-filters`/`janitor`/`hotkey-latency` rows
should jump to their respective Ghostty viewer windows; a row for a worker with no open viewer
(e.g. a hypothetical `menubar-remote` worker) should visibly do nothing — confirming the NO-OP
path in the actual running UI, which I could not do myself.
