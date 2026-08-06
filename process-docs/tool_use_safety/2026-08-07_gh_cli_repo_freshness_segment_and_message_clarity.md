# 2026-08-07 — gh-cli chain hook: repo_freshness segment + block-message clarity

## Incident

Recorded websearch session (`api_requests_opus_websearch_1786052022_original.jsonl`, messages
[118]-[129]). Agent invoked the `gh-cli-search` skill, then tried to combine a repo-freshness
check with two issue-index passes:

- msg [118]: `gh-cli repo_freshness unclecode crawl4ai; echo "=== PASS 1 ==="; gh-cli
  index_issues "Invalid IPv6 URL" unclecode/crawl4ai --limit 30; echo "=== PASS 2 ==="; gh-cli
  index_issues "raw markdown conversion" unclecode/crawl4ai --limit 30` — BLOCKED (echo segments
  AND `repo_freshness` was not yet a legal segment).
- msg [121]: retried without the echo lines, `repo_freshness && index_issues && index_issues` —
  still BLOCKED (`repo_freshness` alone was not a legal chain segment at the time).
- msg [123]: agent gave up combining, stopped and reported the block to the user.
- msg [125]/[127]: user told it to just follow the hook message. Agent ran `repo_freshness`
  standalone (worked), then tried to combine the two `index_issues` calls by CONCATENATING them
  with NO separator at all — `index_issues "q1" ... --limit 30 gh-cli index_issues "q2" ...` —
  this is not a hook block, it's an argparse failure downstream (`unrecognized arguments`) because
  the block message said calls "may be combined" without ever showing the separator syntax.
- msg [129]: corrected with `&&` — succeeded, but the underlying task ran past its 120s timeout
  and had to move to background.

Root cause of the friction: (1) `repo_freshness` was not a legal segment in a combined chain even
though it's a natural pairing with `index_issues`/`search_*` (check freshness, then index), and
(2) `_BLOCK_MESSAGE` said "may be combined" with no example of HOW and no statement that gh-cli
output can't be filtered downstream — the agent had no way to guess the correct separator syntax
from the message alone.

## Fix

`src/hooks/block_gh_cli_chained.py`:

- `_GH_SEARCH_SEGMENT_RE` (the per-segment legality check) gained `repo_freshness` as an
  additional allowed prefix, alongside the existing 7 search/research tools.
- `_GH_SEARCH_RE` (the earlier trigger-gate deciding whether the hook engages at all) was
  DELIBERATELY left untouched — `repo_freshness` is not one of the 7, so a command containing
  only `repo_freshness` (alone, or chained with git/echo/anything) never even reaches the
  segment-split loop. This preserves the existing "repo_freshness is unrestricted on its own"
  behavior exactly — it only becomes a legal SEGMENT once something else in the chain already
  put the hook in scope.
- `_BLOCK_MESSAGE` rewritten to state three things explicitly: one canonical combine example
  with separator syntax (`gh-cli index_issues "q1" owner/repo && gh-cli index_issues "q2"
  owner/repo`), that output ALWAYS returns in full to context (filtering via
  head/tail/grep/sed/awk/wc is impossible — narrowing is only via the tool's own `--limit`/
  `--offset`/`--path`/`--metadata-only`/`--sort-by` args), and that `repo_freshness` may join the
  chain.

## Verification (as of 2026-08-07)

Regression: `dev/hook_smoke/test_block_gh_cli_chained.py` extended from 18 to 21 cases (3 new:
repo_freshness+chain PASS, echo-variant BLOCK, repo_freshness+git PASS-hook-not-triggered) — all
21 pass.

New incident-replay probe `dev/hook_smoke/probe_gh_cli_repo_freshness_incident.py` — feeds the
VERBATIM commands from messages [118], [121], [129] through the real hook via subprocess, plus a
generalized `| head` block case, a `repo_freshness && git log` pass case, and a plain non-gh-cli
baseline. 6/6 case checks pass (msg[121] now passes; msg[118] echo-variant still blocks;
`| head` still blocks; msg[129] double-index chain still passes unaffected; repo_freshness+git
never triggers the hook; plain command untouched). 3/3 `_BLOCK_MESSAGE` content checks pass
(combine example present verbatim, "ALWAYS returns IN FULL" wording present, "repo_freshness may
join the chain" wording present) — checked against the msg[118]-variant's actual stderr output.
Report: `dev/hook_smoke/md/gh_cli_repo_freshness_incident_probe_report.md`.
