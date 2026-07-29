# D1 — bg-launch-ack wording inventory (real corpus)

Generated: 2026-07-29T21:27:41Z

## Corpus

| File | Included | Notes |
|---|---|---|
| `api_requests_opus_monitor_cc_1785336796_original.jsonl` | yes | |
| `api_requests_opus_posts_1785338463_original.jsonl` | yes | |
| `api_requests_opus_wise2627_1785324012_original.jsonl` | yes | |
| `api_requests_worker_25c51a2e_tn-role-system_1785344818_original.jsonl` | yes | |
| `api_requests_opus_monitor_cc_1785347492_original.jsonl` | **excluded** | currently-live session — last entry 2026-07-29T21:06:45Z, ~3min before this worker started (2026-07-29T21:06:41Z); this is the actively-dispatching Opus session |
| `api_requests_worker_25c51a2e_bg-ack-shapes_1785359201_original.jsonl` | **excluded** | this worker's own worktree activity — proxy log starts exactly at dispatch time |

Total requests scanned (deduped pass): 511

## Corpus was NOT static during measurement — counts are a lower bound, not a fixed total

**Review addendum (2026-07-29, post-review):** this run's own request count (511) does not match
the D2 measurement run's count on the nominally identical 4-file corpus (523, ~15 min later) — a
divergence caused by `api_requests_opus_posts_1785338463_original.jsonl` also growing during/after
these runs (105 lines at scan time here, 143 lines and an mtime AFTER both runs when independently
re-checked in review). This means the `posts` session was ALSO live-growing at measurement time —
not just `api_requests_opus_monitor_cc_1785347492` (which was excluded up front for exactly this
reason). Consequence: the occurrence counts below (15 / 1) are a **lower bound on a moving
snapshot**, not a static, final total — a rescan of the grown corpus could show more (deduped)
occurrences of either wording, though not fewer. An independent reviewer re-scan on the grown
corpus reproduced the same 15/1 split and the same 2 distinct wordings — the qualitative
conclusion (exactly 2 wordings; wording B present, real, not fabricated) held up under corpus
growth, even though the exact counts are not final numbers.

## Contamination trap (beyond the 2 named exclusions)

`api_requests_opus_posts_1785338463` and `api_requests_worker_..._tn-role-system_1785344818` are themselves PRIOR investigative sessions on this exact defect area — raw substring grep for `"Output is being written to:"` hits source lines (`_ACK_PATH_RE = re.compile(...)`), templated dev-report printouts (`${O}`, `<pfad>`, `#3: '...'`), and Read-tool dumps of `strip_bg_launch_ack.py`, not just genuine acks. Blanket-excluding these files would also discard genuine acks those sessions produced by actually running background Bash calls. Fix applied: **structural filter, not file exclusion** — a candidate is only counted if the JSON-parsed block's FULL text starts with `Command` at position 0 (checked in `_looks_like_launch_ack_candidate`). Source dumps/reports never satisfy this (Read output starts with line numbers, docstrings start with other prose, report printouts start with `===`/`#N:`).

## Dedup importance (raw vs deduped)

| Session | Raw candidate-block occurrences (all cumulative snapshots) | Deduped (new-message-only) |
|---|---|---|
| `api_requests_opus_monitor_cc_1785336796_original.jsonl` | 1014 | 16 |
| `api_requests_opus_posts_1785338463_original.jsonl` | 176 | 15 |
| `api_requests_opus_wise2627_1785324012_original.jsonl` | 0 | 0 |
| `api_requests_worker_25c51a2e_tn-role-system_1785344818_original.jsonl` | 0 | 0 |

Confirms cumulative dual-log duplication: a single genuine occurrence (same `toolu_id`, same text) reappears in every later request of its session — raw grep would wildly overcount.

## Live-observed text (2026-07-29, from prompt) — corpus cross-check

Matches corpus template (`Command was manually backgrounded by user with ID: <ID>. Output is bei...`) — found in corpus independently, see wording table below.

## Distinct wordings

### Wording 1

- Occurrences (deduped): **15**
- Sessions: ['api_requests_opus_monitor_cc_1785336796_original.jsonl', 'api_requests_opus_posts_1785338463_original.jsonl'] (2 of 4 scanned)
- Roles seen: ['user']
- Content shapes seen: ['tool_result_str']

**Verbatim example (volatile id/path bolded):**

```
Command running in background with ID: **<ID>**. Output is being written to: **<PATH>** You will be notified when it completes. To check interim output, use Read on that file path.
```

**Mechanism fire/no-fire:**

| Mechanism | Result |
|---|---|
| `_BG_LAUNCH_ACK_MARKER` fast-path gate (`'running in background with ID'` in text) | FIRES |
| `_BG_LAUNCH_ACK_PREFIX` startswith check | FIRES |
| `_ACK_ID_RE` | extracts: baky5k8lf |
| `_ACK_PATH_RE` | extracts: /private/tmp/claude-501/-Users-brunowinter2000-Documents-ai-monitor-cc/80b146dd-9d9e-4cae-83c0-a1bbebb9e0cb/tasks/baky5k8lf.output |

### Wording 2

- Occurrences (deduped): **1**
- Sessions: ['api_requests_opus_monitor_cc_1785336796_original.jsonl'] (1 of 4 scanned)
- Roles seen: ['user']
- Content shapes seen: ['tool_result_str']

**Verbatim example (volatile id/path bolded):**

```
Command was manually backgrounded by user with ID: **<ID>**. Output is being written to: **<PATH>**
```

**Mechanism fire/no-fire:**

| Mechanism | Result |
|---|---|
| `_BG_LAUNCH_ACK_MARKER` fast-path gate (`'running in background with ID'` in text) | does NOT fire |
| `_BG_LAUNCH_ACK_PREFIX` startswith check | does NOT fire |
| `_ACK_ID_RE` | FAILS to extract |
| `_ACK_PATH_RE` | FAILS to extract |

## Additional wordings sought but not found

Prompt notes a long-running Bash call WITHOUT `run_in_background` is killed on timeout (exit 143), not backgrounded — no third launch wording expected from that path, and none was found. The structural filter (`Command` + `with ID:` + `Output is being written to:`) is broad enough to catch unknown wordings in the same family; none beyond the ones listed above were found in this corpus.
