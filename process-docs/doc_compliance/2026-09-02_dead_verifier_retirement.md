# Dead dev/ Verifier Retirement (2026-09-02)

Four `dev/` verifiers were removed because they can no longer run and their coverage is already
replaced by other scripts. This is a targeted retirement, not a general sweep — only these four
files were in scope.

## Removed

- `dev/proxy_dual_log/verify_strip_inject.py` (346 LOC) — raised `KeyError: 'spans'` because
  `_diff_messages` stopped emitting a `spans` key once the ops / `compose_block` architecture
  replaced it, and separately called `_build_stripped_injected_deltas` without `all_ops`, making
  its message-level delta coverage vacuous even if the KeyError were fixed. Its BROKEN status
  and both root causes were already recorded in `dev/proxy_dual_log/DOCS.md` before this pass;
  `dev/proxy_dual_log/tt_delta_skip_replay.py` is the replacement — it feeds real ops and
  exercises the message delta path end to end, which `verify_strip_inject.py` structurally could
  not.
- `dev/proxy_instrumentation/p2_badge_words_probe.py` (109 LOC) and
  `dev/proxy_instrumentation/p3_badge_inline_probe.py` (244 LOC) — both load recorded dual-log
  sessions (`api_requests_opus_monitor_cc_*`, `api_requests_opus_websearch_1786052022`) that no
  longer exist on disk; recorded dual-logs are untracked data, not repo content, so their absence
  is not a bug to fix. `p3`'s DOCS.md entry additionally noted two of its six cases were already
  obsolete as of 2026-08-30 (asserting a prepend mechanism removed that day).
- `dev/proxy/test_schema_check.py` (108 LOC) — imported `_check_payload_schema` from
  `src/proxy/schema_check.py`, a module deliberately deleted from `src/`. No DOCS.md existed for
  `dev/proxy/` (confirmed via `dev/DOCS.md`'s index, which has no `proxy/` entry), so nothing
  needed unlisting there.

## Reference cleanup

Grep for each filename across `dev/` and `src/` (`*.py` + `*.md`) before the change surfaced:
- `dev/proxy_dual_log/DOCS.md` — module heading + usage block for `verify_strip_inject.py`
  (removed).
- `dev/proxy_instrumentation/DOCS.md` — module headings for `p2_badge_words_probe.py` and
  `p3_badge_inline_probe.py` (removed).
- `src/proxy/DOCS.md` — the `diff_engine.py` entry's "Called by" line listed
  `dev/proxy_dual_log/verify_strip_inject.py` alongside `dev/proxy_dual_log/diff_strip_inject.py`
  as callers via `sys.path.insert` + `from src.proxy.diff_engine import ...`. Since
  `strip_inject_delta.py` and `diff_strip_inject.py` remain real callers, this was a one-line
  edit, not a dead-code flag. The Purpose line's mention of
  `dev/proxy_dual_log/ (offline verification scripts)` stayed, because `diff_strip_inject.py`
  still lives there and still qualifies.
- `dev/proxy_dual_log/tt_delta_skip_replay.py` — its own docstring names all three retired
  `proxy_dual_log`/`proxy_instrumentation` scripts by name as the rationale for why it exists
  (a dedicated replay was needed because those scripts were structurally blind or unrunnable).
  Left untouched: this is a self-contained explanatory reference, not an import, invocation, or
  DOCS.md listing of a still-available tool.
- `dev/tool_use_analysis/md/20260419_baseline.md` — mentions `test_schema_check.py` as captured
  content unrelated to this retirement (a historical report, not a listing). Left untouched, same
  as the write-once handling of captured forensic records elsewhere in `dev/`.

Post-change grep for `import <name>` / `from <name>` across `dev/` and `src/` `*.py` returned zero
hits for all four retired filenames — nothing imports or invokes them.

## Verification

`./venv/bin/python dev/proxy_dual_log/test_composition_invariant.py` — the composition-invariant
regression guard adjacent to the retired `verify_strip_inject.py` — still reports
`12/12 checks passed`, `entries=9 blocks_checked=11 blocks_passed=11`, `ALL PASS`, confirming the
retirement did not touch anything the invariant suite depends on.

## Kept in place

Report files under `dev/proxy_dual_log/md/` and `dev/proxy_instrumentation/md/` produced by the
retired scripts were not touched — they are historical records, same as any other captured `md/`
output in this codebase.
