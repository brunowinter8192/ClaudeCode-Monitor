# Help Surface Redirect — CLI `--help` Points at the Skill (2026-09-02)

## Problem

Five CLIs sit next to the agent: `reddit-cli`, `gh-cli`, `websearch`, `rag-cli`, `worker-cli`.
Three of them ship a skill (`reddit-cli-search`, `gh-cli-search`, the three `websearch-*` skills)
that describes the mandatory usage pipe. The other two (`rag-cli`, `worker-cli`) have their usage
written into the orchestrator rules and carry no skill.

Observed on 2026-08-24 with `reddit-cli`: the agent never opened the skill and ran
`reddit-cli deep --help` instead. The argparse-generated help listed `--skip-index`, a flag the
skill deliberately leaves undocumented. The agent used it, ~440 posts stayed unindexed, the
`rag-cli search` step of the pipe never ran, and the skill's query rules (1-3 keywords, synonyms as
separate queries) were violated throughout. The skill lay next to the CLI as an optional file;
`--help` was the cheaper entry point and won.

## Options weighed

- **Hook on the first Bash call of a binary** that injects or forces the skill. Rejected for this
  round: another hook in an already large hook family, and it would fire on every legitimate
  first call, not only on help misuse.
- **Inject the skill list into context at session start.** Rejected: the skill list is already
  visible to the agent; visibility was not the failure, the cheaper alternative was.
- **Replace `--help` itself** so the only help a CLI gives is the instruction to invoke its skill.
  Chosen. It removes the cheaper alternative at the exact point where the agent reaches for it,
  costs no hook, and needs one small change per CLI.
- **Rewrite `worker-cli` from Bash to argparse for uniformity.** Rejected: ~940 lines of Bash that
  source `tmux_spawn.sh` for nearly every command, hardened over months (documented `set -e`
  pitfalls in `process-docs/worker_wait/`). Uniformity is achieved on the surface the agent sees,
  not in the implementation language.

## Decision

Every CLI prints one fixed sentence and exits 2 at every place argparse (or the Bash `usage()`)
would print help or usage today: `--help`/`-h` on top level and on every subcommand, no
arguments, unknown subcommand, missing required positional, invalid choice value.

CLIs with a skill name the skill:

```
This CLI has no help text. Invoke the skill reddit-cli-search via the Skill tool and follow it exactly. Do not guess flags.
```

`websearch` names all three of its skills with a short purpose each, because the CLI cannot know
which workflow the agent is in.

CLIs without a skill (`rag-cli`, `worker-cli`) point at the rules and end the turn:

```
You triggered the help function. Usage sits in your rules. Report to the user why you needed help and go idle immediately.
```

The wording follows the lesson from `process-docs/tool_use_safety/`: a rejection that only says
what is forbidden invites a workaround; a rejection that names the permitted form ends the episode
in one retry. The permitted form here is the skill name or the rules.

## Implementation

argparse CLIs: a local `NoHelpParser(argparse.ArgumentParser)` subclass overriding `error()`
and `print_help()`, swapped in at the single `ArgumentParser(...)` construction. `add_subparsers()`
defaults `parser_class` to `type(self)`, so every subparser inherits the behaviour without
per-subcommand wiring; a subcommand added later cannot forget to disable its help. `error()` is
argparse's single choke point for no-args, unknown subcommand, missing positional and invalid
choice. `print_help()` exits 2 before `_HelpAction` reaches its own `exit(0)`.

Two paths outside argparse needed a manual mirror:

- `rag-cli server <action>` dispatches by hand in `src/rag/server_cli.py`; its unknown-action
  branch listed all actions and returned exit 0. Now prints the fixed sentence and exits 2.
- `worker-cli` (Bash, `iterative-dev/bin/worker-cli`): `usage()` body replaced with one `echo >&2`.
  Finding on the way: the `-h|--help|help` case had no `exit` and fell through to exit 0.
  Now exits 2 like the other two call sites.

Per repo, one commit on branch `skill-help`, merged into each repo's `integration`:
reddit-cli, gh-cli, websearch, rag-cli, iterative-dev. The four Python CLIs also got a DOCS.md
gotcha describing the disabled help surface.

## Verification

Per CLI, a throwaway script ran the worktree `cli.py` with its own venv python for all help cases
plus one valid invocation, asserting exact text, exit 2, and absence of `usage`, `--`, and every
subcommand name. All cases passed in all five CLIs (10 cases reddit-cli, 7 each gh-cli and
websearch, 8 rag-cli, 3 worker-cli). Valid invocations returned real results (Reddit API,
GitHub freshness, engine breakdown, collection list, worker registry).

After merge, each prod wrapper in `~/.local/bin` was called with `--help`, a subcommand `--help`,
no args and an unknown subcommand; all printed only the fixed sentence with exit 2.

## Open

- Whether the sentence actually makes an agent invoke the skill is only observable live. The next
  reddit-cli or gh-cli session is the verification; if an agent still reaches for flags, the
  wording is the first lever.
- The worker-cli usage table is gone from the script; its content lives in the orchestrator
  rules. A human reading the script for usage now reads the `case` block.
