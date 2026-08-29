# External-Reading Surface for Workers — Decision (2026-08-29)

## Question

How much orchestrator-procured external material may a worker read directly from
disk by path, before the hand-over stops being "paths to procured material" and
becomes "the worker doing the orchestrator's research on disk"?

## Observed Case (2026-08)

A calibration milestone prompt handed the worker, as absolute paths:

- 27 captured vendor-doc pages plus 2 GitHub READMEs in the RAG documents dir
- the installed package source in the venv
- repo-internal process-docs and src paths
- an orchestrator-distilled prompt block for RAG-only content (Reddit)

This was rules-conform (worker reads only what the orchestrator hands over, no
searching), but the volume of direct external reading per prompt raised the
question whether volume limits, distillation requirements, or per-class rules
(files-on-disk vs prompt-distillation vs own measurements) should constrain it.

## Decision

As of 2026-08-29, no separate hand-over constraint is adopted. The reading-budget
rule in the workers rule set settles the volume question: under 400 KB of
estimated material, the prompt orders full reading of every named file; grep,
sampling, head, and tail are not acceptable substitutes there.

Consequences:

- The line is drawn by the KB budget, not by material class. Files-on-disk,
  procured external captures, and repo-internal paths are treated identically.
- No distillation requirement for on-disk material. Distillation stays mandatory
  only for content the worker cannot reach on disk (e.g. RAG-only sources),
  which the orchestrator distills into the prompt.
- No per-prompt cap on the number of handed-over paths.

## Rationale

- The worker's independent full read of handed material is what makes the
  cross-model check work; orchestrator distillation of on-disk material would
  replace that independent read with a second-hand summary and lose fidelity.
- Volume was the only real risk in the observed case, and the 400 KB budget
  already bounds it explicitly at prompt-writing time.
- Per-class rules would add maintenance surface without changing behavior: every
  class in the observed case was already either on disk (pass paths) or RAG-only
  (distill), and the existing hand-over rule covers both.
