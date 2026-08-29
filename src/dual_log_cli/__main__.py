"""dual_log_cli — read-only inspector for src/logs/dual_log/.

Commands:
    sessions                 list every session (start, context, stem), newest first
    sessions <context>       keep only sessions whose context contains that text (substring, any case)
    sessions --since D --until D   bound that listing by start day, inclusive, YYYY-MM-DD
    timeline <session>       deduplicated turn timeline of one session, from its last request line
    search <term> [scope]    find a term across the deduplicated timelines, each match reported once
                             scope matches a session's context OR stem; omit it to search all
    expand <s> <turn>        classifier lines around one turn (overview mode)
    expand <s> <turn> --full --before N --after N [--only X]   full content of the window

Usage (from project root, or via bin/duallog once symlinked into PATH):
    ./venv/bin/python -m src.dual_log_cli sessions
    ./venv/bin/python -m src.dual_log_cli timeline api_requests_opus_gh_cli_1787995963
    ./venv/bin/python -m src.dual_log_cli search "worker-cli merge" gh_cli_1787939513
    ./venv/bin/python -m src.dual_log_cli search Reißleine websearch --since 2026-08-28
    ./venv/bin/python -m src.dual_log_cli expand websearch_1787924727 721
    ./venv/bin/python -m src.dual_log_cli expand websearch_1787924727 721 --full --before 0 --after 0

<session> is a full stem or any unambiguous substring of one. The log directory is resolved from
MONITOR_CC_ROOT, else from the repo root, else from the main checkout when run inside a worktree.
Every access is read-only — nothing under src/logs/dual_log/ is written, created or locked.
"""

# INFRASTRUCTURE
import argparse
import os
import sys
from datetime import datetime

from .discovery import (
    AmbiguousSessionError,
    UnknownSessionError,
    build_session,
    filter_sessions,
    group_streams,
    list_sessions,
    resolve_dual_log_dir,
    resolve_stem,
)
from .project_map import build_project_map
from .render import (
    render_expand_full,
    render_expand_overview,
    render_search,
    render_sessions,
    render_timeline,
)
from .search import find_matches
from .timeline import full_turn, load_timeline

_OVERVIEW_FLOOR = 30

# ORCHESTRATOR


def main(argv: list) -> int:
    args = _parse_args(argv)
    dual_log_dir = resolve_dual_log_dir()
    if not dual_log_dir.exists():
        print(f"dual_log directory not found: {dual_log_dir}", file=sys.stderr)
        return 2
    if args.command == "sessions":
        return _run_sessions(dual_log_dir, args)
    if args.command == "search":
        return _run_search(dual_log_dir, args)
    if args.command == "expand":
        return _run_expand(dual_log_dir, args)
    return _run_timeline(dual_log_dir, args)


# FUNCTIONS


def _parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.dual_log_cli",
        description="Read-only inspector for the proxy dual_log quartet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sessions = sub.add_parser("sessions", help="list all sessions, newest first")
    sessions.add_argument("context", nargs="?", default="", metavar="CONTEXT",
                          help="only sessions whose context contains this text, e.g. websearch")
    sessions.add_argument("--since", default="", metavar="YYYY-MM-DD",
                          help="only sessions started on or after this day (inclusive)")
    sessions.add_argument("--until", default="", metavar="YYYY-MM-DD",
                          help="only sessions started on or before this day (inclusive)")
    timeline = sub.add_parser("timeline", help="render one session as a turn timeline")
    timeline.add_argument("session", help="session stem or unambiguous substring")
    expand = sub.add_parser(
        "expand",
        help="classifier lines around one turn, or the full content of a window",
        description=(
            "Overview mode (default): classifier lines for every turn in the window — no blocks, "
            f"no previews, no filtering. --before/--after default to {_OVERVIEW_FLOOR} and have a "
            f"HARD FLOOR of {_OVERVIEW_FLOOR}: a smaller value is raised, so the window never gets "
            "too narrow to read context from. "
            "Read mode (--full): both --before and --after are REQUIRED explicit numbers with no "
            "floor (0 and up), and --only may restrict which turns are dumped."
        ),
    )
    expand.add_argument("session", help="session stem or unambiguous substring")
    expand.add_argument("turn", type=int, help="anchor turn index")
    expand.add_argument("--before", type=int, default=None,
                        help=f"turns before the anchor (overview: floor {_OVERVIEW_FLOOR}; --full: required, no floor)")
    expand.add_argument("--after", type=int, default=None,
                        help=f"turns after the anchor (overview: floor {_OVERVIEW_FLOOR}; --full: required, no floor)")
    expand.add_argument("--full", action="store_true",
                        help="dump full turn content instead of classifier lines; requires --before and --after")
    expand.add_argument("--only", default="", metavar="CLASSIFIER",
                        help="with --full: dump only turns whose role or message type matches, e.g. tool_result, thinking, user")
    search = sub.add_parser("search", help="find a term across the deduplicated timelines")
    search.add_argument("term", help="literal term to look for (no regex)")
    search.add_argument("scope", nargs="?", default="", metavar="SCOPE",
                        help="only sessions whose context OR stem contains this text; omit to search all")
    search.add_argument("--since", default="", metavar="YYYY-MM-DD",
                        help="only sessions started on or after this day (inclusive)")
    search.add_argument("--until", default="", metavar="YYYY-MM-DD",
                        help="only sessions started on or before this day (inclusive)")
    search.add_argument("--case-sensitive", action="store_true", help="match case exactly (default: ignore case)")
    return parser.parse_args(argv)


