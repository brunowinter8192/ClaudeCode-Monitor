# 2026-08-29 — system2 rule selection re-keyed from model family to session role

Third consumer of the model/role decoupling to be corrected in this area, after the launcher and
worker model readers and after the `model_override` / `model_override_worker` removal. Same root
cause each time: a consumer that inferred the session's ROLE from its model FAMILY, an inference
that stopped holding the moment the menubar Models tab began assigning `main` and `worker` models
independently.

## The defect

`src/proxy/rules_config.py::_load_system2_rules` mapped family to config key with one line:

```python
model_key = "opus" if model_family == "opus" else "worker"
```

A worker running an opus-family model was therefore classified as an orchestrator session and had
the orchestrator rule files injected into `system[2]` — the exact inversion the model selector
makes reachable, since nothing stops the Models tab from putting an opus-family model in the
`worker` slot. The reverse also held: a main session on a sonnet-family model received worker
rules.

## Why the role signal needed no new plumbing

The role already travelled end-to-end and stopped one function short of its consumer.
`_worker_proxy_setup` in the iterative-dev plugin's `tmux_spawn.sh` starts every worker's
`mitmdump` with `PROXY_LOG_ID=worker_<session_id>_<name>_<ts>`; `claude_proxy_start.sh` gives main
sessions `opus_<project>_<ts>`. `addon._derive_worker_context` turns that into `"worker:<name>"`
or `"main"` once per process, and `rules.apply_modification_rules` had received it as its
`worker_context` parameter since 2026-08-06 — using it only to pick the bg-launch-ack wording. The
whole change is forwarding that existing argument one level down and testing a different predicate
on it:

```python
role_key = "worker" if (worker_context or "").startswith("worker:") else "main"
```

Two predicates now read the same string: rule selection tests the `worker:` prefix, the launch-ack
wording tests `== "main"`. The asymmetry is deliberate — a caller passing neither value, or `None`,
must land on main rules with the unchanged default wording.

## Spawn-path coverage

Traced rather than assumed, because a single uncovered spawn path would silently give a worker
main rules. All three worker entry points — `spawn_claude_worker`, `spawn_claude_worker_from_file`
(which delegates to it), and `worker_revive` — funnel through the one `_worker_proxy_setup` helper
that sets the env var on the `mitmdump` invocation itself. Cross-project spawns are covered too:
that helper strips the `/.claude/worktrees/<name>` suffix only to locate the marker file and port,
never touching the log-id prefix. On the main side, both `PROXY_LOG_ID` (`opus_` prefix) and the
`PROXY_SESSION_ID` fallback (an md5 hex string) are structurally incapable of matching `worker_`.

Boundary case, pre-existing and untouched: with no `/tmp/.monitor_cc_proxy_<sid>` marker,
`_worker_proxy_setup` returns early and the worker runs with no proxy at all, hence no rules from
any key.

## Decisions

**Config key renamed `opus` → `main`, no fallback.** The key was named after the family it was
selected by; keeping that name while selecting by role would leave the same wrong mental model in
the file that caused the defect in the code. A legacy `opus` fallback was deliberately not added —
the rename is a one-shot migration of a single out-of-repo config file plus a directory, and a
fallback would let a half-migrated config keep working silently, which is the failure mode worth
having loud. The `~/.claude/shared-rules/opus/` → `main/` move and the `proxy_rules.json` edit are
user-side and happen after the merge; the proxy re-reads that file by mtime, so no restart is
involved.

**Haiku short-circuit moved above the role handling.** Behaviorally identical — everything it could
have preceded also returned `""` — but haiku sidecar requests occur inside main sessions, and the
short-circuit returning before a role is ever computed is what makes it obvious they cannot start
receiving main rules.

**`projects` / `exclusive` / `exclusive_model_families` left untouched.** No structural conflict:
the `exclusive` branch bypasses the global and role lists identically to how it bypassed the global
and model lists, and `exclusive_model_families` gates on family within a project path, an axis
orthogonal to role. The live config carries `projects: {}`.

## Fixation is unaffected

Checked because `sys[2]` is frozen per model family after the first request, which would be a real
conflict if one freeze map could ever see two roles. It cannot: `ProxyAddon.fixated` is an instance
attribute and `self._worker_context` is derived once in `__init__` from the process environment,
and every session runs its own `mitmdump` process — the main one from `claude_proxy_start.sh`, each
worker one against its own live-copy addon directory. Role is therefore a per-process constant, so
the family-keyed freeze only ever stores the text produced under that process's single role.

## Verification

26 synthetic checks in `dev/proxy/test_role_keyed_rules.py`, all passing: role selection across
`main` / `worker:<name>` / `""` / omitted / `None` / non-prefixed junk; the regression itself in
both directions (opus-family worker gets worker files, sonnet-family main gets main files); the
haiku short-circuit under both roles; four degraded configs (missing `main` key, missing `worker`
key, missing `system2_rules` entirely, a listed rule file absent from disk) each degrading to
global-only or empty rather than crashing; proof the legacy `opus` key is never read; and five
end-to-end cases asserting the selected text in `system[2]` through the real
`apply_modification_rules`. The suite repoints the module's `_SHARED_RULES_DIR` /
`_PROXY_RULES_CONFIG` globals at a temp tree and clears both mtime caches, so it never reads the
real shared-rules directory. It imports the live modules via the `src`-on-`sys.path` form, because
the `block_dev_imports_src` hook rejects `from src.` outside a `tests/` directory.

Existing suites unchanged at 207/207 (`dev/proxy/test_strip_fix.py`) and 12/12
(`dev/proxy_dual_log/test_composition_invariant.py`). All callers of both functions were grepped:
only `addon.py` passes a real context; every dev probe and replay tool resolves to main, including
`tt_delta_skip_replay.py`, whose explicit `None` argument is why the guard is `(worker_context or "")`
rather than a bare `.startswith`.

Not verified: a live worker spawn against the migrated config. Until the `opus/` → `main/` rename
lands, a main session gets global-only rules — the degraded case the suite covers deliberately.

Unrelated pre-existing breakage found while running the suites: `dev/proxy/test_schema_check.py`
fails at import because `_check_payload_schema` no longer exists in `addon.py`. Confirmed present
before this work and left alone.

## Cross-reference

See `process-docs/model_selector/` for the milestones that introduced the independent main/worker
model selection this change follows from.
