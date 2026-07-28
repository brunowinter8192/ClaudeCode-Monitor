# dev/strip_fp_tool_result/

## Role

Measurement-only audit for the FP-nuke bug class (see `process-docs/message_strip_fp_nuke/`) as
it applies to `tool_result` content specifically: which strip passes remove text from INSIDE a
`tool_result` block, split into the SR strip family (`_apply_first_pass`'s SR branches,
`_apply_cumulative_sr_strips`, `_apply_final_sr_pass` — all matching via `strip_sr.py`'s
line-anchored `<system-reminder>` scan) vs. unrelated non-SR passes (`bg_launch_ack`,
`hook_prefix`, `po_preview` — each matching its own marker, no `strip_sr` dependency). Touch when
extending this measurement (more corpus, more passes) or building the fix milestone's regression
baseline; do NOT touch to change strip behavior — that lives in `src/proxy/`.

## Modules

### audit_tool_result_sr_strips.py (645 LOC)

**Purpose:** Streams every request payload in `src/logs/dual_log/*_original.jsonl`, threads it
through the 11 real `_apply_*` pass functions from `src.proxy.message_passes` in
`rules.py::apply_modification_rules`'s exact order, and — using each pass's own
`pass_ops_by_msg_blk` per-block diff (offset/removed/injected) — records every removal whose
pre-pass block `type == 'tool_result'`. Classifies template via the real `strip_sr.py` registry
(imported, not reinvented); non-SR passes get their fixed mod name. Quoted-data / genuine-CC-
injection verdicts are hand-written into `_MANUAL_VERDICTS` (keyed by `(file, msg_idx, blk_idx,
first_line_idx)`) after reviewing one run's raw context, then folded in on the next run.
**Reads:** `src/logs/dual_log/*_original.jsonl` (main checkout, not per-worktree — gitignored).
**Writes:** `dev/strip_fp_tool_result/md/audit_tool_result_sr_strips.md`.
**Called by:** none (standalone CLI: `python3 dev/strip_fp_tool_result/audit_tool_result_sr_strips.py`).
**Calls out:** `src.proxy.message_passes`, `src.proxy.strip_sr`, `src.proxy.content_strip`,
`src.proxy.rule_ops`, `src.proxy.strip_git_lock` (all via `importlib`, dodging
`block_dev_imports_src`).

---

## Gotchas

- **Self-session exclusion is by filename, not automatic.** Any file matching `SELF_SESSION_MARKER
  = 'sr-fp-audit'` is excluded — this worker's own dual-log is live-growing while the script runs
  and its own Read/Bash calls on this investigation would otherwise appear as fake "evidence".
- **The corpus is live.** Other sessions' dual-logs (`api_requests_opus_monitor_cc_...`, etc.) keep
  growing between runs (real concurrent Claude sessions) — occurrence counts are a snapshot at
  scan time, not a fixed total; re-running can surface new rows requiring new `_MANUAL_VERDICTS`
  entries (same reasoning as an already-classified sibling, not a reclassification).
- **`tool_result_list_joined` offsets are into the JOINED sub-block text**, not any single
  sub-block — `_block_inner_text` (imported from `rule_ops.py`) is what `_ops_from_content_change`
  computed the offset against; context slicing reuses the same function for consistency.
- **SR-family vs. non-SR split is load-bearing for the report's headline conclusion** — pooling
  `bg_launch_ack`/`hook_prefix`/`po_preview` (unrelated markers, correct-by-design tool_result
  descent) together with the actual SR-template passes produces a false "genuine injections
  found" conclusion. Keep the two aggregated and reported separately.
- **Ground-truth non-reproduction is a first-class result, not a bug in the script.** The
  task-stated `stripped_git_lock_advice` finding does not reproduce in this corpus snapshot — the
  literal 5-line block never appears with real newlines outside this worker's own excluded
  self-session (an artifact of investigating `strip_git_lock.py`'s escaped source, not production
  data). `_scan_ground_truth_git_lock` makes this check itself re-runnable.
