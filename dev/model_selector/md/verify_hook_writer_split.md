# hook_writer.py split verification — 2026-09-01T21:31:12

UserPromptSubmit -> hooks.json: {'test-session-model-selector': {'status': 'working', 'cwd': '/tmp/test-cwd', 'updated_ts': 1788291072.498386}}
Stop -> hooks.json: {'test-session-model-selector': {'status': 'idle', 'cwd': '/tmp/test-cwd', 'updated_ts': 1788291072.4986749}}
msg_queue.json created: False (expected False)
queue.lock created: False (expected False)

RESULT: PASS — hook-state half intact, no queue side effects.
