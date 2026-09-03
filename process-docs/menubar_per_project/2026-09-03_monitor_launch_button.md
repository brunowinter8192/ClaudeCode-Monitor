# Per-project "monitor" launch/focus button in the menubar panel

Date: 2026-09-03

## Goal

Every MAIN-session row in the menubar panel (`src/menubar/panel_manager.py`) gets a button that
replaces the manual `cd <checkout> && python3 workflow.py --project <cwd>` step the user was
running by hand in a Ghostty terminal. Click behavior: if a `monitor_cc_<hash>` tmux session for
that project already exists, focus its Ghostty window; otherwise open a new Ghostty window that
launches the monitor fresh.

## Reused mechanisms (investigation)

- `src/tmux_launcher.py:generate_session_name(cwd)` is the ONLY correct source for the tmux
  session name — `monitor_cc_<md5(os.path.normpath(os.path.expanduser(cwd)))[:8]>`. Imported
  directly into `system.py`, never re-implemented, so a normalization drift (trailing slash,
  `~` expansion) can never desync the button from what `workflow.py --project` actually creates.
- The "already running → focus" case needed NO new focus mechanism. `workflow.py`'s default
  mode (`all`, via `tmux_launcher.py:launch_split_screen`) ends by running
  `tmux attach-session -t <session>` as the LAST statement, in its own foreground process — the
  exact same process shape (`tmux attach`/`attach-session -t <name>`, live on some tty) that
  `system.py:_find_worker_viewer_tty` already scans `ps -A` for to focus a worker-viewer window.
  `_open_or_focus_monitor` therefore calls the existing `_focus_worker(session_name)` verbatim.
- The Ghostty-window-open mechanism was ported from the iterative-dev plugin's
  `src/spawn/tmux_spawn.sh:open_tmux_viewer` (external repo, read-only reference — not edited).
  Installed Ghostty version at verification time: **1.3.1** (`ghostty +version`) — the native
  AppleScript path (`tell application "Ghostty" ... set win to new window ... input text ...`)
  is what actually runs on this machine today; the pre-1.3 `open -na Ghostty.app --args ... -e`
  fallback is ported too (version-gated via `ghostty +version`, same as the bash reference) but
  unverified live, since no 1.2.x Ghostty install exists to test against.

## Decisions

