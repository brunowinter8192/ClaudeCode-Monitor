# CC background-launch-ack wording inventory — measurement, 2026-07-29

Milestone-1 measurement task: quantify, before any fix, how many DISTINCT CC background-launch
acknowledgement wordings exist in the real recorded corpus, and whether the proxy's 3 recognition
mechanisms (`_BG_LAUNCH_ACK_MARKER` fast-path gate, `_BG_LAUNCH_ACK_PREFIX` startswith check,
`_ACK_ID_RE`/`_ACK_PATH_RE` extraction — all in `strip_bg_launch_ack.py`) fire on each.
No production code touched. Script: `dev/bg_wakeup_id_line/p1_scan_launch_ack_wordings.py`.

## Trigger

A live session earlier the same day observed CC emitting a SECOND launch-ack wording (when the
user manually backgrounds an already-running Bash call) that the proxy's `_BG_LAUNCH_ACK_PREFIX`
anchor does not recognize at all — no replacement, original text forwarded verbatim. The 220-char
live-observed text (id/path redacted): `Command was manually backgrounded by user with ID:
<id>. Output is being written to: <path>` — notably missing the trailing `. You will be notified
when it completes...` sentence the existing `_ACK_PATH_RE` uses as its terminator.

## Corpus

`src/logs/dual_log/*_original.jsonl`, 6 session files present at scan time. Included 4: two prior
completed Opus sessions (`opus_monitor_cc_1785336796`, `opus_posts_1785338463`), one long Opus
session (`opus_wise2627_1785324012`), one prior worker session (`worker_..._tn-role-system_
1785344818`). Excluded 2: the currently-live orchestrating Opus session
(`opus_monitor_cc_1785347492`, still growing at scan time) and this worker's own worktree activity
(`worker_..._bg-ack-shapes_1785359201`, proxy log starting at dispatch time) — both would let the
measurement's own tool calls masquerade as corpus evidence.

**Contamination beyond file-level exclusion:** `opus_posts` and `tn-role-system` are themselves
prior investigative sessions on this exact defect area. Raw substring grep for `"Output is being
written to:"` hit not just genuine acks but source lines (`_ACK_PATH_RE = re.compile(...)`),
templated dev-report printouts (`${O}`, `<pfad>`, `#3: '...'`), and Read-tool dumps of
`strip_bg_launch_ack.py` — reappearing in every later cumulative dual-log snapshot of that session.
Blanket-excluding those files would also discard genuine acks the same sessions produced by
actually running real background Bash calls. Resolved with a structural filter instead of file
exclusion: a candidate is only counted if the JSON-parsed block's FULL text starts with `Command`
at position 0 — Read-tool dumps start with line numbers, docstrings start with other prose, report
printouts start with `===`/`#N:`, none of them satisfy a block-initial match.

**Dedup:** dual-log lines are cumulative snapshots of the whole conversation so far; a message once
introduced reappears verbatim in every later request of its session. Deduped via a
prev-message-count delta (only `messages[prev_count:]` inspected per request) rather than raw
substring counting. Demonstrated concretely: one genuine occurrence (same `toolu_id`, same text)
appeared raw 1014 times across the cumulative snapshots of `opus_monitor_cc_1785336796` alone;
deduped, that session contributed 16 genuine occurrences total.

## Findings (as of 2026-07-29, 511 requests scanned across the 4 included sessions)

Exactly 2 distinct wordings found, no others, despite the structural filter being deliberately
broad (`Command` + `with ID:` + `Output is being written to:`, not hardcoded to either exact known
wording):

1. `Command running in background with ID: <id>. Output is being written to: <path>. You will be
   notified when it completes. To check interim output, use Read on that file path.` — 15 deduped
   occurrences, 2 of 4 sessions, role=user, shape=tool_result_str. All 3 mechanisms fire correctly
   (`_BG_LAUNCH_ACK_MARKER` fires, `_BG_LAUNCH_ACK_PREFIX` fires, both regexes extract).
2. `Command was manually backgrounded by user with ID: <id>. Output is being written to: <path>` —
   1 deduped occurrence, 1 of 4 sessions, role=user, shape=tool_result_str. Matches the live-
   observed text's template exactly. ALL 3 mechanisms fail: it does not contain `"running in
   background with ID"` so the fast-path gate never even reaches the replacement walker; the
   prefix startswith check fails (`"Command was manually"` ≠ `"Command running"`); both regexes
   fail to extract (anchored on the wrong literal prefix).

No third wording found. A long-running Bash call WITHOUT `run_in_background` is killed on timeout
(exit 143), not backgrounded, per a separate live observation the same day — consistent with
finding no third launch-wording family in the corpus.

## Corpus was not static during measurement — counts are a lower bound

The corpus continued growing during/after this measurement. `opus_posts_1785338463` was 105 lines
at this scan's time but had grown to 143 lines (with an mtime after this run) when independently
re-checked shortly afterward during review — meaning that session was ALSO live-growing at
measurement time, not just the excluded currently-live session. A separate measurement run ~15
minutes later, driving the same 4 files through a different script for a related deliverable,
scanned 523 requests instead of 511 on the nominally same corpus — direct evidence of the drift.
Consequence: 15/1 are a lower bound on a moving snapshot, not a final static total — a rescan of
the grown corpus could surface additional (deduped) occurrences of either wording, not fewer. An
independent re-scan on the grown corpus reproduced the identical 15/1 split and the same 2
distinct wordings — the qualitative conclusion held under corpus growth even though the exact
counts are not final.

## Relevant Symbols / Paths

- `_BG_LAUNCH_ACK_MARKER`, `_BG_LAUNCH_ACK_PREFIX`, `_ACK_ID_RE`, `_ACK_PATH_RE`
  (`src/proxy/strip_bg_launch_ack.py`) — the 3 recognition mechanisms measured
- `dev/bg_wakeup_id_line/p1_scan_launch_ack_wordings.py` — measurement script, re-runnable
- `dev/bg_wakeup_id_line/md/launch_ack_wordings_20260729.md` — full report (per-wording verbatim
  text, mechanism fire/no-fire table, dedup evidence)
- Corpus: `src/logs/dual_log/api_requests_{opus_monitor_cc_1785336796,opus_posts_1785338463,
  opus_wise2627_1785324012,worker_25c51a2e_tn-role-system_1785344818}_original.jsonl`
