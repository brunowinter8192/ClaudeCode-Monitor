# Carrying the Background-Task ID Into Both Proxy-Side Wake-Up Messages, 2026-07-29

New area — driving question: how does the model learn WHICH background task a wake-up message
refers to, across both the launch-ack and the termination messages the proxy already rewrites?
Distinct from `message_strip_fp_nuke` (that area's question is "where does a content-blind strip
destroy legitimate content" — a false-positive-nuke investigation thread); this is a forward
enrichment of two messages that were already correct, not a bug fix in that class, even though it
touches two of the same files (`strip_bg_launch_ack.py`, `message_passes.py`'s TN branch).

## Goal

Both proxy-side background messages become 3 lines, same shape at launch and at termination:
```
<message line>
Output: <output-file path>
ID: <task id>
```
Launch (`strip_bg_launch_ack.py`) previously discarded both the id and the path from the CC ack it
replaces. Termination (`message_passes.py`'s `_apply_first_pass` TN branch) already carried
`Output:` (added in an earlier iteration) but not the id.

## Real recorded shapes — verified before writing code

Measured against `src/logs/dual_log/api_requests_opus_monitor_cc_1785336796_original.jsonl` +
`api_requests_opus_posts_1785338463_original.jsonl`: 12 unique real launch-acks and 12 unique real
TN blocks, byte-identical structure in every occurrence, id+path/id+output-file both present in
100% of them (0 missing either field). Ack shape:
```
Command running in background with ID: <id>. Output is being written to: <path>. You will be
notified when it completes. To check interim output, use Read on that file path.
```
TN block shape (unchanged from prior sessions):
```
<task-notification>
<task-id><id></task-id>
<tool-use-id>...</tool-use-id>
<output-file><path></output-file>
<status>completed|failed</status>
<summary>...</summary>
</task-notification>
```

## Extraction

- Ack: two new regexes in `strip_bg_launch_ack.py` — `_ACK_ID_RE` (`[^.]*` up to first `.`, safe
  since every measured id is a dot-free alnum token), `_ACK_PATH_RE` (non-greedy up to the literal
  `. You will be notified` — NOT up to the first dot, since the path routinely contains one, e.g.
  the `.output` extension; a first-dot-stop regex would have truncated every real path).
- TN: new `_extract_task_notification_task_id` in `payload_helpers.py`, a direct mirror of the
  pre-existing `_extract_task_notification_output_file` (`<task-id>(.*?)</task-id>`, DOTALL,
  searched inside `_find_task_notification_blocks(content)`, `''` if absent).

Both verified against the real bodies above before implementing (one-off replay), then pinned as
permanent regression guards (`dev/proxy/test_strip_fix.py` W18/W19 — real ack + real TN block,
exact-string assertions).

## Design choice — build once, reuse never (deliberately NOT shared)

Both sites (launch, termination) independently extract their own id/path and build their own
3-line string via the same shape: `lines = [<message line>]`, append `Output: <path>` only if
non-empty, append `ID: <id>` only if non-empty, join with `\n` + trailing `\n`. No shared helper
function was extracted between the two sites — considered and rejected, because the two sources
are structurally different (a single ack sentence to regex-parse vs. an already-XML-tagged TN
block with existing extraction helpers). The single-source-of-truth concern that matters for THIS
class of change is duplicating the SAME extraction+construction sequence across multiple call
sites for the SAME source content — that does not apply here, since launch and termination parse
genuinely different inputs; two independent 3-liner builders is not that class of duplication.

The termination-path refactor from a 2-branch ternary (`output_path present → 2 lines` /
`absent → bare wakeup`) to an unconditional `lines`-list join is a deliberate simplification:
`_WAKEUP_TEXT` itself already ends in exactly one `\n`, so `'\n'.join([_WAKEUP_TEXT.rstrip('\n')])
+ '\n'` collapses to `_WAKEUP_TEXT` byte-for-byte when neither optional line applies — pinned as
its own regression guard (W22) precisely because it's a refactor-equivalence claim, not just new
functionality.

## `_apply_bg_exit_strip` / `strip_bg_completed.py` — confirmed unchanged, by design

The BGK kill-notification path (`Background command "..." failed/completed (exit code 143/137)`)
shares `_WAKEUP_TEXT` with the TN path but carries no id and no path in its own notification text
— there is nothing to extract. `git diff` on `strip_bg_completed.py` for this session is empty;
it still emits exactly the bare wake-up line it always did.

## Missing-value behavior — defined, not observed in production

Not exercised by real data (12/12 real acks and 12/12 real TN blocks had both fields), so this is
a defensive contract only, tested with synthetic fixtures: an id-less ack (empty capture between
`ID:` and the following `.`), a path-less ack (no `Output is being written to:` segment at all), a
TN block missing `<task-id>`, a TN block missing `<output-file>`, and a TN block missing both. In
every case the corresponding line is OMITTED, never emitted as `ID: None` or a dangling label.

## Pre-existing stale test drift, corrected in the same commit

`dev/proxy_dual_log/proxy_176_bg_launch_ack_tests.py` (4a–4d) asserted `content == "."` — stale
before this session even started (the function has emitted the long hold-instruction sentence, not
`"."`, since some earlier unrecorded change; confirmed via `git stash` baseline in the immediately
preceding session that these 4 failures predate this work). Updated to assert against the new
3-line literal rather than leave them broken against a third, now-also-wrong string.
`dev/proxy/proxy_bgcomplete_tests.py` B01/B02/B04 fixtures already carried `<task-id>` in their TN
blocks (added for an earlier iteration, unused until now) — `expected_injected` and `injected.get`
assertions updated to include the new `ID:` line; B03 (no id, no output-file in its fixture) was
unaffected and stayed green throughout, serving as an incidental confirmation that the neither-
present path was untouched by the refactor.

## Verification

**Regression guards** (`dev/proxy/test_strip_fix.py`): 119/119 passing — 8 new (W15–W22) covering
launch-ack id+path recovery, both missing-value cases, one real-corpus-body exact pin (W18), TN
missing-task-id / missing-output-file / missing-both, and one real-corpus-body exact pin (W19).

**Existing suites, all green after the fixture updates above:**
`dev/proxy_dual_log/proxy_176_bg_launch_ack_tests.py` (0 FAIL, down from 4 pre-existing),
`dev/proxy/proxy_bgcomplete_tests.py` (0 FAIL after fixture updates),
`dev/proxy_dual_log/proxy_176_strip_tests.py`, `dev/proxy_dual_log/proxy_176_agent_types_tests.py`,
`dev/proxy_dual_log/test_composition_invariant.py` (12/12) — all unaffected.

**Integration-level, real recorded data:** replayed the 2 real acks + 2 real TN blocks traced from
the corpus above through the actual production functions (`_strip_bg_launch_ack`,
`_apply_first_pass`) — both produce the exact canonical 3-line text.

**NOT verified:** live proxy restart / a genuine CC session launching and completing a real
background task — the running proxy uses a frozen source copy and only picks up a fix after
restart.

## Relevant Symbols / Paths

- `_build_launch_ack_replacement()` (`src/proxy/strip_bg_launch_ack.py`) — new, builds the 3-line
  launch message from a genuine ack's own text
- `_ACK_ID_RE`, `_ACK_PATH_RE` (`src/proxy/strip_bg_launch_ack.py`) — ack-text extraction
- `_extract_task_notification_task_id()` (`src/proxy/payload_helpers.py`) — new, mirrors
  `_extract_task_notification_output_file()`
- `_apply_first_pass()` TN branch (`src/proxy/message_passes.py`) — `lines`-list refactor,
  3rd optional `ID:` line
- Ground-truth logs: `src/logs/dual_log/api_requests_opus_monitor_cc_1785336796_original.jsonl`,
  `src/logs/dual_log/api_requests_opus_posts_1785338463_original.jsonl`
