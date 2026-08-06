# INFRASTRUCTURE
from .rules_config import _load_config

# FUNCTIONS

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
# Returns (modified_payload, injected_bool).
def _inject_model_override(payload: dict, model_family: str) -> tuple:
    try:
        config = _load_config()
        if "model_params" in config:
            return _inject_model_params(payload, config["model_params"])
        return _inject_legacy_model_override(payload, model_family, config)
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

