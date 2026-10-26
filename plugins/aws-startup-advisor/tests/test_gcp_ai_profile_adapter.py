"""GCP boundary adapter: legacy GCP AI profile -> #415, with named fail-closed errors and the GCP sidecar."""
from __future__ import annotations
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parent.parent
GCP = ROOT / "skills/gcp-to-aws"
ADAPTER_PATH = GCP / "scripts/gcp-ai-profile-adapter.py"
BMA_RUNTIME = ROOT / "skills/bedrock-migration-assessment/scripts/bma-runtime.py"
VENDORED_SCHEMA = GCP / "references/contracts/ai-workload-profile.schema.json"
CANONICAL_SCHEMA = ROOT / "scripts/contracts/ai-workload-profile.schema.json"
_spec = importlib.util.spec_from_file_location("gcp_ai_profile_adapter", ADAPTER_PATH)
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)
# Legacy GCP-shaped sample: direct Anthropic and OpenAI models found in application code.
LEGACY_SAMPLE = {
    "current_costs": {"monthly_ai_spend": 100, "services_detected": ["Anthropic API"], "source": "anthropic_usage_api"},
    "detection_signals": [{"confidence": 0.95, "evidence": "src/ai/anthropic_client.py line 3", "method": "code", "pattern": "anthropic import"}],
    "infrastructure": [],
    "integration": {"gateway_type": "direct", "pattern": "direct_sdk", "primary_sdk": "anthropic", "languages": ["python"]},
    "metadata": {"profile_source": "application_code", "report_date": "2026-02-26"},
    "models": [
        {
            "capabilities_used": ["text_generation"], "detected_via": ["code"],
            "evidence": [{"file": "src/ai/anthropic_client.py", "line": 18, "pattern": "anthropic.Anthropic()", "source": "code"}],
            "model_id": "claude-3-5-sonnet-20240620", "service": "anthropic_api", "usage_context": "Summarization",
        },
        {
            "capabilities_used": ["text_generation"], "detected_via": ["code"],
            "evidence": [{"file": "src/ai/openai_client.py", "line": 9, "pattern": "OpenAI()", "source": "code"}],
            "model_id": "gpt-4o", "service": "openai_api", "usage_context": "Classification",
        },
    ],
    "summary": {"ai_source": "both", "confidence_level": "very_high", "inferred_from_iac": False, "overall_confidence": 0.95},
}
EXPECTED_SAMPLE_415 = {
    "schema_version": "1.0",
    "ai_sources": [
        {
            "provider": "anthropic", "source_service": "anthropic_api", "model_families": ["claude"],
            "model_evidence": "observed", "models": ["claude-3-5-sonnet-20240620"],
            "model_observations": [{
                "normalized_model": "claude-3-5-sonnet-20240620", "raw_model": "claude-3-5-sonnet-20240620",
                "model_family": "claude",
                "evidence": [{"provenance": "code", "confidence": "high", "detail": "src/ai/anthropic_client.py:18"}],
            }],
        },
        {
            "provider": "openai", "source_service": "openai_api", "model_families": ["gpt"],
            "model_evidence": "observed", "models": ["gpt-4o"],
            "model_observations": [{
                "normalized_model": "gpt-4o", "raw_model": "gpt-4o", "model_family": "gpt",
                "evidence": [{"provenance": "code", "confidence": "high", "detail": "src/ai/openai_client.py:9"}],
            }],
        },
    ],
    "gateways": [],
}
SIDECAR_EXPECTED = {
    "schema_version": 1,
    "kind": "BMA_GCP_AI_SIDECAR",
    "workloads": [],
    "observed_costs": LEGACY_SAMPLE["current_costs"],
    "integration_context": {"pattern": "direct_sdk", "primary_sdk": "anthropic", "languages": ["python"]},
    "profile_origin": {"terraform_primary": False},
    "model_context": [
        {"service": "anthropic_api", "model_id": "claude-3-5-sonnet-20240620", "capabilities_used": ["text_generation"], "usage_context": "Summarization"},
        {"service": "openai_api", "model_id": "gpt-4o", "capabilities_used": ["text_generation"], "usage_context": "Classification"},
    ],
}
def _legacy(mutate=None) -> dict:
    doc = copy.deepcopy(LEGACY_SAMPLE)
    if mutate is not None:
        mutate(doc)
    return doc
