# block_po_read.py: split/dd escape closed, block message corrected

Live incident this session: a persisted-output export >25k tokens could not be read naively. The agent escaped via `split -l 400 <PO-path> /tmp/...` + `awk` on the copy — a partial-view consumption of exactly the kind `block_po_read.py` exists to prevent, but `split` was not in `_READ_TOOL_RE` so the hook let it through silently.

## Root cause

`_READ_TOOL_RE` (`head|tail|grep|egrep|fgrep|rg|sed|awk|cut|less|more|cat|tac|nl|zcat`) covers direct content-reading tools but not content-*partitioning* tools. `split`/`dd` don't read-and-print — they copy the file (or a slice of it) to a new location for later partial consumption via a second, unblocked command. Same escape class, different mechanism: the hook's reader-tool ∩ PO-path co-occurrence check never saw a reader-tool token in the `split`/`dd` segment.

## Fix

Added `split`, `dd` to `_READ_TOOL_RE`. Verified both new patterns still resolve correctly through the existing `_strip_redirects` → `_PO_PATH_RE` pipeline: neither `split -l N <PO-path> /tmp/x` (plain positional output arg) nor `dd if=<PO-path> of=/tmp/x` (`if=`/`of=` prefixed, no `>`) trip the `_REDIRECT_STRIP` regex, so the PO-path token survives unstripped and `_PO_PATH_RE`'s unanchored substring match still finds it inside `if=/Users/.../.claude/.../x.txt`.

## Block-message correction

Verified live, same session: CC's Read tool DOES page a large persisted-output export correctly — the trigger file was 46 lines / ~32k tokens (five 6.5-9.3k-char lines), and multiple `Read` calls with `offset>=1` + a small `limit` worked. The previous `_BLOCK_MSG` said "Read supports offset/limit to page through large exports" — true but not actionable enough (didn't say offset starts at 1, didn't call out the multi-call requirement, didn't address the long-single-line case that a naive `limit=N` alone doesn't fix). Rewrote to state the escalation directly: Read tool; when total exceeds the per-call token cap, MULTIPLE Read calls via offset/limit (offset starts at 1); very-long-single-line files need a small line-count limit per call.

## Verification (as of 2026-07-25)

`dev/hook_smoke/test_block_po_read.py`: 16 cases (9 block incl. the new `split`/`dd` cases, 7 no-op incl. parse-error fail-open) — all green, real subprocess + real stdin JSON. `ast.parse` syntax check clean. NOT verified: live PreToolUse firing through the actual registered CC hook (this hook's registration in `~/.claude/settings.json` predates this session and is untouched — filename unchanged, only regex/message content changed).
