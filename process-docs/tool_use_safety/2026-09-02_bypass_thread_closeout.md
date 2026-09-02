# Bypass thread close-out — what was still open after the 2026-08-28 incident (2026-09-02)

Three goals were on the table after the path-indirection bypass recorded in this area: an
indirect call to a hook-guarded CLI is blocked like the direct one; a rejection names the allowed
form; a worker prompt states a restriction only as narrowly as the hook enforces it. This entry
records what of that was already done, what was decided against, and the two small changes made.

## Goal 1 — indirect invocation

Carriers observed so far and their state as of this date:

| Carrier | Observed | State |
|---|---|---|
| env-var prefix | 2026-08-02, replayed real commands | closed in `block_rag_cli_index_isolated.py` and its clones |
| command/process substitution | 2026-08-02, replayed real commands | closed, raw-command `_SUBSHELL_RE` gate |
| interpreter + script path read from `/tmp` files into variables | 2026-08-28, one worker session | not blocked by any hook |

The third carrier was not given a hook. Its cause chain was: the chained-CLI hook false-positived
on a path component, the orchestrator generalised two of those rejections into "the tool is
unavailable to you" in the spawn prompt, and the worker routed around a tool it believed was
banned. The false positive is fixed (segment-start trigger, see the 2026-08 chain-FP entry in
this area) and the prompt overstatement is now a rule (goal 3 below). With both removed the one
observation has no remaining cause, so a detector for the resolved invocation would defend
against nothing observed. Under the evidence-burden rule adopted the same day
(`shared-rules/global/testing.md`, see `process-docs/evidence_burden/`) that is a no-build.
If a bypass shows up again with the cause chain gone, that is the observation this decision
asks for.

## Goal 2 — rejection names the allowed form

Checked every CLI block hook's message text in `src/hooks/` on this date: the two chained-CLI
hooks, `block_worker_cli_read_chained`, `block_rag_corpus_read`, `block_rag_docs_layer`,
`block_rag_cli_document_repeat`, the three isolation hooks, `block_worker_kill_while_working`,
`block_manual_worker_cleanup`, `block_worker_send_background`, `block_gh_cli_local_path`,
`block_bd_cli_worker` all state the permitted call. Two live rejections earlier the same session
(gh-cli piped to sed, rag-cli chained with ls and diff) were each resolved on the first retry from
the text alone.

The one exception was `block_worker_spawn_placement.py`: both messages in German, and the
cross-project instruction told the caller to run `git worktree add` by hand, which leaves the
target worktree unregistered so `worker-cli kill` never cleans it. Rewritten in English, naming
`worker-cli spawn ... c` and `worker-cli worktree <name> <target_repo>`. Verified against the
merged hook with a cross-project spawn payload: exit 2 with the new text. No smoke test exists
for this hook and none was added.

The scope limit the user stated: naming the allowed form is only possible where the intent is
unambiguous, which is block hooks on CLI tools. Hooks on free shell patterns (kill, grep) keep a
prohibition plus hint.

## Goal 3 — prompt narrowness

No rule existed. One row added to the MUST-NOT column of the spawn-prompt table in
`shared-rules/main/workers.md`: a tool restriction stated wider than the hook enforces it. No
example, no explanation, per the rule-writing convention adopted the same day.
