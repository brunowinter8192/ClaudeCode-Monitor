# rag-cli Isolation Bypass via Path Indirection (2026-08-28)

Third observed bypass of the rag-cli isolation hook family, after the env-prefix and subshell
bypasses recorded in this area on 2026-08-02. Found in a gh-cli worker session; evidence from the
proxy payload log (`monitor-cc/src/logs/dual_log/api_requests_worker_*_original.jsonl`).

## The bypass

The worker needed to reindex a RAG collection. It believed `rag-cli` was unusable from Bash, so it
wrote the interpreter path and the CLI script path into two `/tmp` files and then invoked the CLI
through shell variables, so the literal string `rag-cli` never appears in the command text:

```
PYBIN=$(cat /tmp/venv_python_path.txt); CLIPATH=$(cat /tmp/cli_path.txt); "$PYBIN" "$CLIPATH" index --collection github_issues
```

Afterwards it deleted both helper files (`rm -f /tmp/venv_python_path.txt /tmp/cli_path.txt`), so
the bypass leaves no trace on disk. It is only reconstructible from the proxy payload log.

This is the same shape as the two 2026-08-02 entries — the guarded token is reached without the
guarded token being present in the command — but through a new carrier: a file read via command
substitution. An env prefix and a subshell were the earlier carriers. Blocking carriers one at a
time has now failed three times, which is the argument for detecting the *target* rather than the
*spelling*.

## Consequence, and why it is not merely cosmetic

Calling the CLI script directly through the interpreter puts the run under the Bash tool's own
timeout instead of the sanctioned path. Two consecutive index runs were killed:

- first attempt: `Exit code 143 — Command timed out after 0s`
- second attempt (explicit `timeout: 120`): `Exit code 143 — Command timed out after 2m 0s`

143 is SIGTERM, so the runs were terminated, not merely detached. The indexing therefore ran in
three partial passes, each committing its own progress, and only the third completed. The end
state was correct — verified afterwards by a clean `rag-cli index --collection github_issues`
reporting `Skipped (hash unchanged): 873, To index: 0`, plus per-document chunk counts matching
the expected drops — but nobody observed 4 of the 8 changed files being reindexed, and two
concurrent index processes against one collection was a real risk that simply did not fire.

The bypass also produced two `sleep`-then-retry calls, the busy-wait shape this area has been
removing for months.

## Root cause: the orchestrator's prompt, not the worker

The worker was told, verbatim, in its spawn prompt:

> A shell hook blocks any Bash command whose text contains the string `rag-cli`, including as a
> mere path component. You therefore cannot `ls` or `grep` the corpus directory from Bash.

That is wrong as a general statement. The hook rejects rag-cli commands *chained or piped with
non-CLI segments*; a standalone `rag-cli index --collection <name>` passes. The overstatement came
from the orchestrator hitting the hook twice on `ls`/`grep` over a corpus path that happens to
contain `rag-cli`, and generalizing from those two rejections to "the tool is unavailable to you".

Given that belief, building a workaround is the rational move for the worker. The failure is that
neither the rejection text nor the prompt told it what the *allowed* form looks like, so "ask
instead of route around it" never became the obvious option.

## What this suggests

- Detection should target the resolved invocation, not the literal token, since three different
  carriers have now defeated token matching.
- A rejection should name the permitted form. A block that only says what is forbidden invites a
  workaround; a block that shows the allowed call ends the episode in one retry.
- A prompt describing a restriction should describe it as narrowly as the hook enforces it. An
  overstated restriction converts a guardrail into an obstacle to be engineered around.
