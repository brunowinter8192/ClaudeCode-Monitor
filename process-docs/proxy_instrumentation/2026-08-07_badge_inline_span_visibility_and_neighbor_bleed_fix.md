# 2026-08-07 — Inline out-of-window span visibility + neighbor-bleed fix (CC 2.1.223)

## Observation

Live traffic on CC 2.1.223 (recorded session
`api_requests_opus_websearch_1786052022`) introduced mid-conversation system-role messages
(`mid-conversation-system-2026-04-07` beta) — CC dynamically overwrites a message at a FIXED
conversation index with a nag/notice (deferred-tools list, task-tools reminder, date-change
notice) on selected requests. The proxy strips these to a `"."` filler (existing behavior).
Two defects surfaced:

1. **Phantom badge.** The REQ-header correctly showed `strip inject` (has_content derived from
   the delta payload, unchanged from the 2026-07-30 fix), but the expanded view showed no
   colored span anywhere for the affected request. Root cause: the strip/inject happens at the
   message index CC overwrote, but if the POST-strip content there is unchanged from the
   previous request (still `"."`), the forwarded-log reconstruction (`forwarded_parser.py`) sees
   no delta at that index — the normal new/modified-message render window
   (`render_messages.py`, driven off `forwarded_parser`'s own diff) never reaches it. Concrete
   case: flow `fa0ba243` (opus req #2) strips/injects at msg index 1; its own render window is
   `range(2,4)` (new messages only) — index 1 sits below it entirely. Flow `9f02e2cd` (opus req
   #17) strips/injects at msg index 33; its window is `range(34,36)` — same pattern, confirmed
   via `diff_from_prev={'first_diff_index': 34, ...}`.

2. **Neighbor bleed.** `accumulate_dual_log`'s per-family acc dict (`acc['messages']`) is
   mutated in place and shared BY REFERENCE across every entry of that family
   (`entry['_stripped_spans'] = _proxy_acc_stripped[family]` in `pane.py`/`worker_proxy_pane.py`
   — no per-entry copy). A request whose own delta never touched a given message index could
   still see whatever the CURRENT accumulator state holds there — a later or earlier flow's
   span rendering under the wrong request's header.

## Fix

Added a third per-flow accumulator structure alongside the existing
`_has_content_by_flow_id` bool: `_msg_idx_by_flow_id: {flow_id -> set(msg_idx str)}`
(`parser.py::accumulate_dual_log`), populated from the same `messages_delta.keys()` already
being read, cleared on `is_first` like the other sections. `_has_content_by_flow_id` itself
stays an unchanged bool — only its input expression lost `fields_delta` (separate concern, see
below). Attached to entries as `_strip_msgs_lookup`/`_inject_msgs_lookup` in `pane.py` and
`worker_proxy_pane.py`, mirroring the existing `_strip_fns_lookup`/`_inject_fns_lookup` pattern.

`render_messages.py`:
- `_lookup_spans` now filters the shared acc lookup by `msg_key in
  entry['_strip_msgs_lookup'].get(entry['flow_id'], set())` (and the inject equivalent) —
  fixes the neighbor-bleed for the ALREADY-rendered window. Filtering is feature-detected via
  `'_strip_msgs_lookup' in entry` so synthetic test fixtures without the lookup dicts (e.g.
  `dev/proxy_dual_log/A_render_refactor_proof.py`'s hand-built entries) keep the old unscoped
  behavior — required for that suite's byte-identical baseline to hold.
- New `_render_flow_extra_messages(entry, messages, covered_from)`: renders this entry's own
  flow-touched indices below `covered_from` (the lower bound of what the normal window
  rendered) at their `[N]` position, reusing the SAME span-render primitives
  (`_render_block_spans`/`_render_span_content`) as in-window rendering — so olive
  (stripped-original) + green (injected) highlighting is identical in both paths. Output is
  PREPENDED to the normal window's lines (extra indices are chronologically earlier).
- `_render_modified_messages` now returns `(lines, keys, diff_start)` (was 2-tuple) —
  `diff_start` is `covered_from` for the modified-messages branch. No external callers (grep
  confirmed), safe to change.

Verified NOT a systemic in-window bleed in this recorded session — every message index in the
46-line stripped/injected logs was touched by exactly one flow (checked via a `Counter` over
`messages_delta.keys()` grouped by `flow_id`), so the window-based render paths never happened
to straddle a foreign flow's index naturally. The bleed is proven directly instead: calling
`_lookup_spans` on entry `01e683fe` (an empty-delta flow adjacent to `fa0ba243`) for msg index 1
(owned by `fa0ba243`) returns `([], [])` — confirms the ownership filter, not incidental window
placement, is what prevents the bleed.

## Adjacent deliverables (same milestone)

- **`fields_delta` dropped from `has_content`** (`parser.py`) — a field-only override
  (model/effort/max_tokens) must not badge; verified via a synthetic stripped-log line with
  only `fields_delta` populated — `has_content` computes `False`, while `acc['fields']` still
  accumulates the value (fields drill-down unaffected).
- **`⚠S` warn badge removed** (`render_turn.py`) — the `system_total_chars` vs `prev_same`
  comparison and its `warn_parts.append` are gone; `⚠T` (`tools_hash` comparison) is untouched.
  Verified via a full-session collapsed-header render (`format_proxy_block`, no entries
  expanded) — `⚠S` absent from output; `⚠T` present in `render_turn.py` source, `⚠S` absent from
  source.

## Verification (as of 2026-08-07)

`dev/proxy_instrumentation/p3_badge_inline_probe.py` drives the real
`accumulate_dual_log` → pane-style entry attach → `_build_req_header_line` + `render_messages`
path over `api_requests_opus_websearch_1786052022`. 6/6 cases passed:

| case | flow_id | what it proves |
|---|---|---|
| msg1 deferred-tools notice | `fa0ba243` | badge `strip inject`; msg [1] renders olive+green outside window (confirmed `prev_msg_count=2`, window `{2,3}`) |
| msg33 task-tools nag (core case) | `9f02e2cd` | same, window `{34,35}` — furthest below-window case in the session |
| msg38 bg-notification | `9f75f100` | in-window ownership-scoped rendering still correct (window `{36,37,38}` includes 38) |
| empty-delta no-bleed | `01e683fe` | no badge; no span in own render; direct `_lookup_spans` proof against a foreign index |
| synthetic fields-only | (synthetic) | `has_content=False`, fields dict still populated |
| no `⚠S` badge | (all 46 entries) | absent from rendered output and from source; `⚠T` present in both |

Regression: `dev/proxy_dual_log/test_composition_invariant.py` (12/12, unchanged),
`dev/proxy/test_strip_fix.py` (150/150, unchanged), `dev/proxy_dual_log/A_render_refactor_proof.py`
(13/14 byte-identical; the 1 expected mismatch is `expand_fixpoint`, diffed line-by-line against
a freshly captured pre-change baseline — the ONLY difference is the removed `⚠S` token, same
line count, confirming no unrelated rendering drift).

NOT verified: live TUI rendering in a running proxy pane (no user visual check performed this
session).
