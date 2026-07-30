"""
Drives the real proxy_display render path (accumulate_dual_log -> pane attach ->
_build_req_header_line) over recorded dual-logs to verify the `strip`/`inject` word badge
replaced the old numeric `Nstrip Ninj` badge, and that a "."-filler injection counts as
an injection (header agrees with the green span the expanded view renders).

Usage (from project root):
    ./venv/bin/python dev/proxy_instrumentation/badge_words_probe.py
"""

# INFRASTRUCTURE
import json
import re
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT))

# Recorded dual-log sessions live in the main project checkout (untracked data, not
# duplicated into worktrees) — code under test is imported from WORKTREE_ROOT above.
MAIN_REPO_ROOT = Path('/Users/brunowinter2000/Documents/ai/monitor-cc')
LOG_DIR = MAIN_REPO_ROOT / 'src' / 'logs' / 'dual_log'

REPORT_DIR = Path(__file__).parent / 'md'
REPORT_PATH = REPORT_DIR / 'badge_words_probe_report.md'

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

# Cases: (label, stem, request_id_prefix, expected badge words)
CASES = [
    ('msg84_dot_filler_injection', 'api_requests_opus_monitor_cc_1785364138', '0eaf06ba', 'strip inject'),
    ('msg52_bg_wakeup_replacement', 'api_requests_opus_monitor_cc_1785364138', '2ae188e7', 'strip inject'),
    ('strip_only', 'api_requests_opus_monitor_cc_1785347492', 'ca01cd43', 'strip'),
    ('neither', 'api_requests_opus_monitor_cc_1785364138', 'daadb2b0', ''),
]

# FUNCTIONS

# Build (entries, acc_stripped, acc_injected, stripped_path) for one stem, real accumulate_dual_log path
def _load_stem(stem: str):
    from src.proxy_display.forwarded_parser import _parse_forwarded_log
    from src.proxy_display.parser import accumulate_dual_log
    fwd_path = LOG_DIR / f'{stem}_forwarded.jsonl'
    stripped_path = LOG_DIR / f'{stem}_stripped.jsonl'
    injected_path = LOG_DIR / f'{stem}_injected.jsonl'
    entries, _ = _parse_forwarded_log(fwd_path, 0, {})
    acc_stripped: dict = {}
    acc_injected: dict = {}
    accumulate_dual_log(stripped_path, 0, acc_stripped)
    accumulate_dual_log(injected_path, 0, acc_injected)
    return entries, acc_stripped, acc_injected, stripped_path

# request_id lives only in the stripped/injected dual-log lines (forwarded log's own
# request_id field is blank in these recordings) — resolve flow_id via the stripped log.
def _flow_id_for_request(stripped_path: Path, rid_prefix: str) -> str:
    with open(stripped_path, encoding='utf-8') as f:
        for line in f:
            e = json.loads(line)
            if e.get('request_id', '').startswith(rid_prefix):
                return e.get('flow_id', '')
    raise AssertionError(f"request_id prefix {rid_prefix} not found in {stripped_path}")

# Attach _strip_fns_lookup/_inject_fns_lookup exactly as pane.py does, render header, strip ANSI
def _render_badge_for_request(entries: list, acc_stripped: dict, acc_injected: dict, stripped_path: Path, rid_prefix: str) -> tuple:
    from src.proxy_display.forwarded_parser import _infer_model_family
    from src.proxy_display.render_turn import _build_req_header_line
    flow_id = _flow_id_for_request(stripped_path, rid_prefix)
    target = next(e for e in entries if e.get('flow_id', '') == flow_id)
    family = _infer_model_family(target.get('model', ''))
    target['_strip_fns_lookup'] = acc_stripped.get(family, {}).get('_has_content_by_flow_id', {})
    target['_inject_fns_lookup'] = acc_injected.get(family, {}).get('_has_content_by_flow_id', {})
    header = _build_req_header_line(
        target, entry_idx=0, num_label='#1', req_symbol='▶', model_short='opus',
        msg_count=target.get('message_count', 0), mods_str='', warn_str='', pane_width=200,
        copy_feedback=None,
    )
    visible = _ANSI_RE.sub('', header)
    words = ' '.join(w for w in ('strip', 'inject') if re.search(rf'\b{w}\b', visible))
    return flow_id, visible, words

# ORCHESTRATOR
def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    lines = ['# Badge words probe — strip/inject word badge over recorded dual-logs', '']
    lines.append('| case | request_id prefix | flow_id | expected | actual | pass |')
    lines.append('|---|---|---|---|---|---|')
    all_pass = True
    stems_loaded = {}
    for label, stem, rid_prefix, expected in CASES:
        if stem not in stems_loaded:
            stems_loaded[stem] = _load_stem(stem)
        entries, acc_stripped, acc_injected, stripped_path = stems_loaded[stem]
        flow_id, visible_header, words = _render_badge_for_request(entries, acc_stripped, acc_injected, stripped_path, rid_prefix)
        ok = words == expected
        all_pass = all_pass and ok
        lines.append(f"| {label} | {rid_prefix} | {flow_id} | `{expected or '(none)'}` | `{words or '(none)'}` | {'PASS' if ok else 'FAIL'} |")
        lines.append('')
        lines.append(f"  header: `{visible_header.strip()}`")
        lines.append('')
    lines.append(f"## Overall: {'ALL PASS' if all_pass else 'FAILURES PRESENT'}")
    REPORT_PATH.write_text('\n'.join(lines))
    print(f"Report written: {REPORT_PATH}")
    print('ALL PASS' if all_pass else 'FAILURES PRESENT')
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
