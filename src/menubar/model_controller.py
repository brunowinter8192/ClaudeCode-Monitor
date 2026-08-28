# INFRASTRUCTURE
import json
import os
import sys

from AppKit import (NSAttributedString, NSFontAttributeName,
                    NSLayoutAttributeLeading, NSStatusWindowLevel,
                    NSStackView, NSView,
                    NSUserInterfaceLayoutOrientationVertical,
                    NSWindowCollectionBehaviorCanJoinAllSpaces,
                    NSWindowCollectionBehaviorIgnoresCycle,
                    NSWindowStyleMaskNonactivatingPanel, NSWindowStyleMaskResizable)
from Foundation import NSMakeRect, NSMakeSize

# From panel.py: UI constants, factories, helpers shared across panels
from .panel import (PANEL_WIDTH, PANEL_HEIGHT, PANEL_MIN_WIDTH, PANEL_MIN_HEIGHT,
                    PANEL_GAP, _TOP_BAR_H, _ROW_H, _LABEL_H, _MENLO,
                    _CursorlessButton, _KeyablePanel, _make_line_separator)
# From paths.py: on-disk location of the model-selection file
from .paths import MODEL_SELECTION_FILE

# Fixed cycle order; clicking a row button steps forward through this tuple and wraps
_MODEL_CHOICES = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5")
_DEFAULT_MAIN   = _MODEL_CHOICES[0]
_DEFAULT_WORKER = _MODEL_CHOICES[2]

# FUNCTIONS

# Build NSPanel for the Models panel; returns (panel, stack, toggle_btn) — mirrors _make_rag_nspanel
def _make_models_nspanel():
    panel = _KeyablePanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT),
        NSWindowStyleMaskNonactivatingPanel | NSWindowStyleMaskResizable, 2, True)
    panel.setLevel_(NSStatusWindowLevel)
    panel.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorIgnoresCycle)
    panel.setHasShadow_(True)
    panel.setOpaque_(False)
    panel.setAcceptsMouseMovedEvents_(True)
    panel.setContentMinSize_(NSMakeSize(PANEL_MIN_WIDTH, PANEL_MIN_HEIGHT))
    cv = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT))
    panel.setContentView_(cv)
    panel.enableCursorRects()
    top_bar = NSView.alloc().initWithFrame_(
        NSMakeRect(0, PANEL_HEIGHT - _TOP_BAR_H, PANEL_WIDTH, _TOP_BAR_H))
    top_bar.setAutoresizingMask_(10)   # NSViewWidthSizable | NSViewMinYMargin — stays at top edge
    toggle_btn = _CursorlessButton.alloc().initWithFrame_(
        NSMakeRect(0, 0, PANEL_WIDTH - 22, _TOP_BAR_H - 1))
    toggle_btn.setBordered_(False)
    toggle_btn.setButtonType_(7)   # NSButtonTypeMomentaryPushIn
    toggle_btn.setAutoresizingMask_(2)   # NSViewWidthSizable
    top_bar.addSubview_(toggle_btn)
    cv.addSubview_(top_bar)
    stack_h = PANEL_HEIGHT - _TOP_BAR_H
    stack = NSStackView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_WIDTH, stack_h))
    stack.setAutoresizingMask_(18)   # NSViewWidthSizable | NSViewHeightSizable
    stack.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
    stack.setAlignment_(NSLayoutAttributeLeading)
    stack.setSpacing_(1.0)
    stack.setDistribution_(-1)   # NSStackViewDistributionGravityAreas
    cv.addSubview_(stack)
    return panel, stack, toggle_btn

# Position Models panel flush below the NSStatusItem button (same logic as the RAG/main panel)
def _reposition_models_panel(panel, nsstatusitem) -> None:
    btn_win = nsstatusitem.button().window()
    if btn_win is None:
        return
    w  = panel.frame().size.width
    h  = panel.frame().size.height
    sr = btn_win.frame()
    px = sr.origin.x + sr.size.width / 2.0 - w / 2.0
    py = sr.origin.y - h - PANEL_GAP
    panel.setFrame_display_(NSMakeRect(px, py, w, h), False)

# Full-width borderless Menlo-font row button (cycle rows) — mirrors panel.py's toggle_btn style
def _make_model_row_btn(panel_width: int):
    btn = _CursorlessButton.alloc().initWithFrame_(NSMakeRect(0, 0, panel_width - 22, _ROW_H - 1))
    btn.setBordered_(False)
    btn.setButtonType_(7)   # NSButtonTypeMomentaryPushIn
    return btn

# Bordered rounded push-button (Apply) — mirrors panel.py's Restart/Kill footer-button style exactly
def _make_apply_btn():
    btn = _CursorlessButton.alloc().initWithFrame_(NSMakeRect(0, 0, 78, 22))
    btn.setTitle_('Apply')
    btn.setBezelStyle_(1)   # NSBezelStyleRounded
    return btn

# Advance current to the next value in the fixed cycle order, wrapping; an unrecognized
# current value (e.g. a hand-edited file) starts the cycle at the first choice
def _next_model(current: str) -> str:
    try:
        idx = _MODEL_CHOICES.index(current)
    except ValueError:
        idx = -1
    return _MODEL_CHOICES[(idx + 1) % len(_MODEL_CHOICES)]

