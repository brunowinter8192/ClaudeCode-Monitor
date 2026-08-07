# 2026-08-07 — CC 2.1.223 live-verify: cache breakpoints, dual_log composition, strip wordings

Remaining live-verify of the 2.1.223 pin bump (`2026-08-06_cc_223_binary_bump.md`), measurement
only — no code changes this session. Driven over two recorded 223 sessions:
`api_requests_opus_posts_1786051932` (~158 requests) and
`api_requests_opus_websearch_1786052022` (~118 requests). Both sessions' `_response.jsonl` carry
HEADERS ONLY (streaming design) — cache hit-rates are structurally unavailable, not chased.

## Surface 1 — cache breakpoints (`src/proxy/cache.py`)

Replayed every recorded request through a REAL `ProxyAddon()` instance in chronological order
(fresh addon per session, state carrying across requests exactly as a live proxy process would).
BP1 (`system[2]`) and BP2 (last non-defer tool) were positionally stable across both full
sessions — no missing or shifting positions observed anywhere.

Checked the specific interaction the task flagged: does the mid-conversation role='system'
content 2.1.223 introduced (nag/notice messages, our `.` replacements, or — since the same-day
mid-turn-user-message preserve-guard fix landed (see the `proxy_tool_stripping` area) — real
preserved content) shift breakpoint positions request-over-request? Diffing every message index
common to consecutive requests (after normalizing both cache_control presence AND the JSON
single-text-block-list/plain-string shape churn `_add_cache_control_to_message` itself introduces
for ANY role, not just cache.py's own user-only `_normalize_user_content_shape` scope — this
second normalization was the harder-won finding: without it, the probe reported 83 false-positive
content diffs, all pure shape noise from the cache marker's own add/remove cycle) found:

- 4 one-time session-bootstrap events (CC reshaping message 0 in the first 2-3 requests of each
  session)
- 6 tail-adjacent draft edits (the user actively typing/extending their own still-unsettled last
  message — by design excluded from BP3's stable-prefix boundary, not a real bust)
- **1 real instance of the flagged interaction**: posts session, message 274 — the exact
  mid-turn-user-message position (`"The user sent a new message while you were working:\njetzt..."`)
  that used to be permanently `"."` (cache-stable, pre-fix) now carries genuinely different real
  user text whenever it fires, busting the cache prefix at that single point. Occurred once
  across ~276 recorded requests — only one such message existed in either session.
- 0 `deep_history_mutation` cases (a message clearly NOT near the tail changing content, e.g. CC
  reordering an async notification ahead of already-sent history) — none observed in either
  session.

Verdict: FINDING, but the finding is the expected/accepted trade-off of the same-day preserve-guard
fix (correctness — the user's text reaching the model — over cache efficiency at one position),
not a new pipeline defect.

## Surface 2 — dual_log integrity (composition + schema drift)

Composition invariant driven directly over real data: called the REAL
`src.proxy.rules.apply_modification_rules` independently per request (the message-passes pipeline
itself carries no cross-request state — only `ProxyAddon`'s dual-log hash bookkeeping does,
irrelevant to composition), validated its own returned `all_ops` against the REAL `compose_block`
(`src/proxy/diff_engine.py` — the same function `strip_inject_delta.py` uses to build the
dual-log's span data, not the `dev/proxy_dual_log/composition_probe.py` fixture-test's own
reimplementation, which was found to have a stale/incomplete pass_sequence missing
`_apply_role_system_strip`/`_apply_sn_notice_strip`/bg-launch-ack/interrupt-marker — a real gap in
that fixture harness, noted but out of this session's scope to fix). Result: **0 failures across
~4900+ blocks checked** (both Inv1 C0-reconstruction and Inv2 Cfwd-reconstruction hold everywhere).

Schema-drift scan found two unmodeled top-level payload keys (`fallbacks`, model-fallback list;
`thinking`, extended-thinking config) and one unmodeled content-block type (`image`). Verified
directly — not assumed — that both new keys forward byte-identical through
`apply_modification_rules`'s `dict(payload)` shallow-copy pattern (same pattern `cache.py` uses),
confirming these are simply not specially modeled, not silently dropped. `image` blocks fall
through to `message_summary.py`'s generic json.dumps summary (display-only gap; the composition
invariant above already proves no strip pass mishandles them).

Verdict: FINDING (the `image` display gap), low severity, cosmetic only.

## Surface 3 — strip wordings

fn_map census over the REAL recorded `_stripped.jsonl`/`_injected.jsonl` (historical record of
what actually fired at capture time): `_apply_bg_launch_ack_strip` fired 13 times in `posts` — the
only session whose raw original log contains its wording at all (0 raw occurrences in
`websearch`, confirmed directly, a data-availability fact, not a coverage gap).
TN/bg-completion replacement fired via `_apply_bg_exit_strip` in both sessions (12 + 2 times) —
this traffic's dominant real TN wording routes through that function rather than
`_apply_first_pass`'s TN branch (confirmed by inspecting one specific occurrence's fn_map
directly, flow `9f75f100`/msg 38 in websearch → `_apply_bg_exit_strip`).

Unstripped-wording sweep: replayed every request through the CURRENT worktree code, checking
whether any of the 4 known bg-related marker strings survives unstripped into the forwarded
payload — scoped to TOP-LEVEL content only via `payload_helpers._top_level_content_contains`,
matching the real passes' own tool_result-exclusion gate. The harder-won finding here: without
that scoping, the sweep reported 421/2995 "survivals" — ALL false positives, rag-cli/gh-cli
search results returning this project's own indexed process-docs, which discuss
`<task-notification>` and "Background command" wording at length as DATA, not live notifications.
After the fix: **0/1810+ survived**.

Verdict: CLEAN.

## Methodology notes (for future re-verification)

- Both `_original.jsonl` files are live/growing — re-running any probe shifts denominators
  slightly (observed 4924→4999 composition blocks, 1810→1818 marker occurrences across two runs
  in this same session); the CLEAN/FINDING classifications themselves were stable.
- Cache-content comparison needs cache.py's own user-only shape normalization AND a second,
  broader (any-role) single-text-block-list/string collapse to neutralize the cache_control
  marker's own add/remove JSON-shape churn before any real content diff is meaningful.
- The composition-invariant fixture harness (`dev/proxy_dual_log/composition_probe.py`) has a
  pass_sequence that has fallen behind `rules.py`'s real `_passes` list — worth reconciling in a
  future session if that harness is relied on again for anything beyond its original scope.
