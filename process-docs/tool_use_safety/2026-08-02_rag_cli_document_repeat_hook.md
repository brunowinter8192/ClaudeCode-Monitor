# rag-cli Repeated-Document Hook (2026-08-02)

**Topic:** a new PreToolUse hook `block_rag_cli_document_repeat.py` — the first STATEFUL
hook in this family — detecting repeated single-document `rag-cli index`/`delete` calls
across separate Bash invocations in one session.

## Motivation

An observed incident: a worker with ~40 markdown files to index issued ~40 consecutive
`rag-cli index --collection X --document <file>` calls (one file per Bash call) instead of
one collection-wide `rag-cli index --collection X` call, and ~48 `rag-cli delete
--collection X --document <file>` calls earlier in the same session. `--document` is a
legitimate flag for a genuine one-off op — the harm is the REPETITION across consecutive
calls, not the flag itself. Each individual call is fast and never qualifies for
auto-backgrounding, so the worker stayed awake for dozens of sequential turns instead of
sleeping through one long collection-wide run. `block_rag_cli_index_isolated.py` cannot
see this: it forbids CHAINING (>1 index segment in ONE Bash call), and each of the 40
separate calls was individually perfectly isolated.

## Design decision (reported before implementation, one change applied after review)

**State pattern:** cloned `block_polling_loop.py.disabled`'s architecture — append-only
JSONL (`{ts, session_id, target}`), self-pruned to a rolling window on every write, count
by `(session_id, target)`, block when count `>= THRESHOLD`. This is the only established
"N occurrences within a window" precedent in the codebase. The alternative —
`last_cmd_state.jsonl`'s single-record "last command" adjacency pattern — was explicitly
NOT reused: that pattern was redesigned then fully removed in 2026-07-20/21 because
adjacency tracking false-positive-blocked a legitimate interleaved-command case (see the
`2026-07-20_timer_guard_concurrent_redesign.md` entry in this same area). Window-based
counting with session-scoped, time-pruned entries avoids that failure mode by design.

**Target fingerprint:** `f"{subcommand}:{collection}"`, extracted per rag-cli segment via
the same technique `block_rag_docs_layer.py` already uses — regex segment-end scan on the
shell-stripped command, then `shlex.split` the ORIGINAL (unstripped) segment sliced at the
same indices, to recover real quoted flag values for both `--flag value` and `--flag=value`
forms. A segment only counts when BOTH `--collection` and `--document` are present —
that's the exact line between the harmful single-file pattern and a legitimate
collection-wide call, which never touches the state file at all (out of scope by
construction, not merely "allowed").

**Window: 600s.** Argued against reusing the polling-loop's 30s: a full model turn sits
between two rag-cli calls here (unlike a tight sleep-loop), so a 30s window would expire
before a genuine repeat pattern ever registers. 600s reuses the same order of magnitude
already established elsewhere in this hook family (`block_concurrent_timer.py`'s 600s
timer expiry) rather than inventing a new constant.

**Threshold: 2, not 3 (changed after review).** Original proposal was 3, reasoning "let the
pattern establish itself before catching it." Correction applied: a genuine single-document
op is singular by definition — pulling one file back in. A SECOND `--document` call to the
same collection+subcommand within the window is already the loop's opening move, not a
second legitimate one-off. At threshold 2, the first call passes and the second blocks; a
false positive costs exactly one turn (re-issue the collection-wide form instead).
Threshold 3 would have let the incident pattern run two calls deep before catching it —
asymmetry favors the tighter number.

**Accepted trade-off, stated up front:** a legitimate collection-wide call interspersed
between two `--document` calls does NOT reset the window (purely time-based, no adjacency
logic — consistent with why adjacency tracking was rejected elsewhere). Worst case: two
single-doc calls, then a full collection reindex, then a third single-doc call within the
same 10-minute window still blocks even though the collection was already consistent in
between. Rare, low-stakes, and the alternative (adjacency-based reset) is the exact design
class with a documented false-positive history in this codebase.

## Verification

7-case smoke (`dev/hook_smoke/test_block_rag_cli_document_repeat.py`), all passing via real
subprocess + real JSON stdin + a fresh `tempfile`-backed state path per case
(`MONITOR_CC_RAG_DOC_REPEAT_STATE` env override, same isolation mechanic
`block_polling_loop.py.disabled`'s `MONITOR_CC_POLLING_STATE` established):
single `--document` call passes (exit 0); a 2nd `--document` call to the same
collection+subcommand blocks (0 then 2); 3 consecutive collection-wide calls (no
`--document`) always pass; a different session's call does not count toward another
session's counter (sess-A#1=0, sess-B#1=0, sess-A#2=2 — confirms session isolation, not
just non-interference); `rag-cli delete --document` is covered identically to `index`;
malformed stdin fails open (exit 0).

Verified at hook-script level only (real subprocess, real stdin, real exit codes, real
state-file read/write) — NOT verified against a live CC PreToolUse round-trip, and not
installed into `~/.claude/settings.json` (registration added to `hook_setup.py`'s script
list only; the installer's worktree guard correctly refused to run from this worktree on
the post-commit hook's automatic invocation, same behavior confirmed for the two prior
hooks added in this same session).
