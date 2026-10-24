"""BMA accepts only the #415 ai-workload-profile input and rejects legacy shape by name."""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BMA_ROOT = ROOT / "skills/bedrock-migration-assessment"
PATH = BMA_ROOT / "scripts/bma-runtime.py"
FIXTURES = ROOT / "fixtures/ai-workload-profiles"
FIXTURE_NAMES = sorted(path.parent.name for path in FIXTURES.glob("*/ai-workload-profile.json"))

runtime = types.ModuleType("bma_runtime")
exec(compile(PATH.read_text(encoding="utf-8"), str(PATH), "exec"), runtime.__dict__)

LEGACY_PROFILE = {
    "metadata": {"report_date": "2026-02-26", "profile_source": "application_code"},
    "summary": {"ai_source": "gemini", "inferred_from_iac": False},
    "models": [{"model_id": "gemini-2.5-pro", "service": "vertex_ai_generative", "detected_via": ["code"]}],
}


def _profile(name: str) -> dict:
    return json.loads((FIXTURES / name / "ai-workload-profile.json").read_text(encoding="utf-8"))


def _validate_cli(profile: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PATH), "validate-profile", "--profile", str(profile)],
        cwd=ROOT, text=True, capture_output=True,
    )


def _trace_request_from_profile(profile: dict) -> dict:
    """Test-side projection of a #415 document into semantic-trace source rows (direct and gateway)."""
    rows = []
    for source in profile["ai_sources"]:
        rows.append({
            "provider": source["provider"], "source_service": source["source_service"], "gateway": None,
            "models": list(source["models"]), "call_sites": [],
            "observed_monthly_cost": None, "monthly_input_tokens": None, "monthly_output_tokens": None,
        })
    for gateway in profile["gateways"]:
        for upstream in gateway["upstreams"]:
            models = [model for family in upstream["model_families"] for model in family["models"]]
            if not models:
                continue
            rows.append({
                "provider": upstream["provider"], "source_service": upstream.get("source_service") or "upstream",
                "gateway": gateway["product"], "models": models, "call_sites": [],
                "observed_monthly_cost": None, "monthly_input_tokens": None, "monthly_output_tokens": None,
            })
    return {
        "schema_version": 2, "mode": "direct", "source_containing": True, "has_ai_profile": True,
        "iac_vertex": False, "source_evidence": rows, "state": {"phases": {}}, "capture_observations": [],
        "user_decisions": {"execute_requested": False, "generate": False, "include_rollback": False,
                           "report_scope": "none"},
    }


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_415_fixture_validates_and_runs_through_bma(name: str) -> None:
    path = FIXTURES / name / "ai-workload-profile.json"
    completed = _validate_cli(path)
    assert completed.returncode == 0, completed.stderr
    profile = _profile(name)
    assert runtime.validate_ai_workload_profile(profile, BMA_ROOT)["ok"] is True
    result = runtime.semantic_trace(_trace_request_from_profile(profile))
    assert result["route"]["ai_route_active"] is True
    assert result["associations"], name


def test_mixed_direct_and_azure_openai_keeps_both_services() -> None:
    result = runtime.semantic_trace(_trace_request_from_profile(_profile("openai-direct-and-azure-openai")))
    keys = {(row["provider"], row["source_service"], row["model"]) for row in result["associations"]}
    assert ("openai", "openai_api", "gpt-4o") in keys
    assert ("openai", "azure_openai", "gpt-4o") in keys


def test_openrouter_is_gateway_with_upstream_providers_only() -> None:
    profile = _profile("openrouter-multi-upstream")
    assert profile["gateways"][0]["product"] == "openrouter"
    assert all(source["provider"] != "openrouter" for source in profile["ai_sources"])
    result = runtime.semantic_trace(_trace_request_from_profile(profile))
    assert {row["gateway"] for row in result["associations"] if row["gateway"]} == {"openrouter"}


