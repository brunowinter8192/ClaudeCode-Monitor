# dev/native-model-start/

## Role

Verification scripts for starting the orchestrator's main CC session natively on a chosen model
(`--fable`/`--opus` flags on `src/claude_proxy_start.sh`, `p1_`) and the proxy-side per-model
parameter config that replaced the old model-rewrite override (`src/proxy/inject_helpers.py`,
`p2_`). `md/` holds every script's report.

## Modules

### p1_arg_parse_dry_run.sh (148 LOC)

**Purpose:** Pure argument-parsing dry run for `src/claude_proxy_start.sh`'s `--fable`/`--opus`/
`--model` precedence — mirrors the exact parse loop verbatim (kept in sync manually, same
convention as `dev/hook_smoke/test_version_purge.sh`'s mirrored-function pattern). 8 cases: no flag
(byte-identical baseline), `--fable` alone, `--opus` alone, a shortcut then explicit `--model`
(explicit wins), explicit `--model` then a shortcut (explicit STILL wins — position-independence,
pinned as its own case), both shortcuts in each order (last one wins both ways), and a mixed case
with `--project` + another passthrough flag+value. Never starts the proxy or claude.
**Reads:** Nothing persistent — pure in-process argument simulation.
**Writes:** `md/p1_arg_parse_dry_run_<timestamp>.md`.
**Called by:** run manually — regression guard; re-run after any change to
`claude_proxy_start.sh`'s parse loop (keep both copies in sync).
**Calls out:** stdlib bash only.

---

### p2_model_params_probe.py (247 LOC)

**Purpose:** Verifies `src/proxy/inject_helpers.py::_inject_model_override`'s 2026-08-06 rework —
per-model `model_params` config path (exact model-id lookup, never writes `model`) vs the legacy
family-bucketed `model_override`/`model_override_worker` path (byte-identical fallback when
`model_params` is absent from config). 7 test groups, 30 checks: legacy-only config unchanged incl.
the model rewrite (opus/sonnet/haiku); `model_params` hit for each of the 3 snippet models with the
model field verified untouched; miss leaves payload untouched; a suffixed model-id variant
(`claude-opus-4-8[1m]`) is a DELIBERATE miss — exact-match only, no normalization, pinned so a
future report of this is recognized as a known boundary, not a fresh bug; `model_params` presence
(both non-empty and empty `{}`) wins over legacy sections even when both are in the config; empty
vs partial per-model entries; `_load_config` raising fails open. Config injected via
`mock.patch.object(inject_helpers, "_load_config", ...)` — no prior mocking precedent for
`rules_config` existed anywhere in this repo before this script.
**Reads:** Nothing persistent — builds all fixtures in-process.
**Writes:** `md/p2_model_params_probe_<timestamp>.md`.
**Called by:** run manually — regression guard for `inject_helpers.py`; re-run after any change to
`_inject_model_override` or its two path functions.
**Calls out:** `src/proxy/inject_helpers.py`.

---

## Gotchas

**p1's ready-to-paste `model_params` values live in process-docs, not here.** The actual JSON
snippet for `~/.claude/shared-rules/proxy_rules.json` (fable-5/opus-5/sonnet-5, values read from
the live legacy config at write time) is in
`process-docs/native-model-start/2026-08-06_model_params_config.md` — that file is user config
outside the repo and is never edited by any script in this directory.
