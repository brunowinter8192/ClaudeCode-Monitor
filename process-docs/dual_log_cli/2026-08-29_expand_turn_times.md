# 2026-08-29 — Putting a clock on the expand overview

Tenth entry of this area. The `expand` overview showed what surrounds a turn but not WHEN any of it
happened, so a reader could not see that two adjacent turns are twenty-five minutes apart. Each
classifier line now carries the time of the request that first delivered that turn, and the
`--full` turn headers carry the same value.

## Derivation

No timestamp exists per message — the dual logs record them per REQUEST. The mapping falls out of
the `counts.messages` chain already computed for the timeline's boundary markers: **turn N belongs
to the earliest request whose message count exceeds N.** Walking the boundaries in order and
assigning each newly covered index range that request's timestamp produces the whole table in one
pass, with no extra file reads — `build_turn_times` runs on data `load_timeline` already had.

The consequence is visible in the output and worth stating plainly: turns delivered by the same
request share one timestamp, so the column repeats in threes (assistant / user / system). It is a
send time, not a per-turn duration, and nothing in these logs offers the latter.

Rendering is `HH:MM:SS` to keep the lines tight; the calendar day moved into the window header
(`window turns 683-743 of 0-765, anchor #713, 2026-08-28`), taken from the anchor's own day and
falling back to the session start.

## Restarts get `?`, deliberately

A restart — CC restarted inside one log id, the `/clear` case this area recorded earlier — makes
the pre-restart requests describe a different message list. Their counts cannot be walked against
the final one; doing so misaligns everything after them.

`build_turn_times` therefore keeps only the chain from the LAST restart onward and leaves every turn
below that restart's message count unmapped, rendering `?`. Those messages exist in the final list,
but the request that first carried them is not in this chain at all, and inventing a time for them
would be the kind of plausible-looking wrong answer this whole CLI exists to avoid. Same
conservative stance as the timeline's WARNING on the same condition.

## Measurements

| session | turns | mapped | unmapped | restarts | monotonic |
|---|---|---|---|---|---|
| `opus_websearch_1787924727` | 766 | 766 | 0 | 0 | yes |
| `opus_gh_cli_1787939513` | 506 | 504 | `[0, 1]` | 1 | yes |

The unmapped pair in the second session is exactly the two messages that existed at the `/clear`
request, which is the predicted result rather than a coincidence.

The use case, from the window that motivated it: `#708 17:47:51` followed by `#709 18:13:12` — a
25-minute gap that was previously invisible, and which marks where the user left the session and
came back.

## A wrong measurement of my own

The first monotonicity check reported `False`. The cause was the check, not the data: it picked a
column with `awk`, and the anchor line carries an extra leading field (`▶`), so the anchor
contributed a role name where every other line contributed a time. Re-run with a regex over
`#<index> <time>`, all 61 window lines and all 766 session turns are monotonic non-decreasing.
Worth recording because the failure mode is generic — a per-line marker silently shifts every
positional column parse downstream of it.
