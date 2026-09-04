# INFRASTRUCTURE
import os
import re
from pathlib import Path

from .project_map import build_project_map
from .reader import infer_family, iter_jsonl

STREAM_SUFFIXES = ("original", "forwarded", "stripped", "injected", "response", "errors")

_STEM_RE = re.compile(r"^(?P<stem>.+)_(?P<stream>" + "|".join(STREAM_SUFFIXES) + r")\.jsonl$")
_STEM_PREFIX = "api_requests_"
_TRAILING_EPOCH_RE = re.compile(r"_\d+$")
_WORKER_BODY_RE = re.compile(r"^(?P<sid>[0-9a-f]{6,})_(?P<name>.+)$")


class AmbiguousSessionError(Exception):
    pass


class UnknownSessionError(Exception):
    pass


# FUNCTIONS


# Resolve the dual_log directory. MONITOR_CC_ROOT wins; otherwise the repo root derived from
# this file, falling back to the MAIN repo when running inside .claude/worktrees/<name>/
# (the log directory is gitignored and exists only in the main checkout).
def resolve_dual_log_dir() -> Path:
    env_root = os.environ.get("MONITOR_CC_ROOT")
    if env_root:
        return Path(env_root) / "src" / "logs" / "dual_log"
    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    direct = repo_root / "src" / "logs" / "dual_log"
    if direct.exists():
        return direct
    # <main>/.claude/worktrees/<name>/src/dual_log_cli/discovery.py → parents[5] == <main>
    if len(here.parents) > 5:
        from_worktree = here.parents[5] / "src" / "logs" / "dual_log"
        if from_worktree.exists():
            return from_worktree
    return direct


# Render a session stem as "<family>/<project>" for a main session, or "worker/<project>/<name>"
# for a worker. A worker stem carries its project only as md5(project_path)[:8]; project_map
# resolves that id to the label main sessions already use, so ONE context filter term catches a
# project's main sessions and its workers together. An id the map cannot resolve renders as
# "worker/<sid8>/<name>" — still filterable, by the id itself.
# project_map is injected rather than looked up here, which keeps this function pure and testable
# without a filesystem; pass {} to force the fallback rendering everywhere.
def context_for_stem(stem: str, project_map: dict = None) -> str:
    body = stem[len(_STEM_PREFIX):] if stem.startswith(_STEM_PREFIX) else stem
    body = _TRAILING_EPOCH_RE.sub("", body)
    if body.startswith("worker_"):
        match = _WORKER_BODY_RE.match(body[len("worker_"):])
        if not match:
            return f"worker/{body[len('worker_'):]}"
        sid, name = match.group("sid"), match.group("name")
        project = (project_map or {}).get(sid) or sid
        return f"worker/{project}/{name}"
    head, _, tail = body.partition("_")
    return f"{head}/{tail}" if tail else head


# Parse a stem into its raw identity, the same split context_for_stem renders into a string:
# ("worker", sid8, name) or ("main", family_head, label). None when a "worker_" body does not
# match the expected shape. usage.py uses this to locate a session's CC project directory from
# the stem alone, without touching context_for_stem's own rendering path.
def stem_identity(stem: str):
    body = stem[len(_STEM_PREFIX):] if stem.startswith(_STEM_PREFIX) else stem
    body = _TRAILING_EPOCH_RE.sub("", body)
    if body.startswith("worker_"):
        match = _WORKER_BODY_RE.match(body[len("worker_"):])
        if not match:
            return None
        return ("worker", match.group("sid"), match.group("name"))
    head, _, tail = body.partition("_")
    if not tail:
        return None
    return ("main", head, tail)


# Group every *.jsonl in the directory by session stem → {stream: Path}
def group_streams(dual_log_dir: Path) -> dict:
    stems: dict = {}
    for entry in sorted(dual_log_dir.glob("*.jsonl")):
        match = _STEM_RE.match(entry.name)
        if not match:
            continue
        stems.setdefault(match.group("stem"), {})[match.group("stream")] = entry
    return stems


