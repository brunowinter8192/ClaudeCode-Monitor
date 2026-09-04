# `msgs --req F [T]` — selecting request groups by REQ number, 2026-09-04

Continues this area's `msgs` command line. `msgs <s> FROM TO` already selects by msg index; an
agent reading a `── REQ 259 ──` separator and wanting just that group (or a small range of groups)
had to first read `expand`/eyeball the surrounding msg indices to translate REQ numbers into a
FROM/TO pair by hand. `--req F [T]` does that translation itself, then hands the result to the
exact same rendering path FROM/TO already uses — no new output shape, no new code in `render.py`.

## Translating REQ numbers into a msg-index range

`timeline.request_markers` already returns `{msg_index: {number, ...}}`. `request_msg_range`
inverts it into `{number: [msg_indices]}`, resolves `req_from`'s own msg index as the range start,
and computes the range end as the msg index right before the NEXT marker (by msg-index order)
after `req_to`'s own — or the session's last msg index when `req_to`'s group is the last one.
`resolve_req_range` is the one-call wrapper `__main__.py` uses, building `request_markers` from
`data["boundaries"]` internally.

## The duplicate-number question, settled empirically before writing the resolver

The milestone asked for a safeguard: a restart must not let `--req` silently pick the wrong group
if a REQ number occurs twice. Investigated with synthetic fixtures (no session on disk currently
carries a restart, so this could not be checked against real data) rather than assumed either way.

**Numbers themselves never reset.** `_running_request_numbers`' counter is strictly monotonic
across the WHOLE boundaries list, restart or not — a restart only resets the msg-INDEX space
(`start_index` back to 0), never the REQ-number counter. Two DIFFERENT `request_markers` keys
sharing the exact same start_index (a real, but rare, restart artifact — a session's own first
boundary and a later restart's first boundary both legitimately open msg index 0) simply collapse
to ONE surviving dict entry, owned by whichever is temporally last; the earlier one's number just
disappears from `markers` entirely rather than colliding with anything.

**The actual duplicate mechanism found: a trailing re-fire that never completes.** A group's owner
is defined as `positions[-1]` — the temporally LAST boundary sharing that `start_index` — regardless
of whether THAT boundary itself ever added a message. If a re-fire is the very last boundary of the
whole `boundaries` list, opens a `start_index` no earlier group used, and the session simply ends
there without a follow-up request completing it, it becomes the sole member of its own NEW group —
but `_running_request_numbers`' counter never advanced for it, so its assigned number is whatever
the PREVIOUS group's number already was. Reproduced with a 2-line synthetic fixture, no restart
needed at all: `f0` opens msg 0 and adds 2 msgs (REQ 1); `f1` opens msg 2 with `message_count`
exactly equal to its own `start_index` (adds nothing) — `markers` ends up `{0: {number: 1}, 2:
{number: 1}}`. A genuine restart produces the identical symptom under the same condition (the
restarted boundary itself adds nothing), so one general-purpose check covers both.

`request_msg_range` therefore checks candidate count PER NUMBER being resolved (not the whole
`markers` dict up front) — if `req_from` or `req_to` names more than one msg index,
`AmbiguousRequestNumberError` is raised naming the number and every colliding msg index, rather
than defaulting to a "discard everything before the last restart" strategy (which `build_turn_times`
already uses for a DIFFERENT purpose — turn timestamps — but would have silently hidden the
ambiguity here instead of refusing it).

## CLI surface

`--req` is `nargs="+"` (argparse has no native "1 or 2 ints" arity), validated manually in
`_run_msgs`: a length outside `{1, 2}` and a combination with FROM/TO positionals are both usage
errors, exit 2. `UnknownRequestNumberError`/`AmbiguousRequestNumberError` are caught and their own
message printed verbatim. A defensive `end < start` check (mirroring the pre-existing FROM/TO one)
catches the pathological case where a restart's own non-monotonic msg-index/REQ-number relationship
(a stale pre-restart marker can sit at a HIGHER msg-index than a LATER-numbered post-restart one —
an already-documented data characteristic, not something this feature repairs) would otherwise
invert the computed range.

One argparse quirk worth knowing, not fixed: `--req 1 0 5` (i.e. `--req` immediately followed by
what was meant to be separate FROM/TO positionals) gets greedily consumed as THREE values for
`--req` itself, since `nargs="+"` on an option eats every following bare token before positional
assignment happens — the mutual-exclusivity check never even fires, because `from_msg`/`to_msg`
end up `None`. Still safely rejected (exit 2, `"--req takes one or two REQ numbers"`), just via a
different one of the two validation branches than a reader might expect from argument order alone.
Putting FROM/TO before `--req` (`msgs <s> 0 5 --req 1`) exercises the intended
"cannot be combined" message directly.

## Verification

- New suite `dev/dual_log_cli/tests/test_msgs_req_range.py` (11 checks): a single REQ resolves to
  exactly its own group; a REQ range (F T) spans from F's start to T's end; the last REQ of a
  session runs to the session's last msg index; an unknown REQ number raises
  `UnknownRequestNumberError` naming it; the synthetic duplicate-number fixture above raises
  `AmbiguousRequestNumberError` naming both colliding msg indices.
- Full re-run of all 9 suites in `dev/dual_log_cli/tests/`, all passing, confirming no regression
  in the FROM/TO path or anywhere else in the package.
- Real invocation on `opus_monitor_cc_1788464543`: `msgs <s> --req 1` byte-identical to
  `msgs <s> 0 1`; `msgs <s> --req 1 5` correctly spans REQ 1 through REQ 5's own end; an unknown
  number (`--req 99999`) exits 2 with `"REQ 99999 not found"`; combining `--req` with FROM/TO
  (positionals first) exits 2 with `"--req cannot be combined with FROM/TO"`. `expand`, `search`,
  `sessions` and the plain FROM/TO `msgs` path re-checked byte-identical to their pre-change output.

## Relevant Symbols / Paths

- `request_msg_range`, `resolve_req_range`, `UnknownRequestNumberError`,
  `AmbiguousRequestNumberError` (`src/dual_log_cli/timeline.py`)
- `_run_msgs`'s `--req` branch (`src/dual_log_cli/__main__.py`)
- Ground truth for the byte-identity check: `src/logs/dual_log/api_requests_opus_monitor_cc_1788464543_*.jsonl`
