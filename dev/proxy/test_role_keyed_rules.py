#!/usr/bin/env python3
"""Unit tests for ROLE-keyed system2 rule selection (rules_config._load_system2_rules).

Selection is keyed off the session role carried in worker_context ("worker:<name>" from a
worker-cli spawn, "main" otherwise), NOT off the model family — model and role became
independent when the menubar Models tab started assigning main/worker models separately.
model_family retains exactly one job: the haiku short-circuit.

Coverage:
  - role selection: main / worker:<name> / "" / None / non-worker-prefixed junk
  - the actual regression: opus-family worker gets WORKER files, sonnet-family main gets MAIN files
  - haiku short-circuit wins over both roles (haiku sidecars live inside main sessions)
  - degraded configs: missing "main" key, missing "worker" key, missing system2_rules entirely,
    missing rule file on disk — global-only / empty, never a crash
  - no legacy "opus" key fallback (one-shot migration by design)
  - exclude_projects (untouched feature) still suppresses under both roles
  - end-to-end through rules.apply_modification_rules: the selected text lands in system[2]

Isolation: builds a synthetic shared-rules tree in a temp dir and repoints the module globals
_SHARED_RULES_DIR / _PROXY_RULES_CONFIG at it (both are read at call time). The real
~/.claude/shared-rules/ is never read or written by this test.

Imports the live proxy modules via the src/-on-sys.path form used by the other dev/ probes.

Run: ./venv/bin/python dev/proxy/test_role_keyed_rules.py
"""
import sys, os, json, shutil, tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('MONITOR_CC_ROOT', str(_ROOT))
sys.path.insert(0, str(_ROOT / 'src'))

from proxy import rules_config
from proxy.rules_config import _load_system2_rules
from proxy.rules import apply_modification_rules

PASS = []
FAIL = []


def check(name, condition, msg=''):
    if condition:
        PASS.append(name)
        print(f'  PASS  {name}')
    else:
        FAIL.append(name)
        print(f'  FAIL  {name}' + (f': {msg}' if msg else ''))


# ── SYNTHETIC SHARED-RULES TREE ──────────────────────────────────────────────

# Rule file contents — distinct per file so a concatenation identifies its exact members
_FILES = {
    'global/g1.md': 'GLOBAL-ONE',
    'global/g2.md': 'GLOBAL-TWO',
    'main/m1.md': 'MAIN-ONE',
    'main/m2.md': 'MAIN-TWO',
    'worker/w1.md': 'WORKER-ONE',
    'opus/o1.md': 'LEGACY-OPUS-ONE',
}

GLOBAL_TEXT = 'GLOBAL-ONE\n\nGLOBAL-TWO'
MAIN_TEXT = GLOBAL_TEXT + '\n\nMAIN-ONE\n\nMAIN-TWO'
WORKER_TEXT = GLOBAL_TEXT + '\n\nWORKER-ONE'

_FULL_CONFIG = {
    'system2_rules': {
        'global': {'files': ['global/g1.md', 'global/g2.md']},
        'main': {'files': ['main/m1.md', 'main/m2.md']},
        'worker': {'files': ['worker/w1.md']},
        'opus': {'files': ['opus/o1.md']},   # legacy key — must be ignored, no fallback
        'projects': {},
        'exclude_projects': [],
    }
}


# Materialize the synthetic rules tree and point the module globals at it
def install_config(config: dict) -> None:
    for rel, body in _FILES.items():
        p = TMP / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding='utf-8')
    (TMP / 'proxy_rules.json').write_text(json.dumps(config), encoding='utf-8')
    rules_config._SHARED_RULES_DIR = TMP
    rules_config._PROXY_RULES_CONFIG = TMP / 'proxy_rules.json'
    # mtime resolution is coarser than the test's write cadence — clear both caches so a
    # rewritten config/file is never served from the previous case's entry.
    rules_config._config_cache[0] = None
    rules_config._file_cache.clear()


# Minimal payload with a 4-block system array — system[2] is the rule-injection slot
def mk_payload() -> dict:
    return {
        'model': 'claude-opus-4-6',
        'system': [
            {'type': 'text', 'text': 'block0'},
            {'type': 'text', 'text': "You are Claude Code, Anthropic's official CLI for Claude."},
            {'type': 'text', 'text': 'ORIGINAL-SYS2'},
            {'type': 'text', 'text': 'block3'},
        ],
        'messages': [{'role': 'user', 'content': 'hello'}],
        'tools': [],
    }


TMP = Path(tempfile.mkdtemp(prefix='role_rules_test_'))

