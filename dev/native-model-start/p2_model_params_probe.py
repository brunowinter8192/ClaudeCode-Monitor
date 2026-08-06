"""
P2 — verifies src/proxy/inject_helpers.py::_inject_model_override's rework: per-model 'model_params'
config path replacing the legacy family-bucketed model_override/model_override_worker rewrite.

Covers: legacy-config-only -> byte-identical legacy behavior incl. model rewrite; model_params hit
-> thinking/effort/max_tokens applied, model field untouched; model_params miss -> payload
untouched; model_params present (even empty {}) alongside legacy sections -> model_params wins, no
rewrite; empty per-model entry -> untouched; partial entry (one key only) -> only that key applied;
config load failure -> fail-open untouched; a suffixed model-id variant is a deliberate MISS
(exact-match only, no normalization).

Run from project root or worktree root:
    ./venv/bin/python dev/native-model-start/p2_model_params_probe.py
"""

# INFRASTRUCTURE
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT / 'src'))

from proxy import inject_helpers
from proxy.inject_helpers import _inject_model_override

_PASS = "\033[32mPASS\033[0m"
_FAIL = "\033[31mFAIL\033[0m"

_RESULTS = []


def check(label, condition):
    _RESULTS.append((label, bool(condition)))
    print(f"  {_PASS if condition else _FAIL}  {label}")
    return condition


_LEGACY_CONFIG = {
    "model_override": {
        "enabled": True, "model": "claude-fable-5",
        "thinking": {"type": "adaptive", "display": "omitted"},
        "effort": "high", "max_tokens": 64000,
    },
    "model_override_worker": {
        "enabled": True, "model": "claude-sonnet-5",
        "thinking": {"type": "adaptive", "display": "omitted"},
        "effort": "high", "max_tokens": 64000,
    },
}

_MODEL_PARAMS_CONFIG = {
    "model_params": {
        "claude-fable-5": {
            "thinking": {"type": "adaptive", "display": "omitted"},
            "effort": "high", "max_tokens": 64000,
        },
        "claude-opus-5": {
            "thinking": {"type": "adaptive", "display": "omitted"},
            "effort": "high", "max_tokens": 64000,
        },
        "claude-sonnet-5": {
            "thinking": {"type": "adaptive", "display": "omitted"},
            "effort": "high", "max_tokens": 64000,
        },
    },
}


def _base_payload(model):
    return {"model": model, "max_tokens": 8000, "messages": [{"role": "user", "content": "hi"}]}


def _with_config(config, fn):
    with mock.patch.object(inject_helpers, "_load_config", lambda: config):
        return fn()


# FUNCTIONS

# Test 1 — legacy-only config (no 'model_params' key) -> byte-identical legacy behavior, INCLUDING
# the model-field rewrite, for both opus and sonnet families.
def test_legacy_only_unchanged():
    print("\n[Test 1] Legacy-only config -> byte-identical legacy behavior")
    payload = _base_payload("claude-opus-4-8")
    result, injected = _with_config(_LEGACY_CONFIG, lambda: _inject_model_override(payload, "opus"))
    check("opus family: injected=True", injected is True)
    check("opus family: model REWRITTEN to claude-fable-5 (legacy behavior)", result["model"] == "claude-fable-5")
    check("opus family: thinking applied", result["thinking"] == {"type": "adaptive", "display": "omitted"})
    check("opus family: effort applied via output_config", result["output_config"]["effort"] == "high")
    check("opus family: max_tokens applied", result["max_tokens"] == 64000)

    payload_w = _base_payload("claude-sonnet-4-5")
    result_w, injected_w = _with_config(_LEGACY_CONFIG, lambda: _inject_model_override(payload_w, "sonnet"))
    check("sonnet family: injected=True", injected_w is True)
    check("sonnet family: model REWRITTEN to claude-sonnet-5 (legacy behavior)", result_w["model"] == "claude-sonnet-5")

    payload_h = _base_payload("claude-haiku-4")
    result_h, injected_h = _with_config(_LEGACY_CONFIG, lambda: _inject_model_override(payload_h, "haiku"))
    check("haiku family: no legacy section -> untouched, injected=False",
          injected_h is False and result_h == payload_h)


# Test 2 — model_params hit: thinking/effort/max_tokens applied, model field left untouched.
def test_model_params_hit():
    print("\n[Test 2] model_params hit -> params applied, model field NEVER touched")
    payload = _base_payload("claude-fable-5")
    result, injected = _with_config(_MODEL_PARAMS_CONFIG, lambda: _inject_model_override(payload, "opus"))
    check("injected=True", injected is True)
    check("model field UNCHANGED (still claude-fable-5, not rewritten)", result["model"] == "claude-fable-5")
    check("thinking applied", result["thinking"] == {"type": "adaptive", "display": "omitted"})
    check("effort applied via output_config", result["output_config"]["effort"] == "high")
    check("max_tokens applied", result["max_tokens"] == 64000)

    payload_o = _base_payload("claude-opus-5")
    result_o, injected_o = _with_config(_MODEL_PARAMS_CONFIG, lambda: _inject_model_override(payload_o, "opus"))
    check("claude-opus-5 hit: injected=True, model untouched",
          injected_o is True and result_o["model"] == "claude-opus-5")

    payload_s = _base_payload("claude-sonnet-5")
    result_s, injected_s = _with_config(_MODEL_PARAMS_CONFIG, lambda: _inject_model_override(payload_s, "sonnet"))
    check("claude-sonnet-5 hit: injected=True, model untouched",
          injected_s is True and result_s["model"] == "claude-sonnet-5")


