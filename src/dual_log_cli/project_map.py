# INFRASTRUCTURE
import json
import os
from pathlib import Path

from ..proxy_display.forwarded_parser import _proxy_session_id_for_project

# CC keeps one directory per project cwd. The directory NAME is a lossy encoding of the path
# (a "-" may be a separator or a literal hyphen), but the transcript records inside carry the real
# absolute path in a "cwd" field — ground truth, no decoding heuristics needed.
_PROJECTS_ROOT = Path("~/.claude/projects").expanduser()
_CWD_SCAN_LINES = 40          # the first records are mode/permission-mode entries without a cwd
_TRANSCRIPTS_PER_DIR = 3      # newest first; stop at the first one that yields a cwd

# FUNCTIONS


# Project label as the main-session stems already spell it: basename with "-" collapsed to "_"
# (monitor-cc → monitor_cc, gh-cli → gh_cli). Same spelling on both sides is what lets ONE context
# filter term match a main session and its workers together.
def project_label(project_path: str) -> str:
    return os.path.basename(project_path.rstrip("/")).replace("-", "_")


# First "cwd" value in a transcript, or "" — fail-open, a broken transcript just contributes nothing
def _first_cwd(transcript: Path) -> str:
    try:
        with open(transcript, encoding="utf-8") as fh:
            for index, line in enumerate(fh):
                if index >= _CWD_SCAN_LINES:
                    break
                if '"cwd"' not in line:
                    continue
                cwd = json.loads(line).get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
    except Exception:
        return ""
    return ""


# Every project path CC has a transcript for
def _project_cwds(projects_root: Path) -> set:
    cwds = set()
    try:
        entries = sorted(projects_root.iterdir())
    except Exception:
        return cwds
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            transcripts = sorted(
                (p for p in entry.iterdir() if p.suffix == ".jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            continue
        for transcript in transcripts[:_TRANSCRIPTS_PER_DIR]:
            cwd = _first_cwd(transcript)
            if cwd:
                cwds.add(cwd)
                break
    return cwds


# Map the proxy's md5(project_path)[:8] session id to a project label, for every project CC knows.
# The id is hashed with the production helper (src/proxy_display/forwarded_parser), which is the
# single source shared with addon.py's _derive_session_id — never re-derived here.
# Returns {} on any failure; an empty map degrades rendering to the <sid8> fallback, never an error.
def build_project_map(projects_root=None) -> dict:
    root = Path(projects_root) if projects_root else _PROJECTS_ROOT
    mapping = {}
    for cwd in _project_cwds(root):
        mapping.setdefault(_proxy_session_id_for_project(cwd), project_label(cwd))
    return mapping
