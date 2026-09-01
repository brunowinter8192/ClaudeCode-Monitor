# INFRASTRUCTURE
from .rules_config import _load_config

# FUNCTIONS

# Build the 1-entry model_params dict _inject_model_params expects for a single resolved entry —
# shared by the fresh-lookup and fixated-replay paths in _inject_model_override so both call the
# SAME unchanged apply logic. entry falsy (miss, or an explicitly empty {}) yields {} — matches
# _inject_model_params's own "not params -> untouched" miss handling.
def _model_params_dict_for(model_id: str, entry: dict) -> dict:
    return {model_id: entry} if entry else {}


# Dispatch to the per-model 'model_params' path or the legacy family-bucketed path, based on
# config precedence (2026-08-06): the session's model is now chosen at start via
# claude_proxy_start.sh's --fable/--opus flags — the proxy must never force it back, only inject
# thinking/effort/max_tokens for whichever model is actually running.
#
# Precedence: if 'model_params' is PRESENT in the config — presence of the KEY, not truthiness;
# an empty {} still counts as present — it is the ONLY path consulted: payload["model"] is looked
# up EXACTLY (no family bucketing, no normalization) in config["model_params"]; a hit applies
# thinking/effort/max_tokens exactly as the legacy mechanics did (each key independently optional);
# a miss leaves the payload untouched. The legacy 'model_override'/'model_override_worker' sections
# are ignored entirely in this case, even if still present in the config file. If 'model_params' is
# ABSENT, falls back unchanged to the legacy family-bucketed behavior (model_family == "opus" ->
# model_override, "sonnet" -> model_override_worker, INCLUDING the model-field rewrite) — safe
# rollout: an unmigrated config keeps behaving exactly as before this change.
#
# Fixation (2026-09): fixated_model_override is a mutable dict OWNED BY THE CALLER (production:
# ProxyAddon.model_params_fixated, one instance per proxy process — see addon.py), keyed by the
# EXACT model id (payload["model"]). On the first call for a given model id this resolves live
# against _load_config() exactly as before, then snapshots the WHOLE resolved unit — the per-model
# entry dict for the model_params path, or the resolved model_override/model_override_worker
# section dict for the legacy path (never individual fields; thinking/effort/max_tokens/model pin
# together) — under that key. Every SUBSEQUENT call for the SAME model id replays the snapshot by
# calling the SAME UNCHANGED _inject_model_params/_inject_legacy_model_override with a synthesized
# config built from it — _load_config() is not touched again — so a proxy_rules.json edit mid-
# process cannot change an already-running session's injected params, mirroring the sys2/msg0
# session-state fixation in fixation.py (ProxyAddon.fixated) for the same reason (see
# process-docs/cache/cache_rebuild_cases.md Case 3). A genuine miss (successful load, model not in
# the table, or an explicitly enabled=False legacy section) IS pinned too — consistent with "a
# config edit only takes effect in the NEXT process," not a cosmetic difference from a hit. A
# genuine _load_config() exception is NOT pinned — the next request retries live, so a transient
# read failure can't permanently disable injection for the rest of the process. Omitting
# fixated_model_override (default None -> a fresh, discarded dict) makes every call independent
# again, preserving pre-fixation behavior for any 2-arg caller (existing dev probes included).
# Returns (modified_payload, injected_bool).
def _inject_model_override(payload: dict, model_family: str, fixated_model_override: dict = None) -> tuple:
    if fixated_model_override is None:
        fixated_model_override = {}
    model_id = payload.get("model", "")
    if model_id in fixated_model_override:
        snapshot = fixated_model_override[model_id]
        if snapshot["kind"] == "model_params":
            return _inject_model_params(payload, _model_params_dict_for(model_id, snapshot["entry"]))
        return _inject_legacy_model_override(payload, model_family, snapshot["config"])
    try:
        config = _load_config()
        if "model_params" in config:
            entry = config["model_params"].get(model_id) or {}
            fixated_model_override[model_id] = {"kind": "model_params", "entry": entry}
            return _inject_model_params(payload, _model_params_dict_for(model_id, entry))
        if model_family == "opus":
            legacy_config = {"model_override": config.get("model_override", {})}
        elif model_family == "sonnet":
            legacy_config = {"model_override_worker": config.get("model_override_worker", {})}
        else:
            legacy_config = {}
        fixated_model_override[model_id] = {"kind": "legacy", "config": legacy_config}
        return _inject_legacy_model_override(payload, model_family, legacy_config)
    except Exception:
        return payload, False


# New per-model path: exact payload["model"] lookup, NEVER writes the model field itself. A miss
# (model not in the table) or an empty per-model entry both leave the payload untouched.
def _inject_model_params(payload: dict, model_params: dict) -> tuple:
    model_id = payload.get("model", "")
    params = model_params.get(model_id)
    if not params:
        return payload, False
    result = dict(payload)
    if "thinking" in params:
        result["thinking"] = params["thinking"]
    if "effort" in params:
        output_config = dict(result.get("output_config") or {})
        output_config["effort"] = params["effort"]
        result["output_config"] = output_config
    if "max_tokens" in params:
        result["max_tokens"] = params["max_tokens"]
    return result, True


# Legacy family-bucketed path — unchanged mechanics, including the model-field rewrite. Kept
# verbatim (moved, not rewritten) for safe rollout: an unmigrated proxy_rules.json (no
# 'model_params' key) must behave byte-identically to before this change.
def _inject_legacy_model_override(payload: dict, model_family: str, config: dict) -> tuple:
    if model_family == "opus":
        mo_config = config.get("model_override", {})
    elif model_family == "sonnet":
        mo_config = config.get("model_override_worker", {})
    else:
        return payload, False
    if not mo_config.get("enabled", False):
        return payload, False
    result = dict(payload)
    if "model" in mo_config:
        result["model"] = mo_config["model"]
    if "thinking" in mo_config:
        result["thinking"] = mo_config["thinking"]
    if "effort" in mo_config:
        output_config = dict(result.get("output_config") or {})
        output_config["effort"] = mo_config["effort"]
        result["output_config"] = output_config
    if "max_tokens" in mo_config:
        result["max_tokens"] = mo_config["max_tokens"]
    return result, True


# Inject context_management block from proxy_rules.json config if enabled — returns (modified_payload, injected_bool)
def _inject_context_management(payload: dict) -> tuple:
    try:
        config = _load_config()
        cm_config = config.get("context_management", {})
        if not cm_config.get("enabled", False):
            return payload, False

        edits = []

        # clear_thinking MUST be first in edits[] per Anthropic API requirement
        clear_thinking = cm_config.get("clear_thinking", {})
        if clear_thinking.get("enabled", True):
            edits.append({
                "type": "clear_thinking_20251015",
                "keep": {
                    "type": "thinking_turns",
                    "value": clear_thinking.get("keep_thinking_turns", 2),
                },
            })

        clear_tool_uses = cm_config.get("clear_tool_uses", {})
        if clear_tool_uses.get("enabled", True):
            edits.append({
                "type": "clear_tool_uses_20250919",
                "trigger": {
                    "type": "input_tokens",
                    "value": clear_tool_uses.get("trigger_input_tokens", 100000),
                },
                "keep": {
                    "type": "tool_uses",
                    "value": clear_tool_uses.get("keep_tool_uses", 5),
                },
                "clear_at_least": {
                    "type": "input_tokens",
                    "value": clear_tool_uses.get("clear_at_least_tokens", 10000),
                },
            })

        if not edits:
            return payload, False

        result = dict(payload)
        result["context_management"] = {"edits": edits}
        return result, True
    except Exception:
        return payload, False

