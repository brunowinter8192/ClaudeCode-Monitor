"""
Verifies Carbon's GetEventTime(event)/GetCurrentEventTime() symbols resolve and produce a
plausible main-thread-stall delta — the technique used by src/menubar/hotkey_controller.py's
per-press queue_delay_ms instrumentation (see process-docs/hotkey_latency/).

Two checks:
  1. Symbol-resolution + monotonicity — non-interactive, runs standalone (no GUI focus needed).
  2. Live delta on a real key press — registers throwaway global hotkey Cmd+Shift+9 (unused
     elsewhere in this codebase) and prints queue_delay_ms on each press.

Usage (from project root):
    ./venv/bin/python3 dev/hotkey_latency/probe_get_event_time.py

Then press Cmd+Shift+9 anywhere (global hotkey, no focus required) — a line prints per press.
Ctrl+C to exit. No menu bar icon is shown (LSUIElement, no status item).
"""

# INFRASTRUCTURE
import ctypes
import os

import rumps

_OSStatus = ctypes.c_int32
_CMD_SHIFT_9_KEYCODE = 0x19            # kVK_ANSI_9
_CMD_SHIFT_MODIFIERS = 0x0100 | 0x0200  # cmdKey | shiftKey
_MBAR_SIG            = 0x4D424152      # OSType 'MBAR' — matches hotkey_controller.py convention
_PROBE_ID            = 999             # EventHotKeyID.id, collision-free with production IDs (1, 2..10, 20, 21, 30)
_kEventParamDirect   = 0x2D2D2D2D      # kEventParamDirectObject ('----')
_typeEventHotKeyID   = 0x686B6964      # typeEventHotKeyID ('hkid')
_eventNotHandledErr  = -9874

class _EventHotKeyID(ctypes.Structure):
    _fields_ = [('signature', ctypes.c_uint32), ('id', ctypes.c_uint32)]

class _EventTypeSpec(ctypes.Structure):
    _fields_ = [('eventClass', ctypes.c_uint32), ('eventKind', ctypes.c_uint32)]

_HOTKEY_EVENT_SPEC = _EventTypeSpec(0x6B657962, 6)   # kEventClassKeyboard, kEventHotKeyPressed
_EventHandlerProcPtr = ctypes.CFUNCTYPE(_OSStatus, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

# FUNCTIONS

# Load Carbon CDLL with argtypes for GetEventTime/GetCurrentEventTime + hotkey registration calls
def _load_carbon():
    carbon = ctypes.CDLL('/System/Library/Frameworks/Carbon.framework/Carbon')
    carbon.GetApplicationEventTarget.restype  = ctypes.c_void_p
    carbon.GetApplicationEventTarget.argtypes = []
    carbon.GetEventParameter.restype  = _OSStatus
    carbon.GetEventParameter.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p,
    ]
    carbon.InstallEventHandler.restype  = _OSStatus
    carbon.InstallEventHandler.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    carbon.RegisterEventHotKey.restype  = _OSStatus
    carbon.RegisterEventHotKey.argtypes = [
        ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
        ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p),
    ]
    carbon.GetEventTime.restype  = ctypes.c_double
    carbon.GetEventTime.argtypes = [ctypes.c_void_p]
    carbon.GetCurrentEventTime.restype  = ctypes.c_double
    carbon.GetCurrentEventTime.argtypes = []
    return carbon

# Check 1: symbols resolve + GetCurrentEventTime is a plausible, monotonically-increasing double
def _check_symbols_resolve(carbon) -> None:
    t1 = carbon.GetCurrentEventTime()
    t2 = carbon.GetCurrentEventTime()
    assert isinstance(t1, float) and t1 > 0, f'GetCurrentEventTime returned implausible value: {t1}'
    assert t2 >= t1, f'GetCurrentEventTime not monotonic: t1={t1} t2={t2}'
    print(f'[check 1] GetCurrentEventTime resolves: t1={t1:.6f}s t2={t2:.6f}s '
          f'delta={(t2 - t1) * 1000:.4f}ms (seconds since boot) — OK')

# Check 2: register throwaway global hotkey, print live queue_delay_ms per press
def _register_probe_hotkey(carbon) -> None:
    target = carbon.GetApplicationEventTarget()

    def _handler(handler_ref, event, user_data):
        entry_t = carbon.GetCurrentEventTime()
        try:
            hkid = _EventHotKeyID()
            carbon.GetEventParameter(
                event, _kEventParamDirect, _typeEventHotKeyID, None, 8, None,
                ctypes.byref(hkid))
            if hkid.id != _PROBE_ID:
                return _eventNotHandledErr
            event_t = carbon.GetEventTime(event)
            queue_delay_ms = (entry_t - event_t) * 1000
            print(f'[check 2] press: event_t={event_t:.6f}s entry_t={entry_t:.6f}s '
                  f'queue_delay_ms={queue_delay_ms:.3f}')
        except Exception as e:
            print(f'[check 2] handler error: {e!r}')
        return 0

    cb = _EventHandlerProcPtr(_handler)
    handler_ref = ctypes.c_void_p()
    carbon.InstallEventHandler(
        target, cb, 1, ctypes.byref(_HOTKEY_EVENT_SPEC), None, ctypes.byref(handler_ref))
    hk_ref = ctypes.c_void_p()
    rc = carbon.RegisterEventHotKey(
        _CMD_SHIFT_9_KEYCODE, _CMD_SHIFT_MODIFIERS,
        _EventHotKeyID(_MBAR_SIG, _PROBE_ID),
        target, 0, ctypes.byref(hk_ref))
    if rc != 0:
        print(f'[check 2] RegisterEventHotKey failed rc={rc} — Cmd+Shift+9 may be taken by another app')
    else:
        print('[check 2] Cmd+Shift+9 registered — press it anywhere to see a live delta. Ctrl+C to exit.')
    return cb, hk_ref   # caller must keep alive (GC anchor)

# ORCHESTRATOR

class _ProbeApp(rumps.App):
    def __init__(self):
        super().__init__('GetEventTime probe', quit_button=None, menu=[])

def main() -> None:
    carbon = _load_carbon()
    _check_symbols_resolve(carbon)
    os.environ.setdefault('LSUIElement', '1')
    app = _ProbeApp()
    _cb, _hk_ref = _register_probe_hotkey(carbon)
    app._probe_cb, app._probe_hk_ref = _cb, _hk_ref   # GC anchor
    app.run()

if __name__ == '__main__':
    main()