# Build the inventory row for one stem. Reads _forwarded only — it is line-for-line aligned
# with _original (verified: identical line count and per-line model/message_count) and two
# orders of magnitude smaller.
#
# A zero-tool non-haiku line (the sidecar `timeline._is_sidecar` also excludes — a recurring
# "security monitor" review call, not a conversation turn) is skipped from `requests`,
# `requests_main` and `last_message_count` the same way, so this inventory's request count means
# the same thing `timeline.request_boundaries` counts. Its timestamp still extends `start`/`end`,
# since those describe the file's real wall-clock span, unrelated to what counts as a request.
def build_session(stem: str, streams: dict, project_map: dict = None) -> dict:
    total_bytes = sum(p.stat().st_size for p in streams.values())
    requests = 0
    start_ts = ""
    end_ts = ""
    families: dict = {}
    last_message_count = 0
    forwarded = streams.get("forwarded")
    if forwarded is not None:
        for entry in iter_jsonl(forwarded):
            if entry.get("type") != "forwarded_delta":
                continue
            timestamp = entry.get("timestamp", "")
            if not start_ts:
                start_ts = timestamp
            end_ts = timestamp
            family = infer_family(entry.get("model", ""))
            counts = entry.get("counts", {}) or {}
            if family != "haiku" and counts.get("tools", 0) == 0:
                continue
            requests += 1
            families[family] = families.get(family, 0) + 1
            if family != "haiku":
                last_message_count = counts.get("messages", 0)
    main_family = _main_family(families)
    return {
        "stem": stem,
        "context": context_for_stem(stem, project_map),
        "start": start_ts,
        "end": end_ts,
        "requests": requests,
        "requests_main": families.get(main_family, 0),
        "family": main_family,
        "messages": last_message_count,
        "bytes": total_bytes,
        "streams": streams,
    }


# The conversation family of a session — the non-haiku family with the most requests
def _main_family(families: dict) -> str:
    ranked = [(n, f) for f, n in families.items() if f != "haiku"]
    if not ranked:
        return "haiku" if families else ""
    return max(ranked)[1]


# All sessions in the directory, newest first. The project map is built once and shared across
# every session rather than per stem — it costs one scan of CC's transcript store.
def list_sessions(dual_log_dir: Path, project_map: dict = None) -> list:
    if project_map is None:
        project_map = build_project_map()
    sessions = [build_session(stem, streams, project_map)
                for stem, streams in group_streams(dual_log_dir).items()]
    sessions.sort(key=lambda s: (s["start"], s["stem"]), reverse=True)
    return sessions


# Keep the sessions matching every active criterion (AND). Two selector flavours, both optional
# and both case-insensitive substrings:
#   context — matches the rendered context value only. `sessions <CONTEXT>` uses this.
#   scope   — matches the context OR the stem, so one argument covers both "a whole project incl.
#             its workers" and "this one session". `search <term> <SCOPE>` uses this.
# Plus an inclusive [since, until] window on the start day.
#
# Days are compared on the YYYY-MM-DD prefix of the ISO start timestamp — lexicographic order
# equals calendar order for that format, so no timezone maths is involved. A session with no
# start timestamp cannot be placed on a calendar, so an active DATE filter drops it; a context or
# scope filter alone still keeps it, because both of its match targets are known either way.
def filter_sessions(sessions: list, context: str = "", scope: str = "",
                    since: str = "", until: str = "") -> list:
    if not context and not scope and not since and not until:
        return sessions
    needle = context.lower()
    scope_needle = scope.lower()
    kept = []
    for session in sessions:
        if needle and needle not in session.get("context", "").lower():
            continue
        if scope_needle and not _matches_scope(session, scope_needle):
            continue
        if since or until:
            day = (session.get("start") or "")[:10]
            if not day:
                continue
            if since and day < since:
                continue
            if until and day > until:
                continue
        kept.append(session)
    return kept


# True when the lowercased scope needle appears in the session's context or in its stem
def _matches_scope(session: dict, scope_needle: str) -> bool:
    return (scope_needle in session.get("context", "").lower()
            or scope_needle in session.get("stem", "").lower())


# Keep only sessions whose context starts with "opus/" (main) or "worker/" (worker) — the
# --main/--worker filter `reqs` uses. Mutually exclusive at the CLI level (an argparse group), so
# at most one of the two is ever True here; neither set returns `sessions` unchanged.
def filter_by_family(sessions: list, main: bool = False, worker: bool = False) -> list:
    if main:
        return [s for s in sessions if s.get("context", "").startswith("opus/")]
    if worker:
        return [s for s in sessions if s.get("context", "").startswith("worker/")]
    return sessions


# Resolve a stem or unambiguous substring to exactly one session stem
def resolve_stem(dual_log_dir: Path, query: str) -> str:
    stems = sorted(group_streams(dual_log_dir))
    if query in stems:
        return query
    matches = [s for s in stems if query in s]
    if not matches:
        raise UnknownSessionError(f"no session matches {query!r} in {dual_log_dir}")
    if len(matches) > 1:
        listing = "\n  ".join(matches)
        raise AmbiguousSessionError(f"{query!r} matches {len(matches)} sessions:\n  {listing}")
    return matches[0]
