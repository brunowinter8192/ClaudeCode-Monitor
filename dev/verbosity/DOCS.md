# dev/verbosity/

## Role
Holds analysis of redundancy in this assistant's own chat output, transferring the
process-efficiency measurement from Chen et al., "Do NOT Think That Much for 2+3=?" from
LLM solution-rounds to Opus turn-exchanges. No producing script: the clustering is a manual,
per-exchange semantic judgment against a fixed criterion (does a later exchange add a
decision-relevant fact not already present in an earlier exchange of the same turn), not a
reusable pipeline — a future pass over new turns would need a fresh manual read, not a
re-run of code.

## Files
- `md/20260827_k2_distinctness.md` — per-turn distinctness table for 126 turns (626
  exchanges) extracted from real session logs, a per-exchange-index aggregate (Chen Figure 6
  analog), and the ten lowest-distinctness turns quoted in full with per-exchange cluster
  labels. States the measured corpus-wide distinctness (0.952) against a pre-registered
  prediction and flags the turns that required a judgment call beyond the stated criterion.
  Section 2a re-runs the position aggregate indexed from the END of each turn instead of the
  start, with the full 30-row list of redundant exchanges (turn, index, end-offset) that both
  distribution tables are computed from — this discriminates a "redundancy grows with depth"
  reading from a "redundancy is a closing-exchange role effect" reading; the probe rules out
  the former (see `process-docs/verbosity/` for the write-up).

## Gotchas
The source transcript (`/tmp/k2_turns.md`) is not checked into this repo — it is a
throwaway extraction of session JSONL data, referenced only by the report. Any future rerun
needs a fresh extraction; the exchange numbering and turn boundaries are not stable across
extractions if the underlying sessions or the extraction script's exchange-detection
threshold change.
