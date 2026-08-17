# INFRASTRUCTURE
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Tuple
# From paths.py: APP_SUPPORT-relative hook state path
from .paths import HOOKS_FILE as _HOOK_STATE_FILE

_PROC_REFRESH_INTERVAL = 10.0   # seconds between ps/lsof cache rebuilds (expensive: ps -A + lsof)
_HOOK_REFRESH_INTERVAL = 1.0    # seconds between hooks.json reads (cheap: 1KB JSON; MUST be < POLL_INTERVAL=1.5s for tick-freshness; see process-docs/menubar_signal_grace/initial_design.md)
_TMUX_REFRESH_INTERVAL = 3.0    # seconds between tmux list-sessions polls
_TASKS_BASE = Path(f"/tmp/claude-{os.getuid()}")
# Real (symlink-resolved) form of _TASKS_BASE — lsof reports NAME as /private/tmp/... on macOS
# (/tmp is a symlink to /private/tmp); comparing against unresolved paths would never match.
_TASKS_BASE_REAL = str(_TASKS_BASE.resolve())
# central log dir — proxy lives in monitor-cc and intercepts all CC sessions via ANTHROPIC_BASE_URL
_PROXY_LOG_DIR = Path('/Users/brunowinter2000/Documents/ai/monitor-cc/src/logs')

# pid→(tty, cwd) cache for CC processes; incremental: lsof only on new PIDs
_cc_proc_cache: Dict[str, Tuple[str, str]] = {}
_cc_proc_last_refresh: float = 0.0

# Absolute paths (real, resolved) of *.output files currently held open by any process,
# across ALL sessions' tasks dirs at once — one global lsof scan per _PROC_REFRESH_INTERVAL,
# not one per session. TTL = _PROC_REFRESH_INTERVAL (same "expensive lsof" budget as proc cache).
_bg_task_open_paths: set = set()
_bg_task_last_refresh: float = 0.0

# session_name set (alive check only); one list-sessions call per 3s
_tmux_state_cache: set = set()
_tmux_state_last_refresh: float = 0.0

# opus_<project_key>→(checked_at: float, mtime: float|None); TTL = _PROC_REFRESH_INTERVAL
_proxy_log_mtime_cache: Dict[str, Tuple[float, Optional[float]]] = {}

# Hook state file written by hook_writer.py; {session_id → {status, cwd, updated_ts}}
# cached contents + last-read timestamp; TTL = _HOOK_REFRESH_INTERVAL (1s, not coupled to proc cache)
_hook_state_cache: Dict[str, dict] = {}
_hook_state_last_read: float = 0.0

# ORCHESTRATOR

# (No single orchestrator — module exposes independent cache-refresh entry points)

# FUNCTIONS

# True if any process currently holds an open handle on a *.output file in the session tasks dir.
# Reads the global _bg_task_open_paths snapshot (see _refresh_bg_task_cache) — caller MUST have
# called _refresh_bg_task_cache(now) earlier in the tick for this to reflect a fresh scan.
def _has_active_bg(encoded_dir: str, session_id: str) -> bool:
    try:
        tasks_dir_real = f'{_TASKS_BASE_REAL}/{encoded_dir}/{session_id}/tasks/'
        return any(p.startswith(tasks_dir_real) for p in _bg_task_open_paths)
    except OSError:
        return False

# Update _bg_task_open_paths via ONE global lsof scan of _TASKS_BASE (covers every session's
# tasks dir in a single ~100ms call, vs. ~100ms PER session for a per-dir call). Fail-open: any
# lsof error leaves the previous snapshot in place (never escalates a stale True; mirrors
# _refresh_cc_proc_cache's swallow-and-keep-prior-cache shape).
def _refresh_bg_task_cache(now: float) -> None:
    global _bg_task_open_paths, _bg_task_last_refresh
    if now - _bg_task_last_refresh < _PROC_REFRESH_INTERVAL:
        return
    _bg_task_last_refresh = now
    if not _TASKS_BASE.exists():
        _bg_task_open_paths = set()
        return
    try:
        r = subprocess.run(['lsof', '+D', str(_TASKS_BASE), '-Fn'],
                            capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=3)
    except Exception:
        return
    _bg_task_open_paths = {line[1:] for line in r.stdout.split('\n')
                            if line.startswith('n') and line.endswith('.output')}

