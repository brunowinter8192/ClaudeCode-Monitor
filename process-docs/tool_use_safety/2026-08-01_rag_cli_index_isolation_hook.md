# rag-cli index Isolation Hook (2026-08-01)

**Topic:** a new PreToolUse hook `block_rag_cli_index_isolated.py` closing a gap that
`block_rag_cli_chained.py`'s trailing-only rule leaves open for `rag-cli index`.

## Triggering Evidence

An agent issued ONE Bash call that polled a running index log, then started a NEW
`rag-cli index` on the same collection while the first was presumably still holding
the collection's write lock:

```
tail -20 /tmp/linkedin-reference_batch2_index.log
echo "--- is rag-cli still holding lock? ---"
cd ~/Documents/ai/Meta/ClaudeCode/cli/rag-cli && rag-cli index --collection linkedin-reference > /tmp/lock_check4.log 2>&1
```

`block_rag_cli_chained.py` only restricts segments AFTER the first `rag-cli` segment
(leading `cd`/guards are always exempt by design — see that hook's rationale). Here
the noise (`tail`, `echo`) sits BEFORE the `cd && rag-cli index` chain, so the existing
trailing-only rule never fires. `rag-cli index` specifically needs a tighter rule than
other subcommands: it runs for minutes and holds a collection lock, so ANY extra
command sharing the Bash call is a signal of a poll-then-retry pattern racing the lock,
not just wasted noise.

## Design

New hook, NOT a modification of `block_rag_cli_chained.py` (that hook's trailing-only
rule stays correct for `search`/`delete`/`list_documents`/etc. — only `index` needed
the tighter isolation).

**Rule:** when `rag-cli index` appears anywhere in the command, the ONLY things allowed
in the whole Bash invocation are: a leading `cd`, and exactly one `rag-cli index` call
(redirects stay part of that segment — not a separator). Anything else in ANY position
blocks, including a second `rag-cli` command (`rag-cli delete && rag-cli index` is
blocked too — a second rag-cli call is not automatically safe just because it's rag-cli,
unlike the chained hook's "two rag-cli segments are fine" allowance).

Implementation reused the segment-splitting technique from `block_rag_cli_chained.py`
and `block_gh_cli_chained.py` (`_SEPARATOR_RE`, `_strip_non_shell_active`): split on
`&&`/`||`/`;`/newline/`|`/space-bounded `&``, redirects survive inside their segment.
Fast-path anchor `\brag-cli\s+index\b` gates entry (out of scope entirely when absent —
governed by the existing chained hook instead). Every segment must then match either
`^rag-cli\s+index\b` or `^cd\b`; exactly one index segment required (zero → out of
scope/exit early, more than one → block); cd segments allowed in any position since the
"only cd + one index call" requirement did not specify ordering, and no test case ever
put a cd after index in a blocked example.

## Verification

16-case smoke test (`dev/hook_smoke/test_block_rag_cli_index_isolated.py`), all
passing: 6 block cases (the observed incident reproduced verbatim, noise before/after
index, second rag-cli command, piped index) and 10 allow cases (bare index, index +
redirect, cd-before-index with/without redirect, three out-of-scope subcommands,
no-rag-cli, single-quote/heredoc shell-strip). Cross-checked no regression on
`block_rag_cli_chained.py`'s own 11-case smoke (untouched file, still passing).

Verified at hook-script level (real subprocess invocation with real JSON stdin,
real exit code + stderr asserted) — NOT verified against a live CC session (would
require the hook to actually be registered in `~/.claude/settings.json` and fire
during a real Bash tool call, which needs running from the main repo root, not a
worktree).
