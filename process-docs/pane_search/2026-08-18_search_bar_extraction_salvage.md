# search_bar.py Extraction (Rollout Sub-Milestone 1) — Salvaged From a Context-Limit Worker Death

Written by the orchestrator, not the implementing worker — the worker died at 0% context while
polishing DOCS prose for this very milestone, with the ENTIRE implementation uncommitted in its
worktree. This entry records both the milestone content and the salvage procedure.

## The milestone

First step of rolling the proxy pane's search bar out to all other panes: extract the
battle-tested mechanics into `src/search_bar.py` (215 LOC, root-level — same shallow-import
rationale as `constants.py`/`utils.py`) and retrofit the proxy pane onto it with ZERO
user-facing behavior change. Extracted surface: `SearchState` (one object replacing 8
per-pane globals), `render_search_bar` (label + show_counter parametrized),
`col_to_query_index` (cell-width-aware boundary mapping), `handle_search_input` (backspace /
selection-delete / kill-line / Enter with an INJECTED pane-specific `on_commit` callback),
the drag press/motion/release handlers (`copy_to_clipboard_fn` injected so pane-level
monkeypatch test conventions keep working), `KILL_LINE_CHAR`, and the
`_BG_RESTORE_SENTINEL` + `resolve_bg_restore` pair (carrying the empty-`chosen_bg` → `\033[49m`
fix so no future pane re-derives that bug). `proxy_display/pane.py` shrank 663→533 LOC; its
search functions became 1-2-line wrappers preserving pre-extraction call shapes for tests.

## Verification (as of 2026-08-18, run by the orchestrator on the dead worktree)

The acceptance criterion was "all existing suites pass unchanged" — verified independently
AFTER the worker's death, before committing its work: p2 48/48, p3 62/62,
p3_button_click_probe 32 PASS, and A_render_refactor_proof with a baseline captured fresh
from PRE-extraction integration code, verified against the worktree — 14/14 byte-identical
across code states, a stronger form of the proof than the usual same-tree run.

## The salvage procedure (worked, reusable)

Worker death at context limit leaves a worktree with uncommitted work; `worker-cli kill`
would destroy it. Sequence that saved it: (1) `worker-cli capture` BEFORE any kill — the pane
showed the worker mid-DOCS-edit, implementation done; (2) run the milestone's own acceptance
suites directly in the dead worktree; (3) full diff review; (4) commit the worktree state
as-is (`gcommit` in the worktree) and merge normally; (5) orchestrator writes the process-docs
entry itself. The judgment call: salvage was justified ONLY because the acceptance criterion
was fully machine-checkable (four green suites + byte-identity) — for a milestone whose
verification needs the worker's own knowledge, spawning a successor to redo is safer.

## Worker-death observation feeding the worker_wait strand

The wake-up wait held for ~27min on `status=limit_reached` — the same terminal-status
blocking already seen with `unknown` earlier the same day (dead worker never reports idle;
fail-toward-waiting holds until the ceiling). Both sightings motivate the terminal-status
wake change in the iterative-dev repo's `worker_wait` area: stably-terminal statuses should
END the wait with a distinct exit reason, since a dead worker needs orchestrator intervention
and sleeping on it helps nobody. The wait-trace (`wait_trace.log`, built that same morning)
identified the holdout worker and its exact status in one `tail` — its first two live uses
both paid for the feature immediately.
