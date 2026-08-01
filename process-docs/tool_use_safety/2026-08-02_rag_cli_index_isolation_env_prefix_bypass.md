# rag-cli index Isolation Hook — Env-Prefix Bypass Fix (2026-08-02)

**Topic:** two bypass holes in `block_rag_cli_index_isolated.py`, found by replaying real
commands issued by a live agent after the hook was installed and firing.

## Hole 1 — env-var prefix defeats the anchor

`PYTHONUNBUFFERED=1 rag-cli index --collection x` alone correctly allowed (exit 0), but
`tail -20 /tmp/x.log && PYTHONUNBUFFERED=1 rag-cli index --collection x` also passed
(exit 0) — the exact poll-then-index pattern the hook exists to stop, just wrapped in an
env-var prefix.

**Root cause:** `_RAG_INDEX_SEGMENT_RE` was anchored `^rag-cli\s+index\b` with no
allowance for a leading `VAR=value` assignment. An env-prefixed segment matched neither
the index classifier nor the cd classifier, so `index_segments` came back empty — and the
early-exit `if not index_segments: sys.exit(0)` (meant for "no `rag-cli index` at all,
out of scope") silently treated the whole command as out-of-scope instead of falling
through to the per-segment block check that would have caught the `tail` segment.

## Hole 2 — standalone assignment line

The real skill-invocation shape from a live session:
```
RAG_ROOT=~/Documents/ai/Meta/ClaudeCode/cli/rag-cli
cd "$RAG_ROOT" && PYTHONUNBUFFERED=1 rag-cli index --collection linkedin-reference \
    > /tmp/linkedin-reference_batch3_index.log 2>&1
```
passed (exit 0) — correct outcome, but for the wrong reason (same "index_segments empty →
early allow" bug as Hole 1, since the whole command has no segment matching the
un-prefixed `_RAG_INDEX_SEGMENT_RE`). Proof it was accidental: the same shape with a
`tail` line inserted also passed, which must block.

Separately, `rag-cli index --collection x \` + newline + `> /tmp/x.log 2>&1` (backslash
line-continuation alone) blocked incorrectly — `_SEPARATOR_RE` treats bare `\n` as a
separator, splitting the continued redirect into its own segment that matched neither
classifier.

## Fix

Three additions, no change to the trailing-only rule in `block_rag_cli_chained.py`
(explicitly out of scope):

1. `_RAG_INDEX_SEGMENT_RE` now allows an optional repeatable `VAR=value` prefix before
   `rag-cli\s+index` — an env-prefixed index call is classified correctly as the index
   segment itself, not as "other".
2. New `_ASSIGNMENT_ONLY_SEGMENT_RE` classifier — a segment consisting of one or more
   bare `VAR=value` assignments and nothing else (e.g. `RAG_ROOT=~/path` on its own
   line) is now explicitly allowed, matching the real skill form.
3. New `_LINE_CONTINUATION_RE` (`\\\n`) collapsed to a space before segment-splitting —
   backslash-newline is a shell line continuation, not a command separator; only bare
   `\n` remains a real separator afterward.

`_CD_SEGMENT_RE` unchanged; all three classifiers stay position-independent (assignment
and cd segments may appear before or after the index segment — no test case required
strict ordering).

## Verification

Reproduced both holes BEFORE the fix via direct subprocess calls against the hook script
(exit 0 for both, confirmed against the exact commands in the incident). After the fix,
extended smoke suite `dev/hook_smoke/test_block_rag_cli_index_isolated.py` to 24 cases
(was 16) — all passing: 10 block (6 original + 4 new: tail-before-env-prefixed-index,
env-prefixed-index-then-echo, multi-assignment-prefixed-index-piped-to-tee,
assignment-line+tail+cd+env-prefixed-index) and 14 allow (10 original + 4 new:
env-prefixed bare index, the real Hole-2 command verbatim including the backslash
continuation, assignment-line+cd+bare-index+redirect, bare-index-with-line-continued-
redirect). Cross-checked no regression on `block_rag_cli_chained.py`'s own 11-case smoke
(file untouched).

Verified at hook-script level (real subprocess invocation, real JSON stdin, real exit
code asserted) — NOT verified against a live CC session (requires main-repo-root
`hook_setup.py` registration, out of scope for a worktree session).
