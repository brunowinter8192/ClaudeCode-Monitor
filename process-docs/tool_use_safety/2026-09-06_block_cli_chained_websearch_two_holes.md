# block_cli_chained.py: two independent holes against websearch (2026-09-06)

A real run today defeated `block_cli_chained.py`'s protection on `websearch` twice, independently.
Neither was found by inspection — both surfaced from an actual agent transcript: a main agent
redirected a protected scrape to a file and read it back with `head` in the following call, three
times in one session, and none of the three fired any hook.

## Hole 1 — the protected subcommand name no longer existed

`_known_cli.py`'s `PROTECTED_SUBCOMMANDS["websearch"]` listed `{"scrape_url"}`. websearch's
`cli.py` has carried `search_web`, `search_engine_drilldown`, `scrape_url_chromium`, `discover_urls`
for a while — there has been no `scrape_url` subcommand this whole time. `is_protected_segment`
does an exact set-membership test against `PROTECTED_SUBCOMMANDS[tool]`, so
`websearch scrape_url_chromium <url> > /tmp/out.txt` — the real, current, protected subcommand —
never matched the set and rule 2 (redirect-on-protected) silently never fired for it.

Fix: `PROTECTED_SUBCOMMANDS["websearch"]` now reads `{"scrape_url_chromium"}`.

### Audit of the other 7 entries

Each entry was checked the same way hole 1 was found: resolve the wrapper to its actual
interpreter+script invocation, then to the real subcommand list.

| Tool | Wrapper resolves to | Listed subcommand(s) | Result |
|---|---|---|---|
| `gh-cli` | `.../gh-cli/.venv/bin/python .../gh-cli/cli.py` | `get_issue`, `list_issues` | both exist, unchanged |
| `rag-cli` | `.../rag-cli/venv/bin/python .../rag-cli/cli.py` | `search` | exists, unchanged |
| `worker-cli` | itself is a bash script (no cli.py indirection) | `capture`, `response` | both exist as case arms, unchanged |
| `reddit-cli` | `.../reddit-cli/.venv/bin/python .../reddit-cli/cli.py` | `search_subreddits` | exists, unchanged |
| `websearch` | `.../websearch/venv/bin/python .../websearch/cli.py` | `scrape_url` | **did not exist — fixed to `scrape_url_chromium`** |
| `linkedin` | `.../jobscraper/venv/bin/python .../jobscraper/cli.py` | `None` (whole invocation) | all 5 real subcommands (`get_company_info`, `get_company_posts`, `get_messages`, `get_thread`, `get_notifications`) exist; `None` needs no subcommand name to stay correct, unchanged |
| `penny-cli` | `cd .../penny && venv/bin/python -m src` | `None` (whole invocation) | module form, no subcommands at all; unchanged |
| `duallog` | `cd monitor-cc && ./venv/bin/python -m src.dual_log_cli` | `None` (whole invocation) | real subcommands are `sessions`/`msgs`/`expand`/`search`/`reqs` — a 5th, `reqs`, has been added since the table's comment was written, but `None` protects every invocation regardless of subcommand name, so this caused no functional gap; the comment text was updated to mention `reqs` for accuracy |

`linkedin` is the one wrapper whose on-disk project directory (`jobscraper`) differs from its
wrapper/tool name (`linkedin`) — relevant again in hole 2 below.

## Hole 2 — the wrapper name is not the only way in

`_KNOWN_CLI_RE` (and therefore `match_known_cli_segment`) requires one of the 8 tool names at the
start of a chain segment. Five of the eight wrappers (`gh-cli`, `rag-cli`, `reddit-cli`,
`websearch`, `linkedin`) are 2-line bash shims of the identical shape:

```bash
#!/usr/bin/env bash
exec <dir>/venv/bin/python <dir>/cli.py "$@"
```

Invoking the same `cli.py` through the interpreter directly never matches `_KNOWN_CLI_RE`, because
the wrapper name never appears in the command text at all. The command the agent actually ran,
three times:

```
cd /Users/.../Meta/ClaudeCode/cli/websearch && ./venv/bin/python cli.py scrape_url_chromium "<url>" > /tmp/out.txt 2>&1
```

`block_cli_chained.py`'s entry gate (`_segment_stages_with_cli`) returned `False` on the very first
check — no rule was ever evaluated, exit 0.

### The tension with `block_venv_no_redirect.py`

