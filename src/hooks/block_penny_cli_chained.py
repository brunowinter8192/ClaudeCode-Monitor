# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire

# One `VAR=value` shell assignment token, optional prefix on the penny-cli segment itself —
# the only relaxation this hook grants (`penny-cli --klasse "X"` is standalone regardless of
# an env-var prefix). Unlike block_rag_cli_chained.py / block_gh_cli_chained.py / etc., NO
# _known_cli import — cross-CLI chaining, cd guards, echo, and loop scaffolding are all
# ordinary "anything else" here and must all block, not just be excluded from the relaxed set.
_ASSIGN_TOKEN = r'[A-Za-z_][A-Za-z0-9_]*=\S*'
_ASSIGN_PREFIX = rf'(?:{_ASSIGN_TOKEN}\s+)*'
# A segment is a `penny-cli` invocation: optionally env-prefixed, then the literal token
# `penny-cli` followed by whitespace or end-of-segment (not `penny-cli-something`). Matched
# per-segment AFTER splitting, exactly like block_rag_cli_chained.py's _RAG_CLI_SEGMENT_RE —
# a `penny-cli` PATH SUBSTRING (`ls .../penny/bin/penny-cli`, `ln -sf .../penny-cli ~/...`)
# never starts a segment, so it never triggers this hook.
_PENNY_CLI_SEGMENT_RE = re.compile(rf'^{_ASSIGN_PREFIX}penny-cli(?:\s|$)')
# Shell command separators: && || ; newline | (single, after ||) and space-bounded &.
# Order matters — && before single &, || before |. `2>&1` / `>&` not matched (no whitespace
# before &, no |/;/&& token). Same pattern as the rest of the chained-CLI hook family.
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')
# Redirect operators — blocked on the penny-cli segment itself (unlike every other hook in
# this family, which allows a redirect on a non-protected subcommand): penny-cli's output is
# bounded and must land directly in context, never captured to a file and read back.
_REDIRECT_RE = re.compile(r'2>&1|2>|&>|>>|<<|>|<')
# Command/process substitution anywhere in the raw command — checked against the RAW
# (unstripped) command, same reasoning as block_rag_cli_index_isolated.py's _SUBSHELL_RE:
# _strip_non_shell_active blanks $(...)/backticks that sit INSIDE a double-quoted region even
# though real bash still evaluates them there.
_SUBSHELL_RE = re.compile(r'\$\(|`|<\(|>\(')
# A command substitution that itself INVOKES penny-cli as its first token — `$(penny-cli ...)`
# or `` `penny-cli ...` `` — is a trigger even though the outer segment (e.g. `OUT=$(penny-cli
# ...)`) never matches _PENNY_CLI_SEGMENT_RE at segment-start. Anchored right after the opening
# `$(`/backtick (with optional whitespace/env-prefix) so `$(ls .../penny-cli)` — penny-cli as a
# path substring inside an unrelated substitution — does not false-trigger.
_WRAPPED_PENNY_RE = re.compile(rf'(?:\$\(|`)\s*{_ASSIGN_PREFIX}penny-cli(?:\s|$|\)|`)')

_BLOCK_MESSAGE = (
    "penny-cli must run ALONE in its own Bash invocation — no piping, no chaining "
    "(&&, ||, ;, newline, background &), no redirects (>, >>, 2>&1, &>, <), and no command "
    "substitution wrapping or embedding it. None of the chained-CLI relaxations apply here "
    "(cd, other known CLIs, echo, loop scaffolding all block too) — its output is bounded and "
    "must land directly in context. Re-issue `penny-cli --klasse \"<Klasse>\"` as its own "
    "standalone Bash call, with nothing else.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a `penny-cli` invocation shares the Bash
# command with anything else at all — a second segment of ANY kind, a redirect on its own
# segment, or a command substitution anywhere. Fail-open on any parse error.
def block_penny_cli_chained_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    segments = [s.strip() for s in _SEPARATOR_RE.split(stripped) if s.strip()]
    penny_segments = [s for s in segments if _PENNY_CLI_SEGMENT_RE.match(s)]
    wrapped = bool(_WRAPPED_PENNY_RE.search(command))
    if not penny_segments and not wrapped:
        sys.exit(0)
    if wrapped:
        _block(command, session_id)
    if len(segments) > 1:
        _block(command, session_id)
    if _REDIRECT_RE.search(penny_segments[0]):
        _block(command, session_id)
    if _SUBSHELL_RE.search(command):
        _block(command, session_id)
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

# Print block message, log the fire event, exit 2
def _block(command: str, session_id) -> None:
    print(_BLOCK_MESSAGE, file=sys.stderr, end="")
    log_fire("block_penny_cli_chained", "block", "Bash", command,
             reason=_BLOCK_MESSAGE, session_id=session_id)
    sys.exit(2)


if __name__ == "__main__":
    block_penny_cli_chained_workflow()
