# block_dev_imports_src.py: Regression-Suite Exemption (2026-08-28)

## Context

`block_dev_imports_src.py` blocked `Write`/`Edit` calls to any file under a `/dev/` path
whose content imports from `src.`, on the rationale that `dev/` modules are self-contained
pipeline probes — importing from `src/` breaks that isolation. The rule identified a probe
purely by the presence of a `/dev/` path segment.

This broke in a different project (`websearch`), which keeps its pytest regression suite in
`dev/tests/`. A regression suite is the categorical opposite of a probe: it exists specifically
to import and exercise the live `src/` tree. 16 of 18 files already committed under
`websearch/dev/tests/` import from `src.`, and that directory's own DOCS.md documents it as
regression coverage for `src/search/`, `src/scraper/`, and `src/crawler/`. The hook was about
to block the 17th such file from ever being written. `monitor-cc` itself has no `dev/tests/`
directory, which is why the gap never surfaced locally.

## Signal Considered and Rejected

- **Literal `dev/tests` string match.** Rejected outright — reintroduces the exact
  project-specific assumption (one project's directory name) that caused the bug in the first
  place. Would not generalize to a differently-named test directory in a third project.
- **Filename-only** (`test_*.py` anywhere under `dev/`). Rejected — too broad. A probe script
  could be renamed `test_probe.py` without any structural change and slip past the block while
  remaining exactly the non-isolated probe the hook exists to catch.
- **Directory-only** (any file under a `tests/` segment). Rejected — too broad in the other
  direction. A non-test helper module (e.g. a shared fixture builder) dropped into a `tests/`
  directory would get a free pass to import `src.` without actually being a pytest-collected
  test.
- **Reading external files (DOCS.md prose, `pytest.ini` testpaths) at hook time.** Rejected —
  adds filesystem I/O beyond the stdin payload the hook already receives, is fragile for a
  brand-new file that predates its own DOCS.md entry, and breaks the pure-stdin design every
  sibling hook in `src/hooks/` follows.

## Chosen Signal

Two conditions, both required:
1. The file path contains a `/tests/` directory segment.
2. The filename matches pytest's own default discovery convention: `test_*.py`, `*_test.py`,
   or `conftest.py`.

Both conditions key off pytest's own conventions rather than any one project's layout, so the
fix generalizes beyond `websearch`. Requiring both closes the two single-signal holes above:
a bare `tests/` dir alone doesn't exempt a stray probe dropped there, and pytest-shaped naming
alone doesn't exempt a renamed probe living outside an actual test directory.

## Verification

Executed the real hook script (`python3 src/hooks/block_dev_imports_src.py`) with real JSON
payloads on stdin, reading the real exit code — entry-point-level verification, since the
script IS the CC-invoked entry point:

- `Write` to `dev/tests/test_new_case.py` importing `src.` → exit 0 (now passes).
- `Edit` inserting a `src.` import into `dev/tests/test_existing.py` → exit 0 (now passes).
- `Write` to `dev/some_area/01_probe.py` importing `src.` → exit 2 (still blocked).
- Malformed JSON payload → exit 0 (fail-open unchanged).
- Bypass check: `Write` to `dev/tests/helper.py` (non-`test_`-named, bare `tests/` dir)
  importing `src.` → exit 2 (still blocked — confirms the directory-only hole is closed).
- Bypass check: `Write` to `dev/probe_area/test_probe.py` (`test_`-named, no `tests/` dir)
  importing `src.` → exit 2 (still blocked — confirms the filename-only hole is closed).
- Regression: ordinary probe with no `src.` import → exit 0 (baseline unchanged).
- Regression: non-`dev/` path importing `src.` → exit 0 (out of scope, unchanged).

## Outcome

`_parse_targets()`, the fail-open exception handling, and the Write/Edit-only tool scoping were
left untouched. The only behavioral change is the new early-exit branch
(`_is_regression_test_file()`) inserted between the existing `/dev/` gate and the existing
`_SRC_IMPORT` check. `src/hooks/DOCS.md` was updated in the same commit to document the
exemption and its two conditions.
