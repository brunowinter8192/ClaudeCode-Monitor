# Retire over repair — why the four dead verifiers were removed, not fixed (2026-09-02)

The companion entry of the same date in this area records what was removed and how references
were cleaned. This entry records the decision.

## Starting point

Three goals had been set on 2026-08-29: make `verify_strip_inject.py` run green on a current log
pair, make the two badge probes run against fixtures on disk or retire them, and make
`test_schema_check.py` import and pass. All four were reproduced failing on the current tree the
same way the 2026-07-30 and 2026-08-29 entries in `process-docs/proxy_tool_stripping/` and
`process-docs/bg_wakeup_id_line/` had already noted: `KeyError: 'spans'`, two
`FileNotFoundError`/`AssertionError` on missing sessions, one `ImportError` on a deliberately
deleted module.

## Why retire

Two rules adopted or sharpened the same day decided it (`shared-rules/global/testing.md`, derived
in `process-docs/evidence_burden/`):

- A dev script earns its place only if it is useful to an agent with zero context. A script that
  aborts on load gives that agent an error and a riddle, and each of the three earlier entries
  that "confirmed failing on an unmodified tree, left untouched" was cost paid only because the
  file still existed.
- A test is due exactly when an implementation changes behavior, and complexity in production
  traces back to an observed failure. Repairing `verify_strip_inject.py` would build a test for a
  failure nobody has seen since its live run in 2026-06.

Per file:

- `verify_strip_inject.py` was the completeness proof of an architecture that no longer exists.
  Its span-reconstruction check is carried today by `test_composition_invariant.py` (12/12 on the
  merged tree) and by `tt_delta_skip_replay.py`, which drives the real pipeline over the grown
  log. Its field-coverage and model cross-check have no successor; that gap is accepted, because
  no `fields_delta` failure has been observed since the June live verification.
- `p2` and `p3` were one-day verifications of one fix each against one recorded session. Their
  evidence lives in the dated entries of `process-docs/proxy_instrumentation/` with the tables
  and numbers. The regression case that mattered was folded into `dev/proxy/test_strip_fix.py`
  (TT09) on 2026-08-29. Two of p3's six cases were obsolete since 2026-08-30 regardless.
- `test_schema_check.py` tested `_check_payload_schema`, deleted with `schema_check.py` in the
  Stage 3 proxy cleanup with zero callers. A test for a removed function has no subject.

The user's addition on top: dev probes should also work without depending on recorded `src/logs`
data, which is the property all three runnable-fixture failures lacked.

## Side finding, not acted on

`dev/proxy/` holds eight scripts and no `DOCS.md`. Doc drift outside this thread.
