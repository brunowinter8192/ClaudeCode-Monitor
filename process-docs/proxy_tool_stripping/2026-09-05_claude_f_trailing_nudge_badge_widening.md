# claude-f Trailing-Nudge Badge Widening, 2026-09-05

Continues this area's total_tokens line (`2026-08-29_total_tokens_delta_skip.md`,
`2026-08-30_trailing_strip_attribution_lag.md`, `2026-08-30_flow_extra_total_tokens_suppression.md`).
The 2026-08-29 fix silenced the badge for the bare `<total_tokens>N tokens left</total_tokens>`
marker. This entry widens that same class to a shape CC introduced on model claude-f, where the
marker is no longer always bare.

## Symptom

On claude-f sessions, CC's trailing `role='system'` message carries one or two nudge sentences
before the tag instead of the bare tag alone, e.g.:

```
First privately list what you need next; then request every item that doesn't depend on another's result in this one response.

Only you see that command's output — the user's terminal shows at most a few lines of it. If the user needs to read any of it, put it in your reply.

<total_tokens>14986220 tokens left</total_tokens>
```

On the next request CC re-sends the previous trailing message with a sentence dropped, so the
proxy strips a DIFFERENT text at a DIFFERENT index every time — the exact hash-dedup defeat the
2026-08-29 entry diagnosed for the bare tag, now recurring for a shape the bare-only regex does not
recognize. Measured with the real `badge_flags` before this fix, against the three current corpus
stems (`api_requests_opus_{wise2627_1788612045,websearch_1788611995,monitor_cc_1788611156}`):
wise2627 and websearch carried no nudge-shaped messages in this snapshot (unaffected — their
badge-on counts are entirely genuine real strips), while monitor_cc badged 136 of 154 requests, the
overwhelming majority phantom.

## Measurement before designing

`dev/proxy_tool_stripping/probe_trailing_message_shapes.py` scanned every stripped text ending
with the tag across the three `_stripped.jsonl` logs, normalized by replacing the tag's digit run:
**24 distinct shapes** across the three sessions. All but a handful reduce to combinations (any
order, any repeat count, 1–4 paragraphs observed) of exactly three fixed sentences:

- `"First privately list what you need next; then request every item that doesn't depend on another's result in this one response."`
- `"Only you see that command's output — the user's terminal shows at most a few lines of it. If the user needs to read any of it, put it in your reply."`
- `"The user hasn't heard from you in a while — say in a few words what you're doing, then continue."` (1 occurrence)

The remaining shapes are genuine real strips that independently land on the same trailing slot and
inherit the tag: a deferred-tools notice, a skills-available notice, a file-modified notice, and
(in this pre-Milestone-3 corpus) the now-removed `feedback_bash_error` hook's own message, sometimes
combined with a nudge sentence in the same message. None of the three sentences overlaps with any
existing proxy-injected vocabulary.

**A positional (message-index) shortcut was checked and rejected.** Every real-content-plus-tag
occurrence measured sits at exactly the same trailing message index the nudges occupy (verified
directly against `counts.messages`), so "is this the trailing message" cannot discriminate the two
classes — the discrimination has to be content-shape based.

## Design

`_is_total_tokens_nuke_text(text)` (`src/proxy_display/parser.py`) returns True for the existing
bare-tag exact match, OR when the tag is preceded only by paragraphs (split on blank lines) that
are ALL members of `_TOTAL_TOKENS_NUDGE_PARAGRAPHS`, a frozenset of the three sentences above.
Catalogued by exact sentence, the same convention `strip_sr.py` uses for its SR templates — a
heuristic "generic prose" detector was considered and rejected: it would also risk swallowing a
real notice that happens to read as plain prose, and there is no structural marker (no colon, no
file path, no "The following...") reliably separating the nudges from the real notices other than
their exact wording.

**This is deliberately not future-proof against a new, uncatalogued nudge sentence, and that is the
point, not a gap.** An unrecognized sentence fails the paragraph-decomposition test, so the request
stays on the badge — it fails toward SHOWING the strip rather than silently absorbing it into the
quiet class. A future CC wording change (a fourth nudge sentence, a reworded one) surfaces as a
live badge regression the next time someone reads the pane, rather than vanishing unnoticed into
the same silence as the current three. The catalog is meant to be extended when that happens, via
the same probe script that built it — not hardened into a heuristic that guesses at wording it has
never seen.

Both consumers of the old bare-only regex now go through this one function:

