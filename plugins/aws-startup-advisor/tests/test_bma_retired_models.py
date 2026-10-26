"""Retired source models are flagged `retired` in the BMA trace, never priced.

Uses a fixed retirement list and inline trace requests, so no sample app is needed.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "skills/bedrock-migration-assessment/scripts/bma-runtime.py"

runtime = types.ModuleType("bma_runtime")
exec(compile(PATH.read_text(encoding="utf-8"), str(PATH), "exec"), runtime.__dict__)

# Fixed list. Each ID is a shutdown row on https://ai.google.dev/gemini-api/docs/deprecations.
EXPECTED_RETIRED = frozenset({
    "gemini-1.5-pro",
    "gemini-2.0-flash-preview-image-generation",
    "gemini-2.5-flash-image-preview",
    "gemini-3-pro-image-preview",
    "imagen-3.0-generate-002",
    "imagen-4.0-generate-001",
    "imagen-4.0-ultra-generate-001",
    "imagen-4.0-fast-generate-001",
    "imagen-4.0-generate-preview-06-06",
    "imagen-4.0-ultra-generate-preview-06-06",
})


def _request(models: list[str], tokens: int | None) -> dict:
    return {
        "schema_version": 2, "mode": "direct", "source_containing": True, "has_ai_profile": True,
        "iac_route_signal": False,
        "source_evidence": [{
            "provider": "google", "source_service": "gemini_api", "gateway": None,
            "models": models, "call_sites": [], "observed_monthly_cost": None,
            "monthly_input_tokens": tokens, "monthly_output_tokens": tokens,
        }],
        "state": {"phases": {}}, "capture_observations": [],
        "user_decisions": {"execute_requested": False, "generate": True,
                           "include_rollback": False, "report_scope": "none"},
    }


def test_retired_list_is_the_fixed_expected_set() -> None:
    assert runtime.RETIRED_MODELS == EXPECTED_RETIRED


def test_retired_and_priced_model_sets_are_disjoint() -> None:
    assert not (set(runtime.MODEL_TARGETS) & set(runtime.RETIRED_MODELS))


@pytest.mark.parametrize("model", sorted(EXPECTED_RETIRED))
def test_retired_model_is_flagged_and_not_priced(model: str) -> None:
    result = runtime.semantic_trace(_request([model], 1_000_000))
    assert result["design_mappings"] == [
        {"source_model": model, "target_model": None, "migration_path": None, "retired": True}
    ]
    assert result["estimate"]["target_monthly"] is None
    assert result["estimate"]["pricing_source"] == "unavailable"


def test_active_model_is_still_priced() -> None:
    result = runtime.semantic_trace(_request(["gpt-4o"], 1_000_000))
    assert result["design_mappings"] == [
        {"source_model": "gpt-4o", "target_model": "openai.gpt-5.6-terra", "migration_path": "direct_api"}
    ]
    assert result["estimate"]["pricing_source"] == "bedrock_cache"
