# 2026-08-27 — K2 data basis frozen into the repo

## What and why

The distinctness analysis (`dev/verbosity/md/20260827_k2_distinctness.md`) was originally
run against files living only under `/tmp/` and `~/.claude/projects/...` — outside the repo
and not reproducible from it. The full data basis was frozen into `dev/verbosity/corpus/`
so the report stays checkable against its input from the repo alone: the extraction script
(`extract_turns.py`), its filtered output (`k2_turns.md`, 126 turns / 626 exchanges), and
the 7 raw session JSONL files it was run against (`sessions/`, 20 MB, original basenames
kept so the report's session-id prefixes stay resolvable). Both the corpus and the raw logs
are dated snapshots, not regenerated on every run — the live sessions under
`~/.claude/projects/...` keep growing and a fresh extraction is not guaranteed to reproduce
the same 126 turns.

## Secret scan before persisting the raw logs

The 7 raw session files carry full tool output, unlike the filtered `k2_turns.md`, and were
scanned in place before being copied in: 15 targeted credential patterns (AWS, Anthropic,
OpenAI, GitHub, Slack, Bearer, JWT, PEM keys, `.env`-style assignments, password
assignments, basic-auth URLs, SSH keys, certificates) plus a broad word-frequency pass and a
high-entropy-string sweep (1,357 candidates, all individually classified). Result: zero
credential material. The only matches were benign — Claude's own extended-thinking
signature blobs, pasted-screenshot image data, and ordinary file paths/URLs — plus one
`.env` file's bare *existence* surfaced via an `ls -la` listing, contents never shown. Full
scan detail is in the chat record of that session; this entry exists to record that the scan
happened and the raw logs were persisted only after it cleared.

No analysis output, cluster label, or reported number changed as part of this milestone.
