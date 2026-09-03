# INFRASTRUCTURE
import os
from pathlib import Path

_LABEL           = 'com.brunowinter.monitor-cc-menubar'
_PLIST_TMPL      = Path(__file__).resolve().parent / f'{_LABEL}.plist'
_LAUNCH_AGENTS   = Path.home() / 'Library' / 'LaunchAgents'
_DEST            = _LAUNCH_AGENTS / f'{_LABEL}.plist'
# PROJECT_ROOT env var (set by launchd from a prior install's plist) is authoritative when
# present — recomputing via Path(__file__) here would resolve INSIDE the running frozen bundle
# copy in py2app mode (this module ships in the bundle), not the real checkout. Falls back to
# the Path(__file__) computation only for a first-ever dev-mode install with no plist loaded yet
# (see paths.py:MONITOR_CC_ROOT for the matching runtime-launch-side logic).
_PROJECT_ROOT    = Path(os.environ['PROJECT_ROOT']) if os.environ.get('PROJECT_ROOT') \
                   else Path(__file__).resolve().parent.parent.parent
_BUNDLE          = Path.home() / 'Applications' / 'monitor-cc-menubar.app'
_BUNDLE_LAUNCHER = _BUNDLE / 'Contents' / 'MacOS' / 'menubar'
_BUNDLE_EXE      = _BUNDLE / 'Contents' / 'MacOS' / 'monitor-cc-menubar'

# FUNCTIONS

# Read template, substitute tokens with Bash-launcher path, write to ~/Library/LaunchAgents/
def write_plist() -> None:
    content = _PLIST_TMPL.read_text(encoding='utf-8')
    content = content.replace('<PROJECT_ROOT>', str(_PROJECT_ROOT))
    content = content.replace('<BUNDLE_LAUNCHER>', str(_BUNDLE_LAUNCHER))
    _LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    _DEST.write_text(content, encoding='utf-8')
    print(f'  wrote {_DEST}')

# Read template, substitute tokens with py2app native binary path, write to ~/Library/LaunchAgents/
def write_plist_py2app() -> None:
    content = _PLIST_TMPL.read_text(encoding='utf-8')
    content = content.replace('<PROJECT_ROOT>', str(_PROJECT_ROOT))
    content = content.replace('<BUNDLE_LAUNCHER>', str(_BUNDLE_EXE))
    _LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    _DEST.write_text(content, encoding='utf-8')
