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
# From paths.py: on-disk locations of the model-selection + proxy-rules files
from .paths import MODEL_SELECTION_FILE, PROXY_RULES_FILE

# Fixed cycle order; clicking a row button steps forward through this tuple and wraps
_MODEL_CHOICES = ("claude-opus-5", "claude-fable-5", "claude-fable-5-1", "claude-sonnet-5")
_DEFAULT_MAIN   = _MODEL_CHOICES[0]
_DEFAULT_WORKER = _MODEL_CHOICES[3]

# Fixed cycle orders for the per-model parameter rows. 'max' is deliberately excluded from
# effort — it is valid only on specific Opus models and would hard-fail requests elsewhere.
_EFFORT_CHOICES = ("low", "medium", "high")
_MAXTOK_CHOICES = (32000, 64000, 128000)
# Defaults for a model with NO model_params entry — NOT the first cycle value. A missing entry
# means the proxy injects nothing at all, and omitting effort behaves like 'high' per the API;
# 64000 is what every existing entry carries. Displaying the first cycle value (low/32000) would
# misrepresent the effective on-disk state, and an accidental Apply would silently downgrade the
# model. _next_in's unrecognized-current -> first-choice behavior is unrelated cycle mechanics
# and stays unchanged.
_DEFAULT_EFFORT     = "high"
_DEFAULT_MAX_TOKENS = 64000
_DEFAULT_THINKING   = {"type": "adaptive", "display": "summarized"}

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

# Advance current to the next value in a fixed choice tuple, wrapping; an unrecognized current
# value (e.g. a hand-edited file) starts the cycle at the first choice
def _next_in(choices: tuple, current):
    try:
        idx = choices.index(current)
    except ValueError:
        idx = -1
    return choices[(idx + 1) % len(choices)]

# Advance current model to the next value in the fixed cycle order, wrapping
def _next_model(current: str) -> str:
    return _next_in(_MODEL_CHOICES, current)

# Advance current effort to the next value in the fixed cycle order, wrapping
def _next_effort(current: str) -> str:
    return _next_in(_EFFORT_CHOICES, current)

# Advance current max_tokens to the next value in the fixed cycle order, wrapping
def _next_max_tokens(current: int) -> int:
    return _next_in(_MAXTOK_CHOICES, current)

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

