"""
Regression suite for `duallog reqs` (src/dual_log_cli/render.py's `render_reqs`, and
src/dual_log_cli/discovery.py's `filter_by_family`).

Covers: a session's REQ lines match `msgs`' own numbers/timestamps exactly (built via the real
`request_boundaries`/`request_markers`, matching this area's established fixture style); multiple
sessions blank-line separated, newest-first order preserved (listing order, unchanged by
`render_reqs`); a session with zero requests still gets its `session <stem>` header and no REQ
lines; the trailing skipped-sessions note, reused from `search`; an empty result set; and
`filter_by_family` keeping only `opus/`-prefixed sessions for `--main`, only `worker/`-prefixed
for `--worker`, and the list unchanged when neither flag is set.

`request_boundaries` is exercised end to end against a real temp `_forwarded.jsonl`-shaped file —
no dual-log directory or MONITOR_CC_ROOT required.

Run (from project root):
    ./venv/bin/python dev/dual_log_cli/tests/test_reqs.py

Exit 0 = all checks pass. Exit 1 = at least one failure (printed by name).
"""

# INFRASTRUCTURE

import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_HERE.parents[2]))

from src.dual_log_cli.discovery import filter_by_family
from src.dual_log_cli.reader import local_datetime
from src.dual_log_cli.render import render_reqs
from src.dual_log_cli.timeline import request_boundaries

PASS_LIST = []
FAIL_LIST = []


# FUNCTIONS

def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASS_LIST.append(name)
    else:
        FAIL_LIST.append(name)
        print(f"  FAIL  {name}" + (f": {detail}" if detail else ""))


# The LOCAL "HH:MM:SS" a UTC "...Z" timestamp renders as — computed the same way production code
# does (reader.local_datetime), so an expected string built from this is correct on ANY machine's
# timezone, not just the one this suite happened to be written on.
def _local_clock(iso_timestamp: str) -> str:
    return local_datetime(iso_timestamp).strftime("%H:%M:%S")


# One forwarded_delta line as addon.py's dual-log writer would shape it
def _delta_entry(flow_id: str, timestamp: str, messages: int, is_first: bool = False) -> dict:
    return {
        "type": "forwarded_delta",
        "flow_id": flow_id,
        "timestamp": timestamp,
        "model": "claude-sonnet-5",
        "is_first": is_first,
        "counts": {"system": 1, "tools": 1, "messages": messages},
        "system_delta": {},
        "tools_delta": {},
        "messages_delta": {},
    }


# Writes entries to a temp _forwarded.jsonl and runs the real request_boundaries over it
def _boundaries(entries: list) -> list:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
        path = Path(fh.name)
    try:
        return request_boundaries(path, "sonnet")
    finally:
        path.unlink()


def _session(stem: str, context: str = "") -> dict:
    return {"stem": stem, "context": context}


# A session's REQ lines carry exactly the numbers and clock times `msgs`' own separators print.
def test_single_session_req_lines_match_msgs_numbering() -> None:
    boundaries = _boundaries([
        _delta_entry("f0", "2026-09-04T20:16:02Z", 2, is_first=True),
        _delta_entry("f1", "2026-09-04T20:16:40Z", 5),
        _delta_entry("f2", "2026-09-04T20:17:10Z", 9),
    ])
    session = _session("api_requests_worker_25c51a2e_proxy-tn-wrap_1788545000", "worker/monitor_cc/proxy-tn-wrap")
    got = render_reqs([(session, boundaries)])
    # The milestone's own example shows these UTC instants rendering as LOCAL time (verified
    # against the real proxy pane: the same instant read 20:16:02 there, local, against 18:16:02
    # in `reqs` before local-time conversion existed) — so the expected clocks here are computed
    # from the SAME UTC instants via the SAME conversion, not the milestone's illustrative digits.
    expected = (
        "session api_requests_worker_25c51a2e_proxy-tn-wrap_1788545000\n"
        f"REQ 1   {_local_clock('2026-09-04T20:16:02Z')}\n"
        f"REQ 2   {_local_clock('2026-09-04T20:16:40Z')}\n"
        f"REQ 3   {_local_clock('2026-09-04T20:17:10Z')}\n"
    )
    check("output matches the spec's own example byte-for-byte", got == expected, got)


