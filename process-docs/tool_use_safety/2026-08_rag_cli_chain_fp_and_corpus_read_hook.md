# 2026-08 — rag-cli chain-hook path-substring FP + new corpus-read block hook

## Part 1: path-substring false positive in block_rag_cli_chained.py

### Problem

`block_rag_cli_chained.py`'s trigger, `_RAG_CLI_RE = re.compile(r'\brag-cli\b')`, was searched
across the WHOLE (quote-stripped) command. `\brag-cli\b` matches `rag-cli` as a bare word
regardless of what surrounds it — including as a PATH COMPONENT. Two real observed FPs (both
blocked with the chaining/piping message even though no rag-cli tool was invoked anywhere):

```bash
ls /Users/.../cli/rag-cli/data/pdf/searxng
cd /Users/.../cli/rag-cli && ls
```

This is the same failure class the sibling incident (`2026-08-28_rag_cli_path_indirection_bypass.md`)
already documents from the other direction: an orchestrator, having hit exactly this FP twice,
told a worker "you cannot `ls`/`grep` the corpus directory from Bash" — an overstatement that led
the worker to build a `$(cat /tmp/venv_python_path.txt)`-based indirection bypass instead. The two
problems share a root: the hook's trigger was checking for the STRING `rag-cli` anywhere in the
command text, not for an actual rag-cli INVOCATION.

### Fix

Reused the assign-prefix pattern `_known_cli.py` already uses for known-CLI segment detection
(`_ASSIGN_TOKEN` / `_ASSIGN_PREFIX`, duplicated locally rather than imported — matching
`block_rag_cli_index_isolated.py`'s existing convention of a local copy rather than a shared
import). Split first (`_SEPARATOR_RE.split(stripped)`), THEN decide: the trigger is now
`any(_RAG_CLI_SEGMENT_RE.match(seg) for seg in segments)`, where `_RAG_CLI_SEGMENT_RE` requires a
segment to START WITH `rag-cli` (optionally env-var-prefixed), not merely contain the substring
anywhere. A path argument to `ls`/`cd`/`cat`/etc. is never itself the start of a segment, so it
can no longer trigger the hook. The split result is computed once and reused for both the trigger
check and the per-segment policing loop that follows (previously the command was split twice: an
unused `_RAG_CLI_RE.search` over the whole string, then `_SEPARATOR_RE.split` again inside the
loop).

### Sibling-hook audit

Checked whether the same anchor CLASS (`\btool\b` searched over the whole command, not
segment-start-anchored) exists elsewhere in the chained-CLI/rag-cli hook family:

| Hook | Anchor | Affected? |
|---|---|---|
| `block_rag_cli_index_isolated.py` | `\brag-cli\s+index\b` | No — requires literal space between `rag-cli` and `index`; no realistic path contains that. Even if the loose anchor matched a contrived path, the actual policing (`_RAG_INDEX_SEGMENT_RE.match`, segment-start-anchored) already requires the segment to START with `rag-cli index` — an unrelated `ls`/`cat` segment never matches it, so `index_segments` comes back empty and the hook exits 0. |
| `block_rag_cli_document_repeat.py` | `\brag-cli\s+(index\|delete)\b` | No — same space requirement; additionally `_extract_target()` requires BOTH `--collection` and `--document` flags present in the matched segment before it ever touches state, so a bare path text can never produce a false repeat-count. |
| `block_rag_docs_layer.py` | `\brag-cli\s+search\b` | No — same space requirement. |
| `block_gh_cli_chained.py` | `\bgh-cli\s+(?:search_repos\|search_code\|...\|get_issue\|list_issues)\b` | No — requires an actual subcommand name with a space; a path would need to literally contain e.g. `gh-cli search_repos` with a space, which does not occur. |
| `block_gh_cli_local_path.py` | `\bgh-cli\s+(get_file_content\|download_files)\b` | No — same shape. |
| `block_websearch_scrape_chained.py` | `\bwebsearch\s+scrape_url\b` | No — same shape. |
| `block_worker_cli_read_chained.py` | `\bworker-cli\s+(?:capture\|response)\b` | No — same shape. |

Empirically verified: ran all seven sibling hooks against `ls`/`cd && ls` over paths built from
each tool's own name (`cli/rag-cli/...`, `cli/gh-cli/search_repos_backup`,
`cli/websearch/scrape_url_cache`, `cli/worker-cli/capture_logs`) — none blocked. Only
`block_rag_cli_chained.py` was affected, because it is the only one of the family whose trigger
requires just the bare tool name (it applies to ANY rag-cli subcommand, not a fixed short list),
so its anchor could never require a following subcommand token the way the others do.

### Verification (as of 2026-08)

`dev/hook_smoke/test_block_rag_cli_chained.py`: extended from 20 to 24 cases (4 new: the two
verbatim FP commands now PASS, a third `grep`-over-a-rag-cli-path-component PASS, and one
regression check confirming a REAL rag-cli invocation chained with a foreign segment still
BLOCKS — the fix changed only what counts as the trigger, not what counts as an allowed chained
segment). All 24 pass. Full existing suite re-run clean (no case flipped unexpectedly).

## Part 2: block_rag_corpus_read.py — new hook

