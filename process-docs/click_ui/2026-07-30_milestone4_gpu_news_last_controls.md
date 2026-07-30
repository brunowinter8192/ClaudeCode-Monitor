# 2026-07-30 — Milestone 4: gpu + news panes, last keyboard-only controls closed

## Problem

Last milestone in the click-UI effort: gpu pane's digit keys `1`-`9` (toggle a preset server) and
`r`/`R` (force refresh), news pane's `r`/`R` (force refresh). These two panes are the ORIGIN of
the button-region pattern every other milestone adopted (`_button_regions: dict[(start_col,
end_col, phys_row) -> (action, target)]`) — so the question for the digit keys specifically was
whether they needed a NEW control at all, or whether the pattern they invented already covered
them.

## Digit keys: proven redundant, not duplicated

Traced both paths for a preset server:

- **Key path** (`char.isdigit()` branch, `run_gpu_loop`): `idx = int(char)-1` →
  `_toggle_server(idx, presets)` → looks up `s = presets[idx]`, computes `stop` (running+healthy)
  / `restart` (running, unhealthy) / `start` (not running), fires
  `rag-cli server <action> <name>`, sets `_toggle_state[name] = (...)`.
- **Button path** (per-preset row in `_render_pane`): registers `_button_regions[(...)] =
  (action, s['name'])` where `action = ('stop' if s['healthy'] else 'restart') if s['running']
  else 'start'` — the IDENTICAL branching, computed at render time instead of click time. Click
  dispatch calls `_fire_button(action, target)`, which fires the SAME `rag-cli server <action>
  <name>` command and sets the SAME `_toggle_state` entry.

The one thing that needed verifying, not just eyeballing, was whether `presets[idx]['name'] ==
PRESET_NAMES[idx]` always holds — i.e. whether digit `i+1` and the `i`-th rendered row always
refer to the SAME server. Confirmed in `status.py::all_statuses()`: `preset_statuses =
[_status_for_preset(n, states_by_name.get(n)) for n in PRESET_NAMES]` — a list comprehension over
`PRESET_NAMES` itself, always length `len(PRESET_NAMES)`, always same order, entries for
non-running presets synthesized as `running: False` rather than omitted. So `presets` is always
index-parallel to `PRESET_NAMES`; digit-to-row correspondence is structural, not a runtime
coincidence. Conclusion: no gap, no new button — verified with an actual assertion (captured
`subprocess.Popen` args + `_toggle_state` action label compared between the two paths for both a
stopped and a running+healthy preset), not just an argument.

## The `r`/`R` refresh key: not covered, needed a new button in both panes

Neither pane had ANY button for force-refresh. Added `[refresh]` to the header/title line in both
(`GPU Servers` / `CoinDesk News Pipeline`), following the SAME per-row button-registration style
these panes already use (`vis_len`/`pad`/`phys_row` computed the same way), with one deliberate
departure: the EXISTING per-row buttons use `pad = max(1, pane_width - vis_len - len(btn))` — a
floor that ALWAYS registers a region regardless of actual fit (mirrors the milestone-2 main-pane
gap already found and deliberately left alone). The two NEW `[refresh]` buttons use a real guard
instead (`header_pad >= 1`, computed WITHOUT the `max(1, ...)` floor) — no button text and no
region when there's no room, per this milestone's explicit width-guard requirement. The existing
per-row buttons were not touched.

**Dispatch collision, closed once per pane:** both loops' mouse-dispatch `for` loop over
`_button_regions` previously assumed every registered region meant "fire the one action this pane
knows" — gpu's loop called `_fire_button(action, target)` unconditionally once a region matched
(no branch on `action`'s value beyond the `_toggle_state` guard); news's loop called
`_fire_pipeline()` unconditionally (didn't even look at `action`/`target` — there was only ever
one button, so nothing to distinguish). Adding a second button TYPE required a real dispatch
branch in both: `if action == 'refresh': force_refresh = True ... elif ...: <pre-existing
branch>`. This is the only place either loop's control flow changed beyond the region-registration
addition itself. Disjointness with the pre-existing regions is structural, not incidental: the
`[refresh]` button is always on row 1 (the title line, first thing rendered); every pre-existing
button (preset rows, arbitrary rows, run-pipeline) is registered on a LATER row, since at least
one `lines.append()` happens before any of them — verified via an explicit "different phys_row"
assertion in the probe, not just argued from the code layout.

## Verification boundary: inline dispatch, not a standalone function

Neither `run_gpu_loop` nor `run_news_loop` factors mouse dispatch into a standalone function (same
shape milestone 2 hit with the main pane's inline `y`-key branch) — the `for (sc,ec,er),
(action,target) in _button_regions.items(): ...` block lives directly in the blocking `while
True:` loop, and the two force-refresh local variables (`force_refresh`, `input_changed`) it
writes are not reachable from outside without actually running that loop. The probe replicates the
dispatch snippet LINE FOR LINE in two local helpers (`_dispatch_gpu_click`, `_dispatch_news_click`)
against the REAL `_button_regions` dict from a real render, and asserts the replica recognizes the
refresh region and would take the refresh branch (returns a `'refresh'` sentinel) rather than
falling into the pre-existing button-fire branch. This proves the region-matching and
action-branching logic correctly, but does NOT exercise the actual `run_gpu_loop`/`run_news_loop`
closures live — same class of boundary already accepted for the main pane's `y` key in milestone 2.

## Verification

`dev/click_ui/p4_gpu_news_button_probe.py` — no live tmux/terminal, no real `rag-cli` or
news-pipeline subprocess: `subprocess.Popen` monkeypatched per module to a capturing stub (mirrors
milestone 2/3's `copy_to_clipboard` pattern); `gpu_pane.status.PRESET_NAMES` (resolved once at
IMPORT time via a real `rag-cli server presets --json` call) monkeypatched to a fixed synthetic
list so the probe doesn't depend on what's actually running on the machine. **24/24 checks
passing**: digit-key/button parity for both a stopped and a running+healthy preset (captured
subprocess args equal, `_toggle_state` action label equal — timestamps intentionally excluded from
the comparison since the two calls happen microseconds apart), `[refresh]` region+dispatch+width
guard in both panes, disjointness from pre-existing regions, and a regression check that news's
`[run pipeline]` click still fires after the new branch was added ahead of it. Full existing
suite re-run clean: milestone-1 probe 35/35, milestone-2 probe 37/37, milestone-3 probe 24/24,
`pane_error_log` exception-guard suite 52/52 — including the `[gpu]` and `[news]` loop-survival
checks specifically (5 checks each, all passing), confirming the new dispatch branches and header
button didn't disturb either loop's exception guard.

Not verified: a real mouse click through an actual terminal emulator against a live tmux pane, and
the real `force_refresh` local-variable flip inside the actual blocking loops (see verification
boundary above) — same class of gap accepted in milestone 2 for the main pane's `y` key.

## Scope note

Deliberately left untouched: every other pane (all covered in milestones 1-3); the pre-existing
per-row buttons' unconditional-registration width behavior in both gpu and news (a pre-existing
gap, same class as the milestone-2 main-pane tool_call gap, not fixed here); gpu pane's arbitrary
server rows and `RAG Collections`/`Errors today` blocks (unaffected, no keyboard-only control
there to begin with).

With this milestone, the click-UI effort (milestones 1-4) is complete: every control in every
tmux pane is reachable by mouse.
