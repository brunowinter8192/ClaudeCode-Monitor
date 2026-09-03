# INFRASTRUCTURE
from pathlib import Path

_LABEL         = 'com.brunowinter.monitor-cc-sweep'
_PLIST_TMPL    = Path(__file__).resolve().parent / f'{_LABEL}.plist'
_LAUNCH_AGENTS = Path.home() / 'Library' / 'LaunchAgents'
_DEST          = _LAUNCH_AGENTS / f'{_LABEL}.plist'
_PROJECT_ROOT  = Path(__file__).resolve().parent.parent

# FUNCTIONS

# Read template, substitute the checkout path, write to ~/Library/LaunchAgents/.
# Does NOT bootstrap — that is a separate, explicit `launchctl` step (see module docstring
# in DOCS.md / the printed command below), so running this alone never touches a live launchd.
def write_plist() -> str:
    content = _PLIST_TMPL.read_text(encoding='utf-8')
    content = content.replace('<PROJECT_ROOT>', str(_PROJECT_ROOT))
    _LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    _DEST.write_text(content, encoding='utf-8')
    return str(_DEST)

# The exact command to load the sweep into launchd, printed for the user (never run by this script)
def bootstrap_command() -> str:
    return f'launchctl bootstrap gui/$(id -u) {_DEST}'

if __name__ == '__main__':
    dest = write_plist()
    print(f'wrote {dest}')
    print(f'To activate: {bootstrap_command()}')
    print(f'To verify:   launchctl print gui/$(id -u)/{_LABEL}')
