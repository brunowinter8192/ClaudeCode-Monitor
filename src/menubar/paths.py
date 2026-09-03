# INFRASTRUCTURE
import os
from pathlib import Path

_APP_SUPPORT  = Path("~/Library/Application Support/com.brunowinter.monitor-cc-menubar").expanduser()
_SHARED_RULES = Path("~/.claude/shared-rules").expanduser()   # cross-repo config, outside every repository

SETTINGS_FILE             = _APP_SUPPORT / "settings.json"
HOOKS_FILE                = _APP_SUPPORT / "hooks.json"
HOOKS_LOCK                = _APP_SUPPORT / "hooks.lock"
PID_FILE                  = _APP_SUPPORT / "menubar.pid"
GHOSTTY_CWD_UUID_FILE     = _APP_SUPPORT / "ghostty_cwd_uuid.json"
ORCHESTRATOR_SIGNALS_FILE = _APP_SUPPORT / "orchestrator_signals.json"  # {tmux_session_name: send_unix_ts}; written by worker-cli send
MODEL_SELECTION_FILE      = _SHARED_RULES / "model_selection.json"      # {main, worker} model IDs; menubar writes, a later milestone adds readers
PROXY_RULES_FILE          = _SHARED_RULES / "proxy_rules.json"          # proxy config incl. model_params; menubar read-modify-writes effort/max_tokens on Apply, never touches other sections

# Monitor_CC checkout root — used by system.py to build the "cd <root> && python3 workflow.py
# --project <cwd>" launch command for the per-project monitor button. `PROJECT_ROOT` env var
# (set by launchd from the plist's EnvironmentVariables, baked in at build/install time by
# setup_py2app.py:_install_bundle — always run from the real checkout, so always correct there;
# setup_menubar.py's write_plist()/write_plist_py2app() re-propagate the already-set value on
# every Restart rather than recomputing it, since recomputing from a FROZEN bundle's own
# __file__ would resolve inside the bundle copy, not the checkout) is authoritative when
# present. Falls back to this module's own file location — correct only for dev/venv runs
# launched directly from the checkout (not through the installed plist).
MONITOR_CC_ROOT = (Path(os.environ["PROJECT_ROOT"]) if os.environ.get("PROJECT_ROOT")
                   else Path(__file__).resolve().parents[2])

# FUNCTIONS

# Idempotent migration: move $HOME dotfiles → APP_SUPPORT location on first import
# _old_base defaults to ~; override in tests to point at a tempdir
# NEW wins if both old and new exist — old silently removed (new is the intended state)
def _migrate_from_dotfiles(_old_base: Path = Path.home()) -> None:
    _APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    _OLD = {
        _old_base / ".monitor_cc_menubar_settings.json": SETTINGS_FILE,
        _old_base / ".monitor_cc_menubar_hooks.json":    HOOKS_FILE,
        _old_base / ".monitor_cc_menubar_hooks.lock":    HOOKS_LOCK,
        _old_base / ".monitor_cc_menubar.pid":           PID_FILE,
    }
    for old, new in _OLD.items():
        if old.exists():
            if new.exists():
                old.unlink()       # NEW wins — old silently removed
            else:
                old.rename(new)

_migrate_from_dotfiles()

# Idempotent migration: move old bundle-id dir → new bundle-id dir on first import
# OLD: ~/Library/Application Support/com.brunowinter.monitor_cc_menubar/
# NEW: ~/Library/Application Support/com.brunowinter.monitor-cc-menubar/ (= _APP_SUPPORT)
# NEW wins: files already present at new location are skipped (no clobber)
def _migrate_from_old_bundle_id() -> None:
    _old = Path("~/Library/Application Support/com.brunowinter.monitor_cc_menubar").expanduser()
    if not _old.exists():
        return
    _APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    for fname in ("settings.json", "hooks.json", "hooks.lock",
                  "ghostty_cwd_uuid.json", "orchestrator_signals.json",
                  "menubar.pid", "menubar.log", "cwd_desktop.json"):
        old_f = _old / fname
        new_f = _APP_SUPPORT / fname
        if old_f.exists() and not new_f.exists():
            old_f.rename(new_f)

_migrate_from_old_bundle_id()
