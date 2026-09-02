# Worker sessions rebuild the prompt cache more often than expected — observations (2026-09-02)

Opening entry of this area. Observations only; the investigation is deferred to a later session.
Source: the workers pane (tab 2) of the monitor and the dual log of the affected worker sessions.
CR = cache_read_input_tokens, CC = cache_creation_input_tokens, per request as the pane shows
them.

## Expectation stated by the user

Every worker session shares the same system prompt, tool list and injected rules. The first worker
of the day pays for building that prefix once; every later worker inherits it, until a rule file is
edited and the injected rules change. Rule files were edited between roughly 19:00 and 19:40
local (worker code-standards, worker dev-convention, global testing, main workers, main tool-use).

## What the pane showed (all times local)

| Worker | Spawned | REQ #1 | REQ #2 | Note |
|---|---|---|---|---|
| capture-git-status | 18:33 | CR 0, CC 9,435 | CR 9,435, CC 5,108 | first worker of the day |
| gcommit-umlaut | 18:38 | not captured | | |
| spawn-placement-msg | 20:35 | CR 0, CC 9,645 | CR 9,645, CC 25,289 | full rebuild, 2 h after the last worker |
| verifier-retire | 20:56 | CR 8,721, CC 971 | CR 9,692, CC 327 | inherited |
| devproxy-docs | 21:39 | not captured | | REQ #20 rebuild, see below |

Two shapes appear. A CR 0 first request followed by a large CC on the second request (the two
spawns at 18:33 and 20:35), and an inherited first request (20:56). The 20:35 rebuild came after
the rule edits, so it is consistent with the expectation, but it also came about two hours after
the previous worker request, so a cache expiry explains it equally well. The beta list on every
request includes `extended-cache-ttl-2025-04-11`; which TTL actually applied was not checked.
The two explanations are not separated by this data.

Open question from the same table: why REQ #1 reads CR 0 with a small CC and REQ #2 then creates
the bulk. Whether REQ #1 is a different, smaller request shape than the first real turn was not
checked.

## Mid-session rebuild traced to Claude Code, not the proxy

devproxy-docs, REQ #20 (21:41:28, first request of turn 2 after the orchestrator's "Go"): CR 9,564,
CC 63,159. 52 seconds after REQ #19, so no expiry. The forwarded delta for that request lists
message index 3 as changed. Message 3 is the tool_result of a failed `wc` at session start
(exit 1 on a directory). From REQ 3 to REQ 19 the ORIGINAL payload carried that message with two
blocks: the tool_result and a `<system-reminder>` text block with the PostToolUseFailure hook's
retry discipline. At REQ #20 the original payload from Claude Code carried message 3 with the
tool_result only. The proxy never stripped that block (the stripped delta never names message 3),
so the forwarded content changed exactly where the original changed, and the cache broke from
message 3 onward. Hypothesis: Claude Code treats hook-added context as turn-local and removes it
from history at the next user prompt, which would make every failed tool call inside a turn cost a
prefix rebuild at the next send. One instance observed; a second session with an early failure
would confirm or refute it. Tool used: `duallog msgs`, `duallog expand <session> 3`, and the
forwarded/original JSONL of `api_requests_worker_25c51a2e_devproxy-docs_1788377950`.

## What a later session should settle

- Whether cross-session inheritance of the system/tools/rules prefix happens at all, and under
  which TTL. A clean test is two spawns a minute apart with no rule edit in between.
- The REQ #1 versus REQ #2 shape.
- The hook-context hypothesis, on a second early-failure session.
