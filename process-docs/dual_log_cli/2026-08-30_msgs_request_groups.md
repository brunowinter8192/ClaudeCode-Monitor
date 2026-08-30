# `msgs` Grouped by Request, and the Numbering Parity Question, 2026-08-30

Continues this area's command-surface line, directly after the entry that introduced `msgs` as a
bare classifier listing. That listing answered "which msgs exist" but not "which request added
them", which is the question an agent asks when correlating the CLI against the proxy pane. REQ
separators became the default output — no flag, because a listing that cannot be tied back to a
request is the weaker default.

## Output

```
── REQ 259  17:04:54 ──
[763] assi  4 blocks              633c
[764] user  4 blocks            4,949c
[765] syst  system                100c
── REQ 260  17:06:01 ──  (+1 re-fire)
[766] assi  3 blocks            1,321c
```

Kept from the removed `timeline` command's marker: the `── … ──` framing and the collapse of
re-fires into one marker. Dropped: the running `msgs N` total (the `[N]` indices already give
position) and the date (there is no header to anchor it against, so a session crossing midnight
shows only times — a known limit, not an oversight). The msg lines are untouched, which is what
makes `msgs <s> | grep -v '^──'` reproduce the pre-separator listing byte-for-byte.

## Which request owns a group

Boundaries are grouped by the msg index they open. Several land on one index when a request
re-fired without adding a msg, or when a restart reset the index to 0. **At most one boundary per
group can have added msgs, and it is always the last**: every member of a group shares the same
`prev_count`, so the member that raises `message_count` necessarily ends the group. That member
owns the separator — its timestamp is when the msgs below actually arrived — and the earlier
members are counted as re-fires rather than listed.

This was derived from the data structure rather than assumed, and then checked: for all 2872 msgs
across three sessions, the timestamp of the governing separator equals `build_turn_times`' mapping
for that msg. That mapping is built by an independent route (walking the counts chain forward), so
the agreement is evidence rather than a restatement.

## Numbering parity with the proxy pane — achieved, and the two ways it could still break

The milestone asked whether `msgs`' REQ numbers can match the proxy pane's `#N` for the same
session. They can, and the implementation takes it: **`number` counts only requests that ADDED
msgs**, which is precisely the pane's rule (`format.py` advances `#N` on `messages_added > 0` and
renders a re-fire as `#N.M` without advancing it).

Measured pairwise on number, timestamp and message count simultaneously: **971 of 971 requests
agree** across `opus_gh_cli_1787995963` (482), `opus_monitor_cc_1788091735` (116) and
`worker_e5917974_duallog_1788012520` (373).

The obvious alternative — reusing `timeline.request_boundaries`' own `request_no` — would NOT have
matched. It increments on every forwarded line of the family, so the 3 re-fires in the gh_cli
session push it out of step on **223 of its 482 requests**. The two numbers agree only in sessions
with zero re-fires, which is why the monitor_cc and worker sessions alone would have "confirmed"
parity for the wrong implementation. Testing on a re-fire-free session only is the trap here.

Two divergences remain possible and are unexercised by any recorded session on disk:

- **Non-haiku sidecars.** The pane excludes a request with `sys_chars == 0 and tools_chars == 0`
  (labelled `S`, does not advance the counter); these boundaries would count it. Measured: zero
  occurrences in all three sessions.
- **Multi-family sessions.** `request_boundaries` keeps only the family of the last non-haiku
  request; the pane numbers per family. All three sessions are single-family.

Haiku sidecars are excluded by both sides already (family filter here, `H` label there), so they
are not a divergence — 2/2/1 rows, dropped identically.

## A spec violation caught during implementation

The first version emitted a separator only at a group's own start index. With `FROM` landing
mid-group that left msgs under no separator at all: `msgs <s> 177 179` printed 177 and 178 bare,
because their group opens at 176. The requirement was that a partially shown group keeps its
separator, so the first printed msg now falls back to the group that GOVERNS it — the nearest one
opening at or before it. Only the first printed msg gets that fallback; later separators still
appear at their real starts. Worth knowing before changing the emission rule: the fallback is what
prevents a mid-group range from silently losing its request context.

The specification's own example expected `177 179` to sit under a single separator. On the real
session those three msgs straddle two requests, so the correct output carries two separators. A
range that genuinely is one group (`179 181`) does print exactly one.

## Verification (as of 2026-08-30)

Msg lines byte-identical to the pre-change listing on all three sessions (1417 / 337 / 1118 lines)
after stripping `^──`. Separator placement cross-checked against `build_turn_times` for every msg,
zero mismatches. Numbering parity as above. Degenerate cases: an empty `boundaries` list and a
missing `boundaries` key both render exactly the separator-free listing. `sessions`, `search` and
three `expand` variants byte-identical, compared via `git stash` — and this time the stash was
verified to have taken effect (3 dirty files → 0 → 3) before trusting it, which is the correction
to the previous entry's mistake of stashing an already-committed tree and comparing new code
against itself.
