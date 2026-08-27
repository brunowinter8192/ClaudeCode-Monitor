# 2026-08-27 — K2 turn distinctness: process-efficiency measured, position hypothesis discarded

## What was measured

Chen et al., "Do NOT Think That Much for 2+3=?", measures process efficiency in LLM
reasoning: within one response, cluster the produced solutions by strategy, and score each
solution as distinct only if its strategy is not already present among the preceding
solutions of the same response. This session transferred that measurement to this
assistant's own chat output, treating one turn's numbered exchanges as the analog of Chen's
solution rounds. 126 turns (626 exchanges) were extracted from real Claude Code session logs
of this project and hand-clustered against a single criterion: a later exchange counts as
distinct only if a reader who already read the earlier exchanges of the same turn learns a
new decision-relevant fact from it; rephrasing, restating a conclusion, or re-listing
something already listed does not. The clustering was a manual per-exchange read against
that criterion, not a script — there is no reusable pipeline behind the numbers, only the
full report at `dev/verbosity/md/20260827_k2_distinctness.md`, which carries the complete
per-turn table, the per-exchange-index aggregate, and the ten lowest-distinctness turns
quoted in full with cluster labels.

## Finding 1: redundancy is the exception, at 0.952 corpus-wide

Of 626 exchanges, 596 were distinct (596/626 = 0.952). 99 of 126 turns (78.6%) carry zero
redundancy at all (ratio 1.000). Of the 27 turns that do carry an echo, 24 carry exactly one
and only three (turns 112, 114, 116) carry two. The lowest ratio in the corpus is turn 112 at
0.500 (2 clusters over 4 exchanges); no turn falls below that. A distinctness estimate of
0.85–0.95 was stated before any turn was labeled; the measured value lands just outside that
range, above the upper bound by 0.002 — the corpus is marginally less redundant than
predicted, not more.

## Finding 2: redundancy concentrates on the closing exchange's ROLE, not on late position

A first pass indexed distinctness by absolute position from the start of each turn (Chen's
Figure 6 analog). That view showed a dip at indices 5–6 (0.793 / 0.786, against 1.000 at
indices 0–3) with partial recovery at indices 7–8 (0.900 / 0.833) — a shape consistent with
"redundancy grows the deeper into a turn you go." It is equally consistent with a second,
untested explanation: the redundant exchange is specifically the closing decision-question or
closing doubts-recap — the LAST or second-to-last exchange of a turn — and its start-index is
simply a function of turn length, since most turns in this corpus run 4–8 exchanges and their
endings land in exactly that index range either way. The two readings are indistinguishable
from the start-indexed aggregate alone.

**The position reading was discarded by a probe, not by argument.** All 30 redundant
exchanges were re-indexed by their offset from the end of their own turn (offset 0 = last
exchange, offset 1 = second-to-last), reusing the same 30 echo assignments unchanged — no
turn was re-labeled. The distribution: 20 of 30 (66.7%) at offset 0, 7 of 30 (23.3%) at offset
1 — 27 of 30 (90%) within the last two exchanges of their turn. Only one redundant exchange
(turn 3, four positions before the end) sits deeper. The re-indexed aggregate is a steep,
near-monotonic curve — 0.841 at offset 0, 0.944 at offset 1, 0.984 at offset 2, 1.000 (zero
redundancy in the entire 626-exchange corpus) from offset 3 outward, with the single
exception at offset 4. Turns long enough to test the position hypothesis directly (63, 108,
110, 121, at 8–11 exchanges) carry at most one echo each, and it always sits at that turn's
own end — never scattered through the middle, which a genuine depth effect would produce.
The full 30-row list (turn, exchange index, end-offset) that both distributions are computed
from is published in the report, so the probe is reproducible from the report text alone
without re-deriving it from the raw transcript.

**Conclusion:** in this corpus, redundancy is a property of what the closing exchange does —
re-confirming a decision already argued, or re-listing doubts already individually stated
earlier in the same turn — not of how far into the turn that exchange happens to fall. The
"redundancy grows with position" reading is retracted; the report's Section 2 closing text
and the new Section 2a state this explicitly.

## What this does not establish

The end-offset probe rests on n=30 redundant exchanges; the offset-3-and-deeper buckets have
zero echoes each, which is consistent with the role reading but does not rule out that a
larger corpus would place a few echoes at offset 2–3 too. The verdict is solid on the central
split (offset 0 vs. everything else is not a small-sample artifact — 20 of 30 at a single
position is not noise) but the exact shape of the tail beyond offset 1 should be read as
indicative, not as a settled distribution.

Labeling was done by a single rater against the stated criterion; four turn-families were
flagged in the report as genuinely hard calls (the self-correction chains in turns 46,
52–53, 56, and the pervasive closing-question merge heuristic that decided roughly a third of
all echo assignments in the corpus). A second independent labeling pass was not run.
