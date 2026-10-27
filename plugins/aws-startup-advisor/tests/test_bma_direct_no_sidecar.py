"""Direct mode on a #415 profile with no sidecar file (Render option 1: no legacy profile, no sidecar).

The engine must not error on the missing sidecar, must route by provider and price registered targets from
the pricing-cache registry, and must report every sidecar-only field as not available rather than inferring it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BMA_ROOT = ROOT / "skills/bedrock-migration-assessment"
RUNTIME_PATH = BMA_ROOT / "scripts/bma-runtime.py"
runtime = types.ModuleType("bma_runtime_direct_no_sidecar")
runtime.__dict__["__file__"] = str(RUNTIME_PATH)  # the runtime reads the pricing-cache registry beside its own path
exec(compile(RUNTIME_PATH.read_text(encoding="utf-8"), str(RUNTIME_PATH), "exec"), runtime.__dict__)

BMA = "bedrock-migration-assessment"
SIDECAR_FIELDS = (
    "workloads", "agentic_profile", "tool_manifest", "observed_costs",
    "integration_context", "infrastructure", "model_context", "profile_origin",
)
INPUT_TOKENS, OUTPUT_TOKENS = 1_000_000, 500_000


def _source(provider: str, source_service: str, family: str, model: str, detail: str) -> dict:
    return {
        "provider": provider, "source_service": source_service, "model_families": [family],
        "model_evidence": "observed", "models": [model],
        "model_observations": [{
            "normalized_model": model, "raw_model": model, "model_family": family,
            "evidence": [{"provenance": "code", "confidence": "high", "detail": detail}],
        }],
    }


# Three sources whose targets are all Active in references/vendored/ai/bedrock-pricing-cache.md.
PROFILE_415 = {
    "schema_version": "1.0",
    "ai_sources": [
        _source("google", "vertex_ai", "gemini", "gemini-2.5-pro", "src/gemini.py:4"),
        _source("openai", "openai_api", "gpt", "gpt-4o", "src/openai_client.py:9"),
        _source("anthropic", "anthropic_api", "claude", "claude-3-haiku-20240307", "src/anthropic_client.py:12"),
    ],
    "gateways": [],
}


def _validate_cli(profile: Path, sidecar: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_PATH), "validate-profile", "--profile", str(profile), "--sidecar", str(sidecar)],
        cwd=ROOT, text=True, capture_output=True,
    )


def _direct_write(run: Path, phase: str, path: str, payload: dict) -> dict:
    return runtime.execute_contract({
        "schema_version": 1, "mode": "direct", "scenario": "render-direct", "run_dir": str(run),
        "state": {"phases": {}},
        "writes": [{"phase": phase, "path": path, "payload": payload, "logical_owner": BMA}],
    })


def _trace_rows(profile: dict) -> list[dict]:
    return [{
        "provider": source["provider"], "source_service": source["source_service"], "gateway": None,
        "models": list(source["models"]), "call_sites": [],
        "observed_monthly_cost": None,  # no sidecar: observed cost is not available, never guessed
        "monthly_input_tokens": INPUT_TOKENS, "monthly_output_tokens": OUTPUT_TOKENS,
    } for source in profile["ai_sources"]]


def test_direct_415_only_input_without_sidecar_runs_discover_to_estimate(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    profile_path = run / "ai-workload-profile.json"
    sidecar_path = run / "ai-workload-sidecar.json"
    # Discover: only the #415 profile is written. No sidecar exists and none is synthesized.
    result = _direct_write(run, "discover", "ai-workload-profile.json", PROFILE_415)
    assert [(op["path"], op["logical_owner"]) for op in result["operations"]] == [("ai-workload-profile.json", BMA)]
    assert not sidecar_path.exists()
    gate = _validate_cli(profile_path, sidecar_path)
    assert gate.returncode == 0, gate.stderr
    output = json.loads(gate.stdout)
    assert output["ok"] is True and output["ai_sources"] == 3
    assert output["sidecar"] == "absent"
    not_available = {field: "not_available" for field in SIDECAR_FIELDS}
    assert output["sidecar_fields"] == not_available
    assert runtime.sidecar_availability(None) == not_available
    assert not sidecar_path.exists()
    # Clarify: an empty workload list is valid; token volumes come from the user, not from a sidecar.
    clarify = runtime.validate_clarify_result({
        "schema_version": 1, "kind": "BMA_AI_CLARIFY_RESULT",
        "constraints": {"ai_token_volume": {"monthly_input_tokens": INPUT_TOKENS, "monthly_output_tokens": OUTPUT_TOKENS}},
        "workloads": [], "question_metadata": {},
    })
    assert clarify["workloads"] == []
    _direct_write(run, "clarify", "preferences.json", {
        "workloads": [], "ai_token_volume": {"monthly_input_tokens": INPUT_TOKENS, "monthly_output_tokens": OUTPUT_TOKENS},
    })
    assert (run / "preferences.json").exists()
    # Design: routing is by provider/source_service from the profile alone; every target is registry Active.
    trace = runtime.semantic_trace({
        "schema_version": 2, "mode": "direct", "source_containing": True, "has_ai_profile": True,
        "iac_route_signal": False, "source_evidence": _trace_rows(PROFILE_415), "state": {"phases": {}},
        "capture_observations": [],
        "user_decisions": {"execute_requested": False, "generate": False, "include_rollback": False, "report_scope": "none"},
    })
    assert trace["route"]["ai_route_active"] is True
    mappings = {row["source_model"]: row for row in trace["design_mappings"]}
    assert mappings["gemini-2.5-pro"]["target_model"] == "amazon.nova-pro-v1:0"
    assert mappings["gemini-2.5-pro"]["migration_path"] == "vertex_adapter"
    assert mappings["gpt-4o"]["target_model"] == "openai.gpt-5.6-terra"
    assert mappings["gpt-4o"]["migration_path"] == "direct_api"
    assert mappings["claude-3-haiku-20240307"]["target_model"] == "anthropic.claude-haiku-4-5-20251001-v1:0"
    assert mappings["claude-3-haiku-20240307"]["migration_path"] == "anthropic_sdk"
    assert all(row["retirement_status"] == "active" for row in trace["design_mappings"])
    assert len(trace["associations"]) == 3 and all(row["lifecycle_label"] for row in trace["associations"])
    assert runtime.design_target("embedding", "balanced")["target_bedrock_model"] == "amazon.titan-embed-text-v2:0"
    # Estimate: targets are priced from the pricing-cache registry; observed source cost is not available, not fabricated.
    registry = runtime.pricing_registry(BMA_ROOT)
    expected_target = 0.0
    for model in ("gemini-2.5-pro", "gpt-4o", "claude-3-haiku-20240307"):
        input_rate, output_rate = runtime.target_rates(registry, runtime.MODEL_TARGETS[model][0])
        expected_target += round(INPUT_TOKENS / 1_000_000 * input_rate + OUTPUT_TOKENS / 1_000_000 * output_rate, 2)
    estimate = trace["estimate"]
    assert estimate["target_monthly"] == round(expected_target, 2)
    assert estimate["pricing_source"] == "bedrock_cache"
    assert estimate["source_monthly"] is None
    assert estimate["source_monthly_basis"] is None
    assert estimate["monthly_delta"] is None
    assert estimate["evidence"]["observed_source_costs"] == [None, None, None]
    assert not sidecar_path.exists()


def test_validate_profile_cli_reports_present_sidecar_fields(tmp_path: Path) -> None:
    profile_path = tmp_path / "ai-workload-profile.json"
    sidecar_path = tmp_path / "ai-workload-sidecar.json"
    profile_path.write_text(json.dumps(PROFILE_415), encoding="utf-8")
    sidecar_path.write_text(json.dumps({
        "schema_version": 1, "kind": "BMA_GCP_AI_SIDECAR", "workloads": [],
        "observed_costs": {"monthly_ai_spend": 105, "source": "openai_usage_api"},
    }), encoding="utf-8")
    gate = _validate_cli(profile_path, sidecar_path)
    assert gate.returncode == 0, gate.stderr
    output = json.loads(gate.stdout)
    assert output["sidecar"] == "validated"
    assert output["sidecar_fields"]["workloads"] == "available"
    assert output["sidecar_fields"]["observed_costs"] == "available"
    assert output["sidecar_fields"]["agentic_profile"] == "not_available"
    assert output["sidecar_fields"]["integration_context"] == "not_available"
    # Tolerating an absent file does not weaken validation of a present one.
    sidecar_path.write_text(json.dumps({"schema_version": 1, "kind": "BMA_GCP_AI_SIDECAR", "workloads": "no"}), encoding="utf-8")
    invalid = _validate_cli(profile_path, sidecar_path)
    assert invalid.returncode == 1
    assert "ai_sidecar_invalid" in json.loads(invalid.stderr)["message"]
    # Without --sidecar the output shape is unchanged.
    plain = subprocess.run(
        [sys.executable, str(RUNTIME_PATH), "validate-profile", "--profile", str(profile_path)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert plain.returncode == 0
    assert set(json.loads(plain.stdout)) == {"ok", "ai_sources", "gateways"}


@pytest.mark.parametrize("field", SIDECAR_FIELDS)
def test_sidecar_availability_marks_each_field_from_presence_only(field: str) -> None:
    assert runtime.sidecar_availability(None)[field] == "not_available"
    assert runtime.sidecar_availability({field: None})[field] == "available"
    assert runtime.sidecar_availability({})[field] == "not_available"
