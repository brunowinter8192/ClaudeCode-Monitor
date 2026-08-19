# INFRASTRUCTURE

# From discovery_worker.py: background-thread session/bg-sleep-timer snapshot producer
from .discovery_worker import get_latest_snapshot

# FUNCTIONS

# Cache for the background discovery worker's latest published snapshot; one read per call,
# consumed on the main thread. 2026-08 (hotkey_latency M3): no longer calls list_alive_sessions()
# itself — that now runs exclusively on discovery_worker.py's background thread; refresh() is a
# cheap in-memory read (no subprocess/AppleScript I/O on this thread).
class SessionsController:
    def __init__(self, app) -> None:
        self.app = app
        self._last_sessions: list = []
        self._last_bg_by_project: dict = {}

    # Read the latest background-thread snapshot; update cache; return the sessions list
    # (signature/return type unchanged from the pre-M3 shape — existing call sites need no change)
    def refresh(self) -> list:
        snapshot = get_latest_snapshot()
        self._last_sessions = snapshot.sessions
        self._last_bg_by_project = snapshot.bg_by_project
        return snapshot.sessions

    @property
    def data(self) -> list:
        return self._last_sessions

    # Per-project background-sleep-timer info from the same snapshot as the last refresh()
    @property
    def bg_by_project(self) -> dict:
        return self._last_bg_by_project
