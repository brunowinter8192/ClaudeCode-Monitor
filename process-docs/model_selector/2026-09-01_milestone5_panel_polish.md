# Milestone 5 — Models tab polish: orange model rows + Apply success feedback

2026-09-01

## Scope

Two purely visual additions to `src/menubar/model_controller.py`, no I/O or cycle-logic touched:
the two MODEL rows (Main/Worker) render their title text in `NSColor.systemOrangeColor()`, matching
the color already used for main-session rows elsewhere in the menubar app; and a successful Apply
(both `_write_model_selection` and `_write_proxy_rules_model_params` completing without exception)
flashes the Apply button to `'Applied successfully'` for ~1.5s before it reverts to `'Apply'`. A
failed Apply shows no confirmation. `model_controller.py` grew 392 → 454 LOC; `DOCS.md` updated in
the same commit.

## Design — reusing the established orange attribute pattern, not inventing a new one

`panel.py:_make_grid_cell_btn(text, color=None)` is the package's canonical shape for an optionally
colored attributed title: build an `attrs` dict with `NSFontAttributeName`, conditionally add
`NSForegroundColorAttributeName`, pass both to `NSAttributedString.alloc().init...`.
`panel_manager.py` uses `NSColor.systemOrangeColor()` at 3 sites built on exactly this shape (main
session rows' default color, the bg-task badge, and `update_inplace`'s dot/badge recolor).
`_refresh_cycle_titles()` already builds its attrs dicts inline (no shared helper — matches the
rest of the file's no-premature-abstraction style for its per-row title strings), so the two MODEL
rows' dicts simply gained the same `NSForegroundColorAttributeName: NSColor.systemOrangeColor()`
key; the 4 parameter rows and Apply were left untouched, both in code and in this file's existing
per-row inline-dict style.

## Design — Apply success feedback mirrors app.py's `_blink`, the only delayed-revert precedent

A grep across `src/menubar/*.py` for `NSTimer`/`performSelector...afterDelay_`/`threading.Timer`
found exactly one existing "flash now, revert after N seconds, safely on the main thread" pattern
in the whole package: `app.py`'s `_blink()`/`_restore()` (icon flash on session status change) —
`threading.Timer(DURATION, _restore).start()`, where `_restore` dispatches the actual AppKit
mutation back onto the main thread via `NSOperationQueue.mainQueue().addOperationWithBlock_(...)`.
The Apply success feedback mirrors this exactly rather than introducing a second mechanism
(`NSTimer`/Cocoa-side scheduling) for the same class of problem in the same package:
`_show_apply_success()` (called synchronously from the main-thread ObjC action dispatch that ran
`handle_apply`, so `self._apply_btn` is guaranteed live at that exact point) widens the button and
sets its title immediately, then starts `threading.Timer(1.5, self._schedule_apply_revert)`;
`_schedule_apply_revert` (running on the timer thread) hops back to the main thread via
`NSOperationQueue.mainQueue().addOperationWithBlock_(self._revert_apply_button)` before touching
any AppKit object.

`handle_apply`'s try block calls `_show_apply_success()` as its LAST statement, after both writes
succeed — a write exception is caught by the same existing `except` and skips the feedback call
entirely, so no separate success flag or restructuring of the write sequence was needed to satisfy
"a failed Apply must not show the confirmation."

## Design — the stale-button-reference guard

The task's constraint was that a panel rebuild or close before the ~1.5s revert fires must not
crash. `_revert_apply_button` (the delayed callback) resolves `self._apply_btn` DYNAMICALLY at fire
time rather than closing over the specific button object captured when the flash started. Since
`rebuild()` replaces `_apply_btn` with a freshly-built button whenever it runs (and a freshly-built
button's title is always `'Apply'` per `_make_apply_btn`'s own default), a revert firing after a
rebuild just re-asserts `'Apply'` on the current button — a harmless no-op, never an operation on a
detached/freed object. `_show_apply_success` and `_revert_apply_button` each carry their own
`try/except Exception as exc: print(f'[menubar] ...: {exc}', file=sys.stderr)` — the same shape as
every other handler in this file (established in milestone 2's review: an unguarded AppKit call in
an ObjC-adjacent callback chain SIGABRTs the whole app, not just that one call) — so a genuinely
unexpected AppKit failure at either point is caught and logged instead of propagating into the
timer-thread callback or, worse, back into `handle_apply`'s own except (which would misreport a UI
hiccup as a failed write).

## Forward-compatible fallback, not built

The button widen (`setFrame_display_` to `_APPLY_SUCCESS_W = 160` for the duration) is a manual
frame mutation on a view managed by an `NSStackView`; whether the stack view's Auto-Layout
intrinsic-content-size machinery fights that manual resize live was flagged as unverifiable without
a rendered check, same standing gap as milestone 2's original Apply-button styling. Per instruction,
no fallback logic was built pre-emptively — instead `_APPLY_BTN_W`/`_APPLY_BTN_H`/
`_APPLY_SUCCESS_TITLE`/`_APPLY_SUCCESS_W`/`_APPLY_SUCCESS_DURATION` are kept as separate named
constants specifically so that IF the live check shows the stack view fighting the widened frame,
the fix is a 2-constant edit (shorten `_APPLY_SUCCESS_TITLE`, lower `_APPLY_SUCCESS_W` to fit at
constant width) rather than a restructuring.

## Verification

Visual behavior (the orange color rendering, the flash/revert timing, and the stack-view/frame
interaction) is explicitly NOT covered by automated tests — mocking AppKit rendering for this would
test the mock, not the behavior. What WAS run: `python3 -m py_compile` on the touched file; a real
import through the project's `venv` (has pyobjc) to catch any AppKit symbol-name typo at import
time, not just Python syntax; `dev/model_selector/verify_model_cycle_and_io.py` (all 8 sections
pass — proves zero drift in `_next_model`/`_load_*`/`_write_*`/`_dumps_proxy_rules`, none of which
this milestone touches); `dev/model_selector/verify_three_tab_ring.py` (both cycle directions pass
— proves `rebuild()` still constructs and resizes correctly with the new color attrs and the now-
resizable Apply button in place). `src/proxy/` untouched; `setup_py2app.py` not run.

Not verified here (needs a user check after merge + rebuild): the orange text actually rendering
correctly, the flash/revert timing feeling right, and whether the widened Apply button holds its
frame under `NSStackView` layout instead of snapping back or distorting the row.

## Cross-reference

See `process-docs/model_selector/` for milestones 1-4 (Queue-tab removal, Models-tab addition,
launcher/worker readers, the model-ID + per-model parameter rows this milestone's Apply button sits
on top of). See `process-docs/param_fixation/` for the proxy-side fixation work (unrelated to this
milestone — `src/proxy/` was explicitly out of scope here) that makes a Models-tab Apply's on-disk
write behave correctly for already-running sessions.
