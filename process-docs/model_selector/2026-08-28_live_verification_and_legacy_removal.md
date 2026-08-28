# 2026-08-28 — Live verification of the Models tab, and removal of the legacy override sections

Closing entry for the three-milestone model-selector work. The three milestone entries in this
area all end on "not verified visually — needs a user check". This records that check and the
config cleanup that followed from it.

## Live verification

The menubar bundle was rebuilt from the merged `integration` state and installed. Note on the
build: `setup_py2app.py` exceeded a two-minute foreground budget at the codesign stage and had
to be run detached to complete; the first, killed run left `dist/` signed but never reached the
install step, so the running app was unchanged and the failure was harmless.

Verified by the user in the running app:

- The ring shows three tabs, `Sessions · RAG · Models`, and cycles.
- Both rows step through the three model IDs on click.
- Apply writes the file.

Verified afterwards on disk — `~/.claude/shared-rules/model_selection.json`:

```json
{"main": "claude-sonnet-5", "worker": "claude-fable-5"}
```

Exactly two keys, both values present in the `model_params` table, no leftover `.tmp` file.

An earlier check of the same path found no file at all, because Apply had not yet been clicked.
Worth recording because the failure mode is indistinguishable from a silent write failure:
`handle_apply` catches and logs to stderr, and on this build there is no `src/logs/menubar.log`,
so a real failure would leave exactly the same evidence as a button never pressed.

## Removal of `model_override` and `model_override_worker`

Both legacy sections were deleted from `~/.claude/shared-rules/proxy_rules.json`. They had been
unreachable since `model_params` was introduced — `_inject_model_override` dispatches on the
mere presence of the `model_params` key, so the legacy branch is never entered while it exists.

What they did while live: selection by model *family* (`opus` → `model_override`, `sonnet` →
`model_override_worker`, haiku falls through), each gated by its own `enabled` flag, writing
four payload fields — `model`, `thinking`, `effort` into `output_config`, and `max_tokens`. The
`model` rewrite is the part `model_params` deliberately dropped: it overwrote the model field on
every request, so the executed model disagreed with the system prompt Claude Code had built at
startup for the model it actually launched as.

Two concrete reasons for deleting rather than keeping them as a fallback:

1. Their only possible activation is the disappearance of `model_params`, and on activation they
   would restore both known defects at once — the model-field rewrite, and `display: "omitted"`,
   which switches the thinking summaries back off. A fallback that reinstates two known bugs is
   not a safety net.
2. `model_override_worker.model` read `claude-sonnett-5`, with a doubled t. That typo is also the
   cleanest available proof that the section was dead: a live path would have rewritten every
   worker request to a non-existent model id and failed loudly on the first spawn. It never did.

The earlier decision in `process-docs/thinking/` to leave both sections untouched was correct at
the time, because that work hung on a different question and changing dead config would have
altered a fallback nobody had characterised. The fallback is characterised now.

Verified after the edit: the file parses, five sections remain (`system2_rules`,
`tool_injection`, `model_params`, `pyright_diagnostics_strip`, `context_management`),
`model_params` still carries all three model ids, and the dispatcher's key-presence check
therefore resolves to the same branch as before. The proxy reloads this file on mtime, so no
restart was involved.

## Incidental finding, not acted on

`context_management.enabled` is `false`, so `_inject_context_management` returns before it looks
at either sub-block. `clear_tool_uses` carries its own `enabled: true` and a
`trigger_input_tokens` of 100,000, which reads as active server-side tool-result clearing but is
inert. Left as found; switching it on has prompt-cache consequences that were not evaluated here.

## Standing hazard, restated

`setup_py2app.py` builds, installs to `~/Applications` and relaunches the live app in one
command. Running it from a worktree deploys unmerged code over the running menubar; that
happened once during milestone 1 and the LaunchAgent was left unloaded afterwards, so the app
stayed dead until it was re-bootstrapped by hand with `launchctl bootstrap`.
