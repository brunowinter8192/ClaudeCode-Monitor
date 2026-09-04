# 2026-09-04 — Correction: sys/tool tail must use MEASURED wire chars, sys[0] must stay untouched

Same-day correction to the sys/tool original-chars feature this area's other 2026-09-04 entry
describes. Caught on review of the merged `msgs` output for `monitor_cc_1788464543` REQ 1, before
either defect reached anything beyond this worktree.

## Defect 1: the tail's wire figure was computed in the wrong units

The first cut mirrored msg/block lines exactly: `W = original − S + I`, with `S`/`I` summed from
the overlay's recorded stripped/injected TEXT lengths. That mirroring is valid for a msg block,
whose `chars` IS the block's raw text length — but a TOOL's `chars` is `len(json.dumps(tool))`,
the whole tool object JSON-encoded (name, description, input_schema, quoting and escaping all
included), while the recorded stripped/injected text is the raw description SUBSTRING the proxy
touched. The two are not the same unit, so deriving `W` from a raw-text `S`/`I` produced a wrong
number for every desc-stripped tool. Observed on the real session: `tool[Bash]` printed `2,927c
−1,356 +0 → 1,571c`, where the actual forwarded wire size was `517c` (the exact figure
`_tool_lines` had always computed there, before this feature touched anything).

**Fix:** flip which side is measured and which is derived. `W` is now `item["chars"]` —
`_tool_lines`/`_sys_lines`' own pre-existing wire-chars figure, untouched by this feature, computed
exactly as it always was — and 0 for a whole-stripped tool (there is no wire item to measure at
all, since it never appears on the wire). `S` is DERIVED as `original − W + I`, so
`_delta_tail`'s own internal arithmetic (`chars − S + I`) reconstructs precisely that measured `W`
again. This is self-consistent by construction and correct specifically because `W` itself was
never a guess.

System blocks never showed a wrong number under the old formula — `_system_block_chars` reads
`block["text"]` directly, raw text length, the same unit the recorded stripped/injected spans
already use — so the units happened to coincide there. The corrected, measured-`W` rule was still
applied uniformly to system lines too, rather than leaving that coincidence as the only thing
keeping them right.

## Defect 2: sys[0]'s "original" chars is not a coherent concept

The billing header (system index 0) is a hash plus the previous request id — it changes on EVERY
request by construction (already established, `process-docs/cache/`; already the reason
`_sys_lines` excludes it from the changed/new wire comparison on every request but the first). The
first cut of this feature applied the original-chars lookup to EVERY system index uniformly,
including 0 — so REQ 1's `sys[0]` line showed `174c`, the LAST request's own billing header, where
the real wire content for REQ 1 was `132c`. There is no "original" for index 0 that means anything
across requests; each request's billing header is its own, unrelated value.

**Fix:** `_req_delta_lines` now special-cases `idx == _BILLING_HEADER_SYS_INDEX` before attempting
either the original-chars lookup or the overlay tail — `sys[0]` renders with its own wire chars and
no tail, unconditionally, exactly as it did before this feature existed, regardless of what
`data["payload"]` or the overlay happen to carry.

## Verification

- Extended `dev/dual_log_cli/tests/test_msgs_sys_tool_overlay.py`: the desc-stripped-tool test was
  replaced with `test_desc_stripped_tool_uses_measured_wire_not_derived_from_raw_text`, which
  deliberately sets the recorded raw-stripped-text length (50 chars) and the measured wire chars
  (435c) to DISAGREE with what `original − raw_text_length` would produce, so the test would have
  failed under the pre-correction formula and only passes because `W` is read from `item["chars"]`
  directly. New `test_sys_billing_header_untouched` feeds the overlay a (deliberately wrong-headed)
  slot for `sys[0]` and asserts it is ignored — wire chars, no tail, regardless.
- Full re-run of all 8 suites in `dev/dual_log_cli/tests/`: 13/13, 13/13, 26/26, 17/17 (this
  suite, now 17 checks), 13/13, 17/17, 13/13, 14/14 — all pass.
- Real invocation, `msgs monitor_cc_1788464543 0 12`, REQ 1 after the fix: `sys[0]  132c` (no
  tail — matches the wire value it carried before this feature existed), `tool[Bash]  2,927c
  −2,410 +0 → 517c` (wire now correctly `517c`, matching the pre-feature value), and the same
  pattern holds for every other desc-stripped tool on that line (`Edit`, `ListAgents`, `Read`,
  `SendFeedback`, `Skill`, `Write`) and the 8 whole-stripped tool lines (unaffected by either
  defect — whole-strip's `W` was already 0 by design).
- `expand`, `search`, `sessions` re-checked by direct invocation: unaffected (the only drift
  between two back-to-back runs traced to the session's own live growth during this session, not
  to the fix — confirmed by running `expand` twice in immediate succession with identical output).

## Relevant Symbols / Paths

- `_delta_line`, `_req_delta_lines` (`src/dual_log_cli/render.py`)
- Ground truth: `src/logs/dual_log/api_requests_opus_monitor_cc_1788464543_*.jsonl`, REQ 1
- Area: `process-docs/dual_log_cli/` — see the same-date entry this corrects for the full feature
  design and the corpus measurements backing the original-chars source
