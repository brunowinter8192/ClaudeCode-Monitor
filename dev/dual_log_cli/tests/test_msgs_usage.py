"""
Regression suite for `duallog msgs`' CR/CC prompt-cache separator (src/dual_log_cli/usage.py
and the usage-aware half of src/dual_log_cli/render.py).

Covers: `_req_separator`/`render_msgs` render `CR c  CC c` between the clock and the closing
`──` when a marker's flow_id resolves in the usage map (digit-grouped, no `c` suffix, re-fire
suffix staying OUTSIDE the `──` exactly as before), and render the pre-feature plain separator
when it does not — never a placeholder. `usage.build_usage_by_flow` is exercised end to end
against FIXTURE `_response`/transcript files (a temp dir stands in for both the dual-log stream
and `~/.claude/projects/`, via the `projects_root` parameter `_find_transcript` accepts), so the
suite depends only on those fixtures and the system `grep` binary the production code itself
shells out to — never on the real, live-growing dual-log or transcript store.

Run (from project root):
    ./venv/bin/python dev/dual_log_cli/tests/test_msgs_usage.py

Exit 0 = all checks pass. Exit 1 = at least one failure (printed by name).
"""

# INFRASTRUCTURE

import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(_HERE.parents[2]))

from src.dual_log_cli.render import render_msgs
from src.dual_log_cli.usage import build_usage_by_flow, _find_transcript

PASS_LIST = []
FAIL_LIST = []


# FUNCTIONS

def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASS_LIST.append(name)
    else:
        FAIL_LIST.append(name)
        print(f"  FAIL  {name}" + (f": {detail}" if detail else ""))


def _msg(index: int, role: str, chars: int, blocks: list) -> dict:
    return {"index": index, "role": role, "type": blocks[0]["type"], "chars": chars, "blocks": blocks}


def _block(type_: str, chars: int) -> dict:
    return {"label": type_, "type": type_, "chars": chars, "sig_chars": 0, "preview": ""}


def _boundary(start_index: int, message_count: int, timestamp: str, flow_id: str) -> dict:
    return {"start_index": start_index, "message_count": message_count, "timestamp": timestamp,
            "flow_id": flow_id, "restart": False}


# render_msgs with a resolved usage map renders "CR 9,096  CC 1,928" between the clock and the
# closing "──", digit-grouped exactly like the msg lines' chars, with no "c" suffix.
def test_separator_shows_resolved_usage() -> None:
    data = {
        "boundaries": [_boundary(0, 1, "2026-09-02T16:41:13Z", "f0")],
        "turns": [_msg(0, "user", 4, [_block("text", 4)])],
    }
    got = render_msgs(data, 0, 0, usage_by_flow={"f0": (9096, 1928)})
    expected = "── REQ 1  16:41:13  CR 9,096  CC 1,928 ──\n[  0] user  text                    4c\n"
    check("resolved usage renders CR/CC in the right spot", got == expected, got)


# A marker whose flow_id is absent from usage_by_flow renders the plain pre-feature separator —
# no placeholder of any kind.
def test_separator_omits_unresolved_usage() -> None:
    data = {
        "boundaries": [_boundary(0, 1, "2026-09-02T16:41:13Z", "f0")],
        "turns": [_msg(0, "user", 4, [_block("text", 4)])],
    }
    got = render_msgs(data, 0, 0, usage_by_flow={"other-flow": (1, 2)})
    check("unresolved usage keeps the plain separator", got.startswith("── REQ 1  16:41:13 ──\n"), got)
    check("unresolved usage carries no CR/CC/placeholder", "CR" not in got and "CC" not in got, got)


# A None usage_by_flow (the default) must render byte-identical to the pre-feature separator —
# proves the parameter is additive, not a behavior change for existing callers.
def test_separator_default_unchanged() -> None:
    data = {
        "boundaries": [_boundary(0, 1, "2026-09-02T09:00:00Z", "f0")],
        "turns": [_msg(0, "user", 4, [_block("text", 4)])],
    }
    got = render_msgs(data, 0, 0)
    check("default (no usage map) separator unchanged", got.startswith("── REQ 1  09:00:00 ──\n"), got)