`block_venv_no_redirect.py` requires a redirect on any `./venv/bin/python <script>.py` call — it
had already fired on this same session, on the no-redirect form of this exact command, forcing the
agent to add `> /tmp/out.txt 2>&1` in the first place. A naive fix that just adds the interpreter
form to the "protected" check inside `block_cli_chained.py` would then, for the redirected form the
agent actually ran, get BLOCKED by `block_cli_chained.py`'s rule 2 (protected + redirect present) —
while the no-redirect form of the identical command gets BLOCKED by `block_venv_no_redirect.py`
(no redirect present). No version of that command, redirected or not, would pass both hooks.

That is not a bug to reconcile — it is the exact desired outcome. `block_venv_no_redirect.py`'s
redirect-discipline rule has nothing to do with output-boundedness (it exists so ANY long-running
venv-python script call leaves a pollable log, regardless of what the script does); making
`block_cli_chained.py` recognize the interpreter form independently does not change that hook's own
correctness on its own terms. The two hooks together turn the interpreter path into a dead end for
a protected subcommand either way, which is precisely "cannot escape the rule by taking the
interpreter path instead of the wrapper." `block_venv_no_redirect.py` was left untouched.

### Fix

`_known_cli.py` gained `match_interpreter_cli_segment(segment, command_context)`: matches a bare
`(?:\S+/)?python3? (?:\S+/)?cli\.py <sub>?` shape, then resolves WHICH tool by searching
`command_context` (the whole shell-stripped Bash command) for one of 5 known project-directory
basenames (`_CLI_PY_DIR_TOOL`, mapping `jobscraper` → `linkedin` for the one wrapper/directory-name
mismatch) — the directory a preceding `cd` landed in, or one baked into an absolute
interpreter/script path on the same segment. `resolve_cli_segment(segment, command_context)` tries
the wrapper-name match first, then falls back to the interpreter form; `block_cli_chained.py` now
calls this everywhere it used to call `match_known_cli_segment` directly, threading the whole
shell-stripped command through as `command_context` to all 3 rule checks — so rule 1 (pipe) and
rule 3 (readback) apply to the interpreter form exactly like rule 2 does, not just the specific
redirect case that was observed.

### Scope deliberately excluded

`worker-cli` has no interpreter indirection to bypass (its wrapper IS the bash script). `penny-cli`
(`venv/bin/python -m src`, bare) and `duallog` (`./venv/bin/python -m src.dual_log_cli`, run from
monitor-cc's own root) use module-form invocation, not a `cli.py` script path. Extending the same
mechanism to them was considered and rejected: `-m src` is a generic enough anchor that it would
collide with ordinary `python -m src...` invocations any project on this machine might run (this
hook is global, firing for every project), and no interpreter-path bypass of either tool has been
observed. Per the evidence-burden standard — complexity that reaches production traces back to a
failure observed in real data — this stays an open, unobserved, theoretical gap rather than a fix.

## Verification

Fed directly into both hooks (`src/hooks/block_cli_chained.py`, `src/hooks/block_venv_no_redirect.py`):

- `cd .../websearch && ./venv/bin/python cli.py scrape_url_chromium "<url>" > /tmp/out.txt 2>&1` —
  `block_cli_chained.py` exit 2 (rule 2, hole 2 closed); `block_venv_no_redirect.py` exit 0
  (redirect present, satisfies its own rule).
- `websearch scrape_url_chromium "<url>" > /tmp/out.txt` — `block_cli_chained.py` exit 2 (rule 2,
  hole 1 closed); `block_venv_no_redirect.py` exit 0 (not a venv-python-script call, out of its
  scope).
- `websearch search_web "some query" > /tmp/out.txt` — `block_cli_chained.py` exit 0 (deliberately
  unprotected subcommand, confirmed still passing); `block_venv_no_redirect.py` exit 0.
- The no-redirect variant of the first command — `block_venv_no_redirect.py` exit 2 ("add
  redirect: ..."); `block_cli_chained.py` exit 0 (no redirect present, rule 2 doesn't engage) —
  demonstrating the pincer described above: redirected or not, the interpreter path for this
  protected subcommand never passes both hooks.

Smoke suite `dev/hook_smoke/test_block_cli_chained.py`: 36 → 42 cases (the stale `scrape_url`
redirect-BLOCK case corrected to the real `scrape_url_chromium` name, a `search_web` redirect PASS
added, and 5 interpreter-path-bypass cases added — the verbatim incident, the same piped, a
different tool via the interpreter form to confirm the mechanism generalizes beyond websearch, an
unprotected subcommand via the interpreter form staying PASS, and an unrelated project's own
`cli.py` with no known directory marker staying PASS). All 42 pass.
