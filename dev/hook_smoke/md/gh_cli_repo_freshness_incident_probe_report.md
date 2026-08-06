# gh-cli repo_freshness incident probe — block_gh_cli_chained.py

Replays the exact commands from the websearch-session incident (`api_requests_opus_websearch_1786052022_original.jsonl`, messages [118]-[129]) through the real hook via subprocess.

| case | source | expected exit | actual exit | stderr shape | pass |
|---|---|---|---|---|---|
| msg121_fixed_retry_now_passes | incident msg [121] | 0 | 0 | (empty) | PASS |
| msg118_echo_variant_still_blocked | incident msg [118] | 2 | 2 | 732 chars | PASS |

  stderr: `gh-cli search/research tools (search_repos, search_code, get_repo_tree, get_file_content, index_issues, index_discussions, index_releases) must run STANDALONE — do NOT pipe to grep/head/tail/sed/awk/w...`

| index_issues_piped_to_head_still_blocked | generalization of the piping restriction | 2 | 2 | 732 chars | PASS |

  stderr: `gh-cli search/research tools (search_repos, search_code, get_repo_tree, get_file_content, index_issues, index_discussions, index_releases) must run STANDALONE — do NOT pipe to grep/head/tail/sed/awk/w...`

| msg129_double_index_issues_still_passes | incident msg [129] | 0 | 0 | (empty) | PASS |
| repo_freshness_chained_with_git_still_passes | hook must not trigger — repo_freshness alone never matches _GH_SEARCH_RE | 0 | 0 | (empty) | PASS |
| plain_non_gh_cli_command_untouched | baseline no-op | 0 | 0 | (empty) | PASS |

## _BLOCK_MESSAGE content checks (against msg118 echo-variant stderr)

| check | pass |
|---|---|
| combine example present | PASS |
| output-always-full-context stated | PASS |
| repo_freshness-may-join stated | PASS |

## Overall: ALL PASS