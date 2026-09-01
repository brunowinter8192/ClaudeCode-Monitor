# Milestone 4 — new model ID + per-model effort/max_tokens rows (menubar)

2026-09-01

## Scope

Fourth milestone of the model-selector line of work: extend the Models tab from two rows
(Main/Worker model, milestone 2) to seven (Main model, Main effort, Main max_tokens, Worker
model, Worker effort, Worker max_tokens, Apply), and add a fourth model ID, `claude-fable-5-1`,
into the cycle order (`claude-opus-5 → claude-fable-5 → claude-fable-5-1 → claude-sonnet-5 →`
wraps). Effort cycles `low → medium → high →` (`max` deliberately excluded — valid only on
specific Opus models, would hard-fail requests elsewhere); max_tokens cycles
`32000 → 64000 → 128000 →`. Apply now writes both `model_selection.json` (unchanged 2-key
schema) and a read-modify-write of `proxy_rules.json`'s `model_params` table, touching only the
two selected models' `effort`/`max_tokens`.

`src/menubar/model_controller.py` grew 206 → 392 LOC; `app.py` 330 → 342 (4 new one-line
`_PanelController` delegates, same static-selector pattern as milestone 2's 3); `paths.py` 54 →
55 (`PROXY_RULES_FILE`, an independent constant for the path `src/proxy/rules_config.py` already
hardcodes under its own name — no cross-package import, mirrors how `MODEL_SELECTION_FILE` was
added). `dev/model_selector/verify_model_cycle_and_io.py` grew 105 → 283 LOC (extended in place,
not a new file — see dev/ convention). DOCS.md updated in the same commit as the code.

## Finding — proxy_rules.json's real on-disk format is NOT plain json.dumps(indent=2)

Before writing the read-modify-write, the live `~/.claude/shared-rules/proxy_rules.json` was
read (read-only) to confirm the `model_params` shape. A byte-diff of the raw file against
`json.dumps(json.loads(raw), indent=2) + '\n'` showed every section byte-identical EXCEPT
`model_params`: every other section already matches plain `indent=2` output exactly, but each
`model_params` entry is hand-formatted as one compact single-line JSON object
(`{"thinking": {...}, "effort": "...", "max_tokens": ...}`), not multi-line.

This directly shaped the write strategy. The prompt's requirement — "every other section, key,
and the thinking block stay byte-identical" — cannot be satisfied by parsing the whole file into
a dict and re-serializing it with a single `json.dumps(config, indent=2)` call: that would
reformat every untouched `model_params` entry from compact-one-line to multi-line, which is a
byte-level change to content the task explicitly says must not change. The fix was a small
custom serializer (`_dumps_proxy_rules`, plus helpers `_render_model_params` and
`_reindent_nested`): standard `indent=2` for every top-level section, compact single-line
rendering specifically for `model_params` entries. An unmodified round-trip through this
function was verified byte-identical against the live file's actual bytes at implementation
time (a one-off manual check, not left as a standing script against the real path — see
Verification below for the pinned regression check against a fixture instead).

## Correction from review — missing-entry default is 'high'/64000, not the first cycle value

Original plan defaulted a model's displayed effort/max_tokens, when no `model_params` entry
exists for it, to each cycle's first value (`low`/`32000`) — consistent with `_next_model`'s own
"unrecognized current value starts at index 0" convention, and simple to justify by precedent.

Rejected on review: `_next_in`'s unrecognized-current-value behavior is a cycle-mechanics
convenience (index -1 wraps to 0), not a claim about what the *effective* on-disk state is. A
missing `model_params` entry means `_inject_model_params` (`src/proxy/inject_helpers.py`) injects
nothing at all for that model — no `effort` field reaches the request. Per the API, omitting
`effort` behaves like `"high"`, and `64000` is the value every existing entry in the live file
carries. Displaying `low`/`32000` for a missing entry would show a value strictly lower than what
is actually in effect, and an accidental Apply-without-cycling from that display would silently
write `low`/`32000` into a previously-uncapped or higher-effort model — a real downgrade, not a
cosmetic mismatch. Fixed: `_DEFAULT_EFFORT = "high"`, `_DEFAULT_MAX_TOKENS = 64000`, independent
of `_EFFORT_CHOICES`/`_MAXTOK_CHOICES` ordering; `_next_in`'s cycle-wrap behavior itself is
unchanged.

## Design decision — model-change refreshes its own parameter rows from disk

Per the prompt, clicking a model cycle button must refresh the two parameter rows below it to
that model's current on-disk values, not just leave the previous model's pending values in
place. Implemented as: `handle_cycle_main`/`handle_cycle_worker` call
`_load_model_params_for(new_model)` immediately after advancing `_pending_main`/`_pending_worker`,
before `_refresh_cycle_titles()`. This is a fresh disk read on every model-cycle click (not just
on panel open), which is a deliberate deviation from milestone 2's `ModelController` docstring
claim that nothing external is re-read while the panel is open — that claim was true when the
panel had no per-model parameters to track; it no longer holds for the parameter rows
specifically, and DOCS.md was updated to say so.

## Verification

`dev/model_selector/verify_model_cycle_and_io.py`, extended in place, 8 sections, all against
temp paths or in-memory fixtures, never the real `~/.claude/shared-rules/`:

1. Model cycle: 4 values step correctly incl. `claude-fable-5-1`, fourth wraps to first,
   unrecognized value starts at first choice.
2. Effort cycle: `low/medium/high` step + wrap; `"max"` confirmed absent from the choice tuple.
3. max_tokens cycle: `32000/64000/128000` step + wrap.
4-5. `model_selection.json` atomic write + read-back/fallback — unchanged behavior re-verified
   after the cycle-tuple change (existing-caller regression coverage).
6. Serializer format fidelity: an unmodified round-trip through `_dumps_proxy_rules` against a
   fixture mirroring the real file's convention (indent=2 sections + compact-per-line
   `model_params`, including a foreign top-level section and 3 model entries) reproduces the
   fixture byte-for-byte.
7. Read-modify-write: one existing target model (effort/max_tokens updated, `thinking` block and
   all else on that entry untouched) and one missing target model (entry created with the
   established `thinking` shape, appended at the end); asserts the full written file matches an
   independently-computed expected string exactly, AND separately asserts a foreign top-level
   section and two untouched model entries are byte-preserved, AND confirms no leftover `.tmp`.
8. Malformed-file fallback: invalid JSON input does not raise; the write still produces a valid,
   parseable file with fresh `model_params` entries for both selected models.

All 8 sections passed. Also re-ran, unmodified, `dev/model_selector/verify_three_tab_ring.py`
(confirms the new 7-row panel construction/resize doesn't break the Sessions/RAG/Models ring —
still passed both directions) and `dev/model_selector/verify_hook_writer_split.py` (unrelated
sanity check, still passed). `setup_py2app.py` was not run (standing hazard, see milestone 1's
entry — unchanged this milestone). Real `~/.claude/shared-rules/proxy_rules.json` and
`model_selection.json` were confirmed byte-unchanged (md5 before/after) across the whole session.

NOT verified: interactive rendering of the 7-row layout and the new panel height in the live
running app — needs a user check after merge + rebuild, same standing gap as milestone 2's tab
addition.

## Cross-reference

See `process-docs/model_selector/` for milestones 1-3 (Queue-tab removal, Models tab addition,
launcher/worker readers) and the live-verification/legacy-removal entry that closed them out.
