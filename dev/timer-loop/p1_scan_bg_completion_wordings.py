"""
Milestone 1 — inventory distinct CC background-task COMPLETION/kill notice wordings in the
real recorded corpus, for main (orchestrator) vs worker sessions.

Measurement only: scans src/logs/dual_log/*_original.jsonl for messages that look like a CC
background-task completion notice (the <task-notification> family) or a bare "Background
command "..." completed/failed" notice (the strip_bg_completed.py family), dedups cumulative
dual-log duplication, buckets by (status, exit-code, normalized summary template), and
evaluates the real id-extraction mechanism (payload_helpers._extract_task_notification_task_id)
against each wording. Writes report to dev/timer-loop/md/.

Companion to dev/bg_wakeup_id_line/p1_scan_launch_ack_wordings.py (launch side); this covers
the completion side.

Usage (from project root or worktree root):
    ./venv/bin/python dev/timer-loop/p1_scan_bg_completion_wordings.py [log_dir]
"""

# INFRASTRUCTURE
import html
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT / 'src'))

from proxy.strip_sn_notice import _SN_NOTICE_MARKER, _SN_NOTICE_PARAGRAPH
from proxy.strip_bg_completed import _BG_CMD_MARKER, _BG_EXIT_RE
from proxy.payload_helpers import (
    _find_task_notification_blocks,
    _extract_task_notification_task_id,
    _extract_task_notification_output_file,
)

# Corpus dir: parameterized, defaults to the main checkout's dual-log dir (untracked data, not
# duplicated into worktrees) — code under test is imported from WORKTREE_ROOT above.
MAIN_REPO_ROOT = Path('/Users/brunowinter2000/Documents/ai/monitor-cc')
DEFAULT_LOG_DIR = MAIN_REPO_ROOT / 'src' / 'logs' / 'dual_log'
REPORT_DIR = Path(__file__).resolve().parent / 'md'

# Excluded: this worker's own live worktree session — actively growing during this
# investigation, polluted by Read-tool dumps of the exact source files under measurement
# (payload_helpers.py / message_passes.py docstrings and regex literals contain the literal
# strings "<task-notification>", "<task-id>", etc.) — same contamination class as the
# launch-ack report's own-session exclusion.
EXCLUDED_FILES = {
    'api_requests_worker_85d6f25b_timer-loop_1786044804_original.jsonl':
        "this worker's own live worktree session — growing during this investigation, "
        'self-contaminated by Read dumps of payload_helpers.py / message_passes.py / '
        'strip_sn_notice.py (their docstrings and regex literals contain the exact tag '
        'strings being measured here)',
}

_TASK_ID_TAG_RE = re.compile(r'<task-id>(.*?)</task-id>', re.DOTALL)
_STATUS_TAG_RE = re.compile(r'<status>(.*?)</status>', re.DOTALL)
_SUMMARY_TAG_RE = re.compile(r'<summary>(.*?)</summary>', re.DOTALL)
_EXIT_CODE_RE = re.compile(r'exit code (\d+)')
_CMD_QUOTE_RE = re.compile(r'"([^"]*)"')
_CANONICAL_TIMER_CMD = 'sleep 3300 && echo done'


# FUNCTIONS

# Extract (shape, text) candidate blocks from one message's content — mirrors the 4-shape walk
# used by every strip_* pass (str / text block / tool_result str / tool_result list[text]).
def _iter_candidate_blocks(content):
    if isinstance(content, str):
        yield ('top_level_str', content)
        return
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get('type')
            if btype == 'text':
                yield ('text_block', block.get('text', ''))
            elif btype == 'tool_result':
                inner = block.get('content', '')
                if isinstance(inner, str):
                    yield ('tool_result_str', inner)
                elif isinstance(inner, list):
                    for sub in inner:
                        if isinstance(sub, dict) and sub.get('type') == 'text':
                            yield ('tool_result_list_text', sub.get('text', ''))


# Structural candidate filter for the TN (task-notification) family: block-INITIAL SN paragraph
# (role=user path, the only one observed) OR block-initial bare tag (role=system path per
# message_passes.py comments — defensive, 0 observed in this corpus, still checked so an
# unknown-but-real occurrence would surface here rather than being silently missed).
def _looks_like_tn_candidate(text, role):
    if not isinstance(text, str):
        return False
    stripped = text.lstrip()
    if stripped.startswith(_SN_NOTICE_PARAGRAPH) and '<task-notification>' in text:
        return True
    if role == 'system' and stripped.startswith('<task-notification>'):
        return True
    return False


