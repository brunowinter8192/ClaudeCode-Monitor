# INFRASTRUCTURE
import os
import signal
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, NamedTuple, Optional, Tuple

# From proc_cache.py: Tasks base dir + CC process cache for project attribution
from .proc_cache import _TASKS_BASE, _cc_proc_cache
# From menubar_log.py: unified log sink for abort action events
from .menubar_log import log_menubar

# ORCHESTRATOR

# Scan for orchestrator wake-up processes (worker-cli wait + legacy sleep timers) and abort
# them; internal helpers below (No single orchestrator function — module exposes two
# independent public entry points)

# FUNCTIONS

_WORKER_CLI_WAIT_DEFAULT_TIMEOUT = 3300  # mirrors worker-cli wait's own --timeout default

class BgSleepInfo(NamedTuple):
    min_remaining: int        # shortest remaining seconds across all active wake-up processes
    sleep_pids:    List[int]  # PIDs of matching wake-up processes (sleep timers AND worker-cli wait)

# Parse ps etime field to seconds. Formats: SS, MM:SS, HH:MM:SS, D-HH:MM:SS
def _parse_etime(etime: str) -> Optional[int]:
    try:
        days_str, _, rest = etime.partition('-')
        if not rest:
            rest, days_str = days_str, '0'
        parts = rest.split(':')
        d = int(days_str) * 86400
        weights = (1, 60, 3600)   # SS weight, MM weight, HH weight
        return d + sum(int(v) * w for v, w in zip(reversed(parts), weights))
    except (ValueError, IndexError):
        pass
    return None

# True if tokens is a bare 'sleep N' invocation (args split on whitespace)
def _is_bare_sleep(tokens: List[str]) -> bool:
    return len(tokens) == 2 and tokens[0] == 'sleep' and tokens[1].replace('.', '', 1).isdigit()

# True if tokens invoke 'worker-cli wait' — matches both 'worker-cli wait ...' (bare) and
# 'bash <path>/worker-cli wait ...' / '<path>/worker-cli wait ...' (the actual shape CC's
# background-launch produces, args[0] is the interpreter or full script path). Only the
# basename of tokens[i] is checked against 'worker-cli', so any absolute-path invocation matches.
def _worker_cli_wait_index(tokens: List[str]) -> Optional[int]:
    for i, tok in enumerate(tokens[:-1]):
        if os.path.basename(tok) == 'worker-cli' and tokens[i + 1] == 'wait':
            return i
    return None

# Parse a --timeout N or --timeout=N value out of worker-cli wait's argv tail; None if absent
# (caller applies _WORKER_CLI_WAIT_DEFAULT_TIMEOUT).
def _parse_wait_timeout(tokens: List[str]) -> Optional[int]:
    for i, tok in enumerate(tokens):
        if tok == '--timeout' and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            return int(tokens[i + 1])
        if tok.startswith('--timeout=') and tok[len('--timeout='):].isdigit():
            return int(tok[len('--timeout='):])
    return None

# Walk ancestry chain upward from start_pid — handles depth > 2 (intermediate shell layers
# between CC and the process actually running the wake-up command, e.g. CC → sh → zsh → sleep,
# or CC → zsh → bash → worker-cli). Stops when a CC process is found in _cc_proc_cache, or the
# chain runs out (5-level cap), or 5 hops are exhausted. Returns the resolved cwd, or '' if the
# CC ancestor was never found.
def _resolve_ancestor_cwd(start_pid: str, pid_info: Dict[str, Tuple[str, str, str]]) -> str:
    ancestor_pid = start_pid
    for _ in range(5):
        if ancestor_pid in _cc_proc_cache:
            break
        ancestor_info = pid_info.get(ancestor_pid)
        if ancestor_info is None:
            break
        ancestor_pid = ancestor_info[0]
    cc_entry = _cc_proc_cache.get(ancestor_pid)
    return cc_entry[1] if cc_entry else ''

