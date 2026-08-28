# Reading Budget — Why the Orchestrator Orders Full Reading Under 400 KB (2026-08-28)

Opening entry of this area. Subject: the orchestrator's bias toward reports over raw
content, the measurements that bound a reading budget, and the rule changes made in the
`GlobalRules` repo (`~/.claude/shared-rules/`) as a result.

## The observed bias

The orchestrator treats worker context as a scarce resource and briefs accordingly. The
chain that produced the problem is not "worker reads, Opus summarises" — it is worse: the
worker is told to produce a report, and it builds that report from grep hits and aggregate
counts. Nobody in the chain ever reads the raw material. The orchestrator then reads a
summary of a summary that never rested on a reading.

The asymmetry that once justified the frugality is gone. The cross-worker persistence
model (see `process-docs/worker_orchestration/`) argued in 2026-06 that Opus is the memory
layer because Opus has ~1M context while a worker has 200k. The worker window was raised
to 1M in 2026-07 (same area). Worker capacity grew fivefold; briefing habits did not.

The decision itself still stands — Opus holds the report. Only its capacity argument no
longer applies, so it cannot be used to justify short reading in worker prompts.

## Where the bias sat in the rules

Four rule files carried it, none of them alone:

- `global/tool-use.md` prescribed routing verbose output to a `/tmp` file and pulling only
  `grep`/`tail` lines back, with a `tail -20` example. Correct for operational noise,
  wrong for content under judgement — the file did not separate the two cases.
- `worker/verification.md` defined four verification levels (pure-function guard,
  integration, entry-point, user visual check). All four prove that code runs; none
  expresses a judgement about content. For stripped or transformed text the worker had no
  applicable category and had to fall back on counting.
- `worker/worker-rules.md` permits wide reading ("read as much as you need") but requires
  none. Under throughput pressure the worker decides what "need" means.
- `opus/workers.md` had no reading instruction in the dispatch path at all.

## Measurements the threshold rests on

**Worker context window.** The fleet runs uniformly on 1M-context models; the
`_WORKER_CONTEXT_WINDOW` constant is 1000000. Before the CC pin to 2.1.205 (2026-07-20),
CC 2.1.176 capped `claude-sonnet-5` client-side at 200k because its internal window table
predated the model. Details in `process-docs/worker_orchestration/`.

**Characters per token.** Measured on our own payloads: a known prefix of 154,550 chars
became 41,975 tokens, i.e. 3.68 chars/token; the full-rebuild ratio is 3.42 (stddev 0.11,
N=3), stable at 3.4–3.7 across sessions without interleaved thinking. `tiktoken
cl100k_base` underestimates Claude by 35–75% and is unusable. A 1M window therefore holds
roughly 3.4–3.7 MB of raw text. Caveat: measured on Opus payload, prefix-dominated; the
per-model difference is unresolved and the work is parked (see `process-docs/tokenizer/`).

**Observed worker death and observed care collapse.** From the rag-cli project's eval-suite
process history (four-pass paper segmentation, 20 documents, claude-sonnet-5 workers):

- A Pass C worker died after 19 documents and ~1425 KB of source read. A Pass D worker
  died at 17 documents; three artifacts were never backfilled. Effective context load was
  estimated at 2–3x source KB.
- Quality collapsed far earlier, at ~400 KB cumulative. The worker switched from
  line-by-line reading to a heading-grep shortcut and documented the reason as "too slow
  at batch scale". That was throughput pressure, not context exhaustion.
- Position analysis of the degraded output clusters late (cumulative 1.0–1.3 MB); nothing
  in that run suggests trustworthy work beyond ~1 MB.
- The lot size adopted there was 150 KB of source text per worker.
- Document sizes in that batch spanned 38–140 KB (factor 3.7), which is why the unit is KB
  of source and not document count.

**Consistency cross-check.** 1425 KB at 3.68 chars/token is ~387k tokens; with the 2–3x
overhead estimate that is 775k–1.16M tokens. The observed death therefore brackets the 1M
ceiling. The chars/token estimate and the observed death corroborate each other, which is
what makes the KB figures usable outside their original project.

## Decision

**400 KB of source material is the threshold, and it lives at the orchestrator.**

400 KB was chosen over 150 KB and over 1 MB because it is the only one of the three that
is a *measured* boundary of worker care rather than an adopted operating margin (150 KB) or
an extrapolated ceiling (1 MB). Below it, reading in full was observed to hold; at it,
reading was observed to break down.

In tokens the threshold is ~109k, about 11% of the 1M worker window. Even the hard ceiling
of 1 MB would use only about a quarter of it. The budget is therefore generous relative to
prior briefing practice and still conservative relative to capacity.

The rule sits at the orchestrator, not at the worker, because the orchestrator's prompt
determines the worker's behaviour. A worker told to write a report writes a report. Adding
a reading obligation to the worker rules would be overridden by the next prompt that asks
for a report.

## Rule changes made

In `~/.claude/shared-rules/` (repo `GlobalRules`):

1. `global/tool-use.md` — the "Verbose output" section removed without replacement. What
   remains uncontradicted is "Grep for patterns, Read for meaning" and the rule that a
   `<persisted-output>` block is always read in full.
2. `opus/workers.md` — new "Reading Budget" section under "While Workers Run": under
   400 KB the prompt names the files and orders complete reading; grep, sampling, head and
   tail are named as unacceptable substitutes; the worker returns its judgement and what it
   read, never an aggregate count; the estimate is made in KB because file count says
   nothing (twenty source files can be 40 KB, one log line can be 100 KB).
3. `worker/verification.md` — moved to `situational/verification.md` and removed from the
   `system2_rules.worker.files` list in `proxy_rules.json`, so it is no longer injected.
   Rationale: the orchestrator prescribes the verification form per task anyway, so the
   injected level table cost context without steering behaviour.

Verification of change 3: a script parsed `proxy_rules.json` and resolved all eight listed
rule paths against disk — all present, no dangling entry. Changes 1 and 2 are text edits,
verified by reading the resulting files. None of the three is behaviourally verified,
because rules are injected at session start and the editing session ran under the old set.

## Rejected during the discussion

- **Adding a "read and judge" level to `worker/verification.md`.** Rejected together with
  the file itself — a fifth level in a table nobody consults does not change behaviour.
- **Putting the reading budget in `worker/worker-rules.md`.** Rejected because the
  orchestrator's prompt overrides the worker's defaults.
- **A dispatch-table field naming what must be read in full.** Rejected as redundant once
  the reading order sits in the rule.
- **Motivational framing in the rule text** ("worker context is disposable", "the prompt's
  verb decides the outcome", lot-splitting above the threshold). Cut to keep the rule to
  the one actionable block.

## Open threads

- **Transferability of 400 KB.** The figure comes from a segmentation task with four
  writing passes. A read-and-judge task writes far less per KB read, so its care curve may
  differ. Closing this needs a dev/ probe against real logs, not an argument.
- **Reach errors.** Two failures observed on 2026-08-28 were neither reasoning errors nor
  reading errors but scope errors: a grep over two files was correct and incomplete, and a
  test run against the installed plugin cache was correct and aimed at the wrong code
  state. In both cases the missing step was establishing whether the excerpt was the whole.
  No rule requires proving the boundary of a search. Deliberately left out of this round.
- **Per-model chars/token.** The 3.68 anchor is Opus-measured. Sonnet's ratio is unknown
  and the measurement path is blocked for Max subscriptions (`process-docs/tokenizer/`).