# Read model_selection.json; returns (main, worker) verbatim as stored — an unrecognized model
# ID is preserved as-is, NOT replaced (only Apply after an actual cycle click changes a value).
# Missing/unreadable/malformed file, or an individual missing key, falls back to the default pair.
def _load_model_selection(path=MODEL_SELECTION_FILE):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d.get("main", _DEFAULT_MAIN), d.get("worker", _DEFAULT_WORKER)
    except Exception:
        return _DEFAULT_MAIN, _DEFAULT_WORKER

# Atomic write of the model-selection pair: tempfile + os.replace, mirrors app_settings.py's
# write pattern. No try/except here — a failed Apply must not be silently swallowed; the caller
# (ModelController.handle_apply, the AppKit-safety boundary) catches and logs explicitly.
def _write_model_selection(main: str, worker: str, path=MODEL_SELECTION_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps({'main': main, 'worker': worker}), encoding='utf-8')
    os.replace(tmp, path)

# Per-concern controller for the Models panel: state ownership, panel render, cycle + apply actions
class ModelController:
    def __init__(self, app) -> None:
        self.app = app
        self._models_open: bool = False
        self._models_panel, self._models_sv, self._models_toggle_btn = _make_models_nspanel()
        self._pending_main, self._pending_worker = _load_model_selection()
        self._main_cycle_btn   = None   # NSButton; set on first rebuild
        self._worker_cycle_btn = None   # NSButton; set on first rebuild
        self._apply_btn        = None   # NSButton; set on first rebuild

    # Reload pending state from disk and rebuild; used by _open_models_panel
    def open(self) -> None:
        self._pending_main, self._pending_worker = _load_model_selection()
        self.rebuild()

    # Full rebuild of Models panel: clear sv, set header, add separator + 2 cycle rows + apply row.
    # Target/action for the 3 row buttons are (re)wired here every call, not in app.py's one-time
    # init block — these buttons are recreated on each rebuild, so a one-time wire would go stale.
    def rebuild(self) -> None:
        app = self.app
        for sv in list(self._models_sv.arrangedSubviews()):
            self._models_sv.removeView_(sv)
            sv.removeFromSuperview()   # removeView_ removes from arrangedSubviews only; view persists without this
        pw    = app._panel_width
        state = 'ON' if app._auto_focus else 'OFF'
        self._models_toggle_btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                f'Sessions · RAG · [Models]     Auto-Jump: {state}',
                {NSFontAttributeName: _MENLO()}))
        required_h = _TOP_BAR_H + _LABEL_H + 2 * _ROW_H + 22   # top-bar + separator + 2 cycle rows + apply row
        self._resize_models_panel(max(app._panel_min_height, required_h))
        self._models_sv.addView_inGravity_(_make_line_separator(pw), 1)
        self._main_cycle_btn   = _make_model_row_btn(pw)
        self._worker_cycle_btn = _make_model_row_btn(pw)
        self._apply_btn        = _make_apply_btn()
        self._main_cycle_btn.setTarget_(app._panel_controller)
        self._main_cycle_btn.setAction_(b'cycleMainModel:')
        self._worker_cycle_btn.setTarget_(app._panel_controller)
        self._worker_cycle_btn.setAction_(b'cycleWorkerModel:')
        self._apply_btn.setTarget_(app._panel_controller)
        self._apply_btn.setAction_(b'applyModelSelection:')
        self._models_sv.addView_inGravity_(self._main_cycle_btn, 1)
        self._models_sv.addView_inGravity_(self._worker_cycle_btn, 1)
        self._models_sv.addView_inGravity_(self._apply_btn, 1)
        self._refresh_cycle_titles()

    # Update the two cycle-button titles from current pending state; no full rebuild
    def _refresh_cycle_titles(self) -> None:
        self._main_cycle_btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                f'Main:    {self._pending_main}', {NSFontAttributeName: _MENLO()}))
        self._worker_cycle_btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                f'Worker:  {self._pending_worker}', {NSFontAttributeName: _MENLO()}))

    # Advance pending main model to the next fixed-order value; in-place title update only
    def handle_cycle_main(self) -> None:
        self._pending_main = _next_model(self._pending_main)
        self._refresh_cycle_titles()

    # Advance pending worker model to the next fixed-order value; in-place title update only
    def handle_cycle_worker(self) -> None:
        self._pending_worker = _next_model(self._pending_worker)
        self._refresh_cycle_titles()

    # Persist the currently displayed pair to disk. AppKit-safety boundary: catches + logs,
    # never raises, so a write failure cannot propagate into the ObjC action-dispatch chain.
    def handle_apply(self) -> None:
        try:
            _write_model_selection(self._pending_main, self._pending_worker)
        except Exception as exc:
            print(f'[menubar] model selection apply failed: {exc}', file=sys.stderr)

    # Resize Models NSPanel anchored at top edge; mirrors rag_controller._resize_rag_panel pattern
    def _resize_models_panel(self, new_h: float) -> None:
        w     = self.app._panel_width
        frame = self._models_panel.frame()
        top_y = frame.origin.y + frame.size.height
        self._models_panel.setFrame_display_(
            NSMakeRect(frame.origin.x, top_y - new_h, w, new_h), False)
