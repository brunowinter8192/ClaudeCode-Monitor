# block_gh_cli_local_path.py smoke report

15-case smoke via `dev/hook_smoke/test_block_gh_cli_local_path.py`, real subprocess invocation of
`src/hooks/block_gh_cli_local_path.py` with synthetic PreToolUse Bash payloads.

| case | command | expected exit | actual exit | result |
|---|---|---|---|---|
| get_file_content with `/Users/...` path | `gh-cli get_file_content owner repo /Users/x/.claude/projects/foo/tool-results/bar.txt` | 2 | 2 | PASS |
| get_file_content with `~/...` path | `gh-cli get_file_content owner repo ~/foo.py` | 2 | 2 | PASS |
| download_files with an absolute repo-path positional | `gh-cli download_files owner repo /Users/x/abs/path.py` | 2 | 2 | PASS |
| download_files with a `~/...` path among multiple positionals | `gh-cli download_files owner repo src/a.py ~/b.py --dest /tmp/x` | 2 | 2 | PASS |
| get_file_content local path with `--limit` flag before it | `gh-cli get_file_content owner repo --limit 5 /Users/x/foo.py` | 2 | 2 | PASS |
| get_file_content with repo-relative path | `gh-cli get_file_content owner repo src/main.py` | 0 | 0 | PASS |
| **download_files with repo paths + `--dest /tmp/x` (the trap case)** | `gh-cli download_files owner repo src/a.py src/b.py --dest /tmp/x` | 0 | 0 | PASS |
| download_files with `--dest` BEFORE the paths | `gh-cli download_files owner repo --dest /tmp/x src/a.py` | 0 | 0 | PASS |
| get_file_content with `--metadata-only` flag, repo-relative path | `gh-cli get_file_content owner repo src/main.py --metadata-only` | 0 | 0 | PASS |
| get_repo_tree untouched | `gh-cli get_repo_tree owner repo --path /Users/x/foo` | 0 | 0 | PASS |
| index_issues untouched | `gh-cli index_issues "q" owner/repo` | 0 | 0 | PASS |
| repo_freshness untouched | `gh-cli repo_freshness owner repo` | 0 | 0 | PASS |
| non-gh-cli command untouched | `echo hello` | 0 | 0 | PASS |
| pattern inside single-quotes (shell-stripped) | `echo 'gh-cli get_file_content owner repo /Users/x/foo.py'` | 0 | 0 | PASS |
| pattern inside heredoc body (shell-stripped) | `cat <<'EOF' ... gh-cli get_file_content owner repo /Users/x/foo.py ... EOF` | 0 | 0 | PASS |

**Result: 15/15 passed.**

## Trap case verified explicitly

`download_files`'s `--dest` flag takes a LOCAL directory by design (where downloaded files land)
— it must never be checked as a repo-path positional. Verified in both flag positions (after the
paths, and before the paths) — the hook's flag-vs-positional tokenizer correctly skips `--dest`
and its value in either order, never flagging the destination directory itself even though it is
itself an absolute local path (`/tmp/x`).
