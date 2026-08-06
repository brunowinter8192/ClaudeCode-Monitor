# dev/timer-loop/

## Role

Measurement + verification scripts for the proxy-side pending-background-task tracking design:
what background-task completion/kill notices actually look like in the recorded corpus (`p1_`,
feeding milestone-2's design), and the proxy-side state mechanism that arms/clears a pending
tombstone from them (`p2_`, `src/proxy/pending_bg_state.py`). `md/` holds every script's report.

## Modules

### p1_scan_bg_completion_wordings.py (466 LOC)

**Purpose:** Inventories distinct background-task completion/kill notice wordings in the recorded
corpus (`src/logs/dual_log/*_original.jsonl`), split main vs worker session, dedups cumulative
dual-log duplication via a per-session exact-raw-text `seen` set (not a positional delta — robust
to the non-monotonic message-count resets observed in some worker sessions), evaluates the real
`payload_helpers._extract_task_notification_task_id` extraction against each wording.
**Reads:** `src/logs/dual_log/*_original.jsonl` (corpus dir overridable via `sys.argv[1]`).
**Writes:** `md/bg_completion_wordings_<date>.md`.
**Called by:** run manually — measurement only, not a regression guard.
**Calls out:** `src/proxy/strip_sn_notice.py`, `src/proxy/strip_bg_completed.py`,
`src/proxy/payload_helpers.py` (imports the real markers/regexes/extractors).

---

### p2_pending_bg_state_probe.py (415 LOC)

**Purpose:** Verifies `src/proxy/pending_bg_state.py` and the main-context launch-ack wording
sharpening in `src/proxy/strip_bg_launch_ack.py`. 12 test groups: main-context ack arms a pending
entry with a timestamp, a genuine TN completion notice clears it (status/exit-code agnostic —
exercised with the real corpus's exit-144 anomaly, not just 0/143/137), worker context never
writes state, a resighted already-cleared id (resent-history duplication, simulated restart via
clearing the in-memory dedup sets) never re-arms, a TN with no prior arm writes a fresh cleared
tombstone (not a no-op) and a later ack for that id still doesn't arm, ascending-message-index
replay ordering (ack + TN in ONE call, dict constructed with DESCENDING key-insertion order
specifically so a missing `sorted()` would be caught), 24h tombstone pruning on write with pending
entries exempt, failure isolation (corrupt state-file JSON, through both a direct call and a real
`ProxyAddon.request()`), real end-to-end arm/clear/worker-no-write via `ProxyAddon.request()`, and
main-vs-worker wording split (worker/default text byte-identical to pre-2026-08-06).
**Reads:** Nothing persistent — builds all fixtures in-process; every state-file test scopes
`MONITOR_CC_ROOT` to a `tempfile.TemporaryDirectory()`, never the real `src/logs/`.
**Writes:** `md/p2_pending_bg_state_probe_<timestamp>.md`.
**Called by:** run manually — regression guard for `pending_bg_state.py`; re-run after any change
to that module, `strip_bg_launch_ack.py`'s wording selection, or `addon.py`'s wiring of either.
**Calls out:** `src/proxy/pending_bg_state.py`, `src/proxy/strip_bg_launch_ack.py`,
`src/proxy/addon.py` (`ProxyAddon`, `_derive_worker_context`).

---

## Gotchas

**p2's timestamp arithmetic must match `pending_bg_state._now_iso()`'s single-`Z` format, not
`datetime.isoformat() + "Z"`.** A tz-aware `datetime.isoformat()` already appends `+00:00`;
concatenating `"Z"` after that produces an unparseable `...+00:00Z` double-suffix that silently
breaks `_prune_stale_tombstones`'s round-trip parse (caught during this probe's own development —
Test 7 initially failed for exactly this reason, in the test's OWN seed-data construction, not in
production code once `pending_bg_state.py`'s writers were fixed to use `_now_iso()`). Any new test
seeding `armed_at`/`cleared_at` directly must use the same single-`Z`, millisecond-precision format
(`strftime('%Y-%m-%dT%H:%M:%S.') + f'{us//1000:03d}Z'`), not raw `isoformat()`.

**p1's corpus is a moving target — counts are a lower bound, not final.** Same caveat as
`dev/bg_wakeup_id_line`'s p1: `src/logs/dual_log/*_original.jsonl` keeps growing from concurrent
live sessions while the scan runs; a rescan can only add deduped occurrences, never remove them.