try:
    # ── ROLE SELECTION ───────────────────────────────────────────────────────
    print('\n[Role selection]')
    install_config(_FULL_CONFIG)

    check('main context -> global + main',
          _load_system2_rules('opus', '', 'main') == MAIN_TEXT,
          repr(_load_system2_rules('opus', '', 'main')))
    check('worker:<name> context -> global + worker',
          _load_system2_rules('opus', '', 'worker:rule-injection') == WORKER_TEXT,
          repr(_load_system2_rules('opus', '', 'worker:rule-injection')))
    check('worker name with underscores still matches prefix',
          _load_system2_rules('sonnet', '', 'worker:rule_injection_2') == WORKER_TEXT)
    check('empty context -> main (documented default)',
          _load_system2_rules('opus', '', '') == MAIN_TEXT)
    check('omitted context (3-arg call) -> main',
          _load_system2_rules('opus', '') == MAIN_TEXT)
    check('None context -> main, no crash (tt_delta_skip_replay passes None)',
          _load_system2_rules('opus', '', None) == MAIN_TEXT)
    check('non-worker junk context -> main',
          _load_system2_rules('opus', '', 'workerish') == MAIN_TEXT)

    # ── THE REGRESSION: MODEL FAMILY NO LONGER DECIDES ───────────────────────
    print('\n[Model family is not the key]')
    check('opus-family WORKER gets worker rules (the bug this fixes)',
          _load_system2_rules('opus', '', 'worker:w1') == WORKER_TEXT)
    check('sonnet-family MAIN gets main rules (inverse of the bug)',
          _load_system2_rules('sonnet', '', 'main') == MAIN_TEXT)
    check('legacy "opus" config key is never read (no fallback)',
          'LEGACY-OPUS-ONE' not in _load_system2_rules('opus', '', 'main'))

    # ── HAIKU SHORT-CIRCUIT ──────────────────────────────────────────────────
    print('\n[Haiku short-circuit]')
    check('haiku + main context -> empty', _load_system2_rules('haiku', '', 'main') == '')
    check('haiku + worker context -> empty', _load_system2_rules('haiku', '', 'worker:w1') == '')
    check('haiku + absent context -> empty', _load_system2_rules('haiku', '') == '')

    # ── DEGRADED CONFIGS ─────────────────────────────────────────────────────
    print('\n[Degraded configs]')
    no_main = {'system2_rules': {'global': {'files': ['global/g1.md', 'global/g2.md']},
                                 'worker': {'files': ['worker/w1.md']}}}
    install_config(no_main)
    check('config without "main" key -> global files only, no crash',
          _load_system2_rules('opus', '', 'main') == GLOBAL_TEXT,
          repr(_load_system2_rules('opus', '', 'main')))
    check('config without "main" key -> worker role unaffected',
          _load_system2_rules('opus', '', 'worker:w1') == WORKER_TEXT)

    no_worker = {'system2_rules': {'global': {'files': ['global/g1.md']},
                                   'main': {'files': ['main/m1.md']}}}
    install_config(no_worker)
    check('config without "worker" key -> global files only for a worker',
          _load_system2_rules('opus', '', 'worker:w1') == 'GLOBAL-ONE')

    install_config({})
    check('config without system2_rules at all -> empty, no crash',
          _load_system2_rules('opus', '', 'main') == '')

    missing_file = {'system2_rules': {'global': {'files': ['global/g1.md', 'global/nope.md']},
                                      'main': {'files': ['main/m1.md']}}}
    install_config(missing_file)
    check('missing rule file on disk is skipped, rest still concatenated',
          _load_system2_rules('opus', '', 'main') == 'GLOBAL-ONE\n\nMAIN-ONE')

    # ── UNTOUCHED FEATURE: exclude_projects ──────────────────────────────────
    print('\n[exclude_projects still works under both roles]')
    excl = json.loads(json.dumps(_FULL_CONFIG))
    excl['system2_rules']['exclude_projects'] = ['/tmp/excluded_proj']
    install_config(excl)
    check('excluded project -> empty for main',
          _load_system2_rules('opus', '/tmp/excluded_proj/sub', 'main') == '')
    check('excluded project -> empty for worker',
          _load_system2_rules('opus', '/tmp/excluded_proj/sub', 'worker:w1') == '')
    check('non-excluded project unaffected',
          _load_system2_rules('opus', '/tmp/other_proj', 'main') == MAIN_TEXT)

    # ── END-TO-END THROUGH apply_modification_rules ──────────────────────────
    print('\n[End-to-end via apply_modification_rules -> system[2]]')
    install_config(_FULL_CONFIG)

    mod, *_ = apply_modification_rules(mk_payload(), 'opus', '', 'main')
    check('e2e: main context lands main rules in system[2]',
          mod['system'][2]['text'] == MAIN_TEXT, repr(mod['system'][2]['text']))

    mod, *_ = apply_modification_rules(mk_payload(), 'opus', '', 'worker:rule-injection')
    check('e2e: worker context lands worker rules in system[2] on an OPUS-family request',
          mod['system'][2]['text'] == WORKER_TEXT, repr(mod['system'][2]['text']))

    mod, *_ = apply_modification_rules(mk_payload(), 'sonnet', '', 'main')
    check('e2e: main context on a SONNET-family request still lands main rules',
          mod['system'][2]['text'] == MAIN_TEXT, repr(mod['system'][2]['text']))

    mod, *_ = apply_modification_rules(mk_payload(), 'haiku', '', 'main')
    check('e2e: haiku inside a main session lands "." in system[2]',
          mod['system'][2]['text'] == '.', repr(mod['system'][2]['text']))

    mod, *_ = apply_modification_rules(mk_payload(), 'opus', '')
    check('e2e: caller omitting worker_context lands main rules',
          mod['system'][2]['text'] == MAIN_TEXT)

finally:
    shutil.rmtree(TMP, ignore_errors=True)

total = len(PASS) + len(FAIL)
print(f'\n{len(PASS)}/{total} passed')
if FAIL:
    print('FAILED: ' + ', '.join(FAIL))
    sys.exit(1)
print('ALL PASS')
