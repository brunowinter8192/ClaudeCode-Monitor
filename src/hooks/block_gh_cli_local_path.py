# INFRASTRUCTURE
import json
import os
import re
import shlex
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire

# Match a gh-cli get_file_content or download_files call anywhere in the command. These are the
# only two gh-cli subcommands whose positional args include a repo-relative path
# (get_file_content <owner> <repo> <path>; download_files <owner> <repo> <path> [<path>...]).
_GH_LOCAL_PATH_RE = re.compile(r'\bgh-cli\s+(get_file_content|download_files)\b')

# Shell command separators bounding one logical gh-cli segment — same set as block_gh_cli_chained.py.
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')

# Value-consuming flags per subcommand. download_files' --dest is the trap: it takes a LOCAL
# directory BY DESIGN (where downloaded files land) and must never be checked as a repo path —
# excluding it here is what keeps `download_files o r src/a.py --dest /tmp/x` a legal ALLOW.
_VALUE_FLAGS = {
    'get_file_content': {'--offset', '--limit'},
    'download_files': {'--dest'},
}

_BLOCK_MESSAGE = (
    "gh-cli {sub}'s path argument must be repo-relative (e.g. src/main.py), never a local "
    "filesystem path — the GitHub API 404s/validation-errors on it. Offending value: '{path}'. "
    "Pass a path inside the TARGET REPO, not a Claude Code tool-result path "
    "(~/.claude/projects/.../tool-results/...) or any other local/absolute path.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a gh-cli get_file_content/download_files
# call carries a positional path argument starting with / or ~ (a local filesystem path where a
# repo-relative path is required). Fail-open on any parse error.
def block_gh_cli_local_path_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    for m in _GH_LOCAL_PATH_RE.finditer(stripped):
        subcommand = m.group(1)
        seg_end = _segment_end(stripped, m.end())
        segment = command[m.start():seg_end]
        bad_path = _find_local_path(subcommand, segment)
        if bad_path is not None:
            message = _BLOCK_MESSAGE.format(sub=subcommand, path=bad_path)
            print(message, file=sys.stderr, end="")
            log_fire("block_gh_cli_local_path", "block", "Bash", command,
                     reason=message, session_id=session_id)
            sys.exit(2)
    sys.exit(0)


# FUNCTIONS

# Parse stdin JSON; return (command, session_id); (None, None) on any error (fail-open)
def _parse_command():
    try:
        payload = json.loads(sys.stdin.read())
        cmd = payload.get("tool_input", {}).get("command")
        return (cmd if isinstance(cmd, str) else None), payload.get("session_id")
    except Exception:
        return None, None


# End index of the logical gh-cli segment starting at the match end — bounded by the first
# chain/pipe/redirect-adjacent separator, or end of string.
def _segment_end(stripped: str, start: int) -> int:
    m = _SEPARATOR_RE.search(stripped, start)
    return m.start() if m else len(stripped)


# Tokenize the real (quote-preserved) segment text, drop the `gh-cli <subcommand>` prefix, and
# walk the remaining tokens classifying each as a value-consuming flag (skip it AND its value),
# any other flag (skip it alone), or a positional. Returns the first positional AFTER owner/repo
# (index 2+ — the repo-path arg(s): singular for get_file_content, one-or-more for download_files)
# that starts with / or ~; None if none found or the segment fails to tokenize.
def _find_local_path(subcommand: str, segment: str):
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return None
    value_flags = _VALUE_FLAGS.get(subcommand, set())
    positionals = []
    i = 2  # tokens[0]='gh-cli', tokens[1]=subcommand
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith('--'):
            if '=' not in tok and tok in value_flags:
                i += 2
                continue
            i += 1
            continue
        positionals.append(tok)
        i += 1
    for path in positionals[2:]:
        if path.startswith('/') or path.startswith('~'):
            return path
    return None


if __name__ == "__main__":
    block_gh_cli_local_path_workflow()
