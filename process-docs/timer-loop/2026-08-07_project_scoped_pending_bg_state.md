# 2026-08-07 — Project-scoping the pending-background-task tombstone file

## Incident

~01:10 local. The websearch project's MAIN session armed its canonical worker timer
(`sleep 3300 && echo done`, `run_in_background=true`) and was blocked by
`block_timer_pending_bg.py`. The pending entry the hook matched (task `b4z5fzzao`) belonged to a
DIFFERENT project's main session (Posts), not websearch's own.

Root cause: `src/logs/pending_bg_tasks.json` is ONE global file shared by every project's main
session (`src/proxy/pending_bg_state.py` writes it, keyed only by task id). Entries carried
`{status, armed_at}` only — no project identifier — and the hook (`src/hooks/
block_timer_pending_bg.py::_fresh_pending_ids`) filtered purely on status + age. The original
design (`2026-08-06_pending_bg_state_design.md`, `2026-08-06_pending_bg_hook_enforcement.md`)
never modeled multiple parallel main sessions running concurrently against different projects.

## Fix — project-scope the arm/clear/check chain

**Writer (`pending_bg_state.py`):** `_update_pending_bg_state` gained a 3rd param `project_path`
— `addon.py`'s `PROXY_PROJECT_PATH` env var, already in scope at the exact call site (same
variable `_trigger_bg_escape` receives as its 3rd arg two lines earlier). Considered deriving the
project from the dual-log filename stem instead (`api_requests_opus_websearch_*`) — rejected: it
would couple the writer to log-rotation/naming, whereas `PROXY_PROJECT_PATH` is the raw
in-process source those stems are THEMSELVES derived from in `claude_proxy_start.sh`. Threaded
only into the ARM path (`_handle_launch_ack_chunk` → `_arm_pending`) — confirmed and stated
explicitly that the CLEAR path needs no scoping, since task ids are globally unique across
projects; a completion notice for task X can only ever be the completion of task X regardless of
which project's proxy instance observes it.

**Normalization (the stated pitfall):** dual-log stems are already lowercased/underscored
(`monitor_cc`) while a hook's `os.getcwd()` basename is not (`Monitor_CC`, `Posts`). Both sides
now run the SAME normalization: `_normalize_project_slug(name)` = lower-case, any run of
non-`[a-z0-9]` characters (including existing `_`/`-`) collapsed to a single `_`, leading/trailing
`_` stripped. This is an exact mirror of `claude_proxy_start.sh`'s bash pipeline for
`PROJECT_BASENAME` (`tr lower | tr -cs 'a-z0-9' '_' | sed 's/^_*//;s/_*$//'`) — chosen specifically
so the slug space stays identical to the one already used everywhere else in this codebase (dual-
log filenames, marker files). Pinned by tests both directions: `Websearch`→`websearch`,
`Monitor_CC`→`monitor_cc`, `Posts`→`posts`. The helper is duplicated (not imported) between
`pending_bg_state.py` and `block_timer_pending_bg.py` — `src/hooks/` has no import path into
`src/proxy/`, matching the pre-existing convention of duplicating small helpers between the two
(e.g. `_resolve_pending_bg_state_file` was already duplicated this way before this fix).

**Hook (`block_timer_pending_bg.py`):** `_current_project_slug()` derives the hook's own project
from `basename(os.getcwd())` normalized — main-session cwd IS the project root, the same
assumption the existing worktree-fragment exemption check already makes. `decide()` gained a 4th
param `current_project` (default `""`, backward compatible with any caller that doesn't pass it).
`_fresh_pending_ids` now additionally requires: an entry's `"project"` field is either ABSENT
(pre-migration state — blocks every project, unconditionally, unchanged from before this fix) or
EQUAL to `current_project`. A design choice worth stating: expiry is checked BEFORE project match
in the filter order, so an expired foreign-project entry and an expired same-project entry both
allow identically — project scoping never extends an already-stale entry's blocking window.

**Backward compat, confirmed:** a legacy entry (no `"project"` key) blocks every project exactly
as before this fix — verified directly (`dev/hook_smoke/test_block_timer_pending_bg.py`'s Layer 1
"legacy entry" case, and Layer 2's real-subprocess "legacy no-project entry" case with two
DIFFERENT cwd basenames both blocking). Such entries age out via the pre-existing 3600s expiry
regardless of any project logic — no separate migration/backfill needed for the state file.

## Verification (as of 2026-08-07)

New dedicated incident-replay probe `dev/timer-loop/p3_project_scope_incident_probe.py` — drives
the real hook via `subprocess` with a genuinely seeded state file and REAL named cwd directories
(`.../Websearch`, `.../Posts`), not injected strings, so `_current_project_slug()`'s actual
cwd-basename derivation runs end-to-end. 8/8 checks: foreign-project pending now allows (the
incident itself); same-project pending still blocks; legacy no-project entry still blocks
regardless of cwd; expired same-project entry allows; real `ProxyAddon.request()` end-to-end
stamps the project from `PROXY_PROJECT_PATH`. Report:
`dev/timer-loop/md/p3_project_scope_incident_probe_report.md`.

Existing regression guards, extended in place (not new files — same convention as prior sessions
in this area): `dev/hook_smoke/test_block_timer_pending_bg.py` grew from 27 to 36 checks (6 new
`decide()`-level project-scoping unit cases + 3 new real-subprocess cases exercising the actual
cwd-basename normalization) — 36/36 pass. `dev/timer-loop/p2_pending_bg_state_probe.py` grew a
13th test group (writer-side project stamping, both direct-call and real-`ProxyAddon.request()`
paths) — 40/40 pass. `dev/hook_smoke/test_block_timer_no_worker_working.py` (the OTHER timer
hook, explicitly out of scope for this fix) reruns unchanged — 10/10 pass, confirming no
cross-hook regression.
