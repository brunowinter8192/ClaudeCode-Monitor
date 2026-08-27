# dev/verbosity/

## Role
Holds analysis of redundancy in this assistant's own chat output, transferring the
process-efficiency measurement from Chen et al., "Do NOT Think That Much for 2+3=?" from
LLM solution-rounds to Opus turn-exchanges, plus the frozen extraction the analysis was run
against. `extract_turns.py` is the only producing script, and it produces the corpus, not
the analysis: the clustering itself is a manual, per-exchange semantic judgment against a
fixed criterion (does a later exchange add a decision-relevant fact not already present in
an earlier exchange of the same turn), not a reusable pipeline — a future pass over new
turns would need a fresh manual read, not a re-run of code.

## Files
- `extract_turns.py` — reads every `~/.claude/projects/-Users-brunowinter2000-Documents-ai-monitor-cc/*.jsonl`
  session file, reconstructs Opus turns (one user message followed by consecutive
  Opus-model assistant text blocks), splits each turn's text into numbered exchanges on
  bold-point / 🛑 lines, keeps only turns with 4+ exchanges, and writes the result to
  `/tmp/k2_turns.md`. Path and output location are hardcoded (`/tmp/k2_turns.md`), not a
  CLI argument.
- `corpus/k2_turns.md` — the exact output `extract_turns.py` produced on 2026-08-27 (126
  turns, 626 exchanges, 306 KB), copied byte-for-byte from `/tmp/k2_turns.md` into the repo
  for persistence. This is what `md/20260827_k2_distinctness.md` was actually clustered
  against — verify the report's numbers against this file, not against a fresh run.
- `md/20260827_k2_distinctness.md` — per-turn distinctness table for 126 turns (626
  exchanges), a per-exchange-index aggregate (Chen Figure 6 analog), and the ten
  lowest-distinctness turns quoted in full with per-exchange cluster labels. States the
  measured corpus-wide distinctness (0.952) against a pre-registered prediction and flags
  the turns that required a judgment call beyond the stated criterion. Section 2a re-runs
  the position aggregate indexed from the END of each turn instead of the start, with the
  full 30-row list of redundant exchanges (turn, index, end-offset) that both distribution
  tables are computed from — this discriminates a "redundancy grows with depth" reading
  from a "redundancy is a closing-exchange role effect" reading; the probe rules out the
  former (see `process-docs/verbosity/` for the write-up).

## Relation between the three files, and why `corpus/` is frozen

`extract_turns.py` produces `corpus/k2_turns.md`, which the manual clustering in
`md/20260827_k2_distinctness.md` was run against. **`corpus/k2_turns.md` is a frozen
snapshot, not regenerated on every run.** Re-running `extract_turns.py` today would read
the same session JSONL files in their current (possibly since-grown) state and is not
guaranteed to reproduce the same 126 turns byte-for-byte — session files can gain lines
between runs, and the script has no version pin or checksum of its input. Do not re-run it
to "refresh" the corpus without a new dated report: the existing report's per-turn table and
quoted exchanges are checked against the specific frozen `corpus/k2_turns.md` committed
here, and regenerating the corpus would silently invalidate that correspondence.

## Gotchas
The seven source session JSONL files themselves (`~/.claude/projects/-Users-brunowinter2000-Documents-ai-monitor-cc/{451ad7c7,96699adf,defdd334,16cd91af,587284d6,04ca8d8c,80b146dd}*.jsonl`,
~20 MB total) are NOT in this repo and were not copied in — they are full session
transcripts that may carry secrets from tool output (API keys, tokens, `.env` contents,
credentials in command lines) and need a scan-and-decide step before any of that raw data
is persisted. `corpus/k2_turns.md` is a derived, filtered extraction (Opus-authored prose
only, no tool calls or tool output) and does not carry that risk.