# A day flag must be exactly YYYY-MM-DD — strptime rejects both bad shapes and impossible dates
def _valid_day(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


# Exit code 2 plus a stderr line for a malformed day flag; 0 when both are fine
def _reject_bad_days(args: argparse.Namespace) -> int:
    for flag, value in (("--since", args.since), ("--until", args.until)):
        if value and not _valid_day(value):
            print(f"{flag}: {value!r} is not a valid date, expected YYYY-MM-DD", file=sys.stderr)
            return 2
    return 0


# sessions — inventory built from the _forwarded streams only, optionally date-bounded
def _run_sessions(dual_log_dir, args: argparse.Namespace) -> int:
    code = _reject_bad_days(args)
    if code:
        return code
    sessions = filter_sessions(
        list_sessions(dual_log_dir),
        context=args.context,
        since=args.since,
        until=args.until,
    )
    sys.stdout.write(render_sessions(sessions))
    return 0


# Resolve a session argument to a loaded timeline, or (None, exit_code) on a bad argument
def _load_for(dual_log_dir, session_arg: str) -> tuple:
    try:
        stem = resolve_stem(dual_log_dir, session_arg)
    except (AmbiguousSessionError, UnknownSessionError) as exc:
        print(str(exc), file=sys.stderr)
        return None, 2
    session = build_session(stem, group_streams(dual_log_dir)[stem], build_project_map())
    return load_timeline(session), 0


# search — scoped like `sessions`, then the same last-request reconstruction per session, so every
# match is deduplicated. A session whose timeline cannot be loaded is skipped, not fatal: one
# truncated log must not hide the matches in the other sixty.
def _run_search(dual_log_dir, args: argparse.Namespace) -> int:
    if not args.term.strip():
        print("search term is empty", file=sys.stderr)
        return 2
    code = _reject_bad_days(args)
    if code:
        return code
    sessions = filter_sessions(
        list_sessions(dual_log_dir),
        scope=args.scope,
        since=args.since,
        until=args.until,
    )
    results, skipped = [], 0
    for session in sessions:
        try:
            data = load_timeline(session)
        except Exception:
            skipped += 1
            continue
        hits = find_matches(data["payload"], args.term, args.case_sensitive)
        if hits:
            results.append((session, hits))
    sys.stdout.write(render_search(args.term, args.case_sensitive, results, skipped))
    return 0


# timeline — one session, reconstructed from its last conversation request
def _run_timeline(dual_log_dir, args: argparse.Namespace) -> int:
    data, code = _load_for(dual_log_dir, args.session)
    if data is None:
        return code
    sys.stdout.write(render_timeline(data))
    return 0


# expand — a window around one turn: classifier lines by default, full content with --full
def _run_expand(dual_log_dir, args: argparse.Namespace) -> int:
    data, code = _load_for(dual_log_dir, args.session)
    if data is None:
        return code
    turns = data["turns"]
    if args.turn < 0 or args.turn >= len(turns):
        print(f"turn {args.turn} out of range (0..{len(turns) - 1})", file=sys.stderr)
        return 2
    if args.full:
        return _run_expand_full(data, args)
    if args.only:
        print("--only applies to --full only; overview mode always lists every turn in the window",
              file=sys.stderr)
        return 2
    # floor, not a default: an explicit smaller value is raised too
    before = max(_OVERVIEW_FLOOR, args.before if args.before is not None else _OVERVIEW_FLOOR)
    after = max(_OVERVIEW_FLOOR, args.after if args.after is not None else _OVERVIEW_FLOOR)
    start, end = _window(args.turn, before, after, len(turns))
    sys.stdout.write(render_expand_overview(data, args.turn, start, end))
    return 0


# expand --full — both bounds explicit, no floor, optional classifier filter
def _run_expand_full(data: dict, args: argparse.Namespace) -> int:
    if args.before is None or args.after is None:
        print("--full requires both bounds: --full --before N --after N (N >= 0)", file=sys.stderr)
        return 2
    if args.before < 0 or args.after < 0:
        print("--before and --after must be 0 or greater", file=sys.stderr)
        return 2
    turns = data["turns"]
    start, end = _window(args.turn, args.before, args.after, len(turns))
    needle = args.only.lower()
    dumped = [
        (turn, full_turn(data["payload"], turn["index"]))
        for turn in turns[start:end + 1]
        if not needle or needle in (turn["role"].lower(), turn["type"].lower())
    ]
    sys.stdout.write(render_expand_full(data, args.turn, start, end, args.only, dumped))
    return 0


# Clamp an anchor-centred window to the turn list
def _window(anchor: int, before: int, after: int, total: int) -> tuple:
    return max(0, anchor - before), min(total - 1, anchor + after)


if __name__ == "__main__":
    # Piped into `head`/`less`, the reader closes the pipe early. The EPIPE can surface at the
    # write itself OR at the interpreter's shutdown flush, and only the first is catchable here —
    # so stdout is flushed INSIDE the guard, and on failure its fd is redirected to /dev/null so
    # the shutdown flush has nothing left that can fail. Without the redirect Python prints
    # "Exception ignored while flushing sys.stdout" after main() has already returned.
    exit_code = 0
    try:
        exit_code = main(sys.argv[1:])
        sys.stdout.flush()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        exit_code = 0
    sys.exit(exit_code)
