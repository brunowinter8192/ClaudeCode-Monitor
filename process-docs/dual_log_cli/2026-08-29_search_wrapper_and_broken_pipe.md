# 2026-08-29 — Search over the deduplicated timeline, the PATH wrapper, and a broken-pipe leak I first declared absent

Second entry of this area, same day as the opening one. Three subjects: a `search` command, a
`bin/duallog` wrapper so the CLI can live in PATH, and a stderr leak on piped exit. The third is
the one worth reading — the first investigation concluded the bug did not exist, and that
conclusion was wrong.

## Search — what deduplication is worth, measured

Search reuses the timeline reconstruction unchanged: the last non-haiku `_original` line, which
already embeds the whole conversation. Deduplication is therefore structural rather than a filter
applied afterwards.

Measured on the frozen session `api_requests_opus_gh_cli_1787939513` (108.3 MB `_original`,
506 turns, 633 blocks, 672k chars in the reconstructed timeline):

- Naive byte-count of `milestone` across the whole file: **3418**.
- Same term in the deduplicated timeline: **33 occurrences, 26 blocks, 23 turns**.

A factor of ~131. That number is the command's entire justification: the file repeats every
message once per subsequent request, so any grep over `_original` reports a single sentence
dozens to hundreds of times.

Counter-check for the opposite shape — a term concentrated in one place: `updatedInput` occurs
**16 times inside one block of one turn** (#465, role=user, tool_result). It is reported as one
hit carrying `×16`.

## Hit granularity — one (turn, block), not one occurrence

A hit reports turn index, role, block label and a snippet, so the block is the natural unit. The
alternative, one line per occurrence, reintroduces exactly the noise the command removes — 16
identical lines for `updatedInput`. Occurrence counts are not discarded, they ride along as `×N`
and are summed in the header, so all three numbers (hits, turns, occurrences) stay visible and the
count is reproducible by hand.

Searched text is the block's full text, which for a `tool_use` block means the tool name plus its
JSON input. That is what makes `search <session> "worker-cli merge"` find a command inside a Bash
call — verified: 2 hits, turns #272 and #416.

Exit code stays 0 whether or not there are hits. A grep-style 1-on-no-match would surprise callers
running under `set -e`, and the header already states the count in a machine-readable line.

## The broken-pipe leak — a wrong conclusion, then the reproduction

Milestone 1 had added a guard for `cmd | head`:

```python
except BrokenPipeError:
    try: sys.stdout.close()
    finally: sys.exit(0)
```

Asked to fix a leak still being observed, the first investigation ran the guard against the
largest session, `head -1/-3/-5/-45`, `sessions`, a scratch script with one big write, and a
scratch script with 200k small writes. All eight measurements showed 0 bytes on stderr, and the
report concluded the leak was already gone and the observation came from a stale pre-guard
transcript.

That conclusion was wrong. The leak reproduces reliably — 3 runs out of 3, 85 bytes:

```
Exception ignored while flushing sys.stdout:
BrokenPipeError: [Errno 32] Broken pipe
```

**What the first pass missed: the session, not the guard, decides where EPIPE surfaces.** All
probes had used the 4.9 GB session, whose 248 KB of output makes the pipe fail during the
`sys.stdout.write` inside `main()` — precisely the path the old guard covered. On
`api_requests_opus_gh_cli_1787939513` the smaller output is still sitting in the text-layer buffer
when `main()` returns normally, so no exception ever reaches the guard and the failure happens in
the interpreter's shutdown flush, which no `try/except` around `main()` can see. Same code, same
pipe, different session, opposite result.

It surfaced by accident: the new `bin/duallog` wrapper cds to the main checkout, which still held
the milestone-1 code, so the wrapper test ran the old guard against a different session than every
earlier probe had. The A/B then isolated code version from invocation path — old guard 85 bytes,
new guard 0 bytes, three runs each, identical session and pipe.

**Fix:** flush inside the guard so the second failure site becomes catchable, and on failure point
the stdout fd at `/dev/null` so the shutdown flush cannot fail either.

```python
try:
    code = main(sys.argv[1:])
    sys.stdout.flush()
except BrokenPipeError:
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    code = 0
sys.exit(code)
```

Verified 0 bytes across `timeline` at `head -1/-5/-45` on two sessions, `sessions`, `search` at
`head -1/-2/-5/-10/-40`, and `| true` on both commands.

**The transferable lesson: "cannot reproduce" is a statement about the probes, not about the bug.**
Every probe here varied the pipe depth and the writing style while holding the input session fixed,
and the input session was the variable that mattered.

## Wrapper — hardcoded root, deliberately

`~/.local/bin/gh-cli` is a shebang plus one `exec` with absolute paths and no `cd`. A module entry
(`-m`) needs the repo root as cwd, so the wrapper adds it:

```bash
#!/usr/bin/env bash
cd /Users/brunowinter2000/Documents/ai/monitor-cc || exit 1
exec ./venv/bin/python -m src.dual_log_cli "$@"
```

Deriving the root from `$0` was rejected: a copy of the script inside a worktree would then run
that worktree's code, whereas a PATH tool should always run the main checkout. The visible
consequence is that a new subcommand only reaches `duallog` after the branch is merged — during
this milestone `bin/duallog search …` still answered `invalid choice: 'search'` while the same
command worked directly from the worktree. That is the intended behaviour, not a defect.

The executable bit needs `chmod +x`: file-writing tools create mode 644 and cannot set modes, so
the commit records mode 100755 via a separate metadata change.
