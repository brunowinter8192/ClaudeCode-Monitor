"""
Parses menubar.log [latency] lines (tick phase breakdowns, hotkey queue-delays, focus-path
splits — emitted by app.py/hotkey_controller.py/system.py, see process-docs/hotkey_latency/)
into a distribution report: per-phase stats, slowest ticks with full breakdown, hotkey
queue-delay percentiles, focus lookup-vs-osascript split.

Usage (from project root):
    ./venv/bin/python3 dev/hotkey_latency/analyze_latency.py [path/to/menubar.log]

Default log path: menubar.menubar_log.MENUBAR_LOG (live APP_SUPPORT location).
Report written to dev/hotkey_latency/md/latency_report_<UTC-timestamp>.md.
"""

# INFRASTRUCTURE
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT / 'src'))

# From menubar_log.py: default live log location
from menubar.menubar_log import MENUBAR_LOG

REPORT_DIR   = Path(__file__).parent / 'md'
N_SLOWEST    = 10
_LATENCY_RE  = re.compile(r'^(\S+) \[latency\] (.*)$')
_TICK_RE     = re.compile(r'^tick total=(\d+)ms (.*)$')
_PHASE_RE    = re.compile(r'(\w+)=(\d+)ms')
_HOTKEY_RE   = re.compile(r'^hotkey=(\S+) queue_delay_ms=([\d.]+)$')
_FOCUS_RE    = re.compile(r'^focus lookup_ms=([\d.]+) osascript_ms=([\d.]+) (.*)$')

# ORCHESTRATOR

def main() -> None:
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else MENUBAR_LOG
    ticks, hotkeys, focuses = _parse_latency_lines(log_path)
    report = _build_report(log_path, ticks, hotkeys, focuses)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out_path = REPORT_DIR / f'latency_report_{stamp}.md'
    out_path.write_text(report, encoding='utf-8')
    print(f'ticks={len(ticks)} hotkeys={len(hotkeys)} focuses={len(focuses)}')
    print(f'report written to {out_path}')

# FUNCTIONS

# Parse menubar.log for [latency] lines; returns (ticks, hotkeys, focuses)
# ticks:    [{'ts': str, 'total_ms': int, 'phases': {name: ms}}]
# hotkeys:  [{'ts': str, 'name': str, 'delay_ms': float}]
# focuses:  [{'ts': str, 'lookup_ms': float, 'osascript_ms': float, 'label': str}]
def _parse_latency_lines(log_path: Path) -> Tuple[List[dict], List[dict], List[dict]]:
    ticks, hotkeys, focuses = [], [], []
    if not log_path.exists():
        return ticks, hotkeys, focuses
    with open(log_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = _LATENCY_RE.match(line.rstrip('\n'))
            if not m:
                continue
            ts, body = m.group(1), m.group(2)
            tm = _TICK_RE.match(body)
            if tm:
                total_ms = int(tm.group(1))
                phases = {name: int(ms) for name, ms in _PHASE_RE.findall(tm.group(2))}
                ticks.append({'ts': ts, 'total_ms': total_ms, 'phases': phases})
                continue
            hm = _HOTKEY_RE.match(body)
            if hm:
                hotkeys.append({'ts': ts, 'name': hm.group(1), 'delay_ms': float(hm.group(2))})
                continue
            fm = _FOCUS_RE.match(body)
            if fm:
                focuses.append({'ts': ts, 'lookup_ms': float(fm.group(1)),
                                 'osascript_ms': float(fm.group(2)), 'label': fm.group(3)})
    return ticks, hotkeys, focuses

# Nearest-rank percentile over a non-empty list of numbers
def _pct(values: List[float], p: float) -> float:
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round(p / 100 * (len(s) - 1)))))
    return s[idx]

# Distribution line: n, mean, median, p90, p95, max
def _dist_line(values: List[float]) -> str:
    if not values:
        return 'n=0'
    return (f'n={len(values)} mean={statistics.mean(values):.1f} '
            f'median={statistics.median(values):.1f} p90={_pct(values, 90):.1f} '
            f'p95={_pct(values, 95):.1f} max={max(values):.1f}')

# Markdown table of tick total-duration distribution + per-phase distribution + slowest N ticks
def _tick_section(ticks: List[dict]) -> str:
    if not ticks:
        return '## Tick Latency\n\nNo [latency] tick lines found (no tick exceeded TICK_LATENCY_THRESHOLD_MS in this log window).\n'
    totals = [t['total_ms'] for t in ticks]
    phase_names = sorted({name for t in ticks for name in t['phases']})
    phase_lines = []
    for name in phase_names:
        vals = [t['phases'][name] for t in ticks if name in t['phases']]
        phase_lines.append(f'- `{name}`: {_dist_line(vals)}')
    slowest = sorted(ticks, key=lambda t: -t['total_ms'])[:N_SLOWEST]
    slowest_lines = []
    for t in slowest:
        breakdown = ' '.join(f'{k}={v}ms' for k, v in sorted(t['phases'].items(), key=lambda kv: -kv[1]))
        slowest_lines.append(f'- {t["ts"]} total={t["total_ms"]}ms — {breakdown}')
    return (
        '## Tick Latency (over-threshold ticks only)\n\n'
        f'Total-duration distribution: {_dist_line(totals)}\n\n'
        '### Per-Phase Distribution (ms, over over-threshold ticks)\n\n'
        + '\n'.join(phase_lines) + '\n\n'
        f'### Slowest {min(N_SLOWEST, len(ticks))} Ticks\n\n'
        + '\n'.join(slowest_lines) + '\n'
    )

# Markdown section: hotkey queue-delay percentiles, overall + per hotkey name
def _hotkey_section(hotkeys: List[dict]) -> str:
    if not hotkeys:
        return '## Hotkey Queue-Delay\n\nNo [latency] hotkey lines found.\n'
    overall = [h['delay_ms'] for h in hotkeys]
    by_name: Dict[str, List[float]] = {}
    for h in hotkeys:
        by_name.setdefault(h['name'], []).append(h['delay_ms'])
    lines = [f'- `{name}`: {_dist_line(vals)}' for name, vals in sorted(by_name.items())]
    return (
        '## Hotkey Queue-Delay (queue_delay_ms = handler-entry time - Carbon event timestamp)\n\n'
        f'Overall: {_dist_line(overall)}\n\n'
        '### Per Hotkey\n\n' + '\n'.join(lines) + '\n'
    )

# Markdown section: focus-path lookup vs osascript split
def _focus_section(focuses: List[dict]) -> str:
    if not focuses:
        return '## Focus-Path Timing\n\nNo [latency] focus lines found.\n'
    lookup = [f['lookup_ms'] for f in focuses]
    osa    = [f['osascript_ms'] for f in focuses]
    return (
        '## Focus-Path Timing (_focus_session)\n\n'
        f'- `lookup_ms` (get_ghostty_terminal_id): {_dist_line(lookup)}\n'
        f'- `osascript_ms` (osascript run): {_dist_line(osa)}\n'
    )

# Assemble full markdown report
def _build_report(log_path: Path, ticks: List[dict], hotkeys: List[dict], focuses: List[dict]) -> str:
    header = (
        f'# Hotkey/Menubar Latency Report\n\n'
        f'Source: `{log_path}`\n'
        f'Generated: {datetime.now(timezone.utc).isoformat(timespec="seconds")}\n\n'
    )
    return header + _tick_section(ticks) + '\n' + _hotkey_section(hotkeys) + '\n' + _focus_section(focuses)

if __name__ == '__main__':
    main()
