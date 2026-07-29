# Recognizing the second CC background-launch-ack wording, 2026-07-29

Milestone-2 fix: the M1 wording inventory (2026-07-29, same area) established exactly 2 distinct
CC background-launch-ack wordings in the recorded corpus and that wording 2 failed all 3
recognition mechanisms in `strip_bg_launch_ack.py`. This entry records the fix and the reasoning
behind each design choice, not just the diff.

## The two wordings

- Wording 1 (initial background launch): `"Command running in background with ID: <id>. Output
  is being written to: <path>. You will be notified when it completes. To check interim output,
  use Read on that file path."`
- Wording 2 (user manually backgrounds an already-running Bash call): `"Command was manually
  backgrounded by user with ID: <id>. Output is being written to: <path>"` — no trailing sentence;
  the ack was the complete block in the only measured corpus occurrence.

Both produce the identical 3-line replacement shape (hold-instruction line, then optional
`Output: <path>`, then optional `ID: <id>`) — the hold-instruction line itself is byte-identical
regardless of which wording matched; only the recovered id/path differ.

## Design choice — two narrow markers/prefixes, OR'd, not one broadened marker

The fast-path gate (`message_passes.py`) and the anchored decision (`strip_bg_launch_ack.py`)
each gained a second constant (`_BG_LAUNCH_ACK_MARKER_2`, `_BG_LAUNCH_ACK_PREFIX_2`) checked via
OR, rather than widening the existing single marker/prefix to a shared broad substring (e.g. a
bare `"with ID:"`). Reasoning: a broadened marker would match arbitrary unrelated text quoting an
id anywhere and reopen exactly the false-positive-nuke class of bug the anchored-match design
already exists to prevent in this file (a real past bug in this repo, per the module's own
comments) — a large tool_result or pasted user message merely containing an ack-like phrase as
quoted data must never be replaced. Two markers, each staying exactly as narrow/specific to its
own wording as the original single marker was, preserve that precision for both wordings
independently instead of trading it away for code brevity.

## Why loosening the ID/PATH extraction regexes is FP-safe, but the prefix check is not touched

`_ACK_ID_RE` was loosened from anchoring on the full wording-1 sentence prefix to anchoring on
just the `"with ID:"` fragment common to both wordings — this is safe ONLY because `_ACK_ID_RE`
and `_ACK_PATH_RE` are exclusively reachable from `_build_launch_ack_replacement`, and every call
site of that function is gated behind a prior `_is_bg_launch_ack(text)` check on the SAME text
(confirmed by reading every call site in `_strip_bg_launch_ack`). By the time either regex runs,
the text is already confirmed a genuine, block-initial-anchored ack — the false-positive surface
lives entirely in `_is_bg_launch_ack`'s `startswith` check, not in what happens to the text
afterward. This is why `_is_bg_launch_ack` was NOT simplified the same way (e.g. to a shared
`"Command"` + `"with ID:"` combination) — that check is the load-bearing FP guard and stays two
full, wording-specific literal prefixes, each as strict as before.

## One alternation regex, not two wording-specific regexes, for both ID and path

Both wordings share the literal `"with ID: <id>."` and `"Output is being written to:"` substrings
verbatim — only wording 2 lacks the wording-1 trailing sentence that the original `_ACK_PATH_RE`
used as its sole terminator. A single regex with an alternation-based terminator (wording-1's
`". You will be notified"` sentence, OR a line boundary, tried in that order) lets
`_build_launch_ack_replacement` stay completely wording-agnostic — it has no branch on which
wording matched, it just calls `.search()` once per field, exactly as before. Splitting into two
parallel wording-specific regexes would have required threading "which wording matched" through
the call, for no benefit given the two wordings' shared substrings.

## The path-regex newline bound — a real failure mode, not hypothetical

The first version of the path-regex fix used `\s*$` (end-of-string) as the fallback terminator for
wording 2 (which lacks the trailing sentence). Hand-verification before implementing surfaced a
real swallowing failure mode with `re.DOTALL` enabled: a wording-2 ack followed by ANY trailing
content in the same block (e.g. `"<wording-2 ack>\nsome trailing note"`) had that trailing content
swallowed whole into the `Output:` line's path capture — the ID line stayed correct, but the
Output line became `path + "\n" + trailing text` instead of just the path. This is not a
constructed hypothetical: the M1 blast-radius classification of this exact pass (measured
separately, same area) already establishes that `_apply_bg_launch_ack_strip` discards "ANY
trailing content after the ack in that block" as part of its own replacement mechanism — a block
with trailing content after the ack is a shape the pass already contemplates, simply unobserved in
the specific corpus snapshot measured for the wording inventory (the one real wording-2 occurrence
happened to BE the entire block). Fixed by adding a literal `\n` as an earlier-tried alternative
in the terminator alternation, bounding the fallback capture to the current LINE rather than the
whole remaining string — `re.DOTALL` itself was kept (removing it wholesale was explicitly
avoided, since the wording-1 branch relies on it to let the path capture cross a hypothetical
internal newline before the real terminator sentence, though this is not exercised by any measured
wording-1 occurrence either). Pinned as a regression guard: real ack text + a trailing line in the
same block → the Output line carries only the path, the trailing text is absent from the entire
replacement, the ID line is unaffected.

## Verification boundary (as of 2026-07-29)

Verified at integration level: real production functions (`_strip_bg_launch_ack`,
`_apply_bg_launch_ack_strip`, `attribute_chunk`) called directly against the exact 220-char
live-observed wording-2 text, a real wording-1 corpus body (pre-existing exact-match regression
guard, confirmed byte-identical output before vs after this change), and a synthetic
trailing-content fixture exercising the newline-bound fix. The false-positive guard was verified
the same way both wordings were verified for wording 1 originally — a message merely containing
the ack phrase as quoted/pasted data, not block-initial, confirmed unchanged. NOT verified against
a restarted live proxy with a genuine CC session where the user actually backgrounds an
already-running Bash call — the running proxy uses a frozen source copy and only picks up a source
change after restart; that gate is still open.

## Relevant Symbols / Paths

- `_BG_LAUNCH_ACK_MARKER`, `_BG_LAUNCH_ACK_MARKER_2`, `_BG_LAUNCH_ACK_PREFIX`,
  `_BG_LAUNCH_ACK_PREFIX_2`, `_is_bg_launch_ack`, `_ACK_ID_RE`, `_ACK_PATH_RE`
  (`src/proxy/strip_bg_launch_ack.py`)
- `_apply_bg_launch_ack_strip`'s fast-path gate (`src/proxy/message_passes.py`)
- `RULES['BL']` marker list (`src/proxy/strip_vocab.py`)
- Regression guards: `W23`/`W24` (`dev/proxy/test_strip_fix.py`), Items 4m-4p
  (`dev/proxy_dual_log/proxy_176_bg_launch_ack_tests.py`)
- Corpus / live observation: `dev/bg_wakeup_id_line/md/launch_ack_wordings_20260729.md`
