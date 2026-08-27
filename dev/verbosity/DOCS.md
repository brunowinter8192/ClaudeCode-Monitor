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
- `corpus/sessions/*.jsonl` — frozen copies, dated 2026-08-27, of the 7 raw Claude Code
  session JSONL files `extract_turns.py` was actually run against (originals live under
  `~/.claude/projects/-Users-brunowinter2000-Documents-ai-monitor-cc/`, not in this repo).
  Original basenames kept so the 8-char session-id prefixes in the report's turn headers
  stay resolvable to a file: `451ad7c7`, `96699adf`, `defdd334`, `16cd91af`, `587284d6`,
  `04ca8d8c`, `80b146dd`. 20 MB total on disk — a real, deliberate cost, not an accident;
  see "Raw session logs" below for why they were brought in anyway.
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

## Relation between the files, and why `corpus/` is frozen

`corpus/sessions/*.jsonl` (raw) → `extract_turns.py` (filter: Opus-authored text only, no
tool calls or tool output) → `corpus/k2_turns.md` (126 turns, 626 exchanges) → manual
clustering → `md/20260827_k2_distinctness.md`. Every stage from raw log to published report
is now checkable from files committed in this directory, none of it from `/tmp`.

**Both `corpus/sessions/` and `corpus/k2_turns.md` are frozen snapshots, not regenerated on
every run.** Re-running `extract_turns.py` today would read the *live* session JSONL files
under `~/.claude/projects/...` in their current (further-grown) state, not the frozen copies
under `corpus/sessions/` — the script's source path is hardcoded to the live location, it
does not read from this directory. A fresh run is therefore not guaranteed to reproduce the
same 126 turns byte-for-byte: the live sessions can gain lines between runs (session
`04ca8d8c` in particular is still an active session and grew between the original extraction
and the later raw-log copy). Do not re-run the script to "refresh" the corpus without a new
dated report — the existing report's per-turn table and quoted exchanges are checked against
the specific frozen `corpus/k2_turns.md` and `corpus/sessions/` committed here, and
regenerating either would silently break that correspondence.

## Raw session logs: why they're here, and the secret-scan result

The 7 files under `corpus/sessions/` are full session transcripts, meaning they include tool
calls and tool output, not just Opus's prose (unlike `corpus/k2_turns.md`, which is filtered
to prose only). Full transcripts can carry secrets surfaced by tool output — API keys,
tokens, `.env` contents, credentials in command lines — so before committing them they were
scanned in place (unmodified, pre-copy) against 15 targeted patterns (AWS keys, Anthropic
`sk-ant-`, OpenAI `sk-`, GitHub tokens, Slack tokens, Bearer headers, JWTs, PEM private-key
headers, `.env`-style KEY=VALUE assignments, password assignments, basic-auth-in-URL,
`ssh-rsa`/`ssh-ed25519`, `BEGIN CERTIFICATE`) plus a broad word-frequency pass and a
high-entropy-string sweep (1,357 candidates ≥32 chars, entropy >4.5 bits/char, all
individually classified). Result: zero credential material found. The only findings were
benign — 430 base64 blobs are Claude's own extended-thinking signature tokens (standard,
opaque, present in every Claude Code session log), 26 are pasted-screenshot image data, the
rest are long filesystem paths and URLs. One `.env` file's *existence* (not contents) was
visible via an `ls -la` listing in one session; its contents were never displayed in any of
the 7 files. Full scan write-up: `process-docs/verbosity/`.