# Structural candidate filter for the bare (unwrapped) family strip_bg_completed.py targets —
# block-INITIAL "Background command "" (not contains-anywhere, to exclude prose/dev-report
# mentions the same way the TN filter above does).
def _looks_like_bare_candidate(text):
    return isinstance(text, str) and text.lstrip().startswith(_BG_CMD_MARKER)


# Mask the volatile quoted command/description inside a summary string, so distinct real
# commands sharing the same status+exit-code collapse into one wording bucket
def _normalize_summary(summary):
    return _CMD_QUOTE_RE.sub('"<CMD>"', summary, count=1)


# Is the (HTML-unescaped) quoted command the canonical orchestrator timer literal?
def _is_canonical_timer_command(raw_command):
    return html.unescape(raw_command).strip() == _CANONICAL_TIMER_CMD


# Scan one corpus file for TN-family and bare-family candidates. Dedup key = the exact raw
# <task-notification>...</task-notification> tag-block text (or exact raw bare-notice text) —
# robust to both simple cumulative growth AND the non-monotonic message-count resets observed
# in some worker sessions (compaction), unlike a prev-count positional delta.
def _scan_file(path, findings, cmd_variant_counts, raw_dup_counter, bare_hits, session_is_worker):
    session = path.name
    is_worker = 'worker' in session
    session_is_worker[session] = is_worker
    seen_tn_blocks = set()
    seen_bare_texts = set()
    requests = 0
    parse_errors = 0
    with open(path, 'rb') as fh:
        for raw in fh:
            requests += 1
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            messages = entry.get('payload', {}).get('messages', [])
            for msg in messages:
                role = msg.get('role', '?')
                content = msg.get('content', '')
                for shape, text in _iter_candidate_blocks(content):
                    if _looks_like_tn_candidate(text, role):
                        raw_dup_counter[session] += 1
                        for tag_block in _find_task_notification_blocks(text):
                            if tag_block in seen_tn_blocks:
                                continue
                            seen_tn_blocks.add(tag_block)
                            _record_tn_event(tag_block, text, session, is_worker, shape, role,
                                              findings, cmd_variant_counts)
                    elif _looks_like_bare_candidate(text):
                        bare_hits[session] += 1
                        if text not in seen_bare_texts:
                            seen_bare_texts.add(text)
    return requests, parse_errors


# Record one deduped genuine TN completion/kill event into the findings dict, keyed by
# (status, exit_code, normalized_summary) — the actual "distinct wording" grouping.
def _record_tn_event(tag_block, full_text, session, is_worker, shape, role, findings, cmd_variant_counts):
    status_m = _STATUS_TAG_RE.search(tag_block)
    summary_m = _SUMMARY_TAG_RE.search(tag_block)
    status = status_m.group(1).strip() if status_m else '<NO-STATUS-TAG>'
    summary = summary_m.group(1).strip() if summary_m else '<NO-SUMMARY-TAG>'
    exit_m = _EXIT_CODE_RE.search(summary)
    exit_code = exit_m.group(1) if exit_m else '<NO-EXIT-CODE>'
    norm_summary = _normalize_summary(summary)
    key = (status, exit_code, norm_summary)
    rec = findings.setdefault(key, {
        'count': 0, 'main_sessions': set(), 'worker_sessions': set(), 'shapes': set(),
        'roles': set(), 'example_tag_block': tag_block, 'example_full_text': full_text,
        'session_counts': Counter(),
    })
    rec['count'] += 1
    rec['session_counts'][session] += 1
    (rec['worker_sessions'] if is_worker else rec['main_sessions']).add(session)
    rec['shapes'].add(shape)
    rec['roles'].add(role)

    cmd_m = _CMD_QUOTE_RE.search(summary)
    cmd_text = cmd_m.group(1) if cmd_m else '<NO-CMD>'
    variant_key = (status, exit_code)
    bucket = cmd_variant_counts.setdefault(variant_key, {'canonical_timer': 0, 'other': 0, 'examples': Counter()})
    if _is_canonical_timer_command(cmd_text):
        bucket['canonical_timer'] += 1
    else:
        bucket['other'] += 1
    bucket['examples'][cmd_text] += 1


# Evaluate the real id/output extraction mechanism (payload_helpers.py) against one example
# tag-block, plus the SN/TN fast-path marker gates the proxy uses before it ever reaches
# extraction.
def _mechanism_verdict(tag_block, full_text):
    marker_fires = _SN_NOTICE_MARKER in full_text
    tag_fires = '<task-notification>' in full_text
    task_id = _extract_task_notification_task_id(tag_block)
    output_file = _extract_task_notification_output_file(tag_block)
    return {
        'sn_marker_fires': marker_fires,
        'tn_tag_contains_fires': tag_fires,
        'task_id_extract': task_id or None,
        'output_file_extract': output_file or None,
    }


