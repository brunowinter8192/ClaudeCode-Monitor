# 2026-08-29 — Retry discipline after a failed Bash call: the PostToolUseFailure event, measured

Goal: when a Bash tool call comes back as an error, feed one instruction back to the model —
diagnose before retrying, retry corrected once, stop and report after two failures on the same
goal. The task was specified as a **PostToolUse** hook. That event turned out to be the wrong one,
and the measurement that showed it also mapped the whole feedback surface.

## PostToolUse does not fire on failure

A stdin-dumping probe registered on `PostToolUse`/Bash, then seven real Bash calls:

| call | payload captured |
|---|---|
| `echo … ; ls /tmp/pt_probe.py` (exit 0) | yes |
| `python3 …` (exit 0) | yes |
| `wc -l …` (exit 0) | yes |
| `bash -c 'echo warn >&2; exit 0'` | yes |
| `cat /tmp/<missing>` (exit 1) | **no** |
| `false` (exit 1) | **no** |
| `bash -c 'echo out; echo err >&2; exit 3'` | **no** |

Four for four successes, zero for three failures. Probes were then registered under four candidate
names; exactly one is real — **`PostToolUseFailure`** captured the failing call on the next attempt.
`ToolUseFailure`, `PostToolUseError` and `ToolError` never fired. The `…Failure` suffix is a CC-wide
convention rather than a one-off: the same settings file already carried a `StopFailure` sibling.

## The two payload shapes

`PostToolUseFailure` (13 keys) carries `error` — a string of the form
`"Exit code 1\ncat: /tmp/…: No such file or directory"` — plus `is_interrupt`, and **no
`tool_response` at all**. `PostToolUse` (success) is the mirror image: `tool_response`
`{stdout, stderr, interrupted, isImage, noOutputExpected}` and no `error`.

Two consequences shaped the implementation:

- **"Leave non-error results untouched" needs no condition.** Registering on the failure event *is*
  the guarantee. Nothing has to parse a status.
- **`tool_response.stderr` would have been a trap.** On `bash -c 'echo warn_only >&2; exit 0'` the
  text arrived in `stdout` and `stderr` was `""`. A hook built on the assumed `PostToolUse` shape
  would have had to scan `stdout` for `"Exit code"`, which is exactly the guess the measurement
  instruction existed to prevent.

## The feedback channel — four variants, one winner

Each variant was run through a marker-gated probe and observed in the model's own tool result:

| variant | surfaced | rendered as |
|---|---|---|
| exit 2 + stderr | yes | `…hook blocking error from command: "<path>": [<path>]: <MSG>` |
| exit 0 + `{"decision":"block","reason":MSG}` | yes | `…hook blocking error from command: "<path>": <MSG>` |
| exit 0 + `hookSpecificOutput.additionalContext` | yes | `PostToolUseFailure:Bash hook additional context: <MSG>` |
| exit 0 + plain stdout | **no** | swallowed entirely |

All three working forms arrive as a `<system-reminder>` appended after the error result.
`additionalContext` was chosen: the other two frame a non-block as a "blocking error" — misleading,
since the call already ran — and echo the hook's absolute path into context once or twice.

Related, flagged but not acted on: the proxy's `strip_hook_prefix.py` strips the
`PreToolUse:<Tool> hook error: [python3 <path>]:` prefix and covers none of these newer shapes.

## Design decisions

**Three fail-closed gates, keyed on shape rather than on names.** `tool_name == "Bash"`, a
non-empty `error` string, and falsy `is_interrupt`. The `error` check rather than a
`hook_event_name` check is deliberate: the event name is the part a future CC version is most
likely to rename, while the presence of an error field is what the hook actually means. The
`is_interrupt` gate exists because a user ESC produces a failure payload too, and answering a
user-initiated stop with "diagnose and retry" would be precisely wrong.

**Stateless.** The message itself carries the two-failure rule, so the hook counts nothing. The
stateful precedent in this package (`block_rag_cli_document_repeat.py`) exists because *only* state
can see repetition across calls; here the model, not the hook, is the one that has to keep count.

**A third hook class.** `block_*` (exit 2) and `rewrite_*` (updatedInput) both act *before* the
call. `feedback_*` acts after one that already failed and changes nothing about it — so it earned
its own prefix and its own `log_fire` decision value, `"feedback"`, which lands in the `reason`
field alongside `"block"` (it is a message, not a modified input). Reusing `"block"` was rejected:
every future FP analysis would then count a non-blocking event as a block.

**Registration gained an event dimension.** `_HOOK_SCRIPTS` entries are now `(script, matcher)` —
PreToolUse by default — or `(script, matcher, event)`. `decide_entries()` passes entries through in
the shape they arrived, which kept its existing 10-case smoke suite passing untouched; the add-loop
keys `hooks.setdefault(event, [])`. `_sweep_stale_hooks()` already iterated every event key, so
dead PostToolUseFailure paths were swept correctly before this change existed.

## Verification

- Hook smoke, driven by the captured payloads: **10/10** — fires on the real failure with the exact
  message and a `decision="feedback"` fire-log line; silent on success, interrupt, non-Bash,
  whitespace-only `error`, absent `error`, `error: None`, malformed stdin, empty stdin, JSON list.
- `test_hook_setup_main_branch_gate.py`: **10/10**, file unchanged.
- Install simulation into a temp settings.json: the entry lands under `PostToolUseFailure`,
  PreToolUse stays at 38, a second run is byte-identical (idempotent), and the main-branch gate
  applies to the 3-tuple entry like any other.
- **Live, in a real session:** hook registered for real, `cat /tmp/live_verification_no_such_file.txt`
  returned the error and the model received
  `PostToolUseFailure:Bash hook additional context: This tool call FAILED. 1. Diagnose why before any
  retry. …`. The next successful call produced nothing. `~/.claude/settings.json` was snapshotted
  before every edit and restored byte-identically (MD5-verified) afterwards.

## Two honest gaps

**`is_interrupt: true` is covered by a synthetic payload only** — producing a real one needs a live
ESC, which was not staged.

**The live fire wrote no fire-log record**, because `_fire_log` resolves its path from `__file__`
and a worktree has no `src/logs/` directory (gitignored, main-checkout only), so the write raised
and was fail-silently swallowed as designed. Logging is proven for this hook through the smoke
suite's `MONITOR_CC_HOOK_FIRING_LOG` isolation. In production the hook runs from the main repo path
and logs like every other hook — but anyone testing a hook from a worktree should expect the
missing record rather than hunt for a bug.
