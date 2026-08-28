# hook_writer.py split verification — 2026-08-28T19:24:27

UserPromptSubmit -> hooks.json: {'test-session-model-selector': {'status': 'working', 'cwd': '/tmp/test-cwd', 'updated_ts': 1787937867.760148}}
Stop -> hooks.json: {'test-session-model-selector': {'status': 'idle', 'cwd': '/tmp/test-cwd', 'updated_ts': 1787937867.760421}}
msg_queue.json created: False (expected False)
queue.lock created: False (expected False)

RESULT: PASS — hook-state half intact, no queue side effects.