# Read proxy_rules.json verbatim as a dict; missing/unreadable/malformed file falls back to {}
# (Apply then writes a fresh minimal model_params-only file — see _write_proxy_rules_model_params).
def _load_proxy_rules(path=PROXY_RULES_FILE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

# Read (effort, max_tokens) for one model from proxy_rules.json's model_params table. Each key is
# independently defaulted (mirrors inject_helpers.py's own "each key independently optional"
# handling) — a missing file/section/entry/key all fall back the same way, to _DEFAULT_EFFORT /
# _DEFAULT_MAX_TOKENS (NOT the first cycle value — see the module-level comment on those constants).
def _load_model_params_for(model_id: str, path=PROXY_RULES_FILE) -> tuple:
    config = _load_proxy_rules(path)
    params = config.get("model_params", {}).get(model_id, {})
    return params.get("effort", _DEFAULT_EFFORT), params.get("max_tokens", _DEFAULT_MAX_TOKENS)

# Re-indent every line but the first of a json.dumps(..., indent=2) block by one extra level —
# used to splice a value serialized on its own into a line that already carries its key.
def _reindent_nested(text: str, prefix: str) -> str:
    lines = text.split('\n')
    return '\n'.join([lines[0]] + [prefix + line for line in lines[1:]])

# Render the model_params section as one compact single-line JSON object per model entry, inside
# an indent=2 object — matches the on-disk convention already established in proxy_rules.json
# (confirmed by diff: every other section is byte-identical to plain json.dumps(indent=2); only
# model_params uses this compact-per-entry style). Preserves model_params key order.
def _render_model_params(model_params: dict) -> str:
    lines = ['  "model_params": {']
    entries = list(model_params.items())
    for i, (model_id, params) in enumerate(entries):
        comma = ',' if i < len(entries) - 1 else ''
        lines.append(f'    "{model_id}": {json.dumps(params)}{comma}')
    lines.append('  }')
    return '\n'.join(lines)

# Serialize proxy_rules.json preserving its on-disk convention: standard indent=2 for every
# top-level section except model_params (rendered via _render_model_params). Round-tripping an
# untouched config through this function reproduces the original bytes exactly — the mechanism
# that keeps an Apply's diff scoped to only the two changed leaf values.
def _dumps_proxy_rules(config: dict) -> str:
    keys = list(config.keys())
    lines = ['{']
    for i, key in enumerate(keys):
        comma = ',' if i < len(keys) - 1 else ''
        if key == "model_params":
            lines.append(_render_model_params(config[key]) + comma)
        else:
            value_text = _reindent_nested(json.dumps(config[key], indent=2), '  ')
            lines.append(f'  "{key}": {value_text}{comma}')
    lines.append('}')
    return '\n'.join(lines) + '\n'

# Read-modify-write proxy_rules.json's model_params table for the two selected models: updates
# ONLY .effort/.max_tokens on each model's entry, leaving its 'thinking' block and every other
# section/key byte-identical. A missing entry is created mirroring the established shape (a
# 'thinking' block copied from that shape, plus the given effort/max_tokens). Atomic tempfile +
# os.replace, no try/except — same AppKit-safety-boundary split as _write_model_selection.
def _write_proxy_rules_model_params(main: str, main_effort: str, main_max_tokens: int,
                                     worker: str, worker_effort: str, worker_max_tokens: int,
                                     path=PROXY_RULES_FILE) -> None:
    config = _load_proxy_rules(path)
    model_params = dict(config.get("model_params", {}))
    for model_id, effort, max_tokens in (
        (main, main_effort, main_max_tokens),
        (worker, worker_effort, worker_max_tokens),
    ):
        entry = dict(model_params.get(model_id) or {"thinking": dict(_DEFAULT_THINKING)})
        entry["effort"] = effort
        entry["max_tokens"] = max_tokens
        model_params[model_id] = entry
    config = dict(config)
    config["model_params"] = model_params
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(_dumps_proxy_rules(config), encoding='utf-8')
    os.replace(tmp, path)

# Per-concern controller for the Models panel: state ownership, panel render, cycle + apply actions
class ModelController:
    def __init__(self, app) -> None:
        self.app = app
        self._models_open: bool = False
        self._models_panel, self._models_sv, self._models_toggle_btn = _make_models_nspanel()
        self._pending_main, self._pending_worker = _load_model_selection()
        self._pending_main_effort, self._pending_main_max_tokens = _load_model_params_for(self._pending_main)
        self._pending_worker_effort, self._pending_worker_max_tokens = _load_model_params_for(self._pending_worker)
        self._main_cycle_btn    = None   # NSButton; set on first rebuild
        self._main_effort_btn   = None   # NSButton; set on first rebuild
        self._main_maxtok_btn   = None   # NSButton; set on first rebuild
        self._worker_cycle_btn  = None   # NSButton; set on first rebuild
        self._worker_effort_btn = None   # NSButton; set on first rebuild
        self._worker_maxtok_btn = None   # NSButton; set on first rebuild
        self._apply_btn         = None   # NSButton; set on first rebuild

    # Reload pending state from disk and rebuild; used by _open_models_panel
    def open(self) -> None:
        self._pending_main, self._pending_worker = _load_model_selection()
        self._pending_main_effort, self._pending_main_max_tokens = _load_model_params_for(self._pending_main)
        self._pending_worker_effort, self._pending_worker_max_tokens = _load_model_params_for(self._pending_worker)
        self.rebuild()

    # Full rebuild of Models panel: clear sv, set header, add separator + 6 cycle rows + apply row
    # (Main model/effort/max_tokens, Worker model/effort/max_tokens, Apply). Target/action for the
    # 7 row buttons are (re)wired here every call, not in app.py's one-time init block — these
    # buttons are recreated on each rebuild, so a one-time wire would go stale.
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
        required_h = _TOP_BAR_H + _LABEL_H + 6 * _ROW_H + 22   # top-bar + separator + 6 cycle rows + apply row
        self._resize_models_panel(max(app._panel_min_height, required_h))
        self._models_sv.addView_inGravity_(_make_line_separator(pw), 1)
        self._main_cycle_btn    = _make_model_row_btn(pw)
        self._main_effort_btn   = _make_model_row_btn(pw)
        self._main_maxtok_btn   = _make_model_row_btn(pw)
        self._worker_cycle_btn  = _make_model_row_btn(pw)
        self._worker_effort_btn = _make_model_row_btn(pw)
        self._worker_maxtok_btn = _make_model_row_btn(pw)
        self._apply_btn         = _make_apply_btn()
        self._main_cycle_btn.setTarget_(app._panel_controller)
        self._main_cycle_btn.setAction_(b'cycleMainModel:')
        self._main_effort_btn.setTarget_(app._panel_controller)
        self._main_effort_btn.setAction_(b'cycleMainEffort:')
        self._main_maxtok_btn.setTarget_(app._panel_controller)
        self._main_maxtok_btn.setAction_(b'cycleMainMaxTokens:')
        self._worker_cycle_btn.setTarget_(app._panel_controller)
        self._worker_cycle_btn.setAction_(b'cycleWorkerModel:')
        self._worker_effort_btn.setTarget_(app._panel_controller)
        self._worker_effort_btn.setAction_(b'cycleWorkerEffort:')
        self._worker_maxtok_btn.setTarget_(app._panel_controller)
        self._worker_maxtok_btn.setAction_(b'cycleWorkerMaxTokens:')
        self._apply_btn.setTarget_(app._panel_controller)
        self._apply_btn.setAction_(b'applyModelSelection:')
        self._models_sv.addView_inGravity_(self._main_cycle_btn, 1)
        self._models_sv.addView_inGravity_(self._main_effort_btn, 1)
        self._models_sv.addView_inGravity_(self._main_maxtok_btn, 1)
        self._models_sv.addView_inGravity_(self._worker_cycle_btn, 1)
        self._models_sv.addView_inGravity_(self._worker_effort_btn, 1)
        self._models_sv.addView_inGravity_(self._worker_maxtok_btn, 1)
        self._models_sv.addView_inGravity_(self._apply_btn, 1)
        self._refresh_cycle_titles()

    # Update all 6 cycle-button titles from current pending state; no full rebuild
    def _refresh_cycle_titles(self) -> None:
        self._main_cycle_btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                f'Main:    {self._pending_main}', {NSFontAttributeName: _MENLO()}))
        self._main_effort_btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                f'  Main effort:      {self._pending_main_effort}', {NSFontAttributeName: _MENLO()}))
        self._main_maxtok_btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                f'  Main max_tokens:  {self._pending_main_max_tokens}', {NSFontAttributeName: _MENLO()}))
        self._worker_cycle_btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                f'Worker:  {self._pending_worker}', {NSFontAttributeName: _MENLO()}))
        self._worker_effort_btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                f'  Worker effort:    {self._pending_worker_effort}', {NSFontAttributeName: _MENLO()}))
        self._worker_maxtok_btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                f'  Worker max_tokens:{self._pending_worker_max_tokens}', {NSFontAttributeName: _MENLO()}))

    # Advance pending main model to the next fixed-order value; refreshes the main effort/
    # max_tokens rows to the new model's current on-disk values (or defaults). In-place title
    # update only. AppKit-safety boundary: catches + logs, never raises — same shape as handle_apply.
    def handle_cycle_main(self) -> None:
        try:
            self._pending_main = _next_model(self._pending_main)
            self._pending_main_effort, self._pending_main_max_tokens = _load_model_params_for(self._pending_main)
            self._refresh_cycle_titles()
        except Exception as exc:
            print(f'[menubar] model cycle (main) failed: {exc}', file=sys.stderr)

    # Advance pending worker model to the next fixed-order value; refreshes the worker effort/
    # max_tokens rows to the new model's current on-disk values (or defaults). In-place title
    # update only. AppKit-safety boundary: catches + logs, never raises — same shape as handle_apply.
    def handle_cycle_worker(self) -> None:
        try:
            self._pending_worker = _next_model(self._pending_worker)
            self._pending_worker_effort, self._pending_worker_max_tokens = _load_model_params_for(self._pending_worker)
            self._refresh_cycle_titles()
        except Exception as exc:
            print(f'[menubar] model cycle (worker) failed: {exc}', file=sys.stderr)

    # Advance pending main effort to the next fixed-order value; in-place title update only.
    # AppKit-safety boundary: catches + logs, never raises — same shape as handle_apply.
    def handle_cycle_main_effort(self) -> None:
        try:
            self._pending_main_effort = _next_effort(self._pending_main_effort)
            self._refresh_cycle_titles()
        except Exception as exc:
            print(f'[menubar] model effort cycle (main) failed: {exc}', file=sys.stderr)

    # Advance pending main max_tokens to the next fixed-order value; in-place title update only.
    # AppKit-safety boundary: catches + logs, never raises — same shape as handle_apply.
    def handle_cycle_main_max_tokens(self) -> None:
        try:
            self._pending_main_max_tokens = _next_max_tokens(self._pending_main_max_tokens)
            self._refresh_cycle_titles()
        except Exception as exc:
            print(f'[menubar] model max_tokens cycle (main) failed: {exc}', file=sys.stderr)

    # Advance pending worker effort to the next fixed-order value; in-place title update only.
    # AppKit-safety boundary: catches + logs, never raises — same shape as handle_apply.
    def handle_cycle_worker_effort(self) -> None:
        try:
            self._pending_worker_effort = _next_effort(self._pending_worker_effort)
            self._refresh_cycle_titles()
        except Exception as exc:
            print(f'[menubar] model effort cycle (worker) failed: {exc}', file=sys.stderr)

    # Advance pending worker max_tokens to the next fixed-order value; in-place title update only.
    # AppKit-safety boundary: catches + logs, never raises — same shape as handle_apply.
    def handle_cycle_worker_max_tokens(self) -> None:
        try:
            self._pending_worker_max_tokens = _next_max_tokens(self._pending_worker_max_tokens)
            self._refresh_cycle_titles()
        except Exception as exc:
            print(f'[menubar] model max_tokens cycle (worker) failed: {exc}', file=sys.stderr)

    # Persist the currently displayed pair to model_selection.json, and the currently displayed
    # effort/max_tokens for both selected models into proxy_rules.json's model_params table.
    # AppKit-safety boundary: catches + logs, never raises, so a write failure cannot propagate
    # into the ObjC action-dispatch chain.
    def handle_apply(self) -> None:
        try:
            _write_model_selection(self._pending_main, self._pending_worker)
            _write_proxy_rules_model_params(
                self._pending_main, self._pending_main_effort, self._pending_main_max_tokens,
                self._pending_worker, self._pending_worker_effort, self._pending_worker_max_tokens)
        except Exception as exc:
            print(f'[menubar] model selection apply failed: {exc}', file=sys.stderr)

    # Resize Models NSPanel anchored at top edge; mirrors rag_controller._resize_rag_panel pattern
    def _resize_models_panel(self, new_h: float) -> None:
        w     = self.app._panel_width
        frame = self._models_panel.frame()
        top_y = frame.origin.y + frame.size.height
        self._models_panel.setFrame_display_(
            NSMakeRect(frame.origin.x, top_y - new_h, w, new_h), False)
