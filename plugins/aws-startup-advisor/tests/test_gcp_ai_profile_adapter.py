"""GCP boundary adapter: legacy GCP AI profile -> #415, with named fail-closed errors and the GCP sidecar."""
from __future__ import annotations
import copy
import hashlib
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
def test_sidecar_keeps_existing_app_code_workloads_and_merges_observed_costs():
    # BMA discovery already recorded OpenAI usage-API spend; the GCP legacy profile brings Anthropic spend.
    # Per schema-discover-ai.md § Usage-API merge, different providers are summed, never replaced.
    existing = {
        "schema_version": 1, "kind": "BMA_GCP_AI_SIDECAR",
        "workloads": [{"capability": "text_generation"}],
        "observed_costs": {"monthly_ai_spend": 105, "source": "openai_usage_api", "services_detected": ["OpenAI chat"]},
    }
    snapshot = copy.deepcopy(existing)
    sidecar = adapter.convert_legacy_sidecar(_legacy(), existing)
    assert sidecar["workloads"] == [{"capability": "text_generation"}]
    assert sidecar["observed_costs"] == {
        "monthly_ai_spend": 205, "source": "mixed", "services_detected": ["OpenAI chat", "Anthropic API"],
        "breakdown": [
            {"provider": "openai", "monthly_spend": 105, "source": "openai_usage_api", "services_detected": ["OpenAI chat"]},
            {"provider": "anthropic", "monthly_spend": 100, "source": "anthropic_usage_api", "services_detected": ["Anthropic API"]},
        ],
    }
    assert "conflicting_sources" not in sidecar["observed_costs"]
    assert existing == snapshot


def test_merge_observed_costs_same_provider_conflict_is_recorded_not_dropped():
    existing = {"monthly_ai_spend": 400, "source": "code_estimate", "services_detected": ["Google Gen AI"]}
    incoming = {"monthly_ai_spend": 450, "source": "billing_data", "services_detected": ["Vertex AI Predictions"]}
    merged = adapter.merge_observed_costs(existing, incoming)
    assert merged["monthly_ai_spend"] == 450
    assert merged["source"] == "billing_data"
    assert merged["services_detected"] == ["Google Gen AI", "Vertex AI Predictions"]
    assert "breakdown" not in merged
    assert merged["conflicting_sources"] == [
        {"provider": "google", "monthly_spend": 400, "source": "code_estimate", "services_detected": ["Google Gen AI"]},
    ]
    # Equal same-provider rows are a no-op, and a missing existing side returns the incoming object verbatim.
    assert adapter.merge_observed_costs(incoming, incoming) == incoming
    assert adapter.merge_observed_costs(None, incoming) == incoming


def _415_source(provider, source_service, models, provenance="code", family=None):
    families = sorted({family or adapter._model_identity(model, "$")[1] for model in models}) if models else [family]
    return {
        "provider": provider, "source_service": source_service, "model_families": families,
        "model_evidence": "observed" if models else "not_observed", "models": list(models),
        "model_observations": [
            {"normalized_model": model, "raw_model": model, "model_family": family or adapter._model_identity(model, "$")[1],
             "evidence": [{"provenance": provenance, "confidence": "high"}]}
            for model in models
        ],
    }


