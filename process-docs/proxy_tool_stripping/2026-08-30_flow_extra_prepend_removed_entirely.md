# The Out-of-Window Prepend Is Gone Entirely, 2026-08-30

Supersedes the same-day entry that filtered the out-of-window prepend down to its substantial
classes. That design kept prepending a real strip (task-tools nag, deferred-tools notice,
date-changed, mid-conversation overwrite) and suppressed only the per-request total_tokens nuke.
The whole mechanism is now removed: an expanded request body is that request's payload delta and
nothing else, for every class. Related areas: `process-docs/proxy_instrumentation/` holds the
2026-08-07 milestone that introduced the prepend and the per-flow span scoping it rested on.

## The decision

The user's rule is that the expanded message list must mirror the payload delta exactly. The
prepend was the one thing violating it: a request's view could open with a message that request
did not add, which made the list stop corresponding to the API traffic it claims to show.

Measured before removal, across two recorded sessions: 89 of 631 rendered entries prepended
something (22 of 144 on `opus_monitor_cc_1788091735`, 67 of 487 on `opus_gh_cli_1787995963`), 86 of
those prepends being a `syst` message. A further 106 entries carried out-of-window touches that the
earlier partial suppression already hid; after this change all of them are treated alike.

## What it costs, measured — the earlier justification did not survive contact

The removal was proposed with the consolation that the strip stays visible under the request whose
delta legitimately contains the touched message — e.g. msg 176 rendering under REQ #61 with its
spans while REQ #62 loses its prepend. **That is false, and the measurement says so plainly.**

For all 90 indices the mechanism used to prepend across both sessions:

| outcome | count |
|---|---|
| rendered by another request WITH spans | **0** |
| rendered by another request WITHOUT spans | **90** |
| not rendered anywhere else | 0 |

Msg 176 does appear under REQ #61 — as a bare `.` (1c), no olive, no green. The cause is
structural, not incidental: `_lookup_spans` scopes spans to the flow that touched the coordinate,
and REQ #61's flow never touched 176. REQ #62's flow did, which is exactly why #62 was the request
prepending it.

So the real consequence, accepted with that knowledge: **for a strip landing outside a request's
delta, the stripped ORIGINAL text is no longer readable anywhere in the proxy pane.** The
`strip`/`inject` badge words on the REQ header become its only in-pane trace, and the phantom-badge
state (badge with nothing to point at) is now the normal state for these classes rather than a rare
one. The content itself is not lost — it stays in the dual-log `_stripped` stream and is readable
with the duallog CLI (`duallog msgs <session>` to locate the msg, `duallog expand <session> <msg>`
to read it). That recoverability is what made the cost acceptable rather than blocking.

The alternative — relaxing `_lookup_spans`' flow scoping so a neighbouring request could show the
span — was rejected without implementing: it is precisely the 2026-08-07 neighbour-bleed bug, and
it would put one request's transformation under another request's header, trading a visible gap for
an invisible lie.

## What was removed

- `render_messages._render_flow_extra_messages` and its `_own_msgs` helper.
- The prepend call and `covered_from` in `render_messages()`, which now returns whichever window
  renderer applies, directly.
- `_render_modified_messages`' third return value (`diff_start`), which existed only to feed
  `covered_from`; it went back to the pre-2026-08-07 `(lines, keys)` shape. No caller outside the
  module, grep-verified.
- `parser.accumulate_dual_log`'s `_msg_idx_sub_by_flow_id` accumulation, its `is_first` clear and
  its literal key.
- The `_strip_msgs_sub_lookup` / `_inject_msgs_sub_lookup` attachments in both panes.

Deliberately kept: `_msg_delta_entry_is_substantial` (the badge's `_msgs_delta_is_substantial` is an
`any()` over it), the raw `_msg_idx_by_flow_id` lookups, `_lookup_spans`, and every in-window
renderer.

## Verification (as of 2026-08-30)

**The named target.** REQ #62 of `api_requests_opus_monitor_cc_1788091735` now renders headers
`[177] [178] [179]` — the milestone's target picture exactly — with its out-of-window touch of msg
176 unrendered and its badge still `(strip=True, inject=True)`, the accepted phantom badge.

**Before/after over every entry.** Bodies and `badge_flags` were captured for all entries of both
sessions before implementation and re-rendered after: 542 of 631 bodies byte-identical, 89
shortened by exactly their prepend block (verified by checking that the dropped head contains only
out-of-window indices and that the remaining tail is byte-verbatim), **0 changed in any other way**,
and **0 badge changes**.

**Permanent probe.** `dev/proxy_instrumentation/p6_no_flow_extra_prepend_probe.py` replaces the
suppression probe, whose double-render baseline became impossible once the mechanism was deleted.
Its four invariants are self-contained: no body carries a header below its own delta-window start
(635 entries, 0 violations); the removed symbols stay removed; every substantial out-of-window
strip still badges; and in-window spans still render somewhere (37 and 73 entries respectively), so
a regression that killed span rendering cannot masquerade as a clean removal.

Two of those checks failed on first run and both were the probe's fault, not the code's. One
demanded a badge for EVERY out-of-window touch, but a total_tokens-only touch deliberately badges
nothing — it now filters by `_msg_delta_entry_is_substantial` read off the raw delta lines. The
other grepped the parser source for `_msg_idx_sub_by_flow_id` and hit a stale comment block still
describing the removed structure; that comment was real leftover debris and was deleted. The
reintroduction guard earning its keep on its first execution is the argument for keeping it.

**Regression.** `dev/proxy/test_strip_fix.py` 207/207, `dev/proxy_dual_log/test_composition_invariant.py`
12/12, `dev/display/test_hover_map.py` 45/45, `dev/pane_search/p2_search_feature_regression_test.py`
and `dev/proxy_dual_log/tt_delta_skip_replay.py --compare` both PASS.

**Not verified:** the live TUI. Everything above drives the real render path over recorded logs; no
running proxy pane was observed.

## Relevant Symbols / Paths

- `render_messages()` (`src/proxy_display/render_messages.py`) — now returns a window renderer directly
- `_lookup_spans()` (same file) — untouched; the reason an out-of-window strip has no fallback view
- `_msg_delta_entry_is_substantial()`, `accumulate_dual_log()` (`src/proxy_display/parser.py`)
- `dev/proxy_instrumentation/p6_no_flow_extra_prepend_probe.py` — the replacement probe
- Ground-truth logs: `src/logs/dual_log/api_requests_opus_monitor_cc_1788091735_*.jsonl`,
  `src/logs/dual_log/api_requests_opus_gh_cli_1787995963_*.jsonl`
