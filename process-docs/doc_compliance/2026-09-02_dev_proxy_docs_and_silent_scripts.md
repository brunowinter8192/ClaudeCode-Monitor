# dev/proxy/ gets its DOCS.md — and two scripts turn out to pass on nothing (2026-09-02)

## What was done

`dev/proxy/` held seven scripts and no `DOCS.md`; the gap surfaced while retiring dead verifiers
(see `process-docs/fixture_verification/`). A worker read all seven, ran each where safe, and
wrote `dev/proxy/DOCS.md` with one section per script, LOC values equal to `wc -l`, a Role
paragraph that says when a script belongs here versus `dev/proxy_dual_log/` or
`dev/proxy_instrumentation/`, and a Gotchas section. `dev/DOCS.md` gained index lines for
`proxy/` and for the previously unlisted `proxy_dual_log/`.

## Run results on the merged tree

| Script | Result |
|---|---|
| proxy_bgcomplete_tests.py | 32/32 |
| test_role_keyed_rules.py | 26/26 |
| test_strip_fix.py | 207/207 |
| marker_race_repro.sh | 12/12 |
| replay_sn_notice_strip.py | 0 byte-exact failures over 1683 entries in 17 files |
| replay_strip_v2.py | "ALL PASS" over 0 entries |
| scan_sr_catalog.py | empty catalog over 0 files |

## The finding

`replay_strip_v2.py` and `scan_sr_catalog.py` hardcode the log directory under the project's
old name, `.../ai/Monitor_CC/src/logs`. The directory does not exist. `Path.glob` on a missing
directory yields nothing instead of raising, so both scripts process zero entries and report
success. That is the silent-fallback shape the testing rule adopted the same day names: a branch
that produces output a second way instead of refusing. Both are documented as such in the new
DOCS.md and were not repaired, because repair was outside the documentation task.

Open, not decided here: whether the two scripts get repointed at the current corpus or retired
under the same reasoning as the four verifiers removed the same day. They are one-day replay
proofs of the Phase B template strip, whose evidence sits in `process-docs/proxy_tool_stripping/`.
