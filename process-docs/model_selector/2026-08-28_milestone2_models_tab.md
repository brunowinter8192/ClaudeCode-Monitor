# Milestone 2 — Models tab (menubar)

2026-08-28

## Scope

Second milestone of the model-selector line of work: add a third menubar tab, `Models`,
into the ring slot milestone 1's Queue-tab removal vacated. Final ring: `Sessions · RAG ·
Models`, Cmd+→/← cycling correct in both directions. Panel content is deliberately minimal —
two click-cycle buttons (MAIN model, WORKER model), each stepping through a fixed 3-value
order (`claude-opus-5 → claude-fable-5 → claude-sonnet-5 →` wraps) with no dropdown/popup, plus
an Apply button that persists the currently displayed pair to
`~/.claude/shared-rules/model_selection.json`. Cycling only changes in-memory pending state;
nothing reaches disk until Apply. This milestone WRITES the config file only — no reader beyond
the panel's own display was built; a later milestone adds `src/claude_proxy_start.sh` and the
iterative-dev plugin's spawn path as readers.

New module `src/menubar/model_controller.py` (206 LOC) follows `RagController`'s shape
(controller owns all its own state including panel refs; module-level I/O helpers kept local,
not a separate module). `paths.py` gained `MODEL_SELECTION_FILE` under a new `_SHARED_RULES`
base dir (`~/.claude/shared-rules/`, distinct from `_APP_SUPPORT` — real cross-repo config
outside every repository, already holding `proxy_rules.json`). `panel_lifecycle.py`'s ring
wiring went from the milestone-1 two-tab shape back to three, with `models` replacing the old
`queue` slot exactly. `app.py` gained `self.models`, 3 new one-line `_PanelController`
delegates, and a third header-string copy. Full diff is in the commit history; DOCS.md was
updated in the same commits as the code (new module section, State table, Module Import Graph,
Gotchas reverted to three-panel cycling).

Verified: cycle-order correctness (all 3 values step + wrap correctly, both rows independently)
via `dev/model_selector/verify_model_cycle_and_io.py`; atomic write produces exactly the 2-key
schema with no leftover tempfile; read-back correct for valid/missing/malformed files, all
against temp paths, never the real `~/.claude/shared-rules/`. Three-tab ring correctness
verified via `dev/model_selector/verify_three_tab_ring.py` — a lightweight `FakeApp` driving the
REAL, unmocked `_open_*_panel`/`_close_*_panel`/`_deferred_close_open` functions (only the
`NSOperationQueue` async-dispatch wrapper was patched to run synchronously, since no real
AppKit run loop exists in a headless probe); both directions confirmed correct. `setup_py2app.py`
was explicitly NOT run this milestone (see the hazard flagged in milestone 1's entry — a
worktree run would deploy unmerged code to the live app). NOT verified: interactive button
rendering/click-through and the Apply button's bordered visual look in the live running app —
needs a user check after merge + rebuild.

## Design decision — tag/action routing: 3 dedicated ObjC actions, no tag dict

This package's established tag-routing pattern (`panel_manager.py`'s session/worker/abort
buttons, the old queue controller's per-message rows) exists specifically for *dynamic,
repeating* item sets where a tag disambiguates "which item." The Models panel has exactly 2
cycle buttons + 1 Apply button — fixed cardinality, never added or removed at runtime. Using 3
dedicated selectors (`cycleMainModel_`, `cycleWorkerModel_`, `applyModelSelection_`) matches the
existing pattern for other static, singleton buttons in this package (`toggleAutoJump:`,
`restartApp:`, `killApp:`, each its own selector) rather than introducing an unused tag dict for
a cardinality of exactly 3.

## Design decision — target/action wiring lives inside `rebuild()`, not `app.py`'s one-time init

`RagController`'s only per-rebuild content is a non-interactive label, so it never needed
target/action wiring beyond the one-time setup in `app.py:_tick`'s init-guard block (reserved
for buttons built once in a factory and never recreated — `toggle_btn`, `quit_btn`, `kill_btn`).
`ModelController`'s 3 row buttons ARE interactive and get recreated fresh on every `rebuild()`
call. Wiring their target/action once in `_tick`'s init block would go stale the instant the
first `rebuild()` replaced the button objects — a real bug, not a hypothetical one, caught
during planning before any code was written. Fix: wire `setTarget_`/`setAction_` for all 3
buttons INSIDE `rebuild()` itself, using `app._panel_controller` — mirroring
`panel_manager.py`'s own established pattern for its dynamically-recreated session buttons,
which faces the identical constraint.

## Correction from review — unrecognized on-disk model values must be preserved, not replaced

Original plan validated `_load_model_selection`'s two field values against the fixed 3-choice
enum and silently substituted the default for anything outside it. Rejected on review: a
hand-edited or future-model-ID entry in the file would be silently overwritten the moment the
panel is merely opened and closed without cycling — and since a later milestone makes this file
drive the actual session model, that is silent config loss, not a cosmetic display quirk.
Fixed: `_load_model_selection` now returns the two values verbatim from valid JSON, however
unrecognized; only an individually MISSING key falls back to that field's default, and only a
missing/unreadable/malformed file falls back to the full default pair. `_next_model` still
starts an unrecognized current value's cycle at the first choice (unchanged, needed since
cycling requires a defined index) — the distinction is display/round-trip fidelity (preserve)
vs. cycle behavior (normalize), not a fallback vs. no-fallback split.

## Correction from review — Apply gets the bordered Restart/Kill look, not the row-button look

Original plan used the same borderless full-width `_CursorlessButton` style for all 3 rows
(cycle rows + Apply), for visual uniformity with the rest of the deliberately-minimal panel.
Rejected on review: the two cycle rows are state (what's currently selected), Apply is an
action (commit that state to disk) — the visual distinction should say so, and this package
already has an established bordered-action-button look (`panel.py`'s Restart/Kill footer
buttons: `setBezelStyle_(1)`, fixed 78×22, plain `setTitle_`). Fixed: `_make_apply_btn()`
mirrors that exact styling; the two cycle-row buttons keep the borderless full-width look.

## Correction from review — all 3 action handlers wrapped in try/except identically

Original implementation wrapped only `handle_apply` (the one handler with a visible failure
path — the file write). `handle_cycle_main`/`handle_cycle_worker` were left unwrapped, on the
reasoning that no code path in either is known to raise (`_next_model` swallows its own
`ValueError` internally; `setAttributedTitle_` on a live button doesn't raise). Rejected on
review: the prompt's instruction to wrap the action handlers wasn't conditional on a known
failure path — an unhandled exception anywhere in an ObjC action-dispatch chain is a SIGABRT of
the entire menubar app, not a caught, logged error, and that asymmetry (no exception in the log,
just the app vanishing) is a materially worse failure mode than the 2-line cost of guarding it.
Fixed: all 3 handlers now carry the identical `try/except Exception as exc: print(f'[menubar]
...: {exc}', file=sys.stderr)` shape, so the next person reading any one of them sees the same
pattern in all three rather than wondering why one is guarded and two aren't.

## Hazard reference

`setup_py2app.py` builds, installs to `~/Applications`, AND relaunches the live app in one
command, so running it from a worktree deploys unmerged code over the running menubar. That
hazard is recorded in `process-docs/model_selector/` and is the reason this milestone's
verification stopped at import + ring-logic tests rather than a build. Observed follow-on:
after such a run the LaunchAgent was left unloaded and the app stayed dead until it was
re-bootstrapped by hand.