def test_merge_415_profiles_unions_sources_models_observations_and_gateways():
    existing = {
        "schema_version": "1.0",
        "ai_sources": [
            _415_source("openai", "openai_api", ["gpt-4o", "gpt-4o-mini"]),
            _415_source("google", "vertex_ai", [], family="gemini"),
        ],
        "gateways": [{
            "product": "openrouter", "type": "llm_router", "upstream_evidence": "observed",
            "upstreams": [{"provider": "anthropic", "source_service": "anthropic_api",
                           "model_families": [{"family": "claude", "model_evidence": "observed", "models": ["claude-3.5-sonnet"]}]}],
        }],
    }
    converted = {
        "schema_version": "1.0",
        "ai_sources": [
            _415_source("anthropic", "anthropic_api", ["claude-3-5-sonnet-20240620"], provenance="iac"),
            _415_source("google", "vertex_ai", ["gemini-2.5-pro"], provenance="iac"),
            _415_source("openai", "openai_api", ["gpt-4o", "text-embedding-3-small"], provenance="iac"),
        ],
        "gateways": [{
            "product": "openrouter", "type": "llm_router", "upstream_evidence": "observed",
            "upstreams": [
                {"provider": "anthropic", "source_service": "anthropic_api",
                 "model_families": [{"family": "claude", "model_evidence": "observed", "models": ["claude-3-opus"]}]},
                {"provider": "google", "source_service": "vertex_ai",
                 "model_families": [{"family": "gemini", "model_evidence": "observed", "models": ["gemini-1.5-pro"]}]},
            ],
        }],
    }
    merged = adapter.merge_415_profiles(existing, converted)
    keys = [(source["provider"], source["source_service"]) for source in merged["ai_sources"]]
    assert keys == [("openai", "openai_api"), ("google", "vertex_ai"), ("anthropic", "anthropic_api")]
    openai = merged["ai_sources"][0]
    assert openai["models"] == ["gpt-4o", "gpt-4o-mini", "text-embedding-3-small"]
    assert openai["model_families"] == ["gpt", "embedding"]
    gpt4o = openai["model_observations"][0]
    assert gpt4o["normalized_model"] == "gpt-4o"
    assert gpt4o["evidence"] == [{"provenance": "code", "confidence": "high"}, {"provenance": "iac", "confidence": "high"}]
    google = merged["ai_sources"][1]
    assert google["model_evidence"] == "observed" and google["models"] == ["gemini-2.5-pro"]
    gateway = merged["gateways"][0]
    assert [(up["provider"], up["source_service"]) for up in gateway["upstreams"]] == [("anthropic", "anthropic_api"), ("google", "vertex_ai")]
    assert gateway["upstreams"][0]["model_families"] == [
        {"family": "claude", "model_evidence": "observed", "models": ["claude-3.5-sonnet", "claude-3-opus"]},
    ]
    assert _validate_jsonschema(merged) == []
    assert adapter.merge_415_profiles(merged, converted) == merged
    assert adapter.merge_415_profiles(None, converted) == converted


def test_existing_bma_input_that_is_not_415_fails_closed(tmp_path):
    legacy_path = tmp_path / "legacy.json"
    out_path = tmp_path / ".bma-input" / "ai-workload-profile.json"
    sidecar_path = tmp_path / ".bma-input" / "ai-workload-sidecar.json"
    out_path.parent.mkdir()
    legacy_path.write_text(json.dumps(_legacy()), encoding="utf-8")
    out_path.write_text(json.dumps(_legacy()), encoding="utf-8")
    before = out_path.read_bytes()
    failed = subprocess.run(
        [sys.executable, str(ADAPTER_PATH), "convert", "--legacy", str(legacy_path), "--out", str(out_path), "--sidecar", str(sidecar_path)],
        capture_output=True, text=True,
    )
    assert failed.returncode == 1
    assert json.loads(failed.stderr)["code"] == "EXISTING_415_INVALID"
    assert out_path.read_bytes() == before
    assert not sidecar_path.exists()
    with pytest.raises(adapter.GcpProfileNotRepresentable) as info:
        adapter.merge_415_profiles({"schema_version": "1.0", "ai_sources": [], "gateways": [], "workloads": []}, EXPECTED_SAMPLE_415)
    assert info.value.code == "EXISTING_415_INVALID"