def test_unresolved_gateway_has_no_invented_upstreams() -> None:
    profile = _profile("openrouter-unresolved")
    assert profile["gateways"] == [
        {"product": "openrouter", "type": "llm_router", "upstream_evidence": "unresolved", "upstreams": []}
    ]
    assert runtime.validate_ai_workload_profile(profile, BMA_ROOT)["gateways"] == 1


def test_retired_model_is_unpriced_and_not_generated() -> None:
    profile = _profile("ai-only-multi-direct")
    request = _trace_request_from_profile(profile)
    request["user_decisions"]["generate"] = True
    result = runtime.semantic_trace(request)
    retired = [row for row in result["design_mappings"] if row.get("retired")]
    assert retired == [{"source_model": "gemini-1.5-pro", "target_model": None,
                        "migration_path": None, "retired": True}]
    assert result["estimate"]["pricing_source"] == "unavailable"
    assert "ai-migration/gemini-adapter.py" not in result["generation"]["files"]


def test_trace_rejects_same_model_twice_within_one_service() -> None:
    request = _trace_request_from_profile(_profile("ai-only-multi-direct"))
    request["source_evidence"].append(copy.deepcopy(request["source_evidence"][0]))
    with pytest.raises(ValueError, match="trace_source_invalid"):
        runtime.semantic_trace(request)


@pytest.mark.parametrize(
    ("profile", "field"),
    [
        (LEGACY_PROFILE, "metadata"),
        ({"ai_sources": [{"provider": "google", "source_service": "vertex_ai", "service": "x",
                          "model_families": ["gemini"], "model_evidence": "observed", "models": ["gemini-2.5-pro"],
                          "model_observations": []}], "gateways": []}, "ai_sources[0].service"),
        ({"schema_version": "1.0", "ai_sources": [], "gateways": [], "workloads": []}, "workloads"),
    ],
)
def test_legacy_shaped_input_is_rejected_by_name(tmp_path: Path, profile: dict, field: str) -> None:
    path = tmp_path / "ai-workload-profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    completed = _validate_cli(path)
    assert completed.returncode == 1
    error = json.loads(completed.stderr)
    assert error["error"] == "BmaLegacyProfileRejected"
    assert f"'{field}'" in error["message"]
    assert "must be the #415 ai-workload-profile format" in error["message"]
    with pytest.raises(runtime.BmaLegacyProfileRejected, match=re.escape(field)):
        runtime.validate_ai_workload_profile(profile, BMA_ROOT)


def test_415_schema_violation_fails_closed(tmp_path: Path) -> None:
    profile = _profile("openrouter-unresolved")
    profile["ai_sources"][0]["provider"] = "openrouter"
    path = tmp_path / "ai-workload-profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    completed = _validate_cli(path)
    assert completed.returncode == 1
    assert json.loads(completed.stderr)["error"] == "ValueError"
    assert "ai_profile_schema_invalid" in json.loads(completed.stderr)["message"]


def test_observation_mismatch_is_rejected() -> None:
    profile = _profile("ai-only-multi-direct")
    profile["ai_sources"][0]["model_observations"][0]["normalized_model"] = "claude-3-haiku-20240307"
    with pytest.raises(ValueError, match="ai_profile_observation_mismatch"):
        runtime.validate_ai_workload_profile(profile, BMA_ROOT)


def test_sidecar_is_closed_and_temporary_shape() -> None:
    valid = {"schema_version": 1, "kind": "BMA_GCP_AI_SIDECAR", "workloads": [],
             "observed_costs": {"monthly_ai_spend": None}, "integration_context": {"pattern": "unknown"}}
    assert runtime.validate_ai_sidecar(valid) is valid
    with pytest.raises(ValueError, match="ai_sidecar_invalid"):
        runtime.validate_ai_sidecar({**valid, "models": []})
    with pytest.raises(ValueError, match="ai_sidecar_invalid"):
        runtime.validate_ai_sidecar({**valid, "workloads": "not-a-list"})
    with pytest.raises(ValueError, match="ai_sidecar_invalid"):
        runtime.validate_ai_sidecar({**valid, "observed_costs": []})


