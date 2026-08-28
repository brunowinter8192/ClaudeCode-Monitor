# dev/model_selector/

## Role

Verification scripts for the model-selector line of work — the menubar's Queue-tab removal and
Models-tab addition (`src/menubar/`, milestones 1-2), and the launcher/worker-spawn/hook changes
that make the Models tab's config file actually take effect (milestone 3). `md/` holds every
script's report.

## Modules

### verify_hook_writer_split.py (76 LOC)

**Purpose:** Milestone 1 regression guard — `src/menubar/hook_writer.py`'s hook-state half
(`_write_state`/`_load_state`) after the queue-delivery half was removed. Feeds real synthetic
`UserPromptSubmit`/`Stop` payloads through the real `hook_writer_workflow()`, loaded fresh via
`importlib.util.spec_from_file_location` (the module has zero relative imports), against a
tempdir-isolated `_APP_SUPPORT` — asserts both status transitions and the absence of any
`msg_queue.json`/`queue.lock` side effect.
**Reads:** nothing persistent — builds its own tempdir.
**Writes:** `md/verify_hook_writer_split.md`.
**Called by:** run manually — regression guard; re-run after any `hook_writer.py` change.
**Calls out:** `src/menubar/hook_writer.py` (loaded by path).

---

### verify_model_cycle_and_io.py (105 LOC)

**Purpose:** Milestone 2 — `src/menubar/model_controller.py`'s pure cycle logic (`_next_model`:
all 3 values step correctly, third wraps to first, an unrecognized value starts the cycle at the
first choice) and its config I/O (`_write_model_selection`: atomic, exactly the 2-key schema, no
leftover tempfile; `_load_model_selection`: valid/missing/malformed file handling, and —
milestone 2's review correction — an unrecognized-but-valid on-disk value is preserved verbatim,
never silently replaced, with an Apply-without-cycling round-trip proving it). Loads the real
module via `importlib.import_module('src.menubar.model_controller')` (package-relative imports
require real package context, unlike `hook_writer.py`).
**Reads:** nothing persistent — all cases use a tempdir path, never the real
`~/.claude/shared-rules/model_selection.json`.
**Writes:** `md/verify_model_cycle_and_io.md`.
**Called by:** run manually — regression guard; re-run after any `model_controller.py` I/O change.
**Calls out:** `src/menubar/model_controller.py`.

---

### verify_three_tab_ring.py (145 LOC)

**Purpose:** Milestone 2 — the three-tab Cmd+→/← ring (Sessions/RAG/Models). Drives the REAL,
unmocked `_open_main_panel`/`_open_rag_panel`/`_open_models_panel`/`_close_*_panel`/
`_deferred_close_open` from `panel_lifecycle.py` against a lightweight `_FakeApp` (real
`PanelManager`/`RagController`/`ModelController` instances, real NSPanel objects underneath —
confirmed these construct and respond to geometry calls without a running AppKit run loop or
`rumps.App`). Only `Foundation.NSOperationQueue`'s async-dispatch wrapper is patched to run
synchronously, so the captured hotkey callbacks execute inline; the ring logic itself is never
mocked. Verifies both directions land correctly: main→rag→models→main and the reverse.
**Reads:** nothing persistent.
**Writes:** `md/verify_three_tab_ring.md`.
**Called by:** run manually — regression guard; re-run after any ring-wiring change in
`panel_lifecycle.py`.
**Calls out:** `src/menubar/{panel_manager,rag_controller,model_controller,panel_lifecycle}.py`.

---

### verify_launcher_model_precedence.sh (200 LOC)

**Purpose:** Milestone 3 — full precedence-chain dry run for `src/claude_proxy_start.sh`'s model
selection: explicit `--model` > `--fable`/`--opus` shortcut > `main` key from
`~/.claude/shared-rules/model_selection.json` > nothing injected. Mirrors the exact parse loop +
precedence resolution from the real script (keep in sync when editing either) — a complete,
standalone re-check of ALL 4 tiers, not just the new config tier; the narrower, config-unaware
`dev/native-model-start/p1_arg_parse_dry_run.sh` still covers tiers 1-2 in isolation and remains
accurate for what it tests. 12 cases: 5 tier-1/2 sanity re-checks, 3 config-tier cases (config
wins when nothing else applies, shortcut wins over config, explicit wins over config), 4
degradation cases (missing file, malformed JSON, missing key, empty key value) — all against a
temp `MODEL_SELECTION_FILE` override, never the real path.
**Reads:** nothing persistent outside its own tempdir.
**Writes:** `md/verify_launcher_model_precedence_<timestamp>.md`.
**Called by:** run manually — regression guard; re-run after any change to
`claude_proxy_start.sh`'s precedence logic.
**Calls out:** `jq`, `src/claude_proxy_start.sh`'s parse loop (mirrored, not sourced).

---

### verify_hook17_removal.py (82 LOC)

**Purpose:** Milestone 3 — confirms `block_worker_spawn_opus.py`'s retirement: the file is gone,
`hook_setup.py:_HOOK_SCRIPTS` no longer lists it, and the real `_sweep_stale_hooks()` pure
function (the actual mechanism that heals `~/.claude/settings.json` on the next post-merge run)
correctly removes a dead-path entry from a synthetic in-memory settings dict while leaving a live
entry untouched. Never invokes `hook_setup_workflow()` itself (`_guard_not_worktree()` refuses to
run from any worktree path, including this one) and never touches the real settings file.
**Reads:** nothing persistent — synthetic dict built in-process.
**Writes:** `md/verify_hook17_removal.md`.
**Called by:** run manually — one-off verification for the Hook 17 removal; re-run if
`_sweep_stale_hooks()` itself changes.
**Calls out:** `src/hooks/hook_setup.py`.

## Gotchas

**None of these scripts touch the real `~/.claude/shared-rules/model_selection.json` or the real
`~/.claude/settings.json`.** Every script that needs a config file uses a `tempfile`/`mktemp`
path, and `verify_hook17_removal.py` exercises `_sweep_stale_hooks()` on a synthetic dict rather
than invoking the guarded `hook_setup_workflow()`.

**The real regeneration mechanism for `~/.claude/settings.json` after a `src/hooks/` change is
`.githooks/post-merge`** (`git config core.hooksPath` = `.githooks` on this machine), not a
script in this directory — it greps `git diff --name-only ORIG_HEAD HEAD` for `^src/hooks/` and
re-runs `hook_setup.py` automatically on the next real merge. See
`process-docs/model_selector/` for the full trace.
