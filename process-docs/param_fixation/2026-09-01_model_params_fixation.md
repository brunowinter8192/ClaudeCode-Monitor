# Fixating model_params per proxy process at first request

2026-09-01

## Scope

`_inject_model_override` (`src/proxy/inject_helpers.py`) reads `proxy_rules.json` live on every
request via `rules_config._load_config()`'s mtime-cached loader. A Models-tab Apply
(`process-docs/model_selector/`) mid-session therefore changed `effort`/`max_tokens`/`thinking`
(and, on the legacy path, `model`) of an ALREADY RUNNING proxy process the moment the file changed
— unlike sys[2] and msg[0]'s project-rules block, which have been protected against exactly this
class of mid-session file edit since `ProxyAddon.fixated` (`src/proxy/fixation.py`, commit
96e5c98, documented in `process-docs/cache/` Case 3). This closes the same gap for model params:
the params a proxy process starts with now stay pinned for that process's lifetime; a
`proxy_rules.json` edit only affects proxies started afterward.

## Design — fixation lives in inject_helpers.py, not fixation.py

`fixation.py`'s `_capture_fixation`/`_apply_fixation` freeze PAYLOAD CONTENT (sys[2] text, msg[0]'s
project-rules block) — a generic "extract a block from the outgoing payload, replace it on later
requests" shape. Model-params fixation freezes a CONFIG-DERIVED DECISION instead (which
`model_params` entry, or which legacy section, applies) — it needs the config, not the payload, at
capture time, and reading `fixation.py`'s docstring literally ("Freeze sys[2] content and msg[0]
project-rules block") made broadening its scope there a worse fit than keeping the whole feature —
resolution AND fixation — inside `inject_helpers.py`, the module that already owns 100% of the
model-override dispatch logic. The task's framing ("mirrors the established session-state
fixation") was read as an analogy justifying the *approach* (freeze-at-first-request,
apply-thereafter, on a `ProxyAddon`-owned dict), not a literal instruction to add code to
`fixation.py` — confirmed acceptable in the Go instruction. `fixation.py` itself is untouched by
this milestone.

## Design — zero changes to `_inject_model_params`/`_inject_legacy_model_override`

Both apply functions keep their exact pre-existing bodies. The fixation-aware dispatcher
(`_inject_model_override`) wraps them: on the first call for a given EXACT model id, it resolves
live against `_load_config()` exactly as before, snapshots the WHOLE resolved unit (the per-model
`entry` dict for the `model_params` path, or the resolved `{"model_override": {...}}` /
`{"model_override_worker": {...}}` section for the legacy path — never individual fields;
thinking/effort/max_tokens/model pin together as one unit) under that model id, and returns the
result. Every subsequent call for the same model id replays the snapshot by calling the SAME
unchanged apply functions with a synthesized 1-entry config built from the snapshot
(`_model_params_dict_for`) — `_load_config()` is never touched again for that model id. Fresh and
replay paths are therefore byte-identical by shared code, not by two parallel implementations kept
in sync by hand — the strongest form of the "legacy path stays byte-identical" constraint, since it
holds by construction rather than by test coverage alone.

**Backward compatibility:** `_inject_model_override(payload, model_family,
fixated_model_override=None)`. Omitting the third argument creates a fresh, discarded dict inside
the call, so every 2-arg call is independent — exactly the pre-fixation behavior. This is why
`dev/native-model-start/p2_model_params_probe.py`'s original 7 test groups (30 checks) needed zero
changes to keep passing: they all call the function with 2 positional args. Production
(`src/proxy/addon.py`) is the only caller that passes a persistent dict — a new
`ProxyAddon.model_params_fixated: Dict[str, dict]` field, threaded through
`_run_post_fixation_pipeline`'s existing call site. Being a plain instance field, it resets
whenever a fresh `ProxyAddon()` is constructed — i.e. on mitmproxy hot-reload — identically to how
`self.fixated` already resets (see `src/proxy/DOCS.md`'s State section), with no extra code needed
for that property.

## Design decision — pin on a genuine miss too, but not on a load exception

A successful `_load_config()` read that resolves to a miss (model not in the `model_params` table,
or a legacy section with `enabled: false`) IS pinned, same as a hit — consistent with the
fixation's whole rationale ("a config edit only takes effect in the NEXT process"): a later config
edit adding that model's entry mid-process must not retroactively apply, exactly as it wouldn't
for sys[2]/msg[0]. A genuine `_load_config()` EXCEPTION (a transient read race, not a real
decision) is deliberately NOT pinned — the dict simply gets no entry for that model id, so the next
request retries live. Without this split, a single unlucky first-request race (file mid-write, a
permissions hiccup) would permanently disable model-params injection for the rest of the process,
which is a materially worse failure mode than the one-off cost of an extra file read.

## Key granularity — exact model id, not model_family

`self.fixated` (sys2/msg0) is keyed by `model_family` (`opus`/`sonnet`/`haiku`), matching its own
per-family capture semantics. `model_params_fixated` is keyed by the EXACT model id
(`payload["model"]`) instead, matching `_inject_model_params`'s own exact-ID lookup semantics — the
task's "model lookup semantics (exact ID, no normalization) stay unchanged" constraint. In
practice a given proxy process serves one model for its whole lifetime (chosen at session start via
`claude_proxy_start.sh`'s `--fable`/`--opus`/config precedence, `process-docs/native-model-start/`),
so the two key choices are usually equivalent in this codebase; keying by exact id is the more
defensively correct choice and costs nothing extra (the dict stays bounded by however many distinct
model ids one process genuinely sees — typically 1, plus a haiku sidecar id).

## Verification

`dev/native-model-start/p2_model_params_probe.py` extended in place (dev/ convention: a growing
assertion suite for an already-owned module, not a new file per fix) from 7 test groups / 30
checks to 12 groups / 55 checks, all against `mock.patch.object(inject_helpers, "_load_config",
...)`, never the real `~/.claude/shared-rules/proxy_rules.json`. New groups: (Test 8) a config
change against the SAME fixated dict after the first request is ignored; (Test 9) a FRESH dict
picks up the changed config; (Test 10) the legacy path pins the same way and stays byte-identical
to the unfixated Test 1 result on the pinning call, including surviving the legacy section being
disabled in a later read; (Test 11) a genuine miss pins "no injection" too; (Test 12) a genuine
load-exception on the first call does not pin, and the next call retries live and succeeds.
55/55 passed. `dev/proxy/test_strip_fix.py` (unrelated strip-family regression suite, 207/207) was
re-run as the required "every other pipeline step stays untouched" gate — unaffected, as expected,
since this milestone's diff is confined to `inject_helpers.py`'s model-override dispatcher and
`addon.py`'s threading of one new field.

Not verified here: an actual mitmdump load test against a real `proxy_rules.json` edited mid-proxy-
process — the mandatory post-merge load test (`src/proxy/DOCS.md` Gotchas) covers import/startup
correctness but not this specific pinning behavior live; that needs a user check after merge (start
a proxy, note the injected params for a request, edit `proxy_rules.json`'s `model_params` for the
running model, confirm the NEXT request in the same process still shows the old values).

## Cross-reference

See `process-docs/model_selector/` for the Models-tab Apply flow whose live edits this fixation now
insulates running sessions from. See `process-docs/cache/` for the cache-rebuild case log (Case 3)
that established the sys2/msg0 fixation precedent this milestone mirrors, and for the
`ProxyAddon.fixated` mechanism itself.