- `_msg_delta_entry_is_substantial` (the badge filter): widened from "exactly one text full-
  matching the bare tag" to "every stripped text in the message is either bare or nudge-only".
  "Two or more such messages in one delta are still non-substantial" falls out for free — each
  message is checked independently and the aggregate (`_msgs_delta_is_substantial`) is an `any()`
  over real content, so an all-nudge delta with two or more touched messages stays quiet.
- `_is_total_tokens_nuke` (the lag correction's marker guard): widened the same way, kept to its
  existing single-text-per-index requirement.

### Why the lag correction had to widen too

Measured at the exact position `_is_total_tokens_nuke` is asked about (the previous request's
trailing index, single-text delta) in the monitor_cc log: 48 bare-tag cases (already lag-corrected
before this fix) and **55 nudge-shaped cases the narrow bare-only regex missed entirely** — more
than the bare class itself. Left unwidened, those 55 would render with no span correction, the
same in-window symptom the 2026-08-30 entry fixed for the bare case, just for the new shape. At
that same position, 6 cases were genuine real content (all mixed with a nudge, including the old
feedback hook's message) — the catalog test correctly excludes all 6, preserving the "marker guard
is load-bearing" property the 2026-08-30 entry established: a real strip must never be misattributed
to a neighbor request.

## Verification (as of 2026-09-05)

**Before/after over the real accumulator and badge function**, computed by running
`accumulate_dual_log` + `badge_flags` directly against the on-disk `_stripped.jsonl`/
`_injected.jsonl` for all three stems (no replay needed — this is read-side only, the dual-logs
already exist):

| session | total requests | badged before | badged after | real-strip requests | real-strip badged before/after |
|---|---|---|---|---|---|
| wise2627 | 58 | 18 | 18 | 18 | 18/18 |
| websearch | 96 | 19 | 19 | 19 | 19/19 |
| monitor_cc | 154 | 136 | 35 | 35 | 35/35 |

Zero real strips lost on any session; wise2627/websearch are unaffected in this snapshot (no
nudge-shaped messages currently present in their logs — the badge counts there were already
genuine). monitor_cc drops from 136 to 35 badged requests.

**`dev/proxy_dual_log/tt_delta_skip_replay.py --compare`** re-run on all three stems: PASS on all
three (write side unchanged, badge signal correct end to end through the real
`apply_modification_rules` → `_build_stripped_injected_deltas` → `accumulate_dual_log` pipeline).
The script's own `_is_tt_msg` classifier was updated to delegate to the real
`parser._is_total_tokens_nuke_text` (previously a private bare-tag-only copy) — before that update
`--compare` FAILED on the claude-f sessions because the harness's OWN classification (not the
production code) still called nudge-shaped messages `real_strip`/`mixed`.

**`dev/proxy/test_strip_fix.py`**: 217 → 250 passed. New TT10–TT14: single/combined/repeated known
nudges badge neither word; a nudge mixed with real content (deferred-tools, the old feedback-hook
message) or an unrecognized sentence still badges both; two nudge-shaped messages in one delta stay
quiet together while a third real strip in the same delta keeps it loud; `_is_total_tokens_nuke`
widens for the nudge shape and still rejects real content; the real header renderer produces the
correct words end to end for the new class.

**Regression, unaffected:** `dev/proxy_dual_log/A_render_refactor_proof.py` 14/14 byte-identical,
`dev/proxy_dual_log/test_composition_invariant.py` 12/12, `dev/display/test_hover_map.py` 45/45.

**Not verified:** the live TUI. Everything above drives the real accumulator/badge/replay path
over recorded logs.

## Relevant Symbols / Paths

- `_TOTAL_TOKENS_NUDGE_PARAGRAPHS`, `_TOTAL_TOKENS_TRAILING_TAG_RE`, `_is_total_tokens_nuke_text`,
  `_msg_delta_entry_is_substantial`, `_is_total_tokens_nuke` (`src/proxy_display/parser.py`)
- `dev/proxy_tool_stripping/probe_trailing_message_shapes.py` — the shape measurement, re-runnable
  against the live corpus to catch a future uncatalogued nudge
- `dev/proxy_dual_log/tt_delta_skip_replay.py` — replay harness, `_is_tt_msg` updated to delegate
  to the production shape test
- `dev/proxy/test_strip_fix.py` — TT10–TT14
- Ground-truth logs (2026-09-05 snapshot): `src/logs/dual_log/api_requests_opus_{wise2627_1788612045,
  websearch_1788611995,monitor_cc_1788611156}_*.jsonl` — live, growing logs; absolute counts in
  this entry reflect that one measurement pass, not a fixed corpus size
