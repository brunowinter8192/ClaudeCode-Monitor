"""dual_log_cli — read-only inspector for src/logs/dual_log/.

Commands:
    sessions                 list every session (stem, context, start, requests, size), newest first
    timeline <session>       deduplicated turn timeline of one session, from its last request line
    timeline <s> --turn N --full   full content of one turn

Usage (from project root):
    ./venv/bin/python -m src.dual_log_cli sessions
    ./venv/bin/python -m src.dual_log_cli timeline api_requests_opus_gh_cli_1787995963
    ./venv/bin/python -m src.dual_log_cli timeline gh_cli_1787995963 --turn 402 --full

<session> is a full stem or any unambiguous substring of one. The log directory is resolved from
MONITOR_CC_ROOT, else from the repo root, else from the main checkout when run inside a worktree.
Every access is read-only — nothing under src/logs/dual_log/ is written, created or locked.
"""

# INFRASTRUCTURE
import argparse
import sys

from .discovery import (
    AmbiguousSessionError,
    UnknownSessionError,
    build_session,
    group_streams,
    list_sessions,
    resolve_dual_log_dir,
    resolve_stem,
)
from .render import render_sessions, render_timeline, render_turn_full
from .timeline import full_turn, load_timeline

# ORCHESTRATOR


def main(argv: list) -> int:
    args = _parse_args(argv)
    dual_log_dir = resolve_dual_log_dir()
    if not dual_log_dir.exists():
        print(f"dual_log directory not found: {dual_log_dir}", file=sys.stderr)
        return 2
    if args.command == "sessions":
        return _run_sessions(dual_log_dir)
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
    sub.add_parser("sessions", help="list all sessions, newest first")
    timeline = sub.add_parser("timeline", help="render one session as a turn timeline")
    timeline.add_argument("session", help="session stem or unambiguous substring")
    timeline.add_argument("--turn", type=int, default=None, help="restrict output to one turn index")
    timeline.add_argument("--full", action="store_true", help="with --turn: print the turn's full content")
    return parser.parse_args(argv)


# sessions — inventory built from the _forwarded streams only
def _run_sessions(dual_log_dir) -> int:
    sys.stdout.write(render_sessions(list_sessions(dual_log_dir)))
    return 0


# timeline — one session, reconstructed from its last conversation request
def _run_timeline(dual_log_dir, args: argparse.Namespace) -> int:
    try:
        stem = resolve_stem(dual_log_dir, args.session)
    except (AmbiguousSessionError, UnknownSessionError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    session = build_session(stem, group_streams(dual_log_dir)[stem])
    data = load_timeline(session)
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
    try:
        sys.exit(main(sys.argv[1:]))
    except BrokenPipeError:
        # Downstream `head`/`less` closed the pipe — exit quietly, like any well-behaved CLI
        try:
            sys.stdout.close()
        finally:
            sys.exit(0)
