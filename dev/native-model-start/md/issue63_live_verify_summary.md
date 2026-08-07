# Issue #63 live-verify summary — CC 2.1.223 pin bump, remaining surfaces

Measurement-only pass over the two recorded 2.1.223 sessions
(`api_requests_opus_posts_1786051932`, `api_requests_opus_websearch_1786052022`). No fixes
applied in this milestone — findings below await a separate Go.

Note (as stated in the task): both sessions' `_response.jsonl` logs carry HEADERS ONLY (no usage
fields, streaming design) — cache hit-rates are structurally unavailable and were not chased.

Note: both source `_original.jsonl` files are live/growing (concurrent sessions may still be
appending) — re-running any of the three probes can shift denominators slightly; the CLEAN/FINDING
classifications themselves were stable across repeated runs during this session.

## Surface 1 — cache breakpoints (`dev/native-model-start/p3_cache_breakpoints_probe.py`)

**FINDING** (one real, expected-scope item)

- BP1 (`system[2]`) and BP2 (last non-defer tool): stable across both full sessions, no missing
  or shifting positions.
- Of 11 raw content diffs found at common message indices (after normalizing cache_control +
  the JSON single-text-block-list/string shape churn `_add_cache_control_to_message` itself
  causes): 4 are one-time session-bootstrap reshaping (CC's own first-message handling), 6 are
  tail-adjacent draft edits (the user actively typing/extending their own last message before
  submit — correctly excluded from BP3's stable-prefix boundary by design), and **1 is the exact
  interaction this probe was built to check**: the 2026-08-07 mid-turn-user-message preserve-guard
  fix means a position that was previously always `"."` (nuked, cache-stable) now carries real,
  differing user text — busting the cache prefix at that point. Occurred once across ~276 recorded
  requests (only one mid-turn-user-message existed in either session).
- Zero `deep_history_mutation` cases (CC reordering/inserting content ahead of already-sent
  history at a position NOT near the tail).

## Surface 2 — dual_log integrity (`dev/native-model-start/p4_dual_log_integrity_probe.py`)

**FINDING** (one low-severity, display-only item; composition itself is fully clean)

- Composition invariant (real `apply_modification_rules` → real `all_ops` → real `compose_block`
  from `diff_engine.py`, driven over every recorded request): **0 failures / ~4900+ blocks
  checked** across both sessions. Both Inv1 (C0 reconstruction) and Inv2 (Cfwd reconstruction)
  hold everywhere.
- Schema drift: two unmodeled top-level payload keys found (`fallbacks`, `thinking`) — verified
  directly (not assumed) that `apply_modification_rules`'s `dict(payload)` shallow-copy pattern
  forwards both byte-identical, not dropped. One unmodeled content-block type (`image`) —
  `message_summary.py` falls through to its generic summary for it (display gap only; the
  composition invariant above already proves no strip pass mishandles image blocks).

## Surface 3 — strip wordings (`dev/native-model-start/p5_strip_wordings_probe.py`)

**CLEAN**

- fn_map census (real recorded `_stripped`/`_injected` dual-logs): `_apply_bg_launch_ack_strip`
  fired 13 times in `posts` (the only session whose raw log contains its wording at all — 0
  occurrences in `websearch`, confirmed a data fact, not a coverage gap). TN/bg-completion
  replacement fired via `_apply_bg_exit_strip` in both sessions (12 + 2 times) — this traffic's
  dominant TN wording routes through that function, not `_apply_first_pass`'s TN branch (confirmed
  by direct fn_map inspection on a specific occurrence).
- Unstripped-wording sweep (real CURRENT worktree code, replayed over all ~1800 top-level marker
  occurrences, `_top_level_content_contains`-scoped to match production's own tool_result
  exclusion): **0 survived unstripped**.
- Observation, out of scope for the two named targets: `websearch`'s backgrounded commands went
  through CC's 120s auto-timeout path ("...moved to the background") rather than an explicit
  `run_in_background=true` launch-ack — a structurally different message, not something either
  strip function targets or was asked to.

## Overall

| Surface | Verdict | Real findings requiring a future decision |
|---|---|---|
| 1 — cache breakpoints | FINDING | mid-turn-user-message preserve fix busts the cache prefix at that one position (expected trade-off: correctness — the user's text reaching the model — over cache efficiency at that single spot) |
| 2 — dual_log integrity | FINDING | `image` content blocks fall through to a generic summary in the display layer (cosmetic; strip-pipeline correctness already proven clean) |
| 3 — strip wordings | CLEAN | none |

No code changes made. Both surface 1 and 2 findings are informational/low-severity per the
evidence above — neither indicates the strip/cache pipeline is broken on CC 2.1.223 traffic.