### Problem

`2026-08-28_rag_cli_path_indirection_bypass.md` (read in full before this work; referenced here,
not reproduced) documents a worker reading rag-cli's corpus by resolving the interpreter and CLI
script paths through `/tmp` files and invoking them directly, specifically because it believed
(from an overstated orchestrator instruction, itself downstream of the Part 1 FP) that `rag-cli`
was unusable and never received a rejection message telling it what the sanctioned form was. The
entry's conclusion: "a rejection should name the permitted form... a block that only says what is
forbidden invites a workaround."

Separately, and independent of that specific bypass carrier, there was no hook stopping a much
simpler bypass: directly `cat`/`grep`/`head`/etc.-ing files under rag-cli's `data/documents/`
corpus tree, which returns raw chunk-store files rather than ranked/formatted search results.

### Design

New `block_rag_corpus_read.py`. Triggers on nine read commands (`cat`, `grep`, `head`, `tail`,
`sed`, `awk`, `rg`, `less`, `more`) whose segment targets a path matching
`(?:^|/)rag-[^/\s]*/data/documents(?=[/\s'")]|$)` — deliberately `rag-[^/\s]*` rather than a
literal `rag-cli`, so a renamed checkout or worktree (`rag-cli-eval`, `rag-cli-convert`) is still
caught. `ls`/`rm`/`mv`/`mkdir` are deliberately excluded from the read-command list — file
management and deletion over the corpus stay sanctioned per the task; only bypassing rag-cli's
own `search`/`read_document` read path is blocked. The block message names both sanctioned forms
explicitly (`rag-cli search <query> <collection>`, `rag-cli read_document <collection> <doc_id>`)
— directly acting on the path-indirection incident's stated lesson.

Segment handling follows the same shell-strip position-preserving technique the chained-CLI hook
family uses, but needed a NEW two-copy split (`_split_segments()`, `(stripped_segment,
original_segment)` pairs at identical index ranges): the read-command NAME is matched against the
stripped copy (immune to heredoc-body/quote-content mimicking a real command at segment start),
while the corpus PATH is matched against the ORIGINAL copy (a quoted path like `cat
"/path/.../data/documents/x.md"` blanks to spaces in the stripped copy, so checking the stripped
copy for the path would miss every quoted case).

### Dead end caught before shipping: trim-boundary bug

First draft's `_trim_pair()` computed the shared trim range from the STRIPPED segment's own
`.strip()` boundary. A quoted argument sitting at the very END of a segment blanks to trailing
SPACE characters in the stripped copy — indistinguishable from real trailing whitespace — so
`.strip()` silently removed them, and applying that SAME index range to the original copy cut the
real (quoted) path text off too. Concretely: `head -50 "/Users/x/cli/rag-cli/data/documents/x.md"`
under the buggy version stripped down to `original_seg = 'head -50'`, losing the path entirely and
under-matching (verified: this exact case returned exit 0 instead of 2 in manual testing before
the fix). Fixed by computing the trim range from the ORIGINAL segment's own whitespace boundary
instead — real whitespace is never a quote character, so the boundary is accurate regardless of
where a quoted argument sits — and applying that range to both copies.

### Known accepted limitation: argument-role blindness

The hook does not distinguish a `grep` PATTERN argument from a file-path argument (no
`shlex`-based flag/positional parsing, unlike `block_rag_docs_layer.py`'s collection/filter
extraction). `grep "rag-cli/data/documents" /tmp/notes.txt` — searching FOR that literal string,
not reading from that path — happened to NOT false-block in testing, but only because
`_CORPUS_PATH_RE`'s leading boundary (`^` or `/` immediately before `rag-`) fails against a
preceding quote character; a differently-worded pattern could in principle still trigger a false
block. Accepted deliberately: the failure direction (blocking a rare hand-crafted string) is the
safe one for a policy hook, and a full `shlex`-based per-command argument-role parser was judged
over-detailed for this hook's scope — no evidence yet that a real grep call needs it.

### Registration

Added to `hook_setup.py`'s `_HOOK_SCRIPTS`, grouped with the other rag-cli hooks (after
`block_rag_docs_layer.py`), `("block_rag_corpus_read.py", "Bash")`.

### Verification (as of 2026-08)

`dev/hook_smoke/test_block_rag_corpus_read.py`: 29 cases (14 block: all 9 read commands, a
quoted-path case, a non-first-argument case, a real-rag-cli-invocation-chained-with-a-corpus-read
case, two glob-dodge renamed-checkout/worktree cases; 10 allow: ls/rm/mv/mkdir management, no
corpus-path, the two sanctioned rag-cli forms themselves, an echo-quoted-mention, a
heredoc-embedded-mention, and the known relative-path text-only-matching limitation; 1 malformed
payload fail-open; 3 block-message content checks — names `rag-cli search`, names `rag-cli
read_document`, states file management stays allowed). All 29 pass.

Manual verification of the exact commands: `cat`/`grep`/`head`/`tail`/`sed`/`awk`/`rg`/`less`/
`more` all block against `/Users/x/cli/rag-cli/data/documents/z.md`; `ls`/`rm`/`mv`/`mkdir` all
pass against the same path.
