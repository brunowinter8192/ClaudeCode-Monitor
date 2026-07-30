# 2026-07-31 — The interrupt-marker strip pass never fired on real payloads

## Problem

`src/proxy/strip_interrupt_marker.py` (merged 2026-07-30) matched on `text == '[Request
interrupted by user]'` — exact equality, no trailing newline. Called with the three variants that
occur in real payloads, only the (never-occurring) newline-less form stripped; both real forms
survived untouched:

```
'[Request interrupted by user]'                    -> removed=1  result='.'
'[Request interrupted by user]\n'                   -> removed=0  result=(unchanged, has '\n')
'[Request interrupted by user for tool use]\n'      -> removed=0  result=(unchanged)
```

Root cause: the header comment's "measured (full dual-log corpus scan): 1791 occurrences" figure
was never a real per-block count — reproducing the methodology (grep across all
`src/logs/dual_log/*.jsonl`, including every `_forwarded`/`_injected`/`_stripped`/`_response`
variant, without deduping by session) counts the SAME historical conversation turn once per
subsequent request in that session, because each request log line re-embeds the full, growing
message history. Same phrase-count methodology on this repo's current corpus (all files, all
variants, undeduped): 2416 block-level hits of the substring `interrupted by user` — 1770 exact
`'[Request interrupted by user]\n'` + 17 exact `'[Request interrupted by user for tool use]\n'`
among the <60-char blocks alone. Neither number is a real occurrence count; both are the same
per-request-resend inflation.

## Re-measurement methodology

Correct count: take the LAST (fullest, most-complete) line of each `*_original.jsonl` session
file — the final request in a session already contains every prior turn in its accumulated
history — and count block-level hits once per session. Result: **11 occurrences across 5 session
files**, all `role='user'`, block `type='text'`, EVERY occurrence trailing-`\n`-terminated:

```
10  '[Request interrupted by user]\n'
 1  '[Request interrupted by user for tool use]\n'
```

Block position: index 1 of 3 (7x), index 1 of 5 (1x), index 0 of 2 (2x — not the fixed "1 of 3"
the original header claimed), 1 case in a session with 3 total occurrences at that same index
across different messages. Never embedded inside longer text in any of the 11. Cross-check:
25 `>=60`-char blocks in the same last-line-per-session scan contain the substring
`interrupted by user` WITHOUT being the bracketed marker as a whole block — genuine longer
content (a user asking about the strip bug, a grep/cat tool_result quoting the module source, an
assistant reply discussing it) — none of these should ever strip, and none do after the fix.

## Fix

- `_is_interrupt_marker`: `text.strip() in _INTERRUPT_MARKERS` — whole-block match after
  stripping only surrounding whitespace, checked against a 2-member frozenset (both real
  wordings). Still anchored, not substring-anywhere — `.strip()` on a 180-char message that merely
  quotes the bracketed marker mid-sentence does not collapse it into the marker (verified against
  a real corpus example, see Verification).
- `message_passes.py`'s fast-path gate (`_content_contains(old_content, _INTERRUPT_MARKER)`) was
  ALSO broken for the "for tool use" wording specifically: the base marker string
  `'[Request interrupted by user]'` is not a substring of
  `'[Request interrupted by user for tool use]'` (no `]` right after `user`) — so even after
  fixing `_is_interrupt_marker` alone, that wording's blocks would never reach the strip function.
  Changed to `any(_content_contains(old_content, m) for m in _INTERRUPT_MARKERS)`, same OR-gate
  pattern already used by `_BD_NOISE_MARKERS` / `_BG_LAUNCH_ACK_MARKER(_2)` in the same file.
- `strip_vocab.py`'s `RULES['IM']` marker list had the same single-wording gap, breaking
  `attribute_chunk` for the "for tool use" removed chunk (it would resolve to `None`, not `'IM'`,
  for that wording specifically — the base-wording marker substring check fails on it for the same
  bracket reason). Added the second wording as a second marker in the same rule entry.

## Verification

`dev/proxy/test_strip_fix.py`: 150/150 passed (was 143 before this session — added W26b, W29,
extended W25/W27/W28 to the real newline-terminated shape). Pure-function + pass-level regression
guards, not a live call chain.

`dev/bg_wakeup_id_line/p3_strip_interrupt_marker_probe.py`: 32/32 passed (was 28 before — added
Test 2b for the "for tool use" wording, extended Test 3's FP guard with the real 180-char corpus
quote, extended Test 4b's attribution check to both wordings). Test 5 runs the REAL
`apply_modification_rules` → real `_build_stripped_injected_deltas` chain end-to-end for the
newline-terminated marker — this is the level at which the original bug would have shown up had
it been probed with the real (newline-terminated) text instead of a hand-typed newline-less
fixture.

Additional ad hoc script (not committed, `/tmp/measure_im2.py`) ran the fix through
`apply_modification_rules` directly for both real wordings and the real 180-char FP example:
both wordings stripped to `'.'` with `stripped_interrupt_marker` in `modifications`; the FP
example left byte-identical with the mod absent from `modifications` — confirms the integration
path, not just the unit-level checks above.

Not verified this session: a live proxy run against a real worker pane (would need a proxy
restart and a live triggered escape) — out of scope for worktree-only verification.
