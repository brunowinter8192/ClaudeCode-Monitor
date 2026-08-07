# dev/native-model-start/

## Role

Verification scripts for starting the orchestrator's main CC session natively on a chosen model
(`--fable`/`--opus` flags on `src/claude_proxy_start.sh`, `p1_`), the proxy-side per-model
parameter config that replaced the old model-rewrite override (`src/proxy/inject_helpers.py`,
`p2_`), and the CC 2.1.223 pin-bump live-verify (`p3_`/`p4_`/`p5_`, issue #63 — cache breakpoints,
dual_log composition integrity, strip-wording coverage, all driven over two recorded 223 sessions).
`md/` holds every script's report.

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

### p3_cache_breakpoints_probe.py (311 LOC)

**Purpose:** Issue #63 live-verify, surface 1 — `src/proxy/cache.py` breakpoint placement across
both recorded 223 sessions. Replays every recorded request through a REAL `ProxyAddon()` instance
in chronological order (fresh addon per session, state carries across requests as in a live proxy)
and inspects the actual bytes about to be sent. BP1 (`system[2]`)/BP2 (last non-defer tool)
positional stability; message-level content diffs at common indices, classified
`session_bootstrap` / `tail_draft_edit` / `deep_history_mutation` / `mid_turn_marker` (the flagged
2026-08-07 preserve-guard interaction) after two normalizations that neutralize pure JSON-shape
churn from the cache_control add/remove cycle itself (both discovered empirically — first run: 83
raw diffs, all cache_control-list-vs-collapsed-string shape noise; confirmed the second
normalization needed to apply to EVERY role, not just cache.py's own user-only scope).
**Reads:** `src/logs/dual_log/api_requests_opus_{posts_1786051932,websearch_1786052022}_original.jsonl`.
**Writes:** `md/p3_cache_breakpoints_probe_report.md`.
**Calls out:** `src.proxy.addon` (`ProxyAddon`, `_derive_worker_context`).

---

### p4_dual_log_integrity_probe.py (237 LOC)

**Purpose:** Issue #63 live-verify, surface 2 — composition invariant + schema drift over both
recorded 223 sessions. Part A: calls the REAL `apply_modification_rules` (independent per-request
— the message-passes pipeline carries no cross-request state) and validates its own returned
`all_ops` against the REAL `compose_block` (`src/proxy/diff_engine.py`, same function
`strip_inject_delta.py` uses) — Inv1 (C0 reconstruction) / Inv2 (Cfwd reconstruction) over every
block with recorded ops. Part B: top-level payload keys / system-block shapes / content-block
`type` values observed vs the pipeline's explicitly-named sets; any unmodeled top-level key gets a
direct pass-through verification (not assumed) exploiting the `dict(payload)` shallow-copy pattern
`apply_modification_rules`/`cache.py` both use.
**Reads:** same two `_original.jsonl` files as `p3_`.
**Writes:** `md/p4_dual_log_integrity_probe_report.md`.
**Calls out:** `src.proxy.rules` (`apply_modification_rules`), `src.proxy.diff_engine`
(`compose_block`, `_get_inner_text`).

---

### p5_strip_wordings_probe.py (207 LOC)

**Purpose:** Issue #63 live-verify, surface 3 — bg-launch-ack / bg-completed / TN strip coverage
on 223-era wordings. Part A: fn_map census over the REAL recorded `_stripped`/`_injected`
dual-logs (historical record of what fired at capture time). Part B: unstripped-wording sweep —
replays every request through the CURRENT `apply_modification_rules`, checking whether any known
bg-related marker string (bg-launch-ack ×2 wordings, bg-completed, `<task-notification>`) survives
unstripped into the forwarded payload — scoped to TOP-LEVEL content only via
`payload_helpers._top_level_content_contains`, matching the real passes' own tool_result-exclusion
gate (first run without this scoping: 421/2995 false "survivals", all rag-cli/gh-cli search
results quoting these marker strings as prose in this project's own indexed docs).
**Reads:** same two sessions' `_original.jsonl` + `_stripped.jsonl` + `_injected.jsonl`.
**Writes:** `md/p5_strip_wordings_probe_report.md`.
**Calls out:** `src.proxy.rules` (`apply_modification_rules`), `src.proxy.payload_helpers`
(`_top_level_content_contains`).

---

## Gotchas

**p1's ready-to-paste `model_params` values live in process-docs, not here.** The actual JSON
snippet for `~/.claude/shared-rules/proxy_rules.json` (fable-5/opus-5/sonnet-5, values read from
the live legacy config at write time) is in
`process-docs/native-model-start/2026-08-06_model_params_config.md` — that file is user config
outside the repo and is never edited by any script in this directory.

**p3/p4/p5's two recorded sessions are live/growing — counts are a lower bound, not final.** Same
caveat as `dev/timer-loop`'s p1 corpus note: `src/logs/dual_log/api_requests_opus_{posts,
websearch}_*_original.jsonl` can still be appended to by a concurrent live session while a probe
runs; re-running shifts denominators (observed: 4924 → 4999 composition blocks, 1810 → 1818 marker
occurrences across two runs in the same session) but the CLEAN/FINDING classification itself was
stable.

**p3's cache-content comparison needs TWO shape normalizations, not one.** cache.py's own
`_normalize_user_content_shape` (role='user' only) is production behavior and must be mirrored for
fidelity — but is NOT sufficient alone: `_add_cache_control_to_message` wraps a plain string into
a single-text-block list to attach `cache_control`, for ANY role, and once that position stops
being the BP3/BP4 target the pass regenerating it (e.g. `_apply_role_system_strip` re-emitting a
bare `"."`) has no reason to preserve the wrapper. Comparing content across requests without
collapsing this second shape difference (any role, not just user) produces large false-positive
"content changed" counts — went from 83 → 46 → 10 raw diffs across the two normalization passes
before landing on the real signal.