**Separate 6th grid column, not the badge column.** The badge column (`_GRID_COL4_W`) already
carries bg-task-remaining state for a session and is absent on most rows. Routing the monitor
button through it would either hide the launch control whenever a badge renders, or force the
badge cell to alternate between two unrelated meanings depending on state — a single-purpose
column is simpler and the width cost (`_GRID_COL5_W=40` + one spacing gap = 42pt) is small.
`PANEL_WIDTH` raised 380→422 by EXACTLY that amount so the flexible name column (col 2) keeps
its pre-existing effective width — verified by hand: fixed-column-and-spacing budget grows from
162pt (5 cols) to 204pt (6 cols), a 42pt delta matching the 42pt `PANEL_WIDTH` increase, so
`pw - budget` (the name column's share) is unchanged at 218pt.

**`python3` resolution reads the plist template's PATH, not `os.environ`.** The menubar itself
runs under launchd, whose default PATH lacks Homebrew (`src/menubar/DOCS.md`'s "launchd PATH
inheritance" gotcha, pre-existing). `_resolve_launch_python3()` resolves `python3`
(`shutil.which`) against `com.brunowinter.monitor-cc-menubar.plist`'s
`EnvironmentVariables/PATH` value. Live-verified in this worktree: resolves to
`/opt/homebrew/bin/python3` (3.14.3), matching what a real interactive Homebrew shell resolves.

**Bug caught by testing, not by inspection: `plistlib.load` on the plist TEMPLATE always
raises.** First implementation read the template via `plistlib.load`. The template is not valid
XML by itself — `<key>ProgramArguments</key><array><string><BUNDLE_LAUNCHER></string></array>`
carries an unsubstituted `<BUNDLE_LAUNCHER>` token that `expat` parses as an unclosed tag
(confirmed against the current committed template, independent of this change:
`mismatched tag: line 12, column 31`); real substitution only happens as a plain-text
`str.replace()` at install time (`setup_menubar.py`/`setup_py2app.py`), producing a separate,
valid-XML COPY under `~/Library/LaunchAgents/`. The `except Exception: path_value = None`
fallback swallowed the parse failure and silently fell through to this process's own
`os.environ['PATH']` — which happened to also contain Homebrew in the dev shell used for the
first manual check, masking the bug. Caught by adding a regression test that spawns a real
subprocess with a bare launchd-shaped PATH (`/usr/bin:/bin:/usr/sbin:/sbin`, no Homebrew) and
asserts the resolved `python3` is still under `/opt/homebrew/` or `/usr/local/` — this failed
immediately under the `plistlib` implementation. Fixed by reading the template as plain text and
extracting the `PATH` string value with a regex, never invoking `plistlib` on the template at
all. Regression guard: `dev/menubar_per_project/test_open_or_focus_monitor.py`'s
`_test_resolve_python3_uses_plist_path_under_bare_environ`.

**`PROJECT_ROOT` plist env var — completed a half-wired existing mechanism, not new plumbing.**
The launch command's `cd <root>` needed the actual Monitor_CC checkout root, derivable
correctly ONLY from a live source-tree location — but the production menubar runs as a FROZEN
py2app bundle (`_prune_bundle_bloat` whitelist never bundles `workflow.py`), so `Path(__file__)`
computed from `paths.py`/`setup_menubar.py` INSIDE that running frozen process resolves inside
the bundle copy, not the checkout. Investigation found `setup_py2app.py:_install_bundle` and
`setup_menubar.py:write_plist()`/`write_plist_py2app()` ALREADY did
`content.replace('<PROJECT_ROOT>', str(root))` against the plist template — but the template
itself never defined a `<PROJECT_ROOT>` token, so the substitution was a pre-existing no-op.
Added the token as a real `PROJECT_ROOT` env var in the plist; `paths.py:MONITOR_CC_ROOT` reads
it (env var authoritative, `Path(__file__).resolve().parents[2]` as a dev/venv-only fallback).
One additional fix was required to make this correct across the Restart button's whole
lifecycle: `setup_menubar.py`'s `_PROJECT_ROOT` constant used to ALWAYS recompute via
`Path(__file__).resolve().parent.parent.parent` — correct only in dev mode; in frozen mode
(`restartApp_`'s py2app branch) this would have silently overwritten a correct `PROJECT_ROOT`
with a bundle-internal path on every Restart click. Changed to prefer the already-set
`PROJECT_ROOT` env var, falling back to the `Path(__file__)` computation only for the very
first dev-mode install (no plist loaded yet). `setup_py2app.py:_install_bundle`'s own
`root = Path(__file__).resolve().parent` needed no change — that script is always run
by hand from the actual checkout, so it was already correct.

**Command built via `shlex.quote`, never raw interpolation.** `_build_monitor_launch_cmd`
quotes both the checkout root and the row's cwd independently. Verified with a cwd containing a
shell metacharacter (`/tmp/my project; rm -rf /`) — the whole path round-trips through
`shlex.split` as exactly one argument (see `dev/menubar_per_project/test_open_or_focus_monitor.py`).

## Verification

Unit tests (`dev/menubar_per_project/test_open_or_focus_monitor.py`, run via the worktree
venv): session-name identity with `tmux_launcher.generate_session_name` (not re-derived),
quoting safety for a cwd with a space + shell metacharacter, the focus-vs-launch branch under
both `check_session_exists` outcomes, the empty-cwd no-op guard, and the bare-PATH python3-
resolution regression guard above. All 11 checks passed.

Live launch verification (worktree venv, throwaway cwd `/tmp/monitor_btn_test_project`, run
directly against `src/menubar/system.py:_open_or_focus_monitor` — not through the running
production menubar app or bundle): first call with no existing session opened a new Ghostty
window and created tmux session `monitor_cc_338ef3b8` with all 6 windows/panes running
`--project /tmp/monitor_btn_test_project` under `/opt/homebrew/bin/python3` (confirmed via
`ps -ef`); `[monitor] launch OK` logged. Second call against the now-running session took the
focus branch (`_focus_worker`, no second `[monitor] launch` line) — it logged a
`NO-OP reason=tty_unmapped`, which is an artifact of running a short-lived standalone script
(the Ghostty tty→UUID cache `ghostty.py:_ghostty_tty_to_id` is normally kept warm by the live
menubar app's continuously-running discovery thread, absent here), not a defect in the branch
logic itself. Cleanup: `tmux kill-session -t monitor_cc_338ef3b8` — the Ghostty window count
dropped back to its pre-test baseline on its own once the session died, confirming the
`; exit`-appended shell command closes the window exactly when the tmux session goes away,
matching today's manual-launch behavior. No production `monitor_cc_*` session or the running
production menubar bundle was touched at any point.

## Deployment (not run by this change)

This is a `src/menubar/*.py` + plist source edit only — the running production menubar is a
frozen py2app bundle and does not see it until rebuilt. Deploy via
`./venv/bin/python setup_py2app.py py2app` from the actual checkout root (builds, installs to
`~/Applications/`, re-signs, and bootstraps the LaunchAgent — the same command already used for
every prior menubar code change, per `src/menubar/DOCS.md`'s "Restart ≠ code update" gotcha).