# Review PR #483 (vagmur-aws, thread PRRT_kwDOSKiaLs6wWifC): BMA discovery found gpt-4o in code and the usage-API step
# recorded $555 (Google $450 + OpenAI $105); the GCP Vertex seed then ran `convert` and erased both.
VAGMUR_BMA_PROFILE = {
    "schema_version": "1.0", "gateways": [],
    "ai_sources": [{
        "provider": "openai", "source_service": "openai_api", "model_families": ["gpt"], "model_evidence": "observed",
        "models": ["gpt-4o"],
        "model_observations": [{
            "normalized_model": "gpt-4o", "raw_model": "gpt-4o", "model_family": "gpt",
            "evidence": [{"provenance": "code", "confidence": "high", "detail": "src/ai.py:9"}],
        }],
    }],
}
VAGMUR_SIDECAR = {
    "schema_version": 1, "kind": "BMA_GCP_AI_SIDECAR",
    "workloads": [{
        "workload_id": "wl_a1b2c3", "model_id": "gpt-4o", "sdk_method": "chat.completions.create",
        "capability": "text_generation", "capability_confidence": "high", "structured_output": False,
        "call_sites": [{"file": "src/ai.py", "line": 9}],
    }],
    "observed_costs": {
        "monthly_ai_spend": 555, "source": "mixed", "services_detected": ["Vertex AI Predictions", "OpenAI chat"],
        "breakdown": [
            {"provider": "google", "monthly_spend": 450, "source": "billing_data"},
            {"provider": "openai", "monthly_spend": 105, "source": "openai_usage_api"},
        ],
    },
}
VERTEX_SEED_LEGACY = {
    "metadata": {"profile_source": "iac_vertex", "report_date": "2026-10-26"},
    "summary": {"ai_source": "gemini", "inferred_from_iac": True, "overall_confidence": 0.9},
    "models": [{
        "model_id": "gemini-2.5-pro", "service": "vertex_ai_generative", "detected_via": ["terraform"],
        "evidence": [{"resource": "google_vertex_ai_endpoint.chat", "source": "terraform"}],
    }],
    "detection_signals": [{"method": "terraform", "confidence": 0.9}],
    "integration": {"gateway_type": "direct", "pattern": "direct_sdk"},
    "current_costs": {"monthly_ai_spend": 450, "services_detected": ["Vertex AI Predictions"], "source": "billing_data"},
}


def _convert(run: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ADAPTER_PATH), "convert", "--legacy", str(run / "ai-workload-profile.json"),
         "--out", str(run / ".bma-input" / "ai-workload-profile.json"),
         "--sidecar", str(run / ".bma-input" / "ai-workload-sidecar.json")],
        capture_output=True, text=True,
    )


def _validate_bma_input(run: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BMA_RUNTIME), "validate-profile",
         "--profile", str(run / ".bma-input" / "ai-workload-profile.json"),
         "--sidecar", str(run / ".bma-input" / "ai-workload-sidecar.json")],
        capture_output=True, text=True,
    )


def test_convert_merges_into_bma_discovered_profile_and_sidecar_vagmur_repro(tmp_path):
    run = tmp_path / "run"
    (run / ".bma-input").mkdir(parents=True)
    (run / "ai-workload-profile.json").write_text(json.dumps(VERTEX_SEED_LEGACY), encoding="utf-8")
    (run / ".bma-input" / "ai-workload-profile.json").write_text(json.dumps(VAGMUR_BMA_PROFILE), encoding="utf-8")
    (run / ".bma-input" / "ai-workload-sidecar.json").write_text(json.dumps(VAGMUR_SIDECAR), encoding="utf-8")
    converted = _convert(run)
    assert converted.returncode == 0, converted.stderr
    profile = json.loads((run / ".bma-input" / "ai-workload-profile.json").read_text(encoding="utf-8"))
    sources = {(source["provider"], source["source_service"]): source for source in profile["ai_sources"]}
    assert set(sources) == {("google", "vertex_ai"), ("openai", "openai_api")}
    openai = sources[("openai", "openai_api")]
    assert openai["models"] == ["gpt-4o"]
    assert openai["model_observations"][0]["evidence"] == [{"provenance": "code", "confidence": "high", "detail": "src/ai.py:9"}]
    google = sources[("google", "vertex_ai")]
    assert google["models"] == ["gemini-2.5-pro"]
    assert google["model_observations"][0]["evidence"] == [{"provenance": "iac", "confidence": "high", "detail": "google_vertex_ai_endpoint.chat"}]
    sidecar = json.loads((run / ".bma-input" / "ai-workload-sidecar.json").read_text(encoding="utf-8"))
    costs = sidecar["observed_costs"]
    assert costs["monthly_ai_spend"] == 555
    assert costs["source"] == "mixed"
    assert costs["services_detected"] == ["Vertex AI Predictions", "OpenAI chat"]
    assert costs["breakdown"] == [
        {"provider": "google", "monthly_spend": 450, "source": "billing_data"},
        {"provider": "openai", "monthly_spend": 105, "source": "openai_usage_api"},
    ]
    assert "conflicting_sources" not in costs
    assert sidecar["workloads"] == VAGMUR_SIDECAR["workloads"]
    assert sidecar["integration_context"] == {"pattern": "direct_sdk"}
    assert sidecar["profile_origin"] == {"terraform_primary": True}
    validated = _validate_bma_input(run)
    assert validated.returncode == 0, validated.stderr


def _load_runtime(name: str):
    spec = importlib.util.spec_from_file_location(name, BMA_RUNTIME)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    return runtime


