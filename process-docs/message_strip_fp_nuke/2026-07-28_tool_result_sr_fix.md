# SR Strip Family — Stop tool_result Descent, 2026-07-28

Follow-up to `2026-07-28_tool_result_sr_audit.md` in this area: that session measured 0 genuine
SR-family injections and 1 false positive inside `tool_result` across ~660 real requests, and
named `_apply_sn_notice_strip`/`_apply_bg_exit_strip`'s per-pass non-descent as existing
precedent. This session implemented exactly that option for the SR strip family — no new
heuristic, no fence-parity logic (that was classification evidence for one occurrence, never
proposed as a runtime discriminator).

## Scope decision — rejection branch investigated, excluded

`_apply_first_pass`'s rejection branch (`_message_has_rejection`/`_strip_rejection_message`,
`content_strip.py`) was checked against the SR family definition and does not belong: it imports
nothing from `strip_sr.py`, uses its own marker plus an independent `len(tool_content) <= 200`
guard, and by construction only ever inspects `tool_result` blocks (the loop `continue`s past
every non-`tool_result` block) — a rejection message is CC-native content that only ever exists
there, same category as `bg_launch_ack`/`hook_prefix`/`po_preview`. Left untouched.

## Change — single choke point, defense-in-depth gates, matching bookkeeping

`strip_sr.py::_strip_system_reminders` no longer descends into `tool_result` at all — the branch
now returns the block by IDENTITY (not a rebuilt-but-equal dict), so `_ops_from_content_change`'s
diff-based bookkeeping sees zero change rather than a same-content rebuild. Every SR-family
function bottoms out here (`_strip_system_reminder`, `_strip_user_interrupt_sr`,
`_strip_all_system_reminders`, `_strip_pyright_diagnostics`), so this one change is the actual fix
for all three in-scope passes, including `_apply_final_sr_pass`, which has NO gate of its own —
before this change, `_strip_system_reminders`'s traversal was the ONLY thing between it and
`tool_result` content.

The gate swaps (`_content_contains` → `_top_level_content_contains` in all 4 `_apply_first_pass`
SR branches and all 4 `_apply_cumulative_sr_strips` gates) are strictly redundant once the
traversal fix lands — worth stating plainly so a passing test suite doesn't get credited to the
wrong mechanism. They were kept anyway, matching the `sn_notice`/`bg_exit` precedent exactly: each
function's contract (what it checks) now matches its behavior (what it can possibly touch),
rather than relying solely on a downstream no-op.

`_find_system_reminder_blocks`/`_find_all_system_reminder_blocks` (`payload_helpers.py`) had their
`tool_result` branches removed too — grep confirmed these two functions are called exclusively by
the three in-scope passes (message_passes.py lines 168/180/190/200/267/268/294/296), so this was
safe without touching any other pass, and necessary: without it, `pass_removed_by_idx` (feeding
the monitor's removed-content display) would keep reporting `tool_result` chunks as removed after
the strip stopped touching them.

## Verification

`dev/proxy/test_strip_fix.py`: 50 test functions, 81/81 checks pass. Ten template/shape tests
inverted from "stripped inside tool_result" to "preserved byte-exact" (task-tools-nag, pyright,
deferred-tools, user-interrupt partial-mode, system-notification, file-modified, claudemd,
date-changed, both tool_result shape tests); three FP tests that combined a code-literal fake with
a real trailing SR in one tool_result blob had their "real stripped" half inverted to "real now
preserved" too. `_find_system_reminder_blocks`'s pair was kept spanning both sides of the new
boundary rather than becoming a near-duplicate: one case stays on `tool_result` and now asserts 0
found, the other moved to top-level asserting the real SR IS found. Two new tests give
`_apply_final_sr_pass` (the ungated pass) extra scrutiny: both `tool_result` content shapes (str
and list-of-text) assert full untouched content AND identity-preserved block objects. One new test
reproduces the real Occurrence-8 shape (env-context SR fenced inside a markdown code block inside a
`tool_result`, mirroring an actual RAG-search excerpt) and asserts byte-exact preservation. Two more
demonstrate the scope reduction is real, not a disable: task-tools-nag still strips at top level via
`_apply_first_pass`, and date-changed — a template with no dedicated first-pass branch, only reached
via `_apply_final_sr_pass`'s catch-all — still strips too.

Re-running `dev/strip_fp_tool_result/audit_tool_result_sr_strips.py` against the same live corpus
(6 files, one self-excluded, ~660 requests incl. the 2.2GB `wise2627` log) after the fix: SR-family
tool_result occurrences went from 1 to 0; the non-SR passes' occurrence count kept growing only
because two of the scanned sessions were still live during this work (documented in that audit's
own report) — same three templates, same genuine classification, nothing regressed in the family
this fix did not touch.

## Note on git diff scope

Only 3 `src/` files touched (`strip_sr.py`, `message_passes.py`, `payload_helpers.py`) plus the test
file and the audit tool/report. None of `strip_git_lock.py`, `strip_hook_prefix.py`, `strip_po.py`,
`strip_bg_completed.py`, `strip_bg_launch_ack.py`, `strip_bd_noise.py`, `content_strip.py` were
touched — confirming the non-SR passes' correct, necessary `tool_result` descent was left alone.
