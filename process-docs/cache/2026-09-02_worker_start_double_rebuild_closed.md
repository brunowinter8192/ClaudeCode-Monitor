# Worker Start "Double Cache Rebuild" — Closed Without Reproduction (2026-09-02)

## What was reported

On 2026-08-25 the WORKERS monitor flagged two cache-rebuild requests within the first three API
calls of a fresh Sonnet worker: REQ 1 with cache_read 1,228 / cache_creation 11,041 and REQ 3
with cache_read 13,358 / cache_creation 17,681. The reading at the time was that the cached
prefix gets invalidated between the early requests, doubling every worker's startup cost.

## Why it is closed without a fix

The payloads from 2026-08-25 no longer exist, so the original observation cannot be diffed.
The user decided to close the item on that basis.

## Hypothesis from the numbers alone

The reported figures do not describe an invalidation. REQ 3's cache_read (13,358) equals REQ 1's
cache_read plus cache_creation (12,269) plus roughly one short assistant turn. So REQ 3 read the
entire prefix REQ 1 had written and additionally wrote a new 17.7k segment, which is the spawn
prompt plus the first tool results entering the cache for the first time. That is incremental
caching, not a rebuild. The monitor's flag reacts to a large cache_creation value without
checking whether cache_read grew by the previous request's total.

A short look at a fresh worker's forwarded-delta log from 2026-09-02 (worker `skill-help`,
Sonnet) is consistent with that: between REQ 1 and the next Sonnet request (REQ 3, REQ 2 was a
Haiku side call) the only system or tools delta is system block 0, the per-request billing
header, which changes on every request and cannot be what caches or invalidates. Tools and the
rules block carried no delta. Usage figures for that session were not extracted, so this is
a consistency check, not a confirmation.

## If it comes back

Compare cache_read of request N+1 against cache_read plus cache_creation of request N. Equal or
larger means incremental caching; smaller means a real prefix break, and then the forwarded
deltas of the dual log (`system_delta`, `tools_delta`) name the changed block directly.