def _bma_delegated_write(runtime, run: Path, writes: list[tuple[str, dict]]) -> None:
    """One documented BMA boundary write (owner BMA, expected_sha256 of the exact prior bytes when the file exists)."""
    rows = []
    for relative, payload in writes:
        row = {"phase": "discover", "path": relative, "payload": payload, "logical_owner": "bedrock-migration-assessment"}
        target = run / relative
        if target.exists():
            row["expected_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        rows.append(row)
    runtime.execute_contract({
        "schema_version": 1, "mode": "delegated", "scenario": "delegated-e2e", "run_dir": str(run),
        "delegated_route": "combined", "state": {"phases": {}}, "writes": rows,
    })


def test_delegated_flow_end_to_end_keeps_every_provider_model_and_dollar(tmp_path):
    """Findings A and B together: adapter convert, BMA Step 8, usage-API Step 4, adapter convert again. No data loss."""
    runtime = _load_runtime("bma_runtime_delegated_e2e")
    run = tmp_path / "run"
    (run / ".bma-input").mkdir(parents=True)
    profile_path = run / ".bma-input" / "ai-workload-profile.json"
    sidecar_path = run / ".bma-input" / "ai-workload-sidecar.json"
    (run / "ai-workload-profile.json").write_text(json.dumps(VERTEX_SEED_LEGACY), encoding="utf-8")
    # 1. GCP IaC/Vertex seed converted into an empty .bma-input/.
    assert _convert(run).returncode == 0
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert [(source["provider"], source["models"]) for source in profile["ai_sources"]] == [("google", ["gemini-2.5-pro"])]
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["observed_costs"] == VERTEX_SEED_LEGACY["current_costs"]
    # 2. BMA discover-app-code Step 8 adds the gpt-4o source (union by pair, IaC pair kept) and its workload row.
    profile["ai_sources"].append(copy.deepcopy(VAGMUR_BMA_PROFILE["ai_sources"][0]))
    sidecar["workloads"] = copy.deepcopy(VAGMUR_SIDECAR["workloads"])
    _bma_delegated_write(runtime, run, [(".bma-input/ai-workload-profile.json", profile), (".bma-input/ai-workload-sidecar.json", sidecar)])
    # 3. Usage-API Step 4 item 1: different provider -> sum, source mixed, per-provider breakdown.
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar["observed_costs"] = copy.deepcopy(VAGMUR_SIDECAR["observed_costs"])
    _bma_delegated_write(runtime, run, [(".bma-input/ai-workload-sidecar.json", sidecar)])
    # 4. The documented order is sub-discoveries first, then convert: the real-world final adapter write.
    assert _convert(run).returncode == 0
    final_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    sources = {(source["provider"], source["source_service"]): source for source in final_profile["ai_sources"]}
    assert set(sources) == {("google", "vertex_ai"), ("openai", "openai_api")}
    assert sources[("google", "vertex_ai")]["models"] == ["gemini-2.5-pro"]
    assert sources[("google", "vertex_ai")]["model_observations"][0]["evidence"][0]["provenance"] == "iac"
    assert sources[("openai", "openai_api")]["models"] == ["gpt-4o"]
    assert sources[("openai", "openai_api")]["model_observations"][0]["evidence"] == [
        {"provenance": "code", "confidence": "high", "detail": "src/ai.py:9"},
    ]
    final_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    costs = final_sidecar["observed_costs"]
    assert costs["monthly_ai_spend"] == 555 and costs["source"] == "mixed"
    assert costs["breakdown"] == [
        {"provider": "google", "monthly_spend": 450, "source": "billing_data"},
        {"provider": "openai", "monthly_spend": 105, "source": "openai_usage_api"},
    ]
    assert "conflicting_sources" not in costs
    assert final_sidecar["workloads"] == VAGMUR_SIDECAR["workloads"]
    assert final_sidecar["profile_origin"] == {"terraform_primary": True}
    validated = _validate_bma_input(run)
    assert validated.returncode == 0, validated.stderr
    # Idempotent: a third convert leaves both files byte-identical.
    profile_bytes, sidecar_bytes = profile_path.read_bytes(), sidecar_path.read_bytes()
    assert _convert(run).returncode == 0
    assert profile_path.read_bytes() == profile_bytes
    assert sidecar_path.read_bytes() == sidecar_bytes


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


# P4 regression: the v2 app's legacy profile (Gemini text, Gemini image, GPT-4o, and text-embedding-3-small).
V2_SHAPED_LEGACY = {
    "current_costs": {"monthly_ai_spend": 700, "services_detected": ["Google Gen AI", "OpenAI API"], "source": "code_estimate"},
    "detection_signals": [
        {"confidence": 0.98, "evidence": "lib/gemini.ts line 1", "method": "code", "pattern": "@google/genai import"},
        {"confidence": 0.98, "evidence": "lib/openai.ts line 1", "method": "code", "pattern": "openai SDK import"},
    ],
    "infrastructure": [],
    "integration": {"capabilities_summary": {"text_generation": True, "image_generation": True, "embeddings": True},
                    "gateway_type": "direct", "pattern": "direct_sdk", "primary_sdk": "@google/genai", "languages": ["typescript"]},
    "metadata": {"profile_source": "application_code", "report_date": "2026-02-26"},
    "models": [
        {"capabilities_used": ["text_generation"], "detected_via": ["code"], "model_id": "gemini-2.5-flash", "service": "vertex_ai_generative",
         "evidence": [{"file": "lib/gemini.ts", "line": 5, "source": "code"}], "usage_context": "Search intent extraction"},
        {"capabilities_used": ["image_generation"], "detected_via": ["code"], "model_id": "gemini-3.1-flash-image", "service": "vertex_ai_generative",
         "evidence": [{"file": "lib/imagen.ts", "line": 5, "source": "code"}], "usage_context": "Beach image generation"},
        {"capabilities_used": ["text_generation"], "detected_via": ["code"], "model_id": "gpt-4o", "service": "openai_api",
         "evidence": [{"file": "lib/openai.ts", "line": 4, "source": "code"}], "usage_context": "Review summarization"},
        {"capabilities_used": ["embeddings"], "detected_via": ["code"], "model_id": "text-embedding-3-small", "service": "openai_api",
         "evidence": [{"file": "lib/openai.ts", "line": 9, "source": "code"}], "usage_context": "Review embeddings for search"},
    ],
    "summary": {"ai_source": "both", "confidence_level": "very_high", "inferred_from_iac": False, "overall_confidence": 0.98},
}


def test_v2_shaped_input_writes_side_file_and_design_names_titan_v2(tmp_path):
    legacy_path = tmp_path / "legacy.json"
    out_path = tmp_path / ".bma-input" / "ai-workload-profile.json"
    sidecar_path = tmp_path / ".bma-input" / "ai-workload-sidecar.json"
    legacy_path.write_text(json.dumps(V2_SHAPED_LEGACY), encoding="utf-8")
    converted = subprocess.run(
        [sys.executable, str(ADAPTER_PATH), "convert", "--legacy", str(legacy_path), "--out", str(out_path), "--sidecar", str(sidecar_path)],
        capture_output=True, text=True,
    )
    assert converted.returncode == 0, converted.stderr
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["integration_context"]["primary_sdk"] == "@google/genai"
    assert sidecar["integration_context"]["languages"] == ["typescript"]
    contexts = {item["model_id"]: item for item in sidecar["model_context"]}
    assert set(contexts) == {"gemini-2.5-flash", "gemini-3.1-flash-image", "gpt-4o", "text-embedding-3-small"}
    assert contexts["text-embedding-3-small"]["capabilities_used"] == ["embeddings"]
    document = json.loads(out_path.read_text(encoding="utf-8"))
    openai = [source for source in document["ai_sources"] if source["provider"] == "openai"][0]
    assert "text-embedding-3-small" in openai["models"]
    assert [item["model_family"] for item in openai["model_observations"] if item["normalized_model"] == "text-embedding-3-small"] == ["embedding"]
    validated = subprocess.run(
        [sys.executable, str(BMA_RUNTIME), "validate-profile", "--profile", str(out_path), "--sidecar", str(sidecar_path)],
        capture_output=True, text=True,
    )
    assert validated.returncode == 0, validated.stderr
    design = subprocess.run(
        [sys.executable, str(BMA_RUNTIME), "design-target", "--capability", "embedding"],
        capture_output=True, text=True,
    )
    assert design.returncode == 0, design.stderr
    assert json.loads(design.stdout)["target_bedrock_model"] == "amazon.titan-embed-text-v2:0"
