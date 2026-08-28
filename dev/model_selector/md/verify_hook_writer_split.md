# hook_writer.py split verification — 2026-08-28T19:57:00

UserPromptSubmit -> hooks.json: {'test-session-model-selector': {'status': 'working', 'cwd': '/tmp/test-cwd', 'updated_ts': 1787939820.5755}}
Stop -> hooks.json: {'test-session-model-selector': {'status': 'idle', 'cwd': '/tmp/test-cwd', 'updated_ts': 1787939820.575862}}
msg_queue.json created: False (expected False)
queue.lock created: False (expected False)

RESULT: PASS — hook-state half intact, no queue side effects.
