"""Retirement status comes from the lifecycle registry read at run time, never a hand-kept list.

A source model that is not in ai-model-lifecycle.md is labelled `lifecycle unverified`, its baseline is
"observed, not priced from registry", and no monthly delta is built on it. A Bedrock target is priced when
the target itself is listed as Active; its retirement_status comes from its own registry row. An
unregistered target keeps its name but gets no price and carries the retirement-unverified note. No
retirement wording is hardcoded in the runtime. Inline trace requests, so no sample app is needed.
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


def test_gpt4o_unverified_source_with_active_target_is_priced_without_delta() -> None:
    # The source is not in the registry, so its lifecycle is unverified and no delta is built. The target
    # openai.gpt-6-luna is Active in the registry, so it is priced at the US Geo rate (0.11 / 0.55).
    result = _trace("gpt-4o", "openai", "openai_api", observed=550.0)
    assert result["associations"][0]["lifecycle_label"] == "lifecycle unverified"
    assert result["design_mappings"] == [
        {"source_model": "gpt-4o", "target_model": "openai.gpt-6-luna", "migration_path": "direct_api",
         "retirement_status": "active"}
    ]
    assert result["estimate"]["source_monthly"] == 550.0
    assert result["estimate"]["source_monthly_basis"] == "observed, not priced from registry"
    assert result["estimate"]["monthly_delta"] is None
    assert result["estimate"]["target_monthly"] == 0.66  # 1M x 0.11 + 1M x 0.55
    assert result["estimate"]["pricing_source"] == "bedrock_cache"
    _assert_no_hardcoded_retirement_wording(result)


def test_claude_haiku_source_maps_to_documented_haiku_4_5_id_and_is_priced() -> None:
    # decisions.md entry 8: the Haiku target is the documented anthropic.claude-haiku-4-5-20251001-v1:0
    # (Active in the registry), keeping its existing 0.25 / 1.25 price.
    assert runtime.MODEL_TARGETS["claude-3-haiku-20240307"] == (
        "anthropic.claude-haiku-4-5-20251001-v1:0", "anthropic_sdk", 0.25, 1.25)
    result = _trace("claude-3-haiku-20240307", "anthropic", "anthropic_api")
    assert result["associations"][0]["lifecycle_label"] == "lifecycle unverified"
    assert result["design_mappings"] == [
        {"source_model": "claude-3-haiku-20240307", "target_model": "anthropic.claude-haiku-4-5-20251001-v1:0",
         "migration_path": "anthropic_sdk", "retirement_status": "active"}
    ]
    assert result["estimate"]["target_monthly"] == 1.5  # 1M x 0.25 + 1M x 1.25
    assert result["estimate"]["monthly_delta"] is None
    assert result["estimate"]["pricing_source"] == "bedrock_cache"


def test_legacy_sonnet_rows_are_gone_and_claude_3_5_sonnet_source_is_unmapped() -> None:
    # decisions.md entries 6 and 8: no Sonnet 3.5 migration row, and anthropic.claude-sonnet-4-5 (Legacy) is
    # not a target. A claude-3-5-sonnet source stays visible as a real model, unmapped and unpriced.
    assert "claude-3-5-sonnet-20240620" not in runtime.MODEL_TARGETS
    assert not any(target.startswith("anthropic.claude-sonnet-4-5") for target, *_ in runtime.MODEL_TARGETS.values())
    result = _trace("claude-3-5-sonnet-20240620", "anthropic", "anthropic_api")
    assert result["associations"][0]["lifecycle_label"] == "lifecycle unverified"
    assert result["design_mappings"] == [
        {"source_model": "claude-3-5-sonnet-20240620", "target_model": None, "migration_path": None,
         "retirement_status": "unverified", "note": UNVERIFIED_NOTE}
    ]
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


def test_unregistered_source_with_registered_target_is_priced_without_delta() -> None:
    # gemini-2.5-pro is not in the registry (source lifecycle unverified, no delta); its target
    # amazon.nova-pro-v1:0 is Active, so the target is priced.
    result = _trace("gemini-2.5-pro", "google", "gemini_api", observed=200.0)
    assert result["associations"][0]["lifecycle_label"] == "lifecycle unverified"
    assert result["design_mappings"][0]["target_model"] == "amazon.nova-pro-v1:0"
    assert result["design_mappings"][0]["retirement_status"] == "active"
    assert "note" not in result["design_mappings"][0]
    assert result["estimate"]["source_monthly_basis"] == "observed, not priced from registry"
    assert result["estimate"]["monthly_delta"] is None
    assert result["estimate"]["target_monthly"] == 4.0  # 1M x 0.8 + 1M x 3.2
    assert result["estimate"]["pricing_source"] == "bedrock_cache"


def test_registered_source_with_registered_target_is_priced_with_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    # A registered source has a verified baseline, so the delta against its priced target is computed.
    monkeypatch.setattr(runtime, "registered_active_models", lambda _root: frozenset(REGISTERED_ACTIVE | {"gpt-4o"}))
    result = _trace("gpt-4o", "openai", "openai_api", observed=550.0)
    assert result["associations"][0]["lifecycle_label"] == "lifecycle registered"
    assert result["design_mappings"][0]["retirement_status"] == "active"
    assert "note" not in result["design_mappings"][0]
    assert result["estimate"]["source_monthly_basis"] == "observed"
    assert result["estimate"]["target_monthly"] == 0.66  # 1M x 0.11 + 1M x 0.55
    assert result["estimate"]["monthly_delta"] == -549.34
    assert result["estimate"]["pricing_source"] == "bedrock_cache"


def test_fabricated_model_is_still_rejected() -> None:
    with pytest.raises(ValueError, match="trace_source_invalid"):
        _trace("fabricated-model", "google", "gemini_api")


def test_unrecognized_source_model_error_names_the_model_id() -> None:
    # A made-up or unknown provider name is still rejected, and the error says which ID it could not recognize.
    with pytest.raises(ValueError, match=r"trace_source_invalid: source_model_unrecognized: mistral-large-2$"):
        _trace("mistral-large-2", "mistral", "mistral_api")
