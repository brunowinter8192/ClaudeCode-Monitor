# 2026-07-30 — Stripping the "[Request interrupted by user]" marker

## Problem

`src/proxy/bg_escape.py` sends a tmux Escape into a worker's pane when the proxy detects a genuine
background-launch ack, to force the worker idle before it can poll the newly-backgrounded task
(see the 2026-07-29/30 entries in this folder for that mechanism's own history). Claude Code
records that Escape in the conversation exactly the way it records a genuine user Ctrl-C/Escape —
a block whose text is `[Request interrupted by user]`. No user interrupted anything, but the
worker reading the marker cannot tell the difference: it halts and waits for an instruction nobody
intended to give. Live example this session: worker `esc-live2` replied "I was interrupted right
at the point of pivoting to Step 2 … Waiting for the orchestrator's next instruction."

## Measured shape (full dual-log corpus scan, as of 2026-07-30)

1791 occurrences across 4 log files. Every single occurrence: `role='user'`, block `type='text'`,
block text EXACTLY `[Request interrupted by user]` — never embedded inside longer text. Position
stable: block index 1 of 3, preceded by a `tool_result` or `text` block, preceding the proxy's
injected wake-up text. The corpus data itself was supplied as measurement input to this session
(not re-run here — this worktree carries no `src/logs/dual_log/` corpus); the new dev probe
(`dev/bg_wakeup_id_line/p3_strip_interrupt_marker_probe.py`) reproduces the shape as a synthetic
fixture rather than re-scanning it.

## Decisions

**Exact-equality match, not anchored-prefix.** Every other strip pass in this family
(`strip_bg_launch_ack.py`, `strip_sn_notice.py`) anchors on `text.lstrip().startswith(prefix)`
because their target text can have trailing content in the same block. The interrupt marker is
always the block's ENTIRE text in the measured corpus, so `text == marker` is both sufficient and
strictly tighter than `startswith` — no FP surface to close beyond the trivial "marker quoted
inside a longer message," which exact-equality already excludes by construction.

**Emptied-block handling: replace the marker block's text with `'.'` in place, do NOT splice the
block out of the content list.** The marker occupies its own whole block among two others
(tool_result / marker / wake-up). Splicing it out looked structurally cleaner at first (no dangling
`'.'` placeholder) — dismissed once `rule_ops.py::_ops_from_content_change` was checked: it walks
old-content and new-content BY INDEX (`for bi in range(max(len(old), len(new)))`). Removing block 1
from a 3-block list shifts the wake-up block from index 2 to index 1, so the index-keyed comparison
would diff the OLD marker text against the NEW wake-up text at index 1 (read as a spurious "edit"),
and see the wake-up block itself as a deletion at index 2 — corrupting `strip_inject_delta.py`'s
`fn_map`/span attribution for the wake-up block, not just the marker's own. Emptying to `'.'` in
place keeps block count and every subsequent index untouched — the same convention the other passes
already use for a block reduced to nothing (the API rejects an empty text block). Precedent for
whole-block removal DOES exist in this codebase (`message_passes.py::_dedup_wakeup_blocks`, which
drops duplicate wake-up blocks from the list) — its ops recording has the same by-index blast
radius on the block(s) after the removed one; it was accepted there because that pass runs LAST
(after `rule_ops` has already recorded ops from all earlier passes) and the display-instrumentation
imprecision was judged tolerable for a dedup-only pass. Deliberately not extending that tolerance to
a new pass added earlier in the pipeline.

**Rule code `IM`, mod name `stripped_interrupt_marker`.** Wired through the same 4 registration
points every pass in this family needs: `message_passes.py` (`_apply_interrupt_marker_strip`),
`rules.py` (`_passes` list, appended last), `strip_vocab.py` (`RULES['IM']`), `strip_inject_delta.py`
(`_MSG_CODE_TO_FN['IM']`) — the last of these is what keeps the stripped chunk's `fn_map` entry
resolving to a named function instead of falling through to `unknown`, the exact failure mode this
session's `2026-07-30_live_verify_three_backgrounding_paths.md` entry documented for two other
codes (`SNP` missing from `_MSG_CODE_TO_FN`, proxy-authored injected text matching no marker).

## Verification

Regression guards folded into `dev/proxy/test_strip_fix.py` (W25-W28, pure-function + pass-level):
real 3-block shape with byte-identical neighbors, all 4 content shapes, marker-embedded-in-longer-
text left untouched, message-pass role-gating + mod naming. Full suite: 143/143 passed.

New dev probe `dev/bg_wakeup_id_line/p3_strip_interrupt_marker_probe.py`, 28/28 checks, adding one
level beyond the regression guards: a full-pipeline run through the REAL `apply_modification_rules`
followed by the REAL `_build_stripped_injected_deltas`, asserting
`fn_map['msg.0.1'] == '_apply_interrupt_marker_strip'` (not `'unknown'`) — proving attribution
resolves end-to-end through the same call chain production uses, not just at the unit level.

Adjacent suites re-run for regression: `dev/proxy_dual_log/test_composition_invariant.py` (12/12),
`dev/bg_wakeup_id_line/p2_bg_escape_probe.py` (29/29, unaffected — `bg_escape.py` itself untouched).
`dev/proxy/test_schema_check.py` fails on import (`_check_payload_schema` missing from `addon.py`)
both before and after this session's changes (checked via `git stash`) — pre-existing, unrelated.

Not verified at this session: the live entry-point (a real mitmproxy instance forwarding a real
worker's payload) and a real worker session observing the marker's absence — both require a proxy
restart and live worker trigger, out of scope for worktree-only verification.
