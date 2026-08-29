#!/usr/bin/env python3
"""
Smoke test for feedback_bash_error.py — the PostToolUseFailure hook.

Fixtures are the REAL payloads captured from CC 2.1.x with a stdin-dumping probe registered on
PostToolUse and PostToolUseFailure (see process-docs/tool_use_safety/), not hand-written guesses:
a failure carries `error` + `is_interrupt` and NO `tool_response`; a success carries
`tool_response` and no `error`.

Fires  -> exit 0 + stdout JSON hookSpecificOutput.additionalContext + one 'feedback' fire-log line.
Silent -> exit 0, no stdout, no fire-log line.

Usage: python3 dev/hook_smoke/test_feedback_bash_error.py
"""
# INFRASTRUCTURE
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "hooks",
                    "feedback_bash_error.py")

_EXPECTED = ("This tool call FAILED. 1. Diagnose why before any retry. 2. Retry corrected ONCE. "
             "3. After 2 failures on this goal, STOP and report to the user.")

# Real PostToolUseFailure payload (captured 2026-08-29)
FAILURE = {
    "session_id": "790c46a6-80f3-4418-800b-537689c9af2e",
    "transcript_path": "/Users/x/.claude/projects/p/790c46a6.jsonl",
    "cwd": "/Users/x/project",
    "prompt_id": "2c4599f1-3d41-431c-b878-17f7f58027de",
    "permission_mode": "bypassPermissions",
    "effort": {"level": "medium"},
    "hook_event_name": "PostToolUseFailure",
    "tool_name": "Bash",
    "tool_input": {"command": "cat /tmp/no_such_file.txt", "description": "Failing call"},
    "tool_use_id": "toolu_011kSctqhVSm767gvsWbtPer",
    "error": "Exit code 1\ncat: /tmp/no_such_file.txt: No such file or directory",
    "is_interrupt": False,
    "duration_ms": 16,
}

# Real PostToolUse (success) payload — the hook must never see this event in production, but a
# mis-registration must stay silent rather than congratulate the model on a working command.
SUCCESS = {
    "session_id": "790c46a6-80f3-4418-800b-537689c9af2e",
    "hook_event_name": "PostToolUse",
    "tool_name": "Bash",
    "tool_input": {"command": "echo ok", "description": "Succeeding call"},
    "tool_response": {"stdout": "ok", "stderr": "", "interrupted": False,
                      "isImage": False, "noOutputExpected": False},
    "tool_use_id": "toolu_01UcANTzAmqk9DzCC1s7EbB9",
    "duration_ms": 15,
}


# ORCHESTRATOR

def test_feedback_bash_error_workflow() -> None:
    passed = failed = 0
    for label, payload, should_fire in _payload_cases():
        ok, detail = _check_payload(label, payload, should_fire)
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            print(f"       {detail}")
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

    for label, raw in [("malformed stdin -> fail-open silent", b"not json"),
                       ("empty stdin -> fail-open silent", b""),
                       ("JSON list instead of object -> silent", b"[1, 2]")]:
        code, out, _log = _run(raw, None)
        ok = code == 0 and not out.strip()
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            print(f"       exit={code} stdout={out!r}")
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if failed == 0 else 1)


# FUNCTIONS

# (label, payload, should_fire) for every gate the hook implements
def _payload_cases() -> list:
    no_error = {k: v for k, v in FAILURE.items() if k != "error"}
    return [
        ("real Bash failure -> fires",                       FAILURE,                          True),
        ("real Bash success -> silent",                      SUCCESS,                          False),
        ("user interrupt (is_interrupt=True) -> silent",     {**FAILURE, "is_interrupt": True}, False),
        ("non-Bash tool -> silent",                          {**FAILURE, "tool_name": "Read"},  False),
        ("whitespace-only error -> silent",                  {**FAILURE, "error": "   "},       False),
        ("error key absent -> silent",                       no_error,                          False),
        ("error is None -> silent",                          {**FAILURE, "error": None},        False),
    ]


# Run the hook once with an isolated fire-log; returns (exit_code, stdout, log_records)
def _run(raw_stdin: bytes, log_path):
    env = dict(os.environ)
    if log_path:
        env["MONITOR_CC_HOOK_FIRING_LOG"] = log_path
    result = subprocess.run(["python3", HOOK], input=raw_stdin, capture_output=True, env=env)
    records = []
    if log_path and os.path.exists(log_path):
        records = [json.loads(l) for l in open(log_path) if l.strip()]
    return result.returncode, result.stdout.decode(), records


# Verify one payload: exit code, stdout shape, message text, and the fire-log side effect
def _check_payload(label: str, payload: dict, should_fire: bool) -> tuple:
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = f.name
    try:
        code, out, records = _run(json.dumps(payload).encode(), log_path)
        if code != 0:
            return False, f"expected exit 0, got {code}"
        fired = bool(out.strip())
        if fired != should_fire:
            return False, f"expected fired={should_fire}, got {fired} (stdout={out[:80]!r})"
        if not should_fire:
            return (True, "") if not records else (False, f"silent case wrote a fire-log line: {records}")
        emitted = json.loads(out).get("hookSpecificOutput", {})
        if emitted.get("additionalContext") != _EXPECTED:
            return False, f"unexpected message: {emitted.get('additionalContext')!r}"
        if emitted.get("hookEventName") != "PostToolUseFailure":
            return False, f"unexpected hookEventName: {emitted.get('hookEventName')!r}"
        if len(records) != 1:
            return False, f"expected exactly 1 fire-log line, got {len(records)}"
        record = records[0]
        if record.get("decision") != "feedback":
            return False, f"expected decision=feedback, got {record.get('decision')!r}"
        if record.get("hook") != "feedback_bash_error":
            return False, f"expected hook=feedback_bash_error, got {record.get('hook')!r}"
        if "reason" not in record:
            return False, "fire-log record missing 'reason' (feedback records carry reason, not rewritten)"
        if "rewritten" in record:
            return False, "fire-log record carries 'rewritten' — feedback must use 'reason'"
        return True, ""
    finally:
        if os.path.exists(log_path):
            os.unlink(log_path)


if __name__ == "__main__":
    test_feedback_bash_error_workflow()
