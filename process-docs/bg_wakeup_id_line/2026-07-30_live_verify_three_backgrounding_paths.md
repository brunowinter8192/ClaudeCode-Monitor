# 2026-07-30 — Live verification of bg wake-up messages across all three backgrounding paths

Proxy instance: port 8082, addon snapshot `.proxy_addon_live_25c51a2e_19281_1785364138.py` (started 00:28).
Dual-logs read: `src/logs/dual_log/api_requests_opus_monitor_cc_1785364138_{stripped,injected}.jsonl`.

## What was verified

Six messages observed against the running proxy — launch-ack and termination for each of the three ways a
task reaches the background:

| path | launch-ack task id | termination task id |
|---|---|---|
| manual (user presses the background key on a running fg call) | `b0uuj7aq0` | `b0uuj7aq0` |
| explicit (`run_in_background: true`) | `blh1fibsh` | `blh1fibsh` |
| auto (CC moves a long-running fg call to background by itself) | `brwfy55a5` | `brwfy55a5` |

All six arrived at the model in the canonical three-line shape:

```
<message>
Output: /private/tmp/claude-501/<encoded-project>/<session>/tasks/<id>.output
ID: <id>
```

Launch line 1: `Command is running in the background. Do NOT check, poll, or read its output — just wait
until it finishes (you will get a completion notice).`
Termination line 1: `background done — check worker or other process`

No dot-nuke on termination in any of the six — the wake-up text arrives as text, not as a bare `.`.
The launch-ack text is byte-identical across all three paths; the proxy does not discriminate by origin.

## Pane rendering

Every one of the six requests showed header signature `1strip 1inj`, with the injected three-line block
rendered as ONE contiguous green area (no unhighlighted leading word on its own line) and the stripped
original below it in olive. The two colors are the two directions: green = injected by the proxy,
olive = removed by the proxy.

The two-line split defect that was on file for the replaced launch-ack did NOT reproduce. Cause is not a
fix to the span computation — `rule_ops.py::_extract_block_op` still strips common prefix/suffix — but the
reworked replacement text no longer shares a leading word with its original, so nothing gets trimmed and
the replacement lands as one span. The latent condition remains: a future replacement text that shares its
first word with the original would bring the split back.

## Termination fires on both exit outcomes

The stripped-side original for the manual and explicit runs carried `<status>failed</status>` with exit
code 144 (the loop was killed); the auto run carried `<status>completed</status>` with exit code 0. Both
outcomes produce the same three-line wake-up — the replacement is not conditional on the exit status.

## fn_map attribution is wrong for all three terminations

Injected-side `fn_map` labelled all three terminations `_apply_bg_exit_strip`. None came from that pass:

- the stripped chunks for those messages are the SN-notice paragraph plus the `<task-notification>` block
  — no chunk starting with `Background command "`, which is what the BGK path would record
- the auto run had exit code 0, which `_BG_EXIT_RE` in `strip_bg_completed.py` explicitly excludes

Actual origin is `_apply_first_pass`'s TN branch. Cause is the hardcoded text test in
`strip_inject_delta.py` (`elif "background done" in i_text:` → `_apply_bg_exit_strip`): both paths emit
that same sentence deliberately, so the wrong one always wins.

Two further attribution gaps found while reading:

- the three launch-ack replacements are `unknown` on the injected side — proxy-authored text carries none
  of the strip markers `attribute_chunk` looks for, so nothing matches by construction
- the three wake-up messages are `unknown` on the STRIPPED side even though `attribute_chunk` correctly
  returns `SNP` for the chunk — `_MSG_CODE_TO_FN` has no `SNP` entry, so a correctly derived code falls
  through to `unknown`

Common root: attribution is GUESSED from text instead of carried. `rules.py`'s pass loop knows the running
function name in every iteration; `_merge_ops` discards it. Additionally the `fn_map` shape allows only ONE
name per location key, so two passes touching the same block collapse to one label regardless.

## Full-collection delete/re-index round trip (used as the auto-background trigger)

`rag-cli delete --collection trading-reference --document Tsay2010AnalysisFinancialTimeSeries.md` removed
998 chunks plus both on-disk files (`.md` and the `.json` sidecar). Re-indexing after copying the `.md`
back restored 998 chunks and regenerated the sidecar byte-identical to the pre-delete backup; a scoped
search returned 12 hits with top score 0.999. Same round trip on
`HansenLundeNason2011ModelConfidenceSet.md` (127 KB): 96 chunks, sidecar byte-identical.

Both re-index runs were auto-backgrounded by CC — this is the reliable way to produce the auto path on
demand.
