# Launcher model-selection precedence dry run (2026-08-28T18:35:08Z)

**Result: 12/12 checks passed**

Pure argument-parsing simulation of src/claude_proxy_start.sh's full precedence chain
(--model > --fable/--opus > config file 'main' key > nothing) — never starts the proxy
or claude, never touches the real ~/.claude/shared-rules/model_selection.json.

| Case | Resulting CLAUDE_ARGS | Result |
|---|---|---|
| no flag, no config -> byte-identical (nothing injected) | `--extra|val` | PASS |
| --fable alone -> --model claude-fable-5 appended | `--model|claude-fable-5` | PASS |
| --opus alone -> --model claude-opus-5 appended | `--model|claude-opus-5` | PASS |
| --model X --fable (explicit before shortcut) -> explicit still wins | `--model|claude-custom` | PASS |
| mixed: --project + --fable + other passthrough -> --project extracted, model appended | `--other-flag|val|--model|claude-fable-5` | PASS |
| no flag, no shortcut, valid config -> config's main model injected | `--extra|val|--model|claude-opus-5` | PASS |
| --fable + valid config -> shortcut wins, config never consulted | `--model|claude-fable-5` | PASS |
| explicit --model + valid config -> explicit wins | `--model|claude-custom` | PASS |
| missing config file -> nothing injected (falls through to case 4) | `--extra|val` | PASS |
| malformed JSON config -> nothing injected, no crash | `--extra|val` | PASS |
| config present but missing 'main' key -> nothing injected | `--extra|val` | PASS |
| config present with empty 'main' value -> nothing injected | `--extra|val` | PASS |