# Scan for orchestrator wake-up processes: 'worker-cli wait' (canonical, 2026-08 pull migration)
# AND the legacy 'sleep N && echo done' pattern (timers armed before the migration may still be
# in flight — kept, not replaced). Attributes each to a project via ancestry→cwd lookup.
# cwd_to_project: {session_cwd: project_name} built from list_alive_sessions() mains in caller.
# Returns {project_name: BgSleepInfo}; 'unknown' key for processes whose CC process is unresolvable.
def _scan_bg_sleep_timers(cwd_to_project: Dict[str, str]) -> Dict[str, BgSleepInfo]:
    try:
        r = subprocess.run(
            ['ps', '-A', '-o', 'pid=,ppid=,etime=,args='],
            capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=3)
    except Exception:
        return {}
    pid_info: Dict[str, Tuple[str, str, str]] = {}
    for line in r.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            pid_info[parts[0]] = (parts[1], parts[2], parts[3])
    buckets: Dict[str, List[Tuple[int, int]]] = {}   # project_name → [(remaining, pid)]
    for pid, (ppid, etime, args) in pid_info.items():
        tokens = args.strip().split()
        elapsed = _parse_etime(etime)
        if elapsed is None:
            continue
        wait_idx = _worker_cli_wait_index(tokens)
        if wait_idx is not None:
            timeout = _parse_wait_timeout(tokens[wait_idx + 2:])
            if timeout is None:
                timeout = _WORKER_CLI_WAIT_DEFAULT_TIMEOUT
            remaining = max(0, timeout - elapsed)
            # Start the walk at this process's OWN ppid (its immediate parent is typically the
            # zsh wrapper CC launches it through — live-verified shape: worker-cli wait → zsh -c
            # → claude.exe). _resolve_ancestor_cwd checks membership before advancing, so passing
            # ppid directly correctly walks zsh → claude in one extra hop vs. the sleep branch
            # below (which already knows its immediate parent isn't CC and starts one hop higher).
            cwd = _resolve_ancestor_cwd(ppid, pid_info)
            project_name = cwd_to_project.get(cwd, 'unknown')
            buckets.setdefault(project_name, []).append((remaining, int(pid)))
            continue
        if not _is_bare_sleep(tokens):
            continue
        parent = pid_info.get(ppid, ('', '', ''))
        if 'echo done' not in parent[2]:
            continue
        remaining = max(0, int(float(tokens[1])) - elapsed)
        # Walk from the zsh parent's OWN ppid (one level above the sleep process itself).
        cwd = _resolve_ancestor_cwd(parent[0], pid_info)
        project_name = cwd_to_project.get(cwd, 'unknown')
        buckets.setdefault(project_name, []).append((remaining, int(pid)))
    return {
        proj: BgSleepInfo(min_remaining=min(e[0] for e in entries),
                          sleep_pids=[e[1] for e in entries])
        for proj, entries in buckets.items()
    }

# Collapse per-project scan result to single Optional[BgSleepInfo] for panel/abort callers
def _aggregate_bg(result: Dict[str, BgSleepInfo]) -> Optional[BgSleepInfo]:
    if not result:
        return None
    return BgSleepInfo(
        min_remaining=min(info.min_remaining for info in result.values()),
        sleep_pids=[p for info in result.values() for p in info.sleep_pids],
    )

# Kill wake-up-process PIDs (worker-cli wait OR legacy sleep timers) via SIGTERM; write
# 'aborted\n' to all 0-byte task files so the [B] badge clears. Generic by PID — no logic change
# needed for the worker-cli wait case, it was already agnostic to what the pid actually was.
def _abort_bg_sleep_timers(sleep_pids: List[int]) -> int:
    killed = 0
    errors = 0
    last_err = None
    for pid in sleep_pids:
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except (ProcessLookupError, OSError) as e:
            errors += 1
            last_err = e
    try:
        ts = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f')[:23]
        pids_str = ','.join(str(p) for p in sleep_pids)
        err_extra = f' last_err={repr(last_err)}' if last_err else ''
        line = f'{ts} abort_action pids=[{pids_str}] killed={killed} errors={errors}{err_extra}'
        log_menubar('abort', line)
    except Exception as e:
        print(f'[abort-log] abort_action write error: {e}', file=sys.stderr)
    try:
        for encoded_dir in _TASKS_BASE.iterdir():
            if not encoded_dir.is_dir():
                continue
            for session_dir in encoded_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                tasks_dir = session_dir / 'tasks'
                if not tasks_dir.is_dir():
                    continue
                for f in tasks_dir.glob('*.output'):
                    try:
                        if f.stat().st_size == 0:
                            f.write_text('aborted\n')
                    except OSError:
                        pass
    except OSError:
        pass
    return killed