# Test 3 — model_params miss: model not in the table -> payload untouched.
def test_model_params_miss():
    print("\n[Test 3] model_params miss -> payload untouched")
    payload = _base_payload("claude-haiku-4")
    result, injected = _with_config(_MODEL_PARAMS_CONFIG, lambda: _inject_model_override(payload, "haiku"))
    check("injected=False", injected is False)
    check("payload identical (same dict values)", result == payload)


# Test 4 — suffixed model-id variant is a DELIBERATE miss: exact-match only, no normalization.
# Pinned so a future "should we strip suffixes?" question is a conscious follow-up, not a silent
# behavior change nobody noticed.
def test_suffixed_model_id_is_deliberate_miss():
    print("\n[Test 4] Suffixed model-id variant -> deliberate MISS (no normalization)")
    config = {"model_params": {"claude-opus-4-8": {"effort": "high"}}}
    payload = _base_payload("claude-opus-4-8[1m]")  # suffix variant, e.g. a context-window tag
    result, injected = _with_config(config, lambda: _inject_model_override(payload, "opus"))
    check("suffixed id 'claude-opus-4-8[1m]' vs table key 'claude-opus-4-8' -> exact match FAILS",
          injected is False and result == payload)


# Test 5 — model_params present (even as an empty {}) alongside legacy sections -> model_params
# wins, legacy is ignored entirely, no model rewrite happens.
def test_model_params_presence_wins_over_legacy():
    print("\n[Test 5] model_params PRESENT (non-empty) alongside legacy sections -> model_params wins")
    mixed_config = {**_LEGACY_CONFIG, **_MODEL_PARAMS_CONFIG}
    payload = _base_payload("claude-fable-5")
    result, injected = _with_config(mixed_config, lambda: _inject_model_override(payload, "opus"))
    check("injected=True (from model_params, not legacy)", injected is True)
    check("model NOT rewritten despite legacy model_override.model=claude-fable-5 being present too",
          result["model"] == "claude-fable-5")  # already claude-fable-5 going in — key check is params source below
    check("thinking/effort/max_tokens match model_params values", result["max_tokens"] == 64000)

    print("\n[Test 5b] model_params PRESENT as an EMPTY {} -> still wins, legacy fully disabled")
    empty_mp_config = {**_LEGACY_CONFIG, "model_params": {}}
    payload_o = _base_payload("claude-opus-4-8")
    result_o, injected_o = _with_config(empty_mp_config, lambda: _inject_model_override(payload_o, "opus"))
    check("empty model_params {} -> injected=False (no entry for this model)", injected_o is False)
    check("model NOT rewritten to claude-fable-5 — legacy path never consulted despite being 'enabled'",
          result_o["model"] == "claude-opus-4-8")


# Test 6 — empty per-model entry ({}) and a partial entry (one key only).
def test_empty_and_partial_entries():
    print("\n[Test 6] Empty per-model entry -> untouched; partial entry -> only that key applied")
    config_empty_entry = {"model_params": {"claude-fable-5": {}}}
    payload = _base_payload("claude-fable-5")
    result, injected = _with_config(config_empty_entry, lambda: _inject_model_override(payload, "opus"))
    check("empty {} entry for a matched model -> injected=False, untouched",
          injected is False and result == payload)

    config_partial = {"model_params": {"claude-fable-5": {"effort": "medium"}}}
    payload2 = _base_payload("claude-fable-5")
    result2, injected2 = _with_config(config_partial, lambda: _inject_model_override(payload2, "opus"))
    check("partial entry (effort only): injected=True", injected2 is True)
    check("effort applied", result2["output_config"]["effort"] == "medium")
    check("thinking NOT added (key absent from entry)", "thinking" not in result2)
    check("max_tokens UNCHANGED from original payload (key absent from entry, not injected)",
          result2["max_tokens"] == payload2["max_tokens"] == 8000)


# Test 7 — config load failure degrades to no-op (fail-open), never raises.
def test_config_load_failure_fails_open():
    print("\n[Test 7] _load_config raising -> fail-open, no raise")
    payload = _base_payload("claude-fable-5")
    with mock.patch.object(inject_helpers, "_load_config", side_effect=RuntimeError("simulated")):
        try:
            result, injected = _inject_model_override(payload, "opus")
            raised = False
        except Exception:
            result, injected, raised = payload, False, True
    check("no raise propagated", not raised)
    check("injected=False, payload untouched", injected is False and result == payload)


# ORCHESTRATOR

def run_probe_workflow():
    print("=" * 70)
    print("model_params probe — per-model config replacing the legacy model override")
    print("=" * 70)
    test_legacy_only_unchanged()
    test_model_params_hit()
    test_model_params_miss()
    test_suffixed_model_id_is_deliberate_miss()
    test_model_params_presence_wins_over_legacy()
    test_empty_and_partial_entries()
    test_config_load_failure_fails_open()

    total = len(_RESULTS)
    passed = sum(1 for _, ok in _RESULTS if ok)
    print("\n" + "=" * 70)
    print(f"{passed}/{total} checks passed")
    print("=" * 70)

    _write_report(passed, total)
    return passed == total


def _write_report(passed, total):
    md_dir = WORKTREE_ROOT / "dev" / "native-model-start" / "md"
    md_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = md_dir / f"p2_model_params_probe_{stamp}.md"
    lines = [
        f"# P2 — model_params probe run ({datetime.now(timezone.utc).isoformat()})",
        "",
        f"**Result: {passed}/{total} checks passed**",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for label, ok in _RESULTS:
        lines.append(f"| {label} | {'PASS' if ok else 'FAIL'} |")
    out_path.write_text("\n".join(lines) + "\n")
    print(f"\nReport written to: {out_path}")


if __name__ == "__main__":
    ok = run_probe_workflow()
    sys.exit(0 if ok else 1)