def _validate_jsonschema(document: dict) -> list[str]:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(VENDORED_SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(schema)
    return [error.message for error in validator.iter_errors(document)]
def test_vendored_schema_is_byte_identical_to_canonical():
    assert VENDORED_SCHEMA.read_bytes() == CANONICAL_SCHEMA.read_bytes()
def test_sample_converts_to_expected_415_document():
    assert adapter.convert_legacy_profile(_legacy()) == EXPECTED_SAMPLE_415
    assert _validate_jsonschema(EXPECTED_SAMPLE_415) == []
def test_conversion_is_deterministic():
    first = json.dumps(adapter.convert_legacy_profile(_legacy()), sort_keys=True)
    second = json.dumps(adapter.convert_legacy_profile(_legacy()), sort_keys=True)
    assert first == second
def test_mixed_direct_and_azure_keeps_both_services():
    def add_azure(doc):
        doc["models"].append({
            "detected_via": ["terraform"], "model_id": "gpt-4o", "service": "azure_openai",
            "evidence": [{"file": "azure.tf", "resource": "azurerm_cognitive_deployment.gpt4o", "source": "terraform"}],
        })
        doc["detection_signals"].append({"confidence": 0.8, "method": "terraform", "pattern": "azure", "evidence": "azure.tf"})
    document = adapter.convert_legacy_profile(_legacy(add_azure))
    openai = [source for source in document["ai_sources"] if source["provider"] == "openai"]
    assert [source["source_service"] for source in openai] == ["azure_openai", "openai_api"]
    azure = openai[0]["model_observations"][0]
    assert azure["evidence"] == [{"provenance": "iac", "confidence": "medium", "detail": "azurerm_cognitive_deployment.gpt4o"}]
    assert _validate_jsonschema(document) == []
def test_openrouter_upstreams_form_observed_gateway():
    def add_openrouter(doc):
        doc["integration"]["gateway_type"] = "llm_router"
        doc["models"].append({
            "detected_via": ["code"], "model_id": "anthropic/claude-3.5-sonnet", "service": "openrouter_api",
            "evidence": [{"file": "src/ai/router.py", "line": 4, "source": "code"}],
        })
        doc["models"].append({
            "detected_via": ["code"], "model_id": "google/gemini-1.5-pro", "service": "openrouter_api",
            "evidence": [{"file": "src/ai/router.py", "line": 5, "source": "code"}],
        })
    document = adapter.convert_legacy_profile(_legacy(add_openrouter))
    gateway = document["gateways"][0]
    assert gateway["product"] == "openrouter" and gateway["type"] == "llm_router"
    assert gateway["upstream_evidence"] == "observed"
    assert [(up["provider"], up["source_service"]) for up in gateway["upstreams"]] == [
        ("anthropic", "anthropic_api"), ("google", "vertex_ai"),
    ]
    assert gateway["upstreams"][1]["model_families"] == [
        {"family": "gemini", "model_evidence": "observed", "models": ["gemini-1.5-pro"]},
    ]
    assert all(source["provider"] != "openrouter" for source in document["ai_sources"])
    assert _validate_jsonschema(document) == []
def test_openrouter_without_prefix_is_unresolved_with_no_upstreams():
    def add_unprefixed(doc):
        doc["integration"]["gateway_type"] = "llm_router"
        doc["models"].append({
            "detected_via": ["code"], "model_id": "claude-3-haiku-20240307", "service": "openrouter_api",
            "evidence": [{"file": "src/ai/router.py", "line": 9, "source": "code"}],
        })
    document = adapter.convert_legacy_profile(_legacy(add_unprefixed))
    assert document["gateways"] == [{"product": "openrouter", "type": "llm_router", "upstream_evidence": "unresolved", "upstreams": []}]
    assert _validate_jsonschema(document) == []
def test_iac_only_declared_family_stays_not_observed():
    def iac_only(doc):
        doc["models"] = []
        doc["metadata"]["profile_source"] = "iac_vertex"
        doc["summary"]["ai_source"] = "gemini"
        doc["summary"]["inferred_from_iac"] = True
    document = adapter.convert_legacy_profile(_legacy(iac_only))
    assert document["ai_sources"] == [{
        "provider": "google", "source_service": "vertex_ai", "model_families": ["gemini"],
        "model_evidence": "not_observed", "models": [], "model_observations": [],
    }]
    assert _validate_jsonschema(document) == []
def test_legacy_shape_check_rejects_an_already_415_document():
    with pytest.raises(adapter.GcpProfileNotRepresentable) as info:
        adapter.convert_legacy_profile(EXPECTED_SAMPLE_415)
    assert (info.value.code, info.value.field_path) == ("LEGACY_SHAPE_UNEXPECTED", "$")
def _set(path, value):
    def mutate(doc):
        target = doc
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[int(key)] if key.isdigit() else target[key]
        last = keys[-1]
        target[int(last) if last.isdigit() else last] = value
    return mutate
NAMED_ERROR_CASES = [
    ("service unmapped", _set("models.0.service", "bedrock_api"), "LEGACY_SERVICE_UNMAPPED", "$.models[0].service"),
    ("ai_source disagrees with models", _set("summary.ai_source", "gemini"), "LEGACY_AI_SOURCE_UNREPRESENTABLE", "$.summary.ai_source"),
    ("ai_source unknown value", _set("summary.ai_source", "azure"), "LEGACY_AI_SOURCE_UNREPRESENTABLE", "$.summary.ai_source"),
    ("model id has a space", _set("models.0.model_id", "Claude Pro"), "LEGACY_MODEL_ID_INVALID", "$.models[0].model_id"),
    ("model family unknown", _set("models.0.model_id", "mistral-large"), "LEGACY_MODEL_FAMILY_UNKNOWN", "$.models[0].model_id"),
    ("embedding model has no family rule", _set("models.0.model_id", "text-embedding-004"), "LEGACY_MODEL_FAMILY_UNKNOWN", "$.models[0].model_id"),
    ("detection method unknown", _set("models.0.detected_via", ["slack"]), "LEGACY_PROVENANCE_UNKNOWN", "$.models[0].detected_via"),
    ("no numeric confidence for method", _set("detection_signals", []), "LEGACY_CONFIDENCE_MISSING", "$.models[0].detected_via"),
    ("gateway type not llm_router", lambda doc: (
        doc["models"].append({"detected_via": ["code"], "model_id": "openai/gpt-4o", "service": "openrouter_api", "evidence": []}),
        doc["integration"].update(gateway_type="direct"),
    ), "LEGACY_GATEWAY_UNREPRESENTABLE", "$.integration.gateway_type"),
    ("both with no models", lambda doc: (doc.update(models=[]), doc["summary"].update(ai_source="both")), "LEGACY_AI_SOURCE_UNREPRESENTABLE", "$.summary.ai_source"),
    ("absent family with no models", lambda doc: (doc.update(models=[]), doc["summary"].pop("ai_source")), "LEGACY_IAC_FAMILY_UNKNOWN", "$.summary.ai_source"),
]
@pytest.mark.parametrize(("name", "mutate", "code", "field_path"), NAMED_ERROR_CASES, ids=[case[0] for case in NAMED_ERROR_CASES])
def test_unrepresentable_legacy_fails_closed_with_named_error(name, mutate, code, field_path):
    with pytest.raises(adapter.GcpProfileNotRepresentable) as info:
        adapter.convert_legacy_profile(_legacy(mutate))
    assert info.value.code == code
    assert info.value.field_path == field_path
    assert str(info.value).startswith(f"GcpProfileNotRepresentable: {code} at {field_path}:")
def test_schema_gate_fails_closed_when_the_converted_document_is_invalid(monkeypatch, tmp_path):
    schema = json.loads(VENDORED_SCHEMA.read_text(encoding="utf-8"))
    schema["properties"]["schema_version"] = {"const": "2.0"}
    altered = tmp_path / "schema.json"
    altered.write_text(json.dumps(schema), encoding="utf-8")
    monkeypatch.setattr(adapter, "SCHEMA_PATH", altered)
    with pytest.raises(adapter.GcpProfileNotRepresentable) as info:
        adapter.convert_legacy_profile(_legacy())
    assert info.value.code == "SCHEMA_415_INVALID"
    assert info.value.field_path == "$.schema_version"
def test_sidecar_carries_gcp_observed_costs_and_integration_context():
    assert adapter.convert_legacy_sidecar(_legacy()) == SIDECAR_EXPECTED
def test_sidecar_carries_populated_infrastructure_verbatim():
    resources = [{"address": "google_vertex_ai_endpoint.chat", "type": "google_vertex_ai_endpoint", "provider": "google"}]
    sidecar = adapter.convert_legacy_sidecar(_legacy(_set("infrastructure", resources)))
    assert sidecar["infrastructure"] == resources
    assert "infrastructure" not in adapter.convert_legacy_sidecar(_legacy())


def test_non_array_infrastructure_fails_closed():
    with pytest.raises(adapter.GcpProfileNotRepresentable) as info:
        adapter.convert_legacy_sidecar(_legacy(_set("infrastructure", {"address": "x"})))
    assert (info.value.code, info.value.field_path) == ("LEGACY_SHAPE_UNEXPECTED", "$.infrastructure")


def test_sidecar_carries_terraform_primary_origin_for_iac_profiles():
    def iac_origin(doc):
        doc["metadata"]["profile_source"] = "merged"
        doc["summary"]["inferred_from_iac"] = True
    assert adapter.convert_legacy_sidecar(_legacy(iac_origin))["profile_origin"] == {"terraform_primary": True}
    def iac_vertex(doc):
        doc["metadata"]["profile_source"] = "iac_vertex"
    assert adapter.convert_legacy_sidecar(_legacy(iac_vertex))["profile_origin"] == {"terraform_primary": True}
def test_sidecar_is_not_written_when_there_is_nothing_to_carry():
    def bare(doc):
        doc.pop("current_costs")
        doc.pop("integration")
        doc.pop("metadata")
        doc.pop("summary")
        for model in doc["models"]:
            model.pop("capabilities_used")
            model.pop("usage_context")
    assert adapter.convert_legacy_sidecar(_legacy(bare)) is None
def test_sidecar_keeps_existing_app_code_workloads_and_replaces_only_gcp_keys():
    existing = {
        "schema_version": 1, "kind": "BMA_GCP_AI_SIDECAR",
        "workloads": [{"capability": "text_generation"}], "observed_costs": {"monthly_ai_spend": 1},
    }
    sidecar = adapter.convert_legacy_sidecar(_legacy(), existing)
    assert sidecar["workloads"] == [{"capability": "text_generation"}]
    assert sidecar["observed_costs"] == LEGACY_SAMPLE["current_costs"]
    assert existing["observed_costs"] == {"monthly_ai_spend": 1}
def test_existing_sidecar_of_another_kind_fails_closed():
    with pytest.raises(adapter.GcpProfileNotRepresentable) as info:
        adapter.convert_legacy_sidecar(_legacy(), {"schema_version": 1, "kind": "OTHER", "workloads": []})
    assert info.value.code == "LEGACY_SIDECAR_INVALID"
def test_non_object_current_costs_fails_closed():
    with pytest.raises(adapter.GcpProfileNotRepresentable) as info:
        adapter.convert_legacy_sidecar(_legacy(_set("current_costs", 100)))
    assert (info.value.code, info.value.field_path) == ("LEGACY_SHAPE_UNEXPECTED", "$.current_costs")
def test_sidecar_passes_bma_validate_profile_next_to_the_415_document(tmp_path):
    legacy_path = tmp_path / "legacy.json"
    out_path = tmp_path / ".bma-input" / "ai-workload-profile.json"
    sidecar_path = tmp_path / "ai-workload-sidecar.json"
    legacy_path.write_text(json.dumps(_legacy()), encoding="utf-8")
    converted = subprocess.run(
        [sys.executable, str(ADAPTER_PATH), "convert", "--legacy", str(legacy_path), "--out", str(out_path), "--sidecar", str(sidecar_path)],
        capture_output=True, text=True,
    )
    assert converted.returncode == 0, converted.stderr
    validated = subprocess.run(
        [sys.executable, str(BMA_RUNTIME), "validate-profile", "--profile", str(out_path), "--sidecar", str(sidecar_path)],
        capture_output=True, text=True,
    )
    assert validated.returncode == 0, validated.stderr
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
# Keywords the stdlib subset validator in gcp-ai-profile-adapter.py evaluates. Annotations are ignored.
ADAPTER_SUBSET_KEYWORDS = {
    "$ref", "$schema", "$id", "definitions", "properties", "items", "required", "additionalProperties",
    "type", "const", "enum", "pattern", "minLength", "minItems", "maxItems", "uniqueItems", "oneOf",
    "title", "description", "default", "examples",
}
def test_adapter_schema_subset_covers_every_keyword_in_the_vendored_schema():
    assert _schema_keywords(json.loads(VENDORED_SCHEMA.read_text(encoding="utf-8"))) <= ADAPTER_SUBSET_KEYWORDS
def test_gcp_public_profile_stays_legacy_shape_after_delegated_run(tmp_path):
    run = tmp_path / "run"
    (run / ".bma-input").mkdir(parents=True)
    public = run / "ai-workload-profile.json"
    public.write_text(json.dumps(_legacy()), encoding="utf-8")
    before = public.read_bytes()
    converted = subprocess.run(
        [sys.executable, str(ADAPTER_PATH), "convert", "--legacy", str(public),
         "--out", str(run / ".bma-input" / "ai-workload-profile.json"),
         "--sidecar", str(run / ".bma-input" / "ai-workload-sidecar.json")],
        capture_output=True, text=True,
    )
    assert converted.returncode == 0, converted.stderr
    # The public GCP file is byte-identical and keeps the legacy top-level keys, not the #415 shape.
    assert public.read_bytes() == before
    public_doc = json.loads(public.read_text(encoding="utf-8"))
    assert set(public_doc) == set(LEGACY_SAMPLE)
    assert "schema_version" not in public_doc and "ai_sources" not in public_doc
    assert json.loads((run / ".bma-input" / "ai-workload-profile.json").read_text(encoding="utf-8")) == EXPECTED_SAMPLE_415
    # The delegated writer registry must agree: BMA may not write the public path in a GCP run.
    runtime_spec = importlib.util.spec_from_file_location("bma_runtime_public_profile", BMA_RUNTIME)
    runtime = importlib.util.module_from_spec(runtime_spec)
    runtime_spec.loader.exec_module(runtime)
    assert runtime.writer("delegated", "ai-workload-profile.json") == "gcp-to-aws"


def test_cli_writes_valid_document_and_nothing_on_failure(tmp_path):
    legacy_path = tmp_path / "legacy.json"
    out_path = tmp_path / ".bma-input" / "ai-workload-profile.json"
    sidecar_path = tmp_path / "ai-workload-sidecar.json"
    legacy_path.write_text(json.dumps(_legacy()), encoding="utf-8")
    ok = subprocess.run(
        [sys.executable, str(ADAPTER_PATH), "convert", "--legacy", str(legacy_path), "--out", str(out_path), "--sidecar", str(sidecar_path)],
        capture_output=True, text=True,
    )
    assert ok.returncode == 0, ok.stderr
    assert json.loads(out_path.read_text(encoding="utf-8")) == EXPECTED_SAMPLE_415
    assert json.loads(sidecar_path.read_text(encoding="utf-8")) == SIDECAR_EXPECTED
    bad_path = tmp_path / "bad-legacy.json"
    bad_out = tmp_path / "bad-out.json"
    bad_sidecar = tmp_path / "bad-sidecar.json"
    bad_path.write_text(json.dumps(_legacy(_set("models.0.service", "bedrock_api"))), encoding="utf-8")
    failed = subprocess.run(
        [sys.executable, str(ADAPTER_PATH), "convert", "--legacy", str(bad_path), "--out", str(bad_out), "--sidecar", str(bad_sidecar)],
        capture_output=True, text=True,
    )
    assert failed.returncode == 1
    assert not bad_out.exists()
    assert not bad_sidecar.exists()
    error = json.loads(failed.stderr)
    assert error["error"] == "GcpProfileNotRepresentable"
    assert error["code"] == "LEGACY_SERVICE_UNMAPPED"
    assert error["field_path"] == "$.models[0].service"
