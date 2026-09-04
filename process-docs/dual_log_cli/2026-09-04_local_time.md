# duallog renders LOCAL time, not UTC, 2026-09-04

Every dual-log timestamp is UTC by construction (`src/proxy/logging.py` writes via
`datetime.now(timezone.utc)`, always `"...Z"`-suffixed). `duallog` rendered all of them by slicing
the raw ISO string directly — `sessions`' START column, every `msgs`/`reqs` REQ clock, `expand`'s
msg-header clock and window-header day, and the `--since`/`--until` day filter all showed/compared
UTC, while the proxy pane and the menubar log — the two things an agent cross-references `duallog`
output against — already show LOCAL time. Verified before fixing anything: the SAME REQ 1 instant
of `proxy-tn-wrap` read `18:16:02` in `reqs` and `20:16:02` in the proxy pane.

## One conversion point, not one per command

`reader.py` gained `local_datetime(timestamp) -> datetime | None` — parses the UTC `"...Z"` string
into an aware UTC `datetime`, then `.astimezone()` with no explicit `tz=`, which resolves to the
SYSTEM's configured local zone via the OS's own tzdata, correct for whichever specific date is
being converted (DST included) — never a fixed offset computed once and reused. `reader.py` was
the natural home: it already held `infer_family`, the package's other shared, low-level primitive,
and both `discovery.py` (needs the local DAY for its filter) and `render.py` (needs the local
CLOCK for display) already import from it or could without introducing a backward dependency —
unlike putting it in `render.py` itself, which `discovery.py` has no business importing from.

Every consumer became a one-line wrapper around this single function: `render.py`'s
`fmt_timestamp`/`_clock`/`_window_date`, and `discovery.py`'s `filter_sessions` day comparison.
`search`'s own `--since`/`--until` needed no separate code change — it already calls the same
`filter_sessions`.

## Grepped every timestamp-slicing site before writing anything

Rather than trusting the four sites named in the milestone brief, grepped the whole package for
`[:10]`/`[:19]`/`[11:19]`/`timestamp[` — found exactly those four (`discovery.filter_sessions`,
`render.fmt_timestamp`/`_clock`/`_window_date`) and nothing else. `search.py`/`render_search`
render no timestamp at all — "search where applicable" in the brief turned out to mean the shared
`filter_sessions` fix, not a separate code path.

## A related bug claimed, then found not to be one

`usage.py`'s `_epoch_from_iso` looked like the same bug class at first read — `cleaned =
timestamp.rstrip("Z")` followed by `datetime.fromisoformat(cleaned).timestamp()` looks like it
parses a naive (local-assumed) datetime from a UTC string. Flagged as a bug before checking the
REST of the function. On closer reading, the function has a SECOND step that was missed on the
first pass: `if not _OFFSET_RE.search(cleaned): cleaned += "+00:00"` — for the common
`"...998Z"`-only shape, `cleaned` after stripping `Z` carries no offset, so this branch appends
`"+00:00"` before parsing, making the result AWARE UTC all along. Reproduced directly: the
function's output for `"2026-09-04T20:16:02.582Z"` already matched the true UTC epoch exactly,
before any change. The claim was wrong — an incomplete read, not a real bug. Corrected rather than
silently dropped: `_epoch_from_iso` was still refactored to delegate to the new `local_datetime`
(`.timestamp()` on an aware datetime is timezone-independent, so routing through the LOCAL-
converted result yields the identical epoch), which removes duplicate UTC-parsing logic without
changing behavior — a DRY consolidation, not a bug fix, and documented as exactly that.

## Verification

- New suite `dev/dual_log_cli/tests/test_local_time.py` (12 checks): `local_datetime` cross-checked
  against an INDEPENDENTLY computed `datetime.fromisoformat(...).astimezone()` (not just re-calling
  itself); `_clock`/`fmt_timestamp`/`_window_date` all agree with `local_datetime`, and `_clock`'s
  output differs from the raw UTC digits whenever the machine's offset is nonzero; a day-boundary
  case built DYNAMICALLY from the machine's OWN current UTC offset (never a hardcoded "23:30Z",
  since which side of midnight actually crosses a UTC day boundary depends on which side of UTC
  the test machine is on) proves `filter_sessions` lists a session under its LOCAL day and NOT
  under the (different) UTC day; `_epoch_from_iso` matches the true UTC epoch for both recorded
  timestamp shapes (plain `"Z"` and `"+00:00Z"`).
- Every EXISTING hardcoded clock-string assertion across the suite (4 files: `test_msgs_blocks.py`,
  `test_msgs_sys_delta.py` ×2, `test_msgs_usage.py` ×4, `test_reqs.py` ×3) rewritten to compute the
  expected string from the same UTC instant via a local `_local_clock()` helper (calling
  `reader.local_datetime`) rather than a value hardcoded for whatever timezone the suite was
  originally written in — makes the suite pass on any machine, not just this one.
- Full re-run of all 11 suites in `dev/dual_log_cli/tests/`, all passing.
- Real invocation, `reqs proxy-tn-wrap`: REQ 1 now reads `20:16:02` — matching the proxy pane
  exactly, where it read `18:16:02` (UTC) before this fix. `sessions`, `msgs`, `expand`, `search`
  re-invoked and confirmed their own timestamps/day-windows moved by the identical +2h offset
  (this machine is UTC+2/CEST) in the same pass.

## Relevant Symbols / Paths

- `local_datetime` (`src/dual_log_cli/reader.py`) — the one shared conversion point
- `fmt_timestamp`, `_clock`, `_window_date` (`src/dual_log_cli/render.py`)
- `filter_sessions` (`src/dual_log_cli/discovery.py`)
- `_epoch_from_iso` (`src/dual_log_cli/usage.py`) — DRY consolidation, not a bug fix
- Ground truth for the worked example:
  `src/logs/dual_log/api_requests_worker_25c51a2e_proxy-tn-wrap_1788545761_forwarded.jsonl`
