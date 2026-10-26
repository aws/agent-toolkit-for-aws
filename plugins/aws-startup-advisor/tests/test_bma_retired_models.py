"""Retirement status comes from the lifecycle registry read at run time, never a hand-kept list.

A source model that is not in ai-model-lifecycle.md is `unverified`, is never reported as PASS, and is
labelled `lifecycle unverified`. Its target name stays visible in the design mapping, but its target price
is null. A target is priced only when the source and the target are both listed as Active. No retirement
wording is hardcoded in the runtime. Inline trace requests, so no sample app is needed.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BMA = ROOT / "skills/bedrock-migration-assessment"
PATH = BMA / "scripts/bma-runtime.py"

runtime = types.ModuleType("bma_runtime")
runtime.__dict__["__file__"] = str(PATH)  # the runtime reads the registry beside its own path
exec(compile(PATH.read_text(encoding="utf-8"), str(PATH), "exec"), runtime.__dict__)

REGISTERED_ACTIVE = {
    "anthropic.claude-sonnet-5-5",
    "openai.gpt-5.6-terra",
    "openai.gpt-6-luna",
    "amazon.nova-pro-v1:0",
    "anthropic.claude-haiku-4-5-20251001-v1:0",
    "anthropic.claude-haiku-4-5",
}
UNVERIFIED_NOTE = "retirement status unverified, check provider lifecycle"


def _request(models: list[str], provider: str, service: str, tokens: int | None,
             observed: float | None = None) -> dict:
    return {
        "schema_version": 2, "mode": "direct", "source_containing": True, "has_ai_profile": True,
        "iac_route_signal": False,
        "source_evidence": [{
            "provider": provider, "source_service": service, "gateway": None,
            "models": models, "call_sites": [], "observed_monthly_cost": observed,
            "monthly_input_tokens": tokens, "monthly_output_tokens": tokens,
        }],
        "state": {"phases": {}}, "capture_observations": [],
        "user_decisions": {"execute_requested": False, "generate": True,
                           "include_rollback": False, "report_scope": "none"},
    }


def _trace(model: str, provider: str, service: str, observed: float | None = None) -> dict:
    return runtime.semantic_trace(_request([model], provider, service, 1_000_000, observed))


def _assert_no_hardcoded_retirement_wording(result: dict) -> None:
    text = json.dumps(result)
    assert "PASS" not in text
    assert "retiring" not in text
    assert "2027" not in text


def test_hand_kept_retired_list_is_removed() -> None:
    assert not hasattr(runtime, "RETIRED_MODELS")
    assert not hasattr(runtime, "SOURCE_RETIREMENT_NOTICES")


def test_registry_is_read_at_run_time_and_lists_verified_active_models() -> None:
    assert runtime.registered_active_models(BMA) == REGISTERED_ACTIVE


@pytest.mark.parametrize(
    ("model", "provider", "service"),
    [
        ("gemini-2.5-flash", "google", "gemini_api"),
        ("gemini-3.1-flash-image", "google", "gemini_api"),
    ],
)
def test_unmapped_unregistered_source_is_unverified_labelled_and_unpriced(
        model: str, provider: str, service: str) -> None:
    result = _trace(model, provider, service, observed=118.0)
    assert result["associations"][0]["lifecycle_label"] == "lifecycle unverified"
    assert result["design_mappings"] == [
        {"source_model": model, "target_model": None, "migration_path": None,
         "retirement_status": "unverified", "note": UNVERIFIED_NOTE}
    ]
    assert result["estimate"]["source_monthly"] == 118.0  # observed cost kept, labelled lifecycle unverified
    assert result["estimate"]["source_monthly_basis"] == "observed, not priced from registry"
    assert result["estimate"]["evidence"] == {"observed_source_costs": [118.0]}
    assert result["estimate"]["monthly_delta"] is None
    assert result["estimate"]["target_monthly"] is None
    assert result["estimate"]["pricing_source"] == "unavailable"
    _assert_no_hardcoded_retirement_wording(result)


def test_gpt4o_source_is_unverified_target_name_visible_and_target_unpriced() -> None:
    result = _trace("gpt-4o", "openai", "openai_api", observed=550.0)
    assert result["associations"][0]["lifecycle_label"] == "lifecycle unverified"
    assert result["design_mappings"] == [
        {"source_model": "gpt-4o", "target_model": "openai.gpt-6-luna", "migration_path": "direct_api",
         "retirement_status": "unverified", "note": UNVERIFIED_NOTE}
    ]
    assert result["estimate"]["source_monthly"] == 550.0
    assert result["estimate"]["source_monthly_basis"] == "observed, not priced from registry"
    assert result["estimate"]["monthly_delta"] is None
    assert result["estimate"]["target_monthly"] is None
    assert result["estimate"]["pricing_source"] == "unavailable"
    _assert_no_hardcoded_retirement_wording(result)


def test_claude_haiku_source_keeps_target_name_and_is_unpriced() -> None:
    result = _trace("claude-3-haiku-20240307", "anthropic", "anthropic_api")
    assert result["design_mappings"] == [
        {"source_model": "claude-3-haiku-20240307", "target_model": "anthropic.claude-haiku-4-5-v1:0",
         "migration_path": "anthropic_sdk", "retirement_status": "unverified", "note": UNVERIFIED_NOTE}
    ]
    assert result["estimate"]["target_monthly"] is None
    assert result["estimate"]["pricing_source"] == "unavailable"


def test_claude_3_5_sonnet_row_is_restored_and_its_target_is_unverified_and_unpriced() -> None:
    assert runtime.MODEL_TARGETS["claude-3-5-sonnet-20240620"] == (
        "anthropic.claude-sonnet-4-5-v1:0", "anthropic_sdk", 3.0, 15.0)
    result = _trace("claude-3-5-sonnet-20240620", "anthropic", "anthropic_api")
    assert result["associations"][0]["lifecycle_label"] == "lifecycle unverified"
    assert result["design_mappings"][0]["retirement_status"] == "unverified"
    assert result["design_mappings"][0]["target_model"] == "anthropic.claude-sonnet-4-5-v1:0"
    assert result["estimate"]["target_monthly"] is None
    assert result["estimate"]["pricing_source"] == "unavailable"


def test_unregistered_target_is_unverified_unpriced_and_never_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate a MODEL_TARGETS row whose target is not Active in the registry.
    monkeypatch.setitem(runtime.MODEL_TARGETS, "gpt-4o", ("openai.not-in-registry", "direct_api", 2.2, 13.2))
    result = _trace("gpt-4o", "openai", "openai_api")
    assert result["design_mappings"] == [
        {"source_model": "gpt-4o", "target_model": "openai.not-in-registry", "migration_path": "direct_api",
         "retirement_status": "unverified", "note": UNVERIFIED_NOTE}
    ]
    assert result["estimate"]["target_monthly"] is None
    assert result["estimate"]["pricing_source"] == "unavailable"
    _assert_no_hardcoded_retirement_wording(result)


def test_unregistered_source_with_registered_target_is_unpriced() -> None:
    # gemini-2.5-pro is not in the registry, so its target amazon.nova-pro-v1:0 keeps its name but no price.
    result = _trace("gemini-2.5-pro", "google", "gemini_api")
    assert result["design_mappings"][0]["target_model"] == "amazon.nova-pro-v1:0"
    assert result["design_mappings"][0]["retirement_status"] == "unverified"
    assert result["design_mappings"][0]["note"] == UNVERIFIED_NOTE
    assert result["estimate"]["target_monthly"] is None
    assert result["estimate"]["pricing_source"] == "unavailable"


def test_registered_source_with_registered_target_is_priced(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only when the source is registered as Active does its registered target get a price.
    monkeypatch.setattr(runtime, "registered_active_models", lambda _root: frozenset(REGISTERED_ACTIVE | {"gpt-4o"}))
    result = _trace("gpt-4o", "openai", "openai_api")
    assert result["design_mappings"][0]["retirement_status"] == "active"
    assert "note" not in result["design_mappings"][0]
    assert result["estimate"]["target_monthly"] == 0.66  # 1M x 0.11 + 1M x 0.55
    assert result["estimate"]["pricing_source"] == "bedrock_cache"


def test_fabricated_model_is_still_rejected() -> None:
    with pytest.raises(ValueError, match="trace_source_invalid"):
        _trace("fabricated-model", "google", "gemini_api")


def test_unrecognized_source_model_error_names_the_model_id() -> None:
    # A made-up or unknown provider name is still rejected, and the error says which ID it could not recognize.
    with pytest.raises(ValueError, match=r"trace_source_invalid: source_model_unrecognized: mistral-large-2$"):
        _trace("mistral-large-2", "mistral", "mistral_api")
