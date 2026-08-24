# INFRASTRUCTURE
import re

# CLI tools this hook family orchestrates around. A Bash segment invoking one of these
# (optionally env-var-prefixed) is never "foreign" to another such segment — cross-CLI
# chaining in one Bash call is allowed (2026-08 relax: block_gh_cli_chained.py /
# block_rag_cli_chained.py / block_websearch_scrape_chained.py / block_worker_cli_read_chained.py
# used to require same-tool-only chains; sourced by grepping every `-cli\b`/bare-tool anchor
# actually referenced across src/hooks/*.py). `bd` deliberately excluded — retired
# (rewrite_bd_invalid_repo.py deleted 2026-08, bd is dead).
KNOWN_CLI_TOOLS = ("gh-cli", "rag-cli", "worker-cli", "reddit-cli", "linkedin", "websearch")

_ASSIGN_TOKEN = r'[A-Za-z_][A-Za-z0-9_]*=\S*'
_ASSIGN_PREFIX = rf'(?:{_ASSIGN_TOKEN}\s+)*'
_KNOWN_CLI_RE = re.compile(
    rf'^{_ASSIGN_PREFIX}(?:{"|".join(re.escape(t) for t in KNOWN_CLI_TOOLS)})(?:\s|$)'
)
# Leading guard: `cd`, or a `test`/`[ ... ]` conditional (`[ -f x ] && rag-cli ...`) — gates a
# following CLI call without being one itself. Matches block_rag_cli_chained.py's pre-existing
# "cd, guards" allowance, generalized so every chained-CLI hook shares one definition.
_GUARD_RE = re.compile(r'^cd\b|^\[.*\]$|^test\b')


# FUNCTIONS

# True if `segment` (already whitespace-stripped) invokes one of KNOWN_CLI_TOOLS, optionally
# env-var-prefixed. Subcommand-agnostic — any subcommand of a known CLI counts.
def is_known_cli_segment(segment: str) -> bool:
    return bool(_KNOWN_CLI_RE.match(segment))

# True if `segment` is a `cd` or `test`/`[ ... ]` guard — allowed alongside known-CLI segments
# without itself being a CLI call.
def is_guard_segment(segment: str) -> bool:
    return bool(_GUARD_RE.match(segment))
