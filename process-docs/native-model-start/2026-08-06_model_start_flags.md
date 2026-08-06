# Native model-start flags for claude_proxy_start.sh, 2026-08-06

Problem: the orchestrator main session started CC with no `--model` flag, so CC ran its native
default (Opus 4.8) and built the Opus 4.8 system prompt, while the proxy's `model_override`
rewrote the model field per-request to `claude-fable-5` — the executed model and the system prompt
disagreed. Workers didn't have this problem (`tmux_spawn.sh`, a different repo/plugin, passes
`--model claude-sonnet-5` at spawn). Fix: let the main session start natively on the chosen model,
the same way workers already do — via `src/claude_proxy_start.sh` argument parsing, not a proxy
change.

## Design

Two shortcut flags, `--fable` → `--model claude-fable-5`, `--opus` → `--model claude-opus-5` (both
IDs given directly by the user — not verified against the Anthropic API, out of scope for a shell
argument-parsing change). Precedence, simplest rule that still covers the ambiguous case: an
explicit `--model` always wins over either shortcut, REGARDLESS OF ARGUMENT ORDER — `--fable
--model X` and `--model X --fable` both resolve to `X`. If both shortcuts are given with no
explicit `--model`, the last one wins. No flag at all: `CLAUDE_ARGS` is unchanged from before this
feature existed — verified as its own dry-run case, not assumed.

Implementation: two new bash variables threaded through the existing parse loop —
`SHORTCUT_MODEL` (last of `--fable`/`--opus` wins, simple overwrite-on-match) and
`HAS_EXPLICIT_MODEL` (set the instant `--model` is seen in the loop, independent of where in the
argument list it appears — this is what makes the position-independent precedence work: the flag
is set during the SAME single left-to-right pass regardless of whether `--model` comes before or
after a shortcut, and the shortcut-derived `--model` is only appended AFTER the whole loop
finishes, gated on that flag). `--fable`/`--opus` are consumed by the loop (never forwarded to
`claude` as unrecognized flags); an explicit `--model X` is captured inline at its original
position in `CLAUDE_ARGS` (preserves relative order among real passthrough args) and also flips
`HAS_EXPLICIT_MODEL`; the shortcut-derived `--model` (if applicable) is appended once, at the end,
after the loop — a claude CLI is flag-order-agnostic, so this placement difference has no
functional effect on the invocation, only on where the pair sits inside the array.

No validation added for a dangling `--model` with no following value — matches the existing (also
unguarded) rigor level of the pre-existing `--project` handling; adding stricter validation only to
the new flags while leaving `--project` as-is would be an inconsistent scope expansion, not
requested.

## Known limitation (documented in the script, not fixed here)

The pinned `claude-205` binary (`~/.local/bin/claude-205`, referenced at the bottom of
`claude_proxy_start.sh`) predates `claude-opus-5`, introduced in CC 2.1.219. `--opus`'s flag
mapping is correct and ready now, but won't be fully functional until the pin bump — tracked
separately as monitor-cc issue #63, not part of this change's scope.

## Verification

Pure argument-parsing dry run, `dev/native-model-start/p1_arg_parse_dry_run.sh` — mirrors the
exact parse loop from `claude_proxy_start.sh` (same convention as
`dev/hook_smoke/test_version_purge.sh`'s mirrored-function pattern), 8/8 assertions: `--fable`
alone, `--opus` alone, `--fable` then explicit `--model` (explicit wins), explicit `--model` then
`--fable` (explicit STILL wins — the position-independence case, pinned as its own assertion rather
than assumed from the first explicit-wins case), both shortcuts in each order (last one wins both
ways), no flag at all (byte-identical baseline), and a mixed case with `--project` plus another
passthrough flag+value (confirms `--project` extraction and unrelated passthrough args are
untouched by the new logic). Report: `dev/native-model-start/md/p1_arg_parse_dry_run_<timestamp>.md`.

Not verified here, by design (user gate): a live proxy/claude start with either flag. The dry run
only proves the resulting `CLAUDE_ARGS` array is correct — not that `claude-205` accepts
`--model claude-fable-5`/`claude-opus-5` at runtime.
