# Argument-rule CLI hooks: fire audit, 2026-09-05

Follow-up to the same-day unification of the chained-CLI hooks in this area. That cleanout left
the five argument-rule hooks untouched on purpose; this entry records whether their fires were
justified, over the only window the fire log holds.

## Corpus

`src/logs/hook_firing.jsonl`, 2026-08-29 through 2026-09-05. The 24h log janitor keeps seven
days of this file, so no earlier fires exist to audit. Hooks in scope: `block_rag_docs_layer`,
`block_gh_cli_local_path`, `block_search_subreddits_limit`, `block_rag_cli_document_repeat`,
`block_rag_corpus_read`.

## Fires and verdicts

| hook | blocks | verdict |
|---|---|---|
| block_rag_docs_layer | 1 | justified: `rag-cli search` on a `*-docs` collection with no layer filter |
| block_search_subreddits_limit | 1 | justified: two `search_subreddits` calls with `--limit 15` |
| block_rag_corpus_read | 2 | one justified (a probe of the hook itself, `cat data/documents/*/ \| head -1`), one debatable, below |
| block_gh_cli_local_path | 0 | no evidence either way |
| block_rag_cli_document_repeat | 0 | no evidence either way |

Four blocks in a week across five hooks; two hooks did not fire at all.

## The debatable fire

2026-09-03: `cat` on one freshly scraped file under `data/documents/websearch-reference/`, to
check whether it held raw HTML instead of markdown. That is step 5 of the
websearch-capture-and-index skill (read scraped files, judge them, delete or keep) and happens
BEFORE `rag-cli index`, so `read_document` cannot serve it: the file is not in the manifest
yet. The hook's own rationale sanctions file management over the corpus and forbids only the
bypass around `search`/`read_document`; a pre-index `cat` is not that bypass. The skill's own
cleanup scripts read the same files through python, which the hook does not see, so the rule
is enforced against `cat` and not against the equivalent python read.

## Decision

All five hooks stay as they are. The debatable case was closed on the skill side, not in the
hook: the websearch-capture-and-index skill (websearch repo) now scrapes and cleans in
`/tmp/<COLLECTION>_staging/` and moves the surviving `.md` files into `data/documents/` only
in its index step, so a pre-index `cat` never touches the corpus path and the hook's rule holds
without an exemption.

The five hooks keep their individual block messages. Each explains a different argument rule,
unlike the chained-CLI family where one sentence covered every tool.
