# 2026-08-29 — Global testing rule replaces scattered verification fragments

## Context

Testing and verification guidance was scattered across the shared rule files: a debug-loop stop section in the worker rules, deliverable-verification bullets plus a mandatory sample-test block in the orchestrator workflow, and a dev-convention table that declared live-verification of a source fix the standard loop. Live targets as test environments had repeatedly produced undecidable outcomes: a deviation could mean a bug or a changed world, and the two are indistinguishable.

## Decisions (as of 2026-08-29)

- All testing/verification material was extracted from the worker and orchestrator rule files and rebuilt as one short global file, `shared-rules/global/testing.md`, injected for orchestrator and workers alike via the system2 rules manifest.
- A test is defined by controllability: it depends only on factors the agent controls, and repeating it 10 or 100 times, or in a month or a year, produces the same result.
- Test trigger: exactly when an implementation causes a behavior change (A → A.1 or B). The test shows the new behavior should match the specification.
- Regression without a suite: dev/ directories are grown probe collections without a runnable red/green suite (websearch `dev/` served as the reference example), and a maintained suite was rejected because it would itself need maintenance and invite drift. Instead, each change's test weaves in a caller check: callers of the changed code, found via import grep and the DOCS.md maps, must behave as before. A broken caller is a caused behavior change and belongs to the task.
- Verification is distinct from testing: it matches the prod environment exactly and runs once, when tests no longer yield any gain in insight. A failed verification returns to the implementation change, then re-test and re-verify. A second failed verification stops all actions immediately and is reported.
- The concrete fixture-site mechanics (authored page counts, sitemap nesting, robots rules, known orphans and error modes) were generalized away: a fixture is one means of achieving controllable factors, not a rule-level requirement.
- The worker debug-loop stop section was removed in the extraction and is not yet rebuilt; that thread continues under `process-docs/escalation_thresholds/`.

## Removed material

The verbatim pre-extraction text of all removed blocks is preserved in the shared-rules git history at the extraction commit; a working copy existed at `/tmp/testing-extraction.md` during the session. A previously existing `worker/verification.md` (verification levels, honest reporting) had already moved to `situational/verification.md` and stays outside the default injection; it complements the new rule by governing reporting rather than timing.