# A re-fire (adds no new msg) opens the SAME group as the boundary that eventually completes it
# (both share one start_index) and is collapsed into that group's number/timestamp, exactly as
# `msgs`' own separator does — no extra REQ line for the re-fire itself.
def test_refire_collapsed_same_as_msgs() -> None:
    boundaries = _boundaries([
        _delta_entry("f0", "2026-09-04T10:00:00Z", 2, is_first=True),
        _delta_entry("f1", "2026-09-04T10:00:02Z", 2),   # start_index=2, re-fire (2<2 is False)
        _delta_entry("f2", "2026-09-04T10:00:05Z", 5),   # start_index=2 too — same group, adds, owns it
    ])
    session = _session("s")
    got = render_reqs([(session, boundaries)])
    lines = [l for l in got.split("\n") if l.startswith("REQ")]
    check("re-fire produces no extra REQ line (2 groups, not 3)", len(lines) == 2, lines)
    check("the re-fire+add group uses the OWNER's (f2's) timestamp, not the re-fire's (f1's)",
          lines[1] == f"REQ 2   {_local_clock('2026-09-04T10:00:05Z')}", lines)


# Multiple sessions stay in LISTING order (newest-first is the caller's responsibility, unchanged
# here) and are blank-line separated.
def test_multiple_sessions_blank_line_separated() -> None:
    boundaries_a = _boundaries([_delta_entry("fa", "2026-09-04T09:00:00Z", 1, is_first=True)])
    boundaries_b = _boundaries([_delta_entry("fb", "2026-09-04T08:00:00Z", 1, is_first=True)])
    session_a = _session("newer_session")
    session_b = _session("older_session")
    got = render_reqs([(session_a, boundaries_a), (session_b, boundaries_b)])
    expected = (
        "session newer_session\n"
        f"REQ 1   {_local_clock('2026-09-04T09:00:00Z')}\n"
        "\n"
        "session older_session\n"
        f"REQ 1   {_local_clock('2026-09-04T08:00:00Z')}\n"
    )
    check("two sessions render in the order given, blank-line separated", got == expected, got)


# A session with zero requests still prints its own header, with no REQ lines beneath it.
def test_session_with_zero_requests_still_gets_header() -> None:
    session = _session("empty_session")
    got = render_reqs([(session, [])])
    check("session header present, no REQ lines", got == "session empty_session\n", got)


# The trailing skipped-sessions note, reused from `search`.
def test_skipped_note_appended() -> None:
    session = _session("s")
    boundaries = _boundaries([_delta_entry("f0", "2026-09-04T10:00:00Z", 1, is_first=True)])
    got = render_reqs([(session, boundaries)], skipped=2)
    check("skipped note present and pluralised", got.rstrip("\n").endswith(
        "(2 sessions skipped — timeline could not be loaded)"), got)


# An empty result set renders "no sessions found", with the skipped note still appended if nonzero.
def test_empty_results() -> None:
    got = render_reqs([])
    check("no sessions found, no trailing note", got == "no sessions found\n", got)
    got_skipped = render_reqs([], skipped=1)
    check("no sessions found, with skipped note", got_skipped == (
        "no sessions found\n\n(1 session skipped — timeline could not be loaded)\n"), got_skipped)


# filter_by_family: --main keeps only opus/-prefixed, --worker keeps only worker/-prefixed,
# neither flag returns the list unchanged.
def test_filter_by_family() -> None:
    sessions = [
        _session("s1", "opus/monitor_cc"),
        _session("s2", "worker/monitor_cc/foo"),
        _session("s3", "opus/websearch"),
        _session("s4", "worker/websearch/bar"),
    ]
    main_only = filter_by_family(sessions, main=True)
    check("--main keeps only opus/-prefixed sessions",
          [s["stem"] for s in main_only] == ["s1", "s3"], main_only)
    worker_only = filter_by_family(sessions, worker=True)
    check("--worker keeps only worker/-prefixed sessions",
          [s["stem"] for s in worker_only] == ["s2", "s4"], worker_only)
    unfiltered = filter_by_family(sessions)
    check("neither flag set returns the list unchanged",
          [s["stem"] for s in unfiltered] == ["s1", "s2", "s3", "s4"], unfiltered)


# ORCHESTRATOR

def test_reqs_workflow() -> None:
    test_single_session_req_lines_match_msgs_numbering()
    test_refire_collapsed_same_as_msgs()
    test_multiple_sessions_blank_line_separated()
    test_session_with_zero_requests_still_gets_header()
    test_skipped_note_appended()
    test_empty_results()
    test_filter_by_family()

    total = len(PASS_LIST) + len(FAIL_LIST)
    print(f"{len(PASS_LIST)}/{total} checks passed")
    if FAIL_LIST:
        print(f"\nFAILED: {FAIL_LIST}")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    test_reqs_workflow()
