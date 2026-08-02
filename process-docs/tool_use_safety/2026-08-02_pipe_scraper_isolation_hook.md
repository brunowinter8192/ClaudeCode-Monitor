# pipe_scraper Isolation Hook (2026-08-02)

**Topic:** a new PreToolUse hook `block_pipe_scraper_isolated.py` forcing the websearch
project's `python -m src.crawler.pipe_scraper` invocation to run alone in its Bash call.

## Motivation

CC auto-backgrounds a Bash call after 2 minutes only when that call stands ALONE in the
invocation. A poll chained onto it in the SAME invocation (`&& tail /tmp/x_scrape.log`,
a wait-loop) defeats auto-backgrounding: the call instead returns after 2 minutes with
partial output and the worker stays awake polling, or — worse — if it DOES qualify
despite the chain, the chained poll never runs because the whole invocation backgrounds
together, and the worker sleeps until the multi-minute scrape finishes with no way to
check progress. `pipe_scraper` is exactly the long-running command class this escape
exists for, and was unprotected — workers routinely chain a log-tail onto the scrape call
out of habit (the same habit `rewrite_websearch_scrape_noise.py` already corrects for the
bounded `scrape_url` websearch-tool call, a different code path from this standalone CLI
invocation).

## Design

Direct clone of `block_rag_cli_index_isolated.py`, not `block_linkedin_cli_isolated.py` —
the task explicitly named the rag_cli hook as reference because pipe_scraper's real
invocation shape needs the same allowances: a leading `cd` (the module path
`src.crawler.pipe_scraper` is CWD-relative, same reason `rag-cli index` needs a `cd` to
the collection root), shell variable assignments (`OUTPUT_DIR=...`), and output
redirection (`> /tmp/x_scrape.log 2>&1`) surviving as part of the segment. The
`linkedin` hook's tighter "nothing else at all" rule and its explicit non-hardening
against `$(...)` were both inapplicable here for the same reason they don't apply to
`rag-cli index`: pipe_scraper's real skill-generated invocation form legitimately needs
`cd`/assignments/redirect, and a multi-minute crawl has the same correctness stakes as a
multi-minute index (a subshell smuggled through an assignment value or argument is a
proven bypass class already fixed once for `rag-cli index` — see
`2026-08-02_rag_cli_index_isolation_subshell_bypass.md` in this area).

**Anchor difference:** `rag-cli index` is a bare CLI token; pipe_scraper is invoked as
`<interpreter-path> -m src.crawler.pipe_scraper`, always through a venv interpreter
(`./venv/bin/python`, absolute venv paths). The segment classifier
(`_SCRAPER_SEGMENT_RE`) was extended with an optional `(?:\S+/)?` prefix before
`python3?` to match any interpreter path without needing to enumerate venv layouts; the
fast-path anchor (`_SCRAPER_RE`) matches only on `-m\s+src\.crawler\.pipe_scraper\b`,
skipping the interpreter token entirely since the module path alone is the unambiguous
identifier. Separator handling, line-continuation collapsing, and the raw-command
`_SUBSHELL_RE` gate are byte-identical to the reference (same proven hardening: bare `&`
lookaround independent of whitespace, `$(`/backtick/`<(`/`>(` checked against the RAW
command since the double-quote scanner blanks `$()` inside `"..."` even though bash still
evaluates it there).

## Verification

Verified at hook-script level only: real subprocess invocation, real JSON stdin, real
exit code asserted for 5 cases —
1. canonical form (`cd` + assignments on their own newline-separated segment + venv-python
   `-m` scraper call + redirect) → exit 0
2. scraper call chained with `&& tail` → exit 2
3. scraper call with `$(cat /tmp/name.txt)` in an argument → exit 2
4. no scraper invocation at all → exit 0
5. malformed/unparseable stdin → exit 0 (fail-open)

One test-construction pitfall surfaced during verification, not a hook defect: an
assignment glued onto the SAME line as `cd` with no separator (`WEBSEARCH=x OUTPUT_DIR=y
cd "$WEBSEARCH"`) blocks under this hook — matching `block_rag_cli_index_isolated.py`'s
own behavior, since `_CD_SEGMENT_RE` requires the segment to start with `cd`, not tolerate
a leading assignment glued onto the same segment. The real skill-generated form puts
standalone assignments on their own line/segment before `cd`, which is what both hooks'
own "allowed patterns" documentation already states.

NOT verified: no live CC PreToolUse round-trip (registration added to `hook_setup.py`'s
script list only; running the installer from a worktree is explicitly guarded against and
was not attempted), and no `dev/hook_smoke/` regression-guard file was added for this hook
(out of the task's stated scope, unlike the sibling `linkedin` hook which got one).
