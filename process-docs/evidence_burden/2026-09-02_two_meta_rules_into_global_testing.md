# Evidence burden — two interlocking meta rules moved into the global testing rule

**Date**: 2026-09-02
**Files changed**: `shared-rules/global/testing.md`, `shared-rules/worker/dev-convention.md`,
`shared-rules/worker/code-standards.md`, `iterative-dev/skills/iterative-dev-refactor/SKILL.md`

## Starting point

Three goals were on the table: complexity in production traces back to a failure observed in real
data (a fixture written by whoever demands the defence does not count); a defence carries a
measured cost and risk, so a measured loss is never traded for a hypothetical one; a demand for
proof names a finite, decidable body of evidence.

Reading the worker rules and the refactor skill against those goals showed the underlying
structure is two meta rules that interlock:

1. **No fallbacks, fail loud on edge cases.** Existed only inside the refactor skill (fallback vs
   tripwire classifying question, one-way redesign), i.e. as an after-the-fact scan. The worker
   code-standards even contradicted it: an Error Handling table allowed "graceful degradation with
   explicit logging" and "retry with backoff" next to a "fail fast" core rule.
2. **No arming against edge cases nobody has observed.** Existed nowhere as a rule. Only implicit
   in the skill's demand for proof over a real corpus.

The interlock: a fallback is code for a case nobody saw in real data. Rule 2 removes that code
before it is written; rule 1 turns whatever remains into a tripwire. Without rule 2 every defence
wins the argument, because a hypothetical failure cannot be refuted. The mechanism by which the
pattern slips in: a feature is implemented, the implementer invents a "belt and braces" test case,
and the test case then legitimises a fallback for a case that exists only because the implementer
imagined it.

## Fresh evidence from the same day

A staging fix in the gcommit tool (see `process-docs/git_automation/` in the iterative-dev repo)
had been reviewed and merged a few hours earlier. It contained exactly the pattern: a post-hoc
index check after a successful `git add`, described by the implementer as "belt-and-braces against
any other silent-no-op path", plus a `chmod 000` fixture invented to exercise it. Neither the case
nor the fixture came from an observation. The review waved it through. A separate part of the
same fix (prefix matching for directory entries) had come from a measurement and was legitimate.
The two sat side by side in one diff, which is why a scan after the fact is not enough.

## Decision

- **One home for tests, dev/, evidence burden, and fallback/tripwire: `global/testing.md`.**
  Chosen over a separate global rule file because it is all one substance: what gets tested
  decides what gets defended, and what gets defended decides what gets built.
- **Tests cover milestone functionality only.** An edge case nobody observed gets no test; an
  invented test case is not an observation.
- **dev/ placement criteria (permanent value, zero-context question) moved from the worker
  convention into the global rule**, because they bind the orchestrator equally. The worker file
  keeps output layout and staging only. The example tables that sat next to the criteria were
  dropped rather than moved.
- **Rule text carries no examples and no explanations.** Positive and negative examples, and
  "because" clauses, were stripped from the new sections before they landed; the rule states the
  sentence and stops. Reasoning lives here, in process-docs, not in the rule.
- **Error Handling table deleted from the worker code-standards.** "Fail fast and let exceptions
  fly" stays, because that one is code-level.
- **Definition lives in the rule, the skill points at it.** The refactor skill keeps the scan
  passes and the one-way-redesign procedure, and references the rule for the classifying question
  and the pillars. Global rules load in every session, so the skill loses nothing, and there is
  one text to maintain.

Not touched: the orchestrator's workers.md review steps. The global rule binds the reviewer
already; a duplicate line there would be the kind of redundancy the rule argues against.