# The re-fire suffix stays OUTSIDE the closing "──", after any CR/CC — same position as before
# usage existed.
def test_refire_suffix_stays_outside_usage() -> None:
    data = {
        "boundaries": [
            _boundary(0, 0, "2026-09-02T10:00:00Z", "f0"),
            _boundary(0, 1, "2026-09-02T10:00:05Z", "f1"),
        ],
        "turns": [_msg(0, "user", 4, [_block("text", 4)])],
    }
    got = render_msgs(data, 0, 0, usage_by_flow={"f1": (100, 200)})
    expected_line = "── REQ 1  10:00:05  CR 100  CC 200 ──  (+1 re-fire)"
    check("re-fire suffix sits after usage, outside the '──'", got.startswith(expected_line), got)


# usage.build_usage_by_flow end to end: a fixture _response stream plus a fixture transcript
# (via the projects_root override _find_transcript accepts) resolve to the right CR/CC, an
# owner with a non-200 status is dropped even though its request id would otherwise resolve,
# and an id absent from the transcript store degrades to {} rather than raising.
def test_build_usage_by_flow_end_to_end() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        response_path = tmp_path / "session_response.jsonl"
        response_path.write_text("\n".join(json.dumps(line) for line in [
            {"flow_id": "f0", "request_id": "req_AAA", "status_code": 200},
            {"flow_id": "f1", "request_id": "req_BBB", "status_code": 400},
        ]) + "\n")

        projects_root = tmp_path / "projects"
        project_dir = projects_root / "-fake-project"
        project_dir.mkdir(parents=True)
        transcript_path = project_dir / "11111111-1111-1111-1111-111111111111.jsonl"
        # CC's own transcripts are compact JSON (no space after ":") — the fragment
        # `_find_transcript` searches for has none either, so the fixture must match that shape.
        transcript_path.write_text("\n".join(json.dumps(line, separators=(",", ":")) for line in [
            {"type": "assistant", "requestId": "req_AAA",
             "message": {"usage": {"cache_read_input_tokens": 500, "cache_creation_input_tokens": 25}}},
            {"type": "assistant", "requestId": "req_BBB",
             "message": {"usage": {"cache_read_input_tokens": 999, "cache_creation_input_tokens": 999}}},
        ]) + "\n")

        # build_usage_by_flow itself hardcodes the real ~/.claude/projects root, so this test
        # exercises _find_transcript directly against the fixture root — the seam
        # build_usage_by_flow is built from — rather than monkeypatching a private constant.
        found = _find_transcript("req_AAA", projects_root=projects_root)
        check("fixture transcript found via literal requestId fragment", found == transcript_path, found)

        session = {"streams": {"response": response_path}}
        boundaries = [
            _boundary(0, 1, "2026-09-02T10:00:00Z", "f0"),
            _boundary(1, 2, "2026-09-02T10:00:05Z", "f1"),
        ]
        # Patch the module-level search to the fixture root for this call only
        import src.dual_log_cli.usage as usage_module
        original_root = usage_module._PROJECTS_ROOT
        usage_module._PROJECTS_ROOT = projects_root
        try:
            result = build_usage_by_flow(session, boundaries)
        finally:
            usage_module._PROJECTS_ROOT = original_root

        check("200-status flow resolves to its transcript usage", result.get("f0") == (500, 25), result)
        check("400-status flow is dropped despite a resolvable request id", "f1" not in result, result)


# No boundaries, or no _response stream, degrades to {} rather than raising
def test_build_usage_by_flow_degrades_cleanly() -> None:
    check("empty boundaries -> {}", build_usage_by_flow({"streams": {}}, []) == {})
    check("missing _response stream -> {}",
          build_usage_by_flow({"streams": {}}, [_boundary(0, 1, "t", "f0")]) == {})


# ORCHESTRATOR

def test_msgs_usage_workflow() -> None:
    test_separator_shows_resolved_usage()
    test_separator_omits_unresolved_usage()
    test_separator_default_unchanged()
    test_refire_suffix_stays_outside_usage()
    test_build_usage_by_flow_end_to_end()
    test_build_usage_by_flow_degrades_cleanly()

    total = len(PASS_LIST) + len(FAIL_LIST)
    print(f"{len(PASS_LIST)}/{total} checks passed")
    if FAIL_LIST:
        print(f"\nFAILED: {FAIL_LIST}")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    test_msgs_usage_workflow()
