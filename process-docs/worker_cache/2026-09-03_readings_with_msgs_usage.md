# First Readings of the 2026-09-02 Worker Sessions With `duallog msgs` Usage Lines (2026-09-03)

Follows this area's opening observations entry. The tool side landed in `process-docs/dual_log_cli/`
the same day: `msgs` now prints CR/CC per REQ separator, the strip/inject wire tail per msg, and the
sys/tool prefix changes per request, with the zero-tool security-monitor sidecar excluded. These are
the readings taken in chat on the five worker sessions of 2026-09-02, all times UTC as `msgs` prints
them. Nothing here is a root cause yet; each item names what a next session would check.

## Inheritance works, and the shared prefix is ~9.1k tokens

- `capture-git-status` (16:33): REQ 1 CR 0 / CC 9,435. The previous worker (`skill-help`) last sent at
  ~10:12 local, over six hours earlier, so the miss is expiry, not a break.
- `gcommit-umlaut` (16:38): REQ 1 CR 9,096 / CC 1,928 — inherited five minutes after the first worker.
  9,435 − 9,096 = 339 tokens ≈ the first worker's own msg 0 (1,004 chars), so the shared prefix ends
  before msg 0 and each worker pays only its spawn prompt.
- Both sessions then chain exactly: CR(n+1) = CR(n) + CC(n) for REQ 1→5 in each.
- The "big CC on REQ 2" shape from the opening entry is real new content (tool results of the first
  reads), not msg 1: msg 1 (the 10,116-char deferred-tools/agents/skills reminder) is stripped to a
  single `.` by the proxy in REQ 1 in every session, so it never reaches the cache at all.

## spawn-placement-msg's CR 0 is explained by expiry alone

`gcommit-umlaut`'s last request was 16:49:37; `spawn-placement-msg` REQ 1 was 18:35:40 — 106 minutes,
beyond the 1 h TTL. The rule-file edits between 17:00 and 17:40 UTC would also have broken the
prefix, but they are not needed to explain the observation and cannot be separated from expiry on
this session.

## Two mid-session breaks, one of them without any prefix change

- `devproxy-docs` REQ 20 (19:41:28): CR 9,564 / CC 63,159 after REQ 19 CR 69,599 / CC 414, 52 s apart.
  `msgs` prints NO sys/tool line under REQ 20, so the break is in the messages — consistent with the
  opening entry's finding that Claude Code dropped the PostToolUseFailure hook reminder from msg 3.
- `gcommit-umlaut` REQ 16→17: CR 62,676 / CC 0 then CR 54,273 / CC 9,603 — a real break by the
  CR(n+1) < CR(n)+CC(n) rule, also without a sys/tool line. Not yet examined; it is the second
  candidate for the hook-context hypothesis and the first thing to `expand` next time.

## Corpus-wide, the only tool-list change coincides with the only full rebuild

`skill-help` REQ 196 (15:14:57, 49 min after REQ 195): `tool[SendFeedback] removed`, CR 456,637+1,048 → 0,
CC 458,063. With the sidecar excluded and content-based comparison, this is the single flagged
sys/tool change across 24 sessions on disk, and it is the single CR-to-zero event — a 1:1 match.

## What a next session should do

1. `duallog expand gcommit-umlaut_1788367120 <msgs of REQ 16/17>` to see which msg changed between
   the two requests; the forwarded `messages_delta` of REQ 17 names the index.
2. Watch the security-monitor sidecar on the proxy side (`process-docs/proxy_*` areas): its requests
   pollute the proxy's per-family delta chain and are counted by the proxy pane.
3. Spawn two workers a minute apart with no rule edit in between, the clean inheritance test the
   opening entry asked for — the numbers above predict REQ 1 CR ≈ 9.1k for the second.
