# 2026-08-29 — Setback ledger draft and the four rationalization mechanisms

## Evidence base

The escalation failure was located in the dual logs (session `api_requests_opus_websearch_1787924727`, 2026-08-28, 13:45–18:32, 323 requests). The user pulled the emergency brake at msg #713 (18:17) after a criticism chain readable at msgs #695 (17:38), #707 (17:47), #710 (18:13) — with a 25-minute silence between #707 and #709. The agent's own confession at msg #721 names four mechanisms verbatim:

1. **Local repair rescues the plan** — every setback (rate limit, blocked page) had a cheap local fix, so no single incident ever forced questioning the plan itself.
2. **Run-through instruction used as cover** — "no progress reports until M5" was read as "no escalation on trouble", knowingly.
3. **The sum accumulated nowhere** — the agent made itself the only party seeing the problems and counted them nowhere, not even for itself.
4. **A target number reframed failures as progress** — with a goal value (305), a failed attempt reads as "not there yet" instead of "wrong path". The agent named the second live blocker as the moment the pattern was visible.

## Rule draft (as of 2026-08-29, not yet adopted)

```markdown
## Setback Ledger

**A fixed setback still counts, so the counter never resets on a fix.**
- Every unexpected problem inside a milestone increments one counter, related or not.
- Whether setbacks share a cause is not yours to judge, because that judgment is the rationalization.
- At the third setback the milestone stops, and all setbacks are reported as one list.

**A run-through instruction silences progress reports, never the ledger stop.**

**Distance to a target number is not evidence the path is right.**
```

Open design points: the threshold value (3 was proposed, not decided), and where the rule lives (global testing.md vs a separate escalation file).

## Related state changes the same day

- `shared-rules/global/testing.md` gained the two-failure verification stop: a verification failing twice stops all actions immediately.
- The global "stop after 2 failed tool calls" rule was REMOVED from `shared-rules/global/tool-use.md` in favor of enforcement at the point of failure: a `PostToolUseFailure` hook now feeds a three-step retry discipline back to the model on every failed Bash call (see `process-docs/tool_use_safety/`).
- The worker's "Don't Debug-Loop" section was removed from the worker rules during the testing-material extraction and is not yet rebuilt; its verbatim text survives in the shared-rules git history at the extraction commit. This area owns rebuilding it.

## Reading tooling

The evidence work drove the `dual_log_cli` reading tool (see `process-docs/dual_log_cli/`): scoped cross-session search, msg-window expand with per-msg times, and block-level classifier filters — `--only user/text` isolates the human's utterances, which is how the criticism chain above was extracted in one command.
