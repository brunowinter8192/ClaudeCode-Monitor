# INFRASTRUCTURE
import re

# CLI tools this hook family orchestrates around. A Bash segment invoking one of these
# (optionally env-var-prefixed) is never "foreign" to another such segment — cross-CLI
# chaining in one Bash call is allowed (2026-08 relax: block_gh_cli_chained.py /
# block_rag_cli_chained.py / block_websearch_scrape_chained.py / block_worker_cli_read_chained.py
# used to require same-tool-only chains; sourced by grepping every `-cli\b`/bare-tool anchor
# actually referenced across src/hooks/*.py). `bd` deliberately excluded — retired
# (rewrite_bd_invalid_repo.py deleted 2026-08, bd is dead). `duallog` added 2026-09-04 for
# block_duallog_chained.py, so a duallog call may chain with the other six tools and with itself.
KNOWN_CLI_TOOLS = ("gh-cli", "rag-cli", "worker-cli", "reddit-cli", "linkedin", "websearch", "duallog")

_ASSIGN_TOKEN = r'[A-Za-z_][A-Za-z0-9_]*=\S*'
_ASSIGN_PREFIX = rf'(?:{_ASSIGN_TOKEN}\s+)*'
_KNOWN_CLI_RE = re.compile(
    rf'^{_ASSIGN_PREFIX}(?:{"|".join(re.escape(t) for t in KNOWN_CLI_TOOLS)})(?:\s|$)'
)
# Leading guard: `cd`, or a `test`/`[ ... ]` conditional (`[ -f x ] && rag-cli ...`) — gates a
# following CLI call without being one itself. Matches block_rag_cli_chained.py's pre-existing
# "cd, guards" allowance, generalized so every chained-CLI hook shares one definition.
_GUARD_RE = re.compile(r'^cd\b|^\[.*\]$|^test\b')
# Pure `echo`/`printf` segment — produces separator/label output only (e.g. a loop-iteration
# marker) and can never filter or truncate another segment's output elsewhere in the same Bash
# call. 2026-08 loop relax: chained-CLI hooks used to block any echo mixed into a known-CLI
# chain (real case: `for n in ...; do echo "=== #$n ==="; gh-cli get_issue ...; done`).
_ECHO_RE = re.compile(r'^(?:echo|printf)\b')
# `for`/`while` loop headers — pure iteration scaffolding, never a CLI call themselves.
_LOOP_HEADER_RE = re.compile(r'^(?:for|while)\b')
# Bare `do`/`done` — own segment when the loop is written across newlines/semicolons.
_DO_DONE_RE = re.compile(r'^(?:do|done)$')
# `do <segment>` on one line (e.g. `do echo "..."` or `do gh-cli get_issue ...`) — the `do`
# keyword directly prefixing an otherwise-allowed segment.
_DO_PREFIX_RE = re.compile(r'^do\s+(.+)$')


# FUNCTIONS

# True if `segment` (already whitespace-stripped) invokes one of KNOWN_CLI_TOOLS, optionally
# env-var-prefixed. Subcommand-agnostic — any subcommand of a known CLI counts.
def is_known_cli_segment(segment: str) -> bool:
    return bool(_KNOWN_CLI_RE.match(segment))

# True if `segment` is a `cd` or `test`/`[ ... ]` guard — allowed alongside known-CLI segments
# without itself being a CLI call.
def is_guard_segment(segment: str) -> bool:
    return bool(_GUARD_RE.match(segment))

# True if `segment` is a pure `echo`/`printf` call — output-only, never filters or truncates.
def is_echo_segment(segment: str) -> bool:
    return bool(_ECHO_RE.match(segment))

# True if `segment` is for/while loop scaffolding: a `for ...`/`while ...` header, a bare
# `do`/`done`, or `do <segment>` where <segment> is itself a known-CLI call, guard, or echo/printf.
def is_loop_scaffold_segment(segment: str) -> bool:
    if _LOOP_HEADER_RE.match(segment) or _DO_DONE_RE.match(segment):
        return True
    match = _DO_PREFIX_RE.match(segment)
    if not match:
        return False
    inner = match.group(1).strip()
    return is_known_cli_segment(inner) or is_guard_segment(inner) or is_echo_segment(inner)

# True if `segment` needs no further policing in a chained-CLI hook: a known-CLI call, a
# cd/test guard, a pure echo/printf, or for/while/do/done loop scaffolding around one of those.
def is_allowed_chain_segment(segment: str) -> bool:
    return (is_known_cli_segment(segment) or is_guard_segment(segment)
            or is_echo_segment(segment) or is_loop_scaffold_segment(segment))
