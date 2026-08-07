# 2026-08-07 — New hook: block gh-cli local filesystem paths

## Problem

Agents sometimes pass a local filesystem path where `gh-cli get_file_content`/`download_files`
require a repo-relative path — most commonly a Claude Code tool-result path
(`~/.claude/projects/.../tool-results/...`), sometimes any other absolute/`~` path. The GitHub
API then 404s or validation-errors, since these subcommands' `path` argument is resolved against
the TARGET REPO's tree, never the local filesystem. The gh-cli skill prose that used to teach this
distinction is being removed — the enforcement moves to block time instead, same philosophy as
`block_gh_cli_chained.py` (which similarly took over teaching the standalone-call rule from prose).

## Design

New hook `src/hooks/block_gh_cli_local_path.py`, registered in `hook_setup.py`'s `_HOOK_SCRIPTS`
immediately after `block_gh_cli_chained.py`. Anchors on `\bgh-cli\s+(get_file_content|
download_files)\b` — the only two gh-cli subcommands whose positional args include a path (found
by reading the real `cli.py` argparse definitions directly: `get_file_content <owner> <repo>
<path>`; `download_files <owner> <repo> <path> [<path>...] [--dest DIR]`).

Segment isolation follows `block_rag_cli_document_repeat.py`'s pattern exactly: find the segment
boundary via the same separator set `block_gh_cli_chained.py` uses, then slice the segment out of
the ORIGINAL (unstripped) command using indices computed against the `_strip_non_shell_active`d
copy — position-preserving, so the real (quote-intact) argument text is recovered for tokenizing,
not the blanked-out stripped version.

Tokenized via `shlex.split` (not a hand-rolled split — real gh-cli plugin arguments can contain
quoted spaces, e.g. multi-word search queries in other subcommands, so a shell-aware tokenizer is
the correct baseline here too, matching the two existing hooks that already use `shlex` for exactly
this reason). Walked token-by-token classifying each as a value-consuming flag (skip it AND its
value token), any other flag (skip alone), or a positional. Positions `[2:]` (after owner/repo)
are the candidate path argument(s) — checked for a `/` or `~` prefix.

**The one false-positive trap, solved directly rather than by exclusion-listing:**
`download_files --dest DIR` — `DIR` is a LOCAL directory BY DESIGN (where downloaded files land),
and per-subcommand `_VALUE_FLAGS` (`get_file_content`: `--offset`/`--limit`; `download_files`:
`--dest`) means `--dest`'s value is consumed as a flag-value pair and never enters the
positionals list at all — correct regardless of whether `--dest` appears before or after the
repo-path positionals in the command (verified both orderings explicitly in the smoke suite,
since a purely position-based heuristic — e.g. "everything after the Nth token" — would have
broken on the `--dest`-before-paths ordering).

## Verification (as of 2026-08-07)

`dev/hook_smoke/test_block_gh_cli_local_path.py` — 15/15 pass: 5 block cases (`/Users/...`,
`~/...`, `download_files` absolute positional, `~/...` among multiple `download_files`
positionals, a local path preceded by an unrelated value-flag), 4 pass cases (repo-relative path,
the `--dest` trap in both flag orderings, `--metadata-only` boolean flag present), 4
untouched-command cases (`get_repo_tree`/`index_issues`/`repo_freshness`/non-gh-cli), 2
shell-strip cases (single-quoted, heredoc). Report: `dev/hook_smoke/md/
block_gh_cli_local_path_smoke_report.md`. `hook_setup.py` registration confirmed via direct
import (entry present exactly once, correct neighbors, `Bash` matcher). Regression:
`test_block_gh_cli_chained.py` (21/21), `test_rewrite_gh_cli_read_noise.py` (12/12),
`test_hook_setup_main_branch_gate.py` (10/10) — all unaffected.
