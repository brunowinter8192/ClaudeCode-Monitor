# Rebuild classification with `reqs --gap/--merged/--rebuild/--drop` — first pass (2026-09-04)

Same-day sequel to the `reqs`, `--gap`, `--merged`, `--rebuild`/`--drop` entries in this area.
Run over the four monitor-cc worker sessions of 2026-09-04.

## What the flags separated

- `--merged --gap 10` over the worker chain: the within-session pauses of one worker shrink or
  vanish once the other workers' requests are interleaved (a 76-minute pause of
  duallog-search-chars became two pauses of 28 and 29 minutes bridged by two other workers).
  Real chain gaps left: 42, 89 and 46 minutes.
- `--merged --drop` (after the same-session-predecessor fix of the same day): six drops in
  five sessions. Three are the TTL rebuilds behind the long pauses (CR near 0, CC 501k–650k).
  Two are small partial rewrites without any pause (1,691 and 8,782 tokens). One is a silent
  full rebuild mid-flow: proxy-tn-wrap REQ 61, 60 seconds after REQ 60, CR 35,417 (= the
  system+tools prefix), CC 158,664.
- The "constant ~10k shortfall" seen before the predecessor fix was an artifact of comparing a
  request against another session's totals; it disappeared with the fix.

## The silent rebuild, explained from the forwarded delta

REQ 61's `messages_delta` carried key `9` besides the three new msgs. Msg 9 at REQ 4 was a
two-block user message: the failed tool_result plus a `<system-reminder>` block holding the
PostToolUseFailure hook's retry instruction. At REQ 61 the same msg has only the tool_result
block. Claude Code rewrote index 9 in place, so everything after it was re-cached. The trigger
in time was the orchestrator's `worker-cli send` to the idle worker; the mechanism (CC dropping
hook context from old messages on the next user turn) is a hypothesis, not verified.

## Open

- `--drop` should print the changed message indices from that request's forwarded
  `messages_delta` (keys below the request's own new-msg range) so the rewritten message is
  visible without a separate probe.
- Whether every PostToolUseFailure system-reminder is removed on the next user turn, and thus
  every hook-error in a worker's history costs one full rebuild, is untested.
