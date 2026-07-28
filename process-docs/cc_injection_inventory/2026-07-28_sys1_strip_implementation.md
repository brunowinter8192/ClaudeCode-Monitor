# sys[1] strip — acting on the inventory's first Strip Candidate, 2026-07-28

## Why this task

The initial inventory audit (`2026-07-28_initial_audit.md`, this area) surfaced 3 UNCLASSIFIED
strip candidates. `system[1]` — CC's constant `"You are Claude Code, Anthropic's official CLI
for Claude."` (57 chars) — was one of them: never touched by any proxy function, byte-identical
across every request. A later corpus check (5 sessions, 935 request entries) confirmed the same
finding at larger scale: still 57 chars, still byte-identical in every request of every session,
opus and worker families alike. User decision: strip it, since `system[2]` (fully replaced with
our own injected rules) already establishes the agent's role, making the line redundant.

Explicitly kept out of scope, both reviewed and deliberately preserved: `system[0]` (the
`x-anthropic-billing-header` line — CC rewrites parts of this string post-serialization;
touching it risks breaking prompt caching) and CC's `[Image: source: <path>]` attachment
notation (the path is actionable — lets a later Read reach the image).

## Mechanism decision: content replacement, not block removal

`system[2]`/`system[3]` were already handled by content replacement (`text` → the injected
rules / `"."`), never by removing the block from the array. Followed the same pattern for
`system[1]`: `_apply_system_passes` (`src/proxy/rules.py`) now replaces `system[1]`'s `text`
with `"."` when it exact-matches the boilerplate string, leaving the block itself in place.

Reason this matters beyond consistency: `strip_inject_delta.py` logs `counts.system =
len(fwd_sys)` per request, consumed by the dual-log delta reconstruction, and multiple modules
address system blocks by fixed index — `cache.py`'s BP1 cache anchor reads `system[2]`,
`fixation.py` reads `system[2]`, `_SYS_FN` in `strip_inject_delta.py` is index-keyed. Removing
`system[1]` would shift every later index down by one (`system[2]`→`system[1]`,
`system[3]`→`system[2]`), silently breaking all of the above. Content replacement changes the
array length not at all — `counts.system` and every fixed-index consumer are unaffected by
construction, not by additional guards.

## Guard: exact content match, not index alone

`_SYS1_BOILERPLATE_TEXT` is compared against `system[1].text` verbatim before any mutation — an
unrecognized value at index 1 (a future CC version changing this line) is left untouched, not
nuked by position. Verified with a synthetic payload carrying different sys[1] text: passed
through byte-for-byte, `stripped_sys1_boilerplate` absent from `modifications[]`. The guard is
also naturally idempotent — once reduced to `"."`, it no longer matches the expected text, so
re-running the pipeline on an already-stripped payload is a no-op without a separate check.

## Verification (pure-function + integration, no live-traffic claim)

Ran the real `apply_modification_rules` against a captured payload from
`src/logs/dual_log/api_requests_opus_trading_..._original.jsonl`:

- Before: `sys[1]` = the 57-char boilerplate. After: `sys[1]` = `"."`.
- `modifications[]` included `stripped_sys1_boilerplate` alongside the pre-existing
  `replaced_system_prompt` (sys[2] still fully replaced, now 52,312 chars of injected rules),
  `stripped_session_guidance`/`stripped_git_status` (sys[3] unchanged behavior), and
  `stripped_role_system_msg` (unrelated message-level pass, unaffected).
- `sys[0]` (billing header) byte-identical before/after — untouched, as required.
- `counts.system`: 4 before, 4 after.

Broader spot-check: iterated 346 real entries across 3 project sessions (the 3.9GB session
sample-capped at 60 entries for runtime) calling `apply_modification_rules` directly — 346/346
fired where `sys[1]` matched the expected text, 0 guard misfires, 3 entries skipped for having
fewer than 2 system blocks (haiku title-generation requests, no system array at all).

Dual-log attribution path also exercised directly: built a real stripped/injected delta pair via
`strip_inject_delta._build_stripped_injected_deltas` on the same orig/modified payloads —
`system_delta["1"]` correctly holds the stripped text, `fn_map["sys.1"] = "_apply_system_passes"`
resolves correctly (added an explicit `1: '_apply_system_passes'` entry to `_SYS_FN` for
consistency with the existing, equally-redundant explicit entry at index 2 — the `.get(idx,
"_apply_system_passes")` fallback would have resolved both correctly either way).

Not verified, and explicitly not claimed: live proxy / end-to-end traffic — the live proxy is a
frozen per-session snapshot from inside a worktree, so this can only be pure-function and
integration-level verification against captured payloads.

## `strip_vocab.py` — checked, no change needed

`RULES` is exclusively consumed by `attribute_chunk()` for MESSAGE-level `stripped_msg_removed`
chunk attribution (`_process_messages_section` in `strip_inject_delta.py`). None of the existing
system-level structural mods — `replaced_system_prompt`, `stripped_session_guidance`,
`stripped_git_status`, `normalized_worktree_path` — have ever had an entry there; system-level
attribution runs entirely through `_SYS_FN`, which was updated instead. Confirmed this by
tracing both call sites before deciding, not by pattern-matching the prior entries.

## `render_sections.py` (`src/proxy_display/`) — read, not changed

The primary, dual-log-backed rendering path (`use_dual = '_stripped_spans' in entry`) computes
its yellow-highlight badge generically per system index from `entry['_stripped_spans']['system']`
— no per-index hardcoding — so `sys[1]` highlights correctly with zero code change, confirmed
indirectly via the `fn_map`/`system_delta` check above. A separate legacy fallback path (used
only for entries that predate dual-log span capture, `is_old_stripped`) hardcodes its highlight
check to `bidx == 2` and `bidx == 3` and will not highlight `sys[1]`. Left as is: no entry
predating this session's code change can ever carry `stripped_sys1_boilerplate` in its stored
`mods` list (the mod did not exist when they were captured), so this is a dead branch for the new
mod, not a functional regression — nothing is actually broken by leaving it untouched.

## Files touched

`src/proxy/rules.py` (new `_SYS1_BOILERPLATE_TEXT` constant, guarded strip added to
`_apply_system_passes`), `src/proxy/strip_inject_delta.py` (`_SYS_FN[1]` entry). No other files
changed — no `strip_vocab.py` entry, no `render_sections.py` change, no new strip rules beyond
this one.
