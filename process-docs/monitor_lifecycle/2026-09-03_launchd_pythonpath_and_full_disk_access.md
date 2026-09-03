# LaunchAgent import failure under launchd: PYTHONPATH fix + a deeper TCC wall, 2026-09-03

## Report from the live install

User wrote `com.brunowinter.monitor-cc-sweep.plist` (WorkingDirectory = the main checkout,
confirmed via `launchctl print`), bootstrapped it, then `launchctl kickstart`. Result in
`/tmp/monitor-cc-sweep.err`: `ModuleNotFoundError: No module named 'src'`, last exit code 1. The
identical command run by hand from the checkout with an emptied environment
(`env -i PATH=... /usr/bin/python3 -m src.monitor_janitor`) worked. Integration was merged into
the worktree first (fast-forward, `4ba863b..0156741`, no conflicts) before investigating.

## First fix: `-m` under launchd needs PYTHONPATH, not just WorkingDirectory

`python3 -m src.monitor_janitor` resolves the `src` package by scanning `sys.path`, which
normally includes the current working directory automatically. A hand-run shell repro (`cd
<checkout> && python3 -m src.monitor_janitor`, even with `env -i`) never reproduced the failure —
`sys.path[0]` picked up the shell's `cd`'d directory correctly every time. Added `PYTHONPATH`
to the plist's `EnvironmentVariables`, set to `<PROJECT_ROOT>` (same token substitution as
`WorkingDirectory`, done by `setup_monitor_sweep.py`) — this makes the package resolvable from
the environment alone, independent of whatever launchd does or does not do with
`WorkingDirectory` for `-m` resolution specifically.

## Second, deeper finding: this alone does not fix it — Full Disk Access (TCC)

Proving the fix required a REAL launchd run (a hand-run shell repro had already been shown
insufficient once). Built a test LaunchAgent (`com.brunowinter.monitor-cc-sweep-test`,
`WorkingDirectory`/`PYTHONPATH`/`MONITOR_CC_ROOT` all pointing at this worktree, separate
`StandardOutPath`/`StandardErrorPath`), bootstrapped it, `launchctl kickstart -k`'d it for real.
Sequence of diagnostics (each one a distinct `-c` payload substituted into the SAME test plist,
re-bootstrapped between runs):

1. `os.environ.get('PYTHONPATH')` and `sys.path` printed under launchd — both correct, the
   worktree path present as a `sys.path` entry. PYTHONPATH itself IS honored.
2. Despite that, `import src.monitor_janitor` still raised `ModuleNotFoundError: No module
   named src'` under launchd (not reproducible by hand).
3. `os.getcwd()` in the same run raised `PermissionError: [Errno 1] Operation not permitted` —
   the first real clue.
4. Control: moved `WorkingDirectory` to `/tmp` (TCC-exempt) — `os.getcwd()` now succeeded
   (`/private/tmp`), but `import src.monitor_janitor` (via `PYTHONPATH` still pointing at the
   worktree) still failed the same way. This isolates the failure to the worktree path
   specifically, not a general cwd problem.
5. Direct test: `os.listdir()` on `~/Documents`, `~/Documents/ai`, `~/Documents/ai/monitor-cc`
   all raised `PermissionError` under launchd; `os.listdir('/tmp')` and
   `os.listdir('~/Documents/../..')` (i.e. `$HOME`) succeeded. `/tmp` and `$HOME` itself are
   fine; everything under `~/Documents` is not.

Root cause: macOS TCC ("Files and Folders" privacy protection) blocks filesystem access to
`~/Documents` (and `~/Desktop`/`~/Downloads`) for a process unless its executable has been
explicitly granted access — normally inherited from an approved parent (Terminal.app, a login
shell someone once approved) for interactive work, but a bare `/usr/bin/python3` spawned
directly by launchd has no such ancestor and is denied outright. Python's import machinery needs
to list a `sys.path` entry's directory to find `src/__init__.py`; TCC denies that `readdir`, so
the entry is silently treated as empty — `ModuleNotFoundError`, not a permissions error, is what
surfaces. `PYTHONPATH`/`WorkingDirectory` being correct cannot bypass this: TCC operates below
the level either of those settings can reach. Since the checkout (main or any `.claude/worktrees/
<name>` copy) lives under `~/Documents`, EVERY invocation of this LaunchAgent hits the same wall
regardless of which checkout it points at.

This is not fixable by any plist or code change — it requires a one-time, interactive,
GUI-only grant: System Settings > Privacy & Security > Full Disk Access > + > Cmd+Shift+G >
`/Library/Developer/CommandLineTools/usr/bin/python3` > Open > enable. Documented in the plist
itself (a `<dict>`-level comment), in `setup_monitor_sweep.py`'s `full_disk_access_note()`
(printed alongside the bootstrap command), and in `src/DOCS.md`.

## Log path: `MONITOR_CC_ROOT`-or-else-`__file__`, no main-checkout fallback

Separately: the initial task's own live verification run had written
`src/logs/monitor_sweep.log` inside the WORKTREE, not the main checkout, because
`monitor_janitor.py` derived its log path purely from its own `__file__` location with no
override. Considered mirroring `dual_log_cli.discovery.resolve_dual_log_dir`'s pattern
(env var wins, else derive from `__file__`, else fall back to the main checkout if the direct
path doesn't already exist) — rejected the fallback-to-main part: that function's fallback
exists because dual-log content is only ever POPULATED by real proxy sessions run from the main
checkout, so a worktree-local copy is a read source unlikely to hold anything worth reading. The
sweep log is a WRITE target instead — it must record wherever the code that ran actually
executed, especially for a test LaunchAgent that deliberately points at a worktree (the sweep
log for the test label needs to land IN the worktree the test targets, not silently redirect to
the main checkout). Implemented `_resolve_monitor_cc_root()`: `$MONITOR_CC_ROOT` env var wins,
else `Path(__file__).resolve().parent.parent` (no existence-based fallback). Both LaunchAgent
plists now set `MONITOR_CC_ROOT` explicitly, pinning the log location independent of any
ambiguity in how `__file__`/cwd resolve under launchd; the bash trigger doesn't need it, since
`cd "$MONITOR_CC_ROOT"` before `-m` already makes `__file__` match by construction.

## Verification (2026-09-03, second round)

- `dev/monitor_lifecycle/tests/test_monitor_sweep.py`: 11/11 checks still pass after switching
  `_LOG_PATH` (module constant) to `_log_path()` (function, re-resolves per call).
- Test LaunchAgent (`com.brunowinter.monitor-cc-sweep-test`) bootstrapped + kickstarted for real
  under launchd, per the diagnostic sequence above — confirmed the PYTHONPATH fix is necessary
  and correctly wired (sys.path evidence), and confirmed conclusively (not by hand) that Full
  Disk Access is the remaining, separate, code-unfixable blocker on this machine. Did NOT
  achieve a genuine successful end-to-end `src.monitor_janitor` run under launchd this session —
  Full Disk Access cannot be granted non-interactively. Test label, its plist
  (`~/Library/LaunchAgents/com.brunowinter.monitor-cc-sweep-test.plist`), and its
  `/tmp/monitor-cc-sweep-test.{log,err}` were all removed after the investigation
  (`launchctl bootout` + `rm`).
- Production label (`com.brunowinter.monitor-cc-sweep`) was never bootstrapped, kickstarted, or
  edited by this investigation — confirmed byte-identical to the user's own install (still the
  pre-fix plist, still `state = not running`, i.e. idle awaiting its `StartCalendarInterval`).
  The user re-installs it from `main` after this fix per their own instruction; it will still
  need the Full Disk Access grant above to actually run.
