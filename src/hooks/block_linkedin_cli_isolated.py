# INFRASTRUCTURE
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _shell_strip import _strip_non_shell_active
from _fire_log import log_fire

# One `VAR=value` shell assignment token, optional prefix on the linkedin segment itself —
# needed for the real `LINKEDIN_HEADED=1 linkedin get_messages` debug pattern
# (src/linkedin/browser.py reads LINKEDIN_HEADED for headed-browser mode). NOT a `cd`
# allowance: unlike `rag-cli index` (path-relative, needs a preceding cd),
# `~/.local/bin/linkedin` is resolved via $PATH from any directory — there is no
# legitimate reason to chain a `cd` before it, so none is exempted here.
_ASSIGN_TOKEN = r'[A-Za-z_][A-Za-z0-9_]*=\S*'
_ASSIGN_PREFIX = rf'(?:{_ASSIGN_TOKEN}\s+)*'
# A segment is a `linkedin` invocation: optionally env-prefixed, then the literal token
# `linkedin` followed by whitespace or end-of-segment (NOT `linkedin-something`/`linkedinX`
# — a bare `\b` word boundary would wrongly match those, since `-`/digits are non-word
# chars too; requiring `\s|$` after the token is the tighter, correct boundary).
_LINKEDIN_SEGMENT_RE = re.compile(rf'^{_ASSIGN_PREFIX}linkedin(?:\s|$)')
# Shell command separators: && || ; newline | (single, after ||) and space-bounded &.
# Order matters — && before single &, || before |. `2>&1` / `>&` not matched
# (no whitespace before &, no |/;/&& token). Same pattern as block_gh_cli_chained.py /
# block_rag_cli_chained.py (the simpler, non-hardened separator form — see the subshell
# note below for why the more aggressive bare-`&` variant from
# block_rag_cli_index_isolated.py was not adopted here).
_SEPARATOR_RE = re.compile(r'&&|\|\||;|\n|\||\s&(?=\s|$)')

# SCOPE DECISION, stated here (not only in the session's chat/report) so a future reader
# does not "fix" this as an oversight: this hook does NOT chase command/process
# substitution ($(...), `...`, <(...), >(...)) the way block_rag_cli_index_isolated.py
# hardens against it (see that hook's Gotchas — env-var-value smuggling, bare-`&` with no
# surrounding whitespace, etc.). That hook's target (`rag-cli index`, a multi-minute
# operation that takes a collection lock) has real correctness stakes if a bypass sneaks a
# second command through. This hook's target is a PERFORMANCE guard — chaining/piping
# `linkedin` wastes ~7s of cold Chrome start + a process-lock wait, it does not corrupt
# state. A false negative here (a cleverly obfuscated bypass) only loses that optimization;
# a false positive blocks legitimate work outright (a $-var, a path, a quoted mention, a
# grep argument that happens to contain the word "linkedin"). Given that asymmetry, this
# hook is intentionally biased toward precision (segment-start-anchored matching, quote
# stripping) over exhaustive recall against deliberate obfuscation. Revisit only if a real
# bypass incident is observed, the same way block_rag_cli_index_isolated.py's hardening
# was driven by an actual observed incident, not by anticipation.

_BLOCK_MESSAGE = (
    "The `linkedin` CLI must run ALONE in its own Bash invocation — no piping "
    "(grep/head/tail/sed/awk/wc), no chaining with any other command, and no more than one "
    "`linkedin` call per Bash invocation. It holds a process lock for its WHOLE dispatch "
    "and cold-starts Chrome (~7s) per invocation — a second `linkedin` call in the same "
    "Bash block does NOT run in parallel with the first, it blocks on the first's lock "
    "until that invocation finishes (or its own 120s wait times out). Chaining cannot make "
    "this faster, only slower. Run each `linkedin` call in its own separate Bash tool call "
    "instead; use the CLI's own --count/--days/--date args to narrow results.\n"
)


# ORCHESTRATOR

# Read Bash tool_input from stdin; exit 2 + stderr if a `linkedin` invocation shares the
# Bash command with anything else at all — a second segment of ANY kind (another command,
# a pipe target, or a second `linkedin` call) is a violation. Fail-open on any parse error.
def block_linkedin_cli_isolated_workflow() -> None:
    command, session_id = _parse_command()
    if command is None:
        sys.exit(0)
    stripped = _strip_non_shell_active(command)
    segments = [s.strip() for s in _SEPARATOR_RE.split(stripped) if s.strip()]
    linkedin_segments = [s for s in segments if _LINKEDIN_SEGMENT_RE.match(s)]
    if not linkedin_segments:
        sys.exit(0)
    if len(segments) > 1:
        print(_BLOCK_MESSAGE, file=sys.stderr, end="")
        log_fire("block_linkedin_cli_isolated", "block", "Bash", command,
                 reason=_BLOCK_MESSAGE, session_id=session_id)
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


if __name__ == "__main__":
    block_linkedin_cli_isolated_workflow()