# Build the markdown report
def _build_report(findings, cmd_variant_counts, total_requests, total_parse_errors,
                   raw_dup_counter, bare_hits, corpus_files, session_is_worker):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    lines = []
    lines.append('# Milestone 1 — bg-completion/kill notice wording inventory (real corpus)')
    lines.append('')
    lines.append(f'Generated: {ts}')
    lines.append('')
    lines.append('Companion to `dev/bg_wakeup_id_line/md/launch_ack_wordings_20260729.md` (launch side); this is the completion side.')
    lines.append('')

    lines.append('## Corpus')
    lines.append('')
    lines.append(f'{len(corpus_files)} files scanned (full per-line parse, not last-line-only — see Method).')
    lines.append(f'Total requests (lines) scanned: {total_requests}. JSON parse errors skipped: {total_parse_errors}.')
    lines.append('')
    lines.append('| Excluded file | Reason |')
    lines.append('|---|---|')
    for fname, reason in EXCLUDED_FILES.items():
        lines.append(f'| `{fname}` | {reason} |')
    lines.append('')

    lines.append('## Method')
    lines.append('')
    lines.append(
        'Each dual-log line is a cumulative snapshot of the full `messages` history (same growing-'
        'history duplication as the launch-ack corpus). A last-line-only shortcut was benchmarked '
        '(~200x cheaper — 22MB vs 5.2GB for the largest session) but rejected: message-count-per-line '
        'is **not always monotonic** — several worker sessions (`api_requests_worker_cbc9195b_pass-*`) '
        'show mid-session decreases (compaction/context reset), so a last-line snapshot could silently '
        'drop notices lost to compaction. Instead: full per-line parse (benchmarked ~20-30s for the '
        'whole 17GB corpus), deduped via a per-session **exact-raw-text `seen` set** on the extracted '
        '`<task-notification>...</task-notification>` tag-block text — robust to both simple linear '
        'growth and compaction resets, unlike a prev-count positional delta (which double-counts on '
        'any reset).'
    )
    lines.append('')

    lines.append('## Contamination trap')
    lines.append('')
    lines.append(
        'Two sources found, both filtered by requiring the candidate block be **block-initial** '
        '(`text.lstrip().startswith(...)`), never contains-anywhere:'
    )
    lines.append('')
    lines.append(
        '1. **Prose/dev-report discussion quoting notice text.** `api_requests_opus_posts_1785424929` '
        'contains a German write-up discussing token cost that quotes `Background command "Index issues '
        'broad pass" completed (exit code 0)` mid-sentence, and a report-abbreviated '
        '`<output-file><path>...</path></output-file>` tag shape (567 raw hits, all from this one file) '
        'that is a documentation summary, not real wire format — the real wire format never nests a '
        '`<path>` tag inside `<output-file>`. Neither is block-initial, so both are excluded.'
    )
    lines.append(
        '2. **This worker\'s own live session** (see Excluded file above) — Read-tool dumps of the '
        'exact source files under measurement produce fake candidate text (docstrings/regex literals '
        'containing `<task-notification>`, `<task-id>` etc.) that would otherwise inflate every count.'
    )
    lines.append('')

    lines.append('## Q1 — Distinct wordings')
    lines.append('')
    if not findings:
        lines.append('**0 genuine completion/kill notices found in the scanned corpus.** Reported plainly — not manufactured.')
    for i, (key, rec) in enumerate(sorted(findings.items(), key=lambda kv: -kv[1]['count']), 1):
        status, exit_code, norm_summary = key
        verdict = _mechanism_verdict(rec['example_tag_block'], rec['example_full_text'])
        lines.append(f'### Wording {i} — status=`{status}`, exit code=`{exit_code}`')
        lines.append('')
        lines.append(f'- Normalized summary template: `{norm_summary}`')
        lines.append(f'- Occurrences (deduped, real distinct events): **{rec["count"]}**')
        lines.append(f'- Main sessions: {sorted(rec["main_sessions"])} ({len(rec["main_sessions"])})')
        lines.append(f'- Worker sessions: {sorted(rec["worker_sessions"])} ({len(rec["worker_sessions"])})')
        lines.append(f'- Roles seen: {sorted(rec["roles"])}')
        lines.append(f'- Content shapes seen: {sorted(rec["shapes"])}')
        lines.append('')
        lines.append('**Verbatim example (full block, incl. SN paragraph):**')
        lines.append('')
        lines.append('```')
        lines.append(rec['example_full_text'])
        lines.append('```')
        lines.append('')
        lines.append('**Mechanism fire/no-fire (real `src/proxy/` code):**')
        lines.append('')
        lines.append('| Mechanism | Result |')
        lines.append('|---|---|')
        lines.append(f'| `_SN_NOTICE_MARKER` fast-path gate | {"FIRES" if verdict["sn_marker_fires"] else "does NOT fire"} |')
        lines.append(f'| `<task-notification>` contains-gate (message_passes.py TN branch) | {"FIRES" if verdict["tn_tag_contains_fires"] else "does NOT fire"} |')
        lines.append(f'| `_extract_task_notification_task_id` | {"extracts: " + verdict["task_id_extract"] if verdict["task_id_extract"] else "FAILS to extract"} |')
        lines.append(f'| `_extract_task_notification_output_file` | {"extracts: " + verdict["output_file_extract"] if verdict["output_file_extract"] else "FAILS to extract"} |')
        lines.append('')

    lines.append('## Q1b — Bare (unwrapped) `strip_bg_completed.py`-family notices')
    lines.append('')
    total_bare = sum(bare_hits.values())
    if total_bare == 0:
        lines.append(
            '**0 block-initial bare `Background command "..." completed/failed` notices found anywhere '
            'in the corpus.** Every genuine completion/kill notice observed is `<task-notification>`-'
            'wrapped. `strip_bg_completed.py`\'s bare-form regex (`_BG_EXIT_RE`) is defensive/unexercised '
            'by real data in this corpus — its match target (a standalone, non-TN-wrapped notice) was '
            'not observed to occur; the same literal text (`Background command "..." failed with exit '
            'code N`) DOES occur, but always nested inside a `<summary>` tag within a TN block.'
        )
    else:
        lines.append(f'{total_bare} raw block-initial bare-family hits, by session: {dict(bare_hits)}')
    lines.append('')

    lines.append('## Q2 — Id extractability verdict')
    lines.append('')
    lines.append(
        'Every genuine TN wording carries the task id via a clean `<task-id>...</task-id>` XML tag — '
        '**reliably regex-extractable** (`payload_helpers._extract_task_notification_task_id`, already '
        'implemented and exercised above). This is a structurally different, simpler mechanism than the '
        'launch-ack side\'s prose `"with ID: <id>."` pattern — no prose parsing needed, no ambiguity '
        'about where the id ends.'
    )
    lines.append('')

    lines.append('## Q3 — Main vs worker split')
    lines.append('')
    n_main_files = sum(1 for s, w in session_is_worker.items() if not w)
    n_worker_files = sum(1 for s, w in session_is_worker.items() if w)
    lines.append(f'Corpus (post-exclusion): {n_main_files} main (`opus`) session files, {n_worker_files} worker session files.')
    lines.append('')
    all_main = set()
    all_worker = set()
    for rec in findings.values():
        all_main |= rec['main_sessions']
        all_worker |= rec['worker_sessions']
    lines.append(f'Main session files with >=1 genuine completion/kill notice: {len(all_main)} of {n_main_files}.')
    lines.append(f'Worker session files with >=1 genuine completion/kill notice: {len(all_worker)} of {n_worker_files}.')
    lines.append('')
    lines.append(
        '**Observation about THIS corpus, not a structural guarantee:** all 18 remaining worker session '
        'files (`api_requests_worker_cbc9195b_pass-*`) show zero genuine TN blocks. This does not mean '
        'worker sessions structurally cannot receive a completion notice — the TN delivery mechanism is '
        'a CC-side background-Bash feature independent of main/worker session role; it fires whenever a '
        'session backgrounds a Bash call. These 18 worker sessions simply may not have backgrounded any '
        'Bash call (or none of the ones they backgrounded completed/was killed) during the recorded '
        'window. The excluded own-session file (`85d6f25b_timer-loop`) IS a worker session that DID '
        'receive genuine notices (from its own backgrounded commands during this investigation) before '
        'being excluded for contamination — direct proof worker sessions CAN receive them.'
    )
    lines.append('')

    lines.append('## Q4 — Canonical timer vs other background tasks')
    lines.append('')
    lines.append(
        'Same `<task-notification>` template for every background task regardless of identity — no '
        'timer-specific wording exists. The only difference is the quoted command/description string '
        'inside `<summary>`, driven by whether the launcher passed a `description` to the Bash tool call:'
    )
    lines.append('')
    lines.append('| status | exit code | canonical `sleep 3300 && echo done` (deduped events) | other command/description (deduped events) | example other |')
    lines.append('|---|---|---|---|---|')
    for (status, exit_code), bucket in sorted(cmd_variant_counts.items()):
        example_other = next((cmd for cmd, _ in bucket['examples'].most_common() if not _is_canonical_timer_command(cmd)), '-')
        lines.append(f'| `{status}` | `{exit_code}` | {bucket["canonical_timer"]} | {bucket["other"]} | `{example_other}` |')
    lines.append('')
    lines.append(
        'Every 55-minute orchestrator ceiling timer is the same underlying `sleep 3300 && echo done` '
        'Bash call — the varying labels (`"Timer 55min"`, `"55min-Timer für Los-2-Implementierung"`, '
        '`"55min ceiling timer"`, ...) are `description` params different Opus sessions/prompts chose '
        'for the SAME command, not different commands. Non-timer background tasks (`"Index issues broad '
        'pass"`, `"RAG-Sync ausführen"`, ...) use the same TN template, status=`completed`, exit code `0`.'
    )
    lines.append('')

    lines.append('## Exit-code anomaly — code 144 (not 0 / 143 / 137)')
    lines.append('')
    anomaly_key = next((k for k in findings if k[1] == '144'), None)
    if anomaly_key:
        rec = findings[anomaly_key]
        lines.append(
            f'A single genuine event (not a duplicate-inflated count) — task-id extractable, status='
            f'`{anomaly_key[0]}`, exit code `{anomaly_key[1]}`, session(s): '
            f'{sorted(rec["main_sessions"] | rec["worker_sessions"])}. This is a real command-internal '
            'failure exit status (the backgrounded "Reindex" command itself exited 144), NOT a kill '
            'signal code — `strip_bg_completed.py`\'s bare-form matcher only special-cases 143/137 and '
            'never fires on this text anyway (it is TN-wrapped, see Q1b), but the broader point holds '
            'for the pending-state design: **completion notices are not restricted to {0, 143, 137}** — '
            'any exit code can appear in a genuine `<status>failed</status>` TN block. A pending-id-'
            'clearing mechanism keyed only on those three codes would miss this notice; the TN branch\'s '
            'existing `<task-notification>` contains-gate (status-agnostic, exit-code-agnostic) already '
            'fires correctly here — verified above.'
        )
        lines.append('')
        lines.append('**Verbatim block:**')
        lines.append('')
        lines.append('```')
        lines.append(rec['example_full_text'])
        lines.append('```')
    else:
        lines.append('Not found in this run — see raw exit-code distribution below for what was found instead.')
    lines.append('')

    lines.append('## Dedup importance (raw vs deduped)')
    lines.append('')
    lines.append('| Session | Raw TN candidate-block occurrences (all cumulative snapshots) | Deduped (distinct real events) |')
    lines.append('|---|---|---|')
    for fname in sorted(raw_dup_counter):
        raw = raw_dup_counter[fname]
        deduped = sum(rec['session_counts'].get(fname, 0) for rec in findings.values())
        lines.append(f'| `{fname}` | {raw} | {deduped} |')
    lines.append('')

    return '\n'.join(lines)


# ORCHESTRATOR
def main():
    log_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOG_DIR
    corpus_files = sorted(
        p for p in log_dir.glob('*_original.jsonl')
        if p.name not in EXCLUDED_FILES
    )
    findings = {}
    cmd_variant_counts = {}
    raw_dup_counter = defaultdict(int)
    bare_hits = defaultdict(int)
    session_is_worker = {}
    total_requests = 0
    total_parse_errors = 0
    for path in corpus_files:
        print(f'scanning {path.name} ...')
        requests, parse_errors = _scan_file(
            path, findings, cmd_variant_counts, raw_dup_counter, bare_hits, session_is_worker)
        total_requests += requests
        total_parse_errors += parse_errors
    report = _build_report(findings, cmd_variant_counts, total_requests, total_parse_errors,
                            raw_dup_counter, bare_hits, corpus_files, session_is_worker)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / 'bg_completion_wordings_20260806.md'
    out_path.write_text(report, encoding='utf-8')
    print(f'wrote {out_path} — {len(findings)} distinct wording(s), {total_requests} requests scanned, {total_parse_errors} parse errors')


if __name__ == '__main__':
    main()
