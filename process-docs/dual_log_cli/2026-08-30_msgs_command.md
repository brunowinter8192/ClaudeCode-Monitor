# `msgs` — a Dedicated Classifier Listing, 2026-08-30

Continues this area's command-surface line. The entry earlier the same day removed the `timeline`
command and `expand`'s classifier-rows overview, leaving `sessions` / `expand` / `search` and no
way to see a session's msg list at all. This entry adds that capability back as its own command,
deliberately narrower than either of the two things that were removed.

## Why it came back, and why not by reverting

The slimming removed two listings because both mixed a msg list with something else: `timeline`
interleaved `── REQ n ──` request markers and one sub-row per block, and the expand overview
carried a time column, an anchor marker, an enforced 30-row floor and a `--only` filter. The
listing itself was never the problem — the decoration around it was, and neither view could be
used as a plain index without filtering its own output back out.

So `msgs` is not a revert. It prints one line per msg and nothing else: no header, no count line,
no block sub-rows, no time column, no anchor marker, no request markers, no flags. The division of
labour across the surviving four commands is now one view per question — `sessions` which session,
`msgs` which msg, `search` where a term occurs, `expand` what a msg says.

## Line shape

```
[177] user  text                  454c
[178] syst  system                 49c
[179] assi  3 blocks            3,759c
```

`[{idx:3d}] {role:.4}  {type:<20}{chars:>6}`, taken from the proxy pane's grammar: role clipped to
four characters, and a multi-block msg showing its block COUNT instead of a type, because the
aggregated type names only one of the blocks it stands for. Chars use the pane's `1,234c` spelling
rather than the package's own `fmt_chars` (`1.2k`), since this view exists to locate a msg by size,
not to skim magnitudes.

The column widths were derived byte-wise from the specification's own sample rather than
approximated: all three sample lines are exactly 38 characters, which pins the type column at 20
and the chars column at 6.

### The two widths that overflow, measured

On `api_requests_opus_gh_cli_1787995963` (1417 msgs), 427 lines are not 38 characters wide:

- 417 because the index reached four digits (`[1416]`), inherent to the `:3d` field the pane uses.
- 12 because the chars value needs seven characters (`68,021c`, the widest msg in the session).
- 2 rows are in both groups.

Right-alignment means both cases still read correctly; the line simply sits one column off its
neighbours. Widening the columns would trade a rare one-character jog for permanent extra padding
on every one of the ~1000 short lines, so the narrow columns stayed.

## Range semantics

`FROM` and `TO` are inclusive and optional. Omitting both prints the whole session; giving `FROM`
alone runs from there to the last msg, which is how a trailing optional positional normally reads.
Bad bounds exit 2 naming the offending side (`FROM 1417 out of range (0..1416)`,
`TO 2 is before FROM 5`).

Two implementation notes worth knowing before touching the parser: `from` is a Python keyword, so
the argparse destinations are `from_msg`/`to_msg` with `metavar="FROM"`/`"TO"` — the user-facing
name and the code-side name deliberately differ. And a negative bound needs a `--` separator
(`msgs <s> -- -1`), otherwise argparse reads it as a flag; the exit code is 2 either way, only the
message differs.

## Verification (as of 2026-08-30)

Full-session runs on two recorded sessions produced exactly one line per msg with contiguous
indices (1417/1417 and 286/286). The `[177] [178] [179]` range printed exactly three lines. Every
error path was exercised: reversed bounds, either bound out of range, a negative bound, a
non-integer bound, an unknown session, and the last valid index as a single-msg range.

`sessions`, `search` and three `expand` variants were captured on the pre-change package
(`git checkout <commit>^ -- src/dual_log_cli/`), then on the post-change package moments later:
byte-identical on all five.

That comparison had to be redone. The first attempt diffed against baselines captured earlier in
the session and reported `sessions` as changed — the cause was a new proxy session appearing in the
live log directory between captures, not the code. A second attempt used `git stash`, which was a
no-op because the work was already committed, so it compared the new code against itself and proved
nothing. Only the commit-based checkout comparison above is evidence. The lesson generalises: this
package reads a directory that the running proxy appends to, so any before/after comparison has to
bracket both captures as closely as possible and must not assume a stash isolated anything.