# Update pid→(tty,cwd) cache incrementally: drop gone PIDs, lsof only for new ones
def _refresh_cc_proc_cache(now: float) -> None:
    global _cc_proc_last_refresh
    if now - _cc_proc_last_refresh < _PROC_REFRESH_INTERVAL:
        return
    _cc_proc_last_refresh = now
    try:
        r = subprocess.run(['ps', '-A', '-o', 'pid,tty,comm'],
                           capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=3)
    except Exception:
        return
    # Build {pid: tty} for active CC processes with valid TTY
    active: Dict[str, str] = {}
    for line in r.stdout.strip().split('\n')[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3 and 'claude' in parts[2].lower() and parts[1] != '??':
            active[parts[0].strip()] = parts[1].strip()
    # Drop entries for gone PIDs
    for pid in list(_cc_proc_cache):
        if pid not in active:
            del _cc_proc_cache[pid]
    # lsof only for PIDs not yet in cache (cwd is stable after launch)
    for pid, tty in active.items():
        if pid in _cc_proc_cache:
            continue
        try:
            r2 = subprocess.run(['lsof', '-a', '-d', 'cwd', '-p', pid],
                                 capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=2)
            for line in r2.stdout.strip().split('\n'):
                if line.startswith('COMMAND') or not line:
                    continue
                fields = line.split(None, 8)
                if len(fields) == 9:
                    _cc_proc_cache[pid] = (tty, fields[8])
                    break
        except Exception:
            pass

# Refresh tmux session state via one list-sessions call; no-op within 3s TTL
def _refresh_tmux_state(now: float) -> None:
    global _tmux_state_cache, _tmux_state_last_refresh
    if now - _tmux_state_last_refresh < _TMUX_REFRESH_INTERVAL:
        return
    _tmux_state_last_refresh = now
    try:
        r = subprocess.run(
            ['tmux', 'list-sessions', '-F', '#{session_name}'],
            capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=3)
        if r.returncode != 0:
            _tmux_state_cache = set()
            return
    except Exception:
        return
    _tmux_state_cache = {line.strip() for line in r.stdout.strip().split('\n') if line.strip()}

# True if session_name appears in the tmux state cache (= exists)
def _tmux_session_exists(session_name: str) -> bool:
    return session_name in _tmux_state_cache

# Return unix timestamp of last pane byte-write for session; 0 if query fails
def _tmux_window_activity(session: str) -> int:
    try:
        result = subprocess.run(
            ['tmux', 'display-message', '-t', f'{session}:^', '-p', '#{window_activity}'],
            capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=2)
        if result.returncode != 0:
            return 0
        return int(result.stdout.strip())
    except Exception:
        return 0

# Return newest mtime of proxy logs matching opus_<project_key>; None if no match or dir missing
def _proxy_log_newest_mtime(project_key: str, now: float) -> Optional[float]:
    cached = _proxy_log_mtime_cache.get(project_key)
    if cached is not None and (now - cached[0]) < _PROC_REFRESH_INTERVAL:
        return cached[1]
    result: Optional[float] = None
    if _PROXY_LOG_DIR.is_dir():
        needle = f'_opus_{project_key}_'
        for p in _PROXY_LOG_DIR.glob('api_requests_*.jsonl'):
            if needle in p.stem:
                try:
                    mt = p.stat().st_mtime
                    if result is None or mt > result:
                        result = mt
                except OSError:
                    pass
    _proxy_log_mtime_cache[project_key] = (now, result)
    return result

# Return hook state dict {session_id: {status, cwd, updated_ts}}; cached with _HOOK_REFRESH_INTERVAL TTL
def _read_hook_state(now: float) -> Dict[str, dict]:
    global _hook_state_cache, _hook_state_last_read
    if now - _hook_state_last_read < _HOOK_REFRESH_INTERVAL:
        return _hook_state_cache
    _hook_state_last_read = now
    try:
        _hook_state_cache = json.loads(_HOOK_STATE_FILE.read_text(encoding='utf-8'))
    except Exception:
        _hook_state_cache = {}
    return _hook_state_cache
