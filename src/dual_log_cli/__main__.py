"""dual_log_cli — read-only inspector for src/logs/dual_log/.

Commands:
    sessions                 list every session (start, context, stem), newest first
    sessions <context>       keep only sessions whose context contains that text (substring, any case)
    sessions --since D --until D   bound that listing by start day, inclusive, YYYY-MM-DD
    timeline <session>       deduplicated turn timeline of one session, from its last request line
    timeline <s> --turn N --full   full content of one turn
    search <session> <term>  find a term in that timeline, each match reported once

Usage (from project root, or via bin/duallog once symlinked into PATH):
    ./venv/bin/python -m src.dual_log_cli sessions
    ./venv/bin/python -m src.dual_log_cli timeline api_requests_opus_gh_cli_1787995963
    ./venv/bin/python -m src.dual_log_cli timeline gh_cli_1787995963 --turn 402 --full
    ./venv/bin/python -m src.dual_log_cli search gh_cli_1787939513 "worker-cli merge"

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
from .render import render_search, render_sessions, render_timeline, render_turn_full
from .search import find_matches
from .timeline import full_turn, load_timeline

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
    timeline.add_argument("--turn", type=int, default=None, help="restrict output to one turn index")
    timeline.add_argument("--full", action="store_true", help="with --turn: print the turn's full content")
    search = sub.add_parser("search", help="find a term in one session's deduplicated timeline")
    search.add_argument("session", help="session stem or unambiguous substring")
    search.add_argument("term", help="literal term to look for (no regex)")
    search.add_argument("--case-sensitive", action="store_true", help="match case exactly (default: ignore case)")
    return parser.parse_args(argv)


# A day flag must be exactly YYYY-MM-DD — strptime rejects both bad shapes and impossible dates
def _valid_day(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


# sessions — inventory built from the _forwarded streams only, optionally date-bounded
def _run_sessions(dual_log_dir, args: argparse.Namespace) -> int:
    for flag, value in (("--since", args.since), ("--until", args.until)):
        if value and not _valid_day(value):
            print(f"{flag}: {value!r} is not a valid date, expected YYYY-MM-DD", file=sys.stderr)
            return 2
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
    session = build_session(stem, group_streams(dual_log_dir)[stem])
    return load_timeline(session), 0


# search — same last-request reconstruction as timeline, so every match is deduplicated
def _run_search(dual_log_dir, args: argparse.Namespace) -> int:
    if not args.term.strip():
        print("search term is empty", file=sys.stderr)
        return 2
    data, code = _load_for(dual_log_dir, args.session)
    if data is None:
        return code
    hits, stats = find_matches(data["payload"], args.term, args.case_sensitive)
    sys.stdout.write(render_search(data, args.term, args.case_sensitive, hits, stats))
    return 0


# timeline — one session, reconstructed from its last conversation request
def _run_timeline(dual_log_dir, args: argparse.Namespace) -> int:
    data, code = _load_for(dual_log_dir, args.session)
    if data is None:
        return code
    if args.turn is None:
        sys.stdout.write(render_timeline(data))
        return 0
    if not args.full:
        turns = data["turns"]
        if args.turn < 0 or args.turn >= len(turns):
            print(f"turn {args.turn} out of range (0..{len(turns) - 1})", file=sys.stderr)
            return 2
        single = dict(data, turns=[turns[args.turn]], boundaries=[])
        sys.stdout.write(render_timeline(single))
        return 0
    blocks = full_turn(data["payload"], args.turn)
    sys.stdout.write(render_turn_full(data, args.turn, blocks))
    return 0 if blocks else 2


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
