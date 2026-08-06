# P3 — project-scoped timer incident probe

Replays the 2026-08-07 ~01:10 cross-project false-block incident (websearch main session blocked by a POSTS-project pending entry, task `b4z5fzzao`) through the real `block_timer_pending_bg.py` hook via subprocess, plus the writer-side `src/proxy/pending_bg_state.py` stamping via a real `ProxyAddon.request()` call.

**Result: 8/8 checks passed**

| Check | Result |
|---|---|
| posts pending entry + websearch cwd -> exit 0 (allow) | PASS |
| no stderr on allow | PASS |
| websearch pending entry + websearch cwd -> exit 2 (block) | PASS |
| block message names the id | PASS |
| legacy entry (pre-migration, no project field) -> exit 2 (block) | PASS |
| same legacy entry, different cwd (Posts) -> also exit 2 (blocks every project) | PASS |
| expired same-project entry -> exit 0 (allow) | PASS |
| armed entry has project == 'websearch' (from PROXY_PROJECT_PATH=/Users/x/Websearch) | PASS |