def _schema_keywords(node: object, parent_key: str = "") -> set[str]:
    """Keywords used by a JSON Schema node. Keys directly under properties/definitions are names, not keywords."""
    if isinstance(node, list):
        return set().union(*(_schema_keywords(item) for item in node)) if node else set()
    if not isinstance(node, dict):
        return set()
    found: set[str] = set()
    for key, value in node.items():
        if parent_key in ("properties", "definitions"):
            found |= _schema_keywords(value)
        else:
            found.add(key)
            found |= _schema_keywords(value, key)
    return found


# Keywords the stdlib subset validator in bma-runtime.py evaluates. Annotations are ignored.
RUNTIME_SUBSET_KEYWORDS = {
    "$ref", "$schema", "$id", "definitions", "properties", "items", "required", "additionalProperties",
    "type", "const", "enum", "pattern", "minLength", "minItems", "maxItems", "uniqueItems", "oneOf",
    "title", "description", "default", "examples",
}


def test_runtime_schema_subset_covers_every_keyword_in_the_vendored_schema() -> None:
    schema = json.loads((BMA_ROOT / "references/contracts/ai-workload-profile.schema.json").read_text(encoding="utf-8"))
    assert _schema_keywords(schema) <= RUNTIME_SUBSET_KEYWORDS


def test_sidecar_profile_origin_is_only_the_terraform_primary_flag() -> None:
    valid = {"schema_version": 1, "kind": "BMA_GCP_AI_SIDECAR", "workloads": [],
             "profile_origin": {"terraform_primary": True}}
    assert runtime.validate_ai_sidecar(valid) is valid
    with pytest.raises(ValueError, match="ai_sidecar_invalid"):
        runtime.validate_ai_sidecar({**valid, "profile_origin": {"terraform_primary": "yes"}})
    with pytest.raises(ValueError, match="ai_sidecar_invalid"):
        runtime.validate_ai_sidecar({**valid, "profile_origin": {"profile_source": "merged"}})
def test_sidecar_accepts_infrastructure_and_model_context_only_as_arrays() -> None:
    valid = {"schema_version": 1, "kind": "BMA_GCP_AI_SIDECAR", "workloads": [],
             "infrastructure": [{"address": "x"}], "model_context": [{"model_id": "gpt-4o", "capabilities_used": ["embeddings"]}]}
    assert runtime.validate_ai_sidecar(valid) is valid
    with pytest.raises(ValueError, match="ai_sidecar_invalid"):
        runtime.validate_ai_sidecar({**valid, "infrastructure": {"address": "x"}})
    with pytest.raises(ValueError, match="ai_sidecar_invalid"):
        runtime.validate_ai_sidecar({**valid, "model_context": "embeddings"})


def test_bma_never_imports_or_invokes_gcp_to_aws() -> None:
    """BMA is the target-side contract: no code or path under it may reach into the GCP shim."""
    forbidden = ("gcp-to-aws/scripts", "gcp_ai_profile_adapter", "from gcp", "import gcp")
    # Provenance strings in closure.json name gcp-to-aws as a copy source, not an invocation.
    for path in sorted(BMA_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits = [token for token in forbidden if token in text]
        assert not hits, f"{path.relative_to(ROOT)} references {hits}"


def test_delegated_bma_input_is_gcp_adapter_owned_and_public_profile_unchanged():
    # Delegated runs: the adapter writes the #415 input under bma-input/; the public root file keeps its label.
    assert runtime.writer("delegated", "bma-input/ai-workload-profile.json") == "gcp-to-aws"
    assert runtime.writer("delegated", "ai-workload-profile.json") == "bedrock-migration-assessment"
