"""Contract tests for the target-only, canonical aws-design-ai.json contract.

Pins the schema's self-validity and proves that `metadata.ai_sources[]` / `metadata.gateways[]`
project exactly into #415's `ai-workload-profile.schema.json` shape, reusing #415's own
semantic-assertion helper (`_assert_profile_semantics`) as the oracle — the same way #415
reused #410's `test_ai_migration_matrix_contracts.py` helpers. Target-only: no producer emits
this shape yet (`design-ai.md` is unchanged in both skills); no runtime behavior is asserted.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = PLUGIN_ROOT / "fixtures" / "aws-design-ai"
DESIGN_AI_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "aws-design-ai.schema.json"
VALIDATOR_PATH = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
MANIFEST_PATH = PLUGIN_ROOT / "scripts" / "artifact-contracts.json"
WORKLOAD_PROFILE_TEST_PATH = Path(__file__).resolve().parent / "test_ai_workload_profile_contracts.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("aws_design_ai__validator", VALIDATOR_PATH)
# #415's own test module: imports/executes it to reuse _assert_profile_semantics as the oracle,
# exactly as #415 reused #410's test_ai_migration_matrix_contracts.py (MATRIX) module.
WORKLOAD_PROFILE = _load_module("aws_design_ai__workload_profile_contracts", WORKLOAD_PROFILE_TEST_PATH)

POSITIVE_FIXTURES = sorted(FIXTURE_ROOT.glob("*/aws-design-ai.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _design_ai_schema() -> dict:
    return _load(DESIGN_AI_SCHEMA)


def _design_ai_findings(design: dict) -> list:
    findings = []
    VALIDATOR.validate_json_schema(_design_ai_schema(), design, "", "design", str(DESIGN_AI_SCHEMA), findings)
    return findings


def _project_to_profile(design: dict) -> dict:
    """The deterministic projection: metadata.ai_sources[]/gateways[] already carry the exact
    #415-shaped fields (provider, source_service, model_families, model_evidence, models,
    model_observations for sources; product/type/upstream_evidence/upstreams for gateways) —
    this wraps them in a synthetic ai-workload-profile.json skeleton purely so #415's own
    schema/semantics helpers can be reused unmodified."""
    return {
        "schema_version": "1.0",
        "ai_sources": copy.deepcopy(design["metadata"]["ai_sources"]),
        "gateways": copy.deepcopy(design["metadata"]["gateways"]),
    }


# --------------------------------------------------------------------------- schema self-validity

def test_schema_has_no_unsupported_keywords() -> None:
    assert VALIDATOR.unsupported_keywords(_design_ai_schema()) == []


def test_schema_is_valid_json_and_draft07_shaped() -> None:
    schema = _design_ai_schema()
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["type"] == "object"


def test_metadata_rejects_the_retired_single_scalar_ai_source() -> None:
    """additionalProperties: false on the metadata object means a vestigial scalar ai_source
    field (the retired #386-era shape) is rejected outright, not merely undocumented."""
    schema = _design_ai_schema()
    assert schema["definitions"]["metadata"]["additionalProperties"] is False
    assert "ai_source" not in schema["definitions"]["metadata"]["properties"]


# --------------------------------------------------------------------------- positive fixtures

@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_validate_against_design_ai_schema(fixture_path: Path) -> None:
    design = _load(fixture_path)
    assert _design_ai_findings(design) == []


@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_project_exactly_into_pr415_semantics(fixture_path: Path) -> None:
    design = _load(fixture_path)
    profile = _project_to_profile(design)
    assert WORKLOAD_PROFILE._profile_findings(profile) == []
    WORKLOAD_PROFILE._assert_profile_semantics(profile)
    # `_assert_profile_semantics` checks source observations and duplicate upstream
    # identities, but not whether a gateway upstream's retained models/families actually
    # match its resolved source's full set — that stronger correspondence oracle lives one
    # layer up, in #410's `_assert_scenario_semantics`. Run it here too so every POSITIVE
    # fixture is protected by the same oracle the dedicated negative mutation test already
    # proves is strict (`test_dropped_model_under_a_resolved_gateway_upstream_is_rejected`),
    # not only the weaker profile-level check.
    WORKLOAD_PROFILE.MATRIX._assert_scenario_semantics(
        WORKLOAD_PROFILE._project_to_scenario(profile)
    )


def test_multi_provider_fixture_carries_two_simultaneous_direct_sources() -> None:
    """Exercises the multi-provider case: one Anthropic-sourced + one OpenAI-sourced
    design_block in a single aws-design-ai.json, with no gateway involved."""
    design = _load(FIXTURE_ROOT / "multi-provider-direct" / "aws-design-ai.json")
    providers = {s["provider"] for s in design["metadata"]["ai_sources"]}
    assert providers == {"anthropic", "openai"}
    assert not design["metadata"]["gateways"]
    assert len(design["design_blocks"]) == 2


def test_gateway_fixture_carries_multi_upstream_openrouter_fronting_two_providers() -> None:
    """Exercises the gateway-fronted multi-upstream case: one OpenRouter gateway fronting
    Anthropic (two models) and OpenAI simultaneously."""
    design = _load(FIXTURE_ROOT / "openrouter-gateway-multi-upstream" / "aws-design-ai.json")
    gateways = design["metadata"]["gateways"]
    assert len(gateways) == 1
    upstream_providers = {u["provider"] for u in gateways[0]["upstreams"]}
    assert upstream_providers == {"anthropic", "openai"}
    claude = next(s for s in design["metadata"]["ai_sources"] if s["provider"] == "anthropic")
    assert len(claude["models"]) == 2
    assert len(design["design_blocks"]) == 3


# --------------------------------------------------------------------------- negative mutations

def _base_design() -> dict:
    return copy.deepcopy(_load(FIXTURE_ROOT / "multi-provider-direct" / "aws-design-ai.json"))


def test_old_single_scalar_ai_source_shape_is_rejected() -> None:
    """The retired Azure-only shape: a single scalar metadata.ai_source string standing in
    for the multi-provider reality, instead of metadata.ai_sources[]/gateways[]. Proves the
    sentinel single-identity pattern is actually retired by this contract, not just
    redocumented — directly answering #415's own Cursor-review precedent of locking a negative
    case with an assertion rather than a fixture directory."""
    design = _base_design()
    del design["metadata"]["ai_sources"]
    del design["metadata"]["gateways"]
    design["metadata"]["ai_source"] = "both"
    assert _design_ai_findings(design) != []


def test_old_single_scalar_ai_source_with_one_provider_is_also_rejected() -> None:
    """Even a single-valued old-shape scalar (not just the 'both' sentinel) is rejected,
    because additionalProperties: false on metadata means ai_sources[]/gateways[] are
    required and ai_source is unknown — the scalar shape cannot coexist with the new one."""
    design = _base_design()
    del design["metadata"]["ai_sources"]
    del design["metadata"]["gateways"]
    design["metadata"]["ai_source"] = "anthropic"
    assert _design_ai_findings(design) != []


def test_duplicate_ai_source_identity_is_rejected() -> None:
    design = _base_design()
    design["metadata"]["ai_sources"].append(copy.deepcopy(design["metadata"]["ai_sources"][0]))
    assert _design_ai_findings(design) != []


def test_openrouter_as_a_direct_provider_is_rejected() -> None:
    design = _base_design()
    design["metadata"]["ai_sources"][0]["provider"] = "openrouter"
    assert _design_ai_findings(design) != []


def test_dropped_model_under_a_resolved_gateway_upstream_is_rejected() -> None:
    design = _load(FIXTURE_ROOT / "openrouter-gateway-multi-upstream" / "aws-design-ai.json")
    profile = _project_to_profile(design)
    upstream = next(
        u for u in profile["gateways"][0]["upstreams"] if u["provider"] == "anthropic"
    )
    upstream["model_families"][0]["models"].remove("claude-3-haiku-20240307")
    with pytest.raises(AssertionError):
        WORKLOAD_PROFILE.MATRIX._assert_scenario_semantics(
            WORKLOAD_PROFILE._project_to_scenario(profile)
        )


def test_design_block_without_exactly_one_target_is_rejected() -> None:
    design = _base_design()
    design["design_blocks"][0]["target_bedrock_model"] = None
    assert _design_ai_findings(design) != []

    design = _base_design()
    design["design_blocks"][0]["target_aws_service"] = "textract"
    assert _design_ai_findings(design) != []


def test_fabricated_unknown_model_in_metadata_is_rejected() -> None:
    design = _base_design()
    design["metadata"]["ai_sources"][0]["models"] = ["unknown"]
    design["metadata"]["ai_sources"][0]["model_observations"][0]["normalized_model"] = "unknown"
    assert _design_ai_findings(design) != []


def test_observed_source_with_empty_model_observations_is_rejected_by_profile_semantics() -> None:
    """The schema's observed branch (model_evidence: 'observed') now requires
    model_observations[] non-empty, in addition to models[] non-empty, so clearing
    model_observations on an observed source is rejected directly by the schema. The
    projected-profile semantic oracle (#415's _assert_profile_semantics, reused unmodified)
    remains as defense-in-depth for the exact-correspondence check (models[] keys ==
    model_observations[] keys) that minItems alone cannot express (Draft-07 cannot express
    cross-array correspondence without $data)."""
    design = _base_design()
    anthropic = next(s for s in design["metadata"]["ai_sources"] if s["provider"] == "anthropic")
    anthropic["model_observations"] = []
    assert _design_ai_findings(design) != []  # schema now rejects this directly
    profile = _project_to_profile(design)
    with pytest.raises(AssertionError):
        WORKLOAD_PROFILE._assert_profile_semantics(profile)


# --------------------------------------------------------------------------- model traceability


def _assert_model_traceability(design: dict) -> None:
    """Every design_blocks[].model_id MUST trace to a metadata.ai_sources[] entry (directly)
    or a metadata.gateways[].upstreams[] entry (through a gateway upstream model_family) —
    schema-design-aws-ai.md's model_id provenance rule. Draft-07 cannot express this
    cross-array correspondence without $data, so this helper is the lock, mirroring the
    pattern _assert_profile_semantics already established for ai_sources[]/gateways[]
    internal consistency."""
    reachable_models: set[str] = set()
    for source in design["metadata"]["ai_sources"]:
        reachable_models.update(source["models"])
    for gateway in design["metadata"]["gateways"]:
        for upstream in gateway["upstreams"]:
            for family in upstream["model_families"]:
                reachable_models.update(family["models"])
    for block in design["design_blocks"]:
        assert block["model_id"] in reachable_models, (
            f"design_blocks[] model_id {block['model_id']!r} traces to no "
            f"metadata.ai_sources[] entry or metadata.gateways[] upstream"
        )


@pytest.mark.parametrize("fixture_path", POSITIVE_FIXTURES, ids=lambda p: p.parent.name)
def test_positive_fixtures_have_traceable_design_block_models(fixture_path: Path) -> None:
    design = _load(fixture_path)
    _assert_model_traceability(design)


def test_design_block_naming_an_untraceable_model_is_rejected() -> None:
    design = _base_design()
    design["design_blocks"][0]["model_id"] = "made-up-model"
    with pytest.raises(AssertionError):
        _assert_model_traceability(design)


def test_model_reachable_only_through_gateway_upstream_passes_traceability() -> None:
    """claude-3-haiku-20240307 is removed from the Anthropic ai_sources[] entry's models
    (and its matching model_observations entry, to keep the source internally consistent)
    but remains on the gateway upstream's model_families[].models — proving the
    gateway-upstream-walk branch of _assert_model_traceability, not just the direct
    ai_sources[] branch, is what makes the design_blocks[] row naming it traceable."""
    design = copy.deepcopy(_load(FIXTURE_ROOT / "openrouter-gateway-multi-upstream" / "aws-design-ai.json"))
    anthropic = next(s for s in design["metadata"]["ai_sources"] if s["provider"] == "anthropic")
    anthropic["models"].remove("claude-3-haiku-20240307")
    anthropic["model_observations"] = [
        obs for obs in anthropic["model_observations"] if obs["normalized_model"] != "claude-3-haiku-20240307"
    ]
    _assert_model_traceability(design)  # does NOT raise


def test_model_removed_from_both_source_and_gateway_upstream_fails_traceability() -> None:
    """Starting from the same base as the gateway-upstream-only case, also drop
    claude-3-haiku-20240307 from the gateway upstream's model_families[].models — now no
    ai_sources[] entry or gateway upstream carries it, so the design_blocks[] row naming it
    must be rejected."""
    design = copy.deepcopy(_load(FIXTURE_ROOT / "openrouter-gateway-multi-upstream" / "aws-design-ai.json"))
    anthropic = next(s for s in design["metadata"]["ai_sources"] if s["provider"] == "anthropic")
    anthropic["models"].remove("claude-3-haiku-20240307")
    anthropic["model_observations"] = [
        obs for obs in anthropic["model_observations"] if obs["normalized_model"] != "claude-3-haiku-20240307"
    ]
    for gateway in design["metadata"]["gateways"]:
        for upstream in gateway["upstreams"]:
            if upstream["provider"] == "anthropic":
                for family in upstream["model_families"]:
                    if "claude-3-haiku-20240307" in family["models"]:
                        family["models"].remove("claude-3-haiku-20240307")
    with pytest.raises(AssertionError):
        _assert_model_traceability(design)


# --------------------------------------------------------------------------- manifest shadowing (Azure)


def _azure_scalar_design() -> dict:
    """A document matching Azure's OLD single-scalar metadata.ai_source shape — the shape
    Azure's design-ai.md actually emits today (schema-design-aws-ai.md, restored from #415's
    head). Everything else matches the canonical top-level shape so only `metadata` differs."""
    design = _base_design()
    design["metadata"] = {
        "ai_source": "azure_openai",
        "bedrock_models_selected": design["metadata"]["bedrock_models_selected"],
        "regional_validation": design["metadata"]["regional_validation"],
    }
    return design


def test_azure_scalar_ai_source_validates_under_the_restored_azure_shape_contract() -> None:
    """Validated AS skill=azure-to-aws, the scalar document follows the restored Shape
    contract at skills/azure-to-aws/references/shared/schema-design-aws-ai.md and is
    accepted — Azure's own manifest entry shadows the shared target-only schema."""
    manifest = VALIDATOR.load_manifest(MANIFEST_PATH)
    findings: list = []
    contracts = VALIDATOR.build_contracts(manifest, "azure-to-aws", findings)
    matched = [c for c in contracts if c.artifact_glob == "aws-design-ai.json"]
    assert len(matched) == 1
    assert matched[0].shape is not None, (
        "azure-to-aws must shadow the shared aws-design-ai.json schema with its own Shape "
        "contract, or Azure's actual scalar emission is validated against the target-only "
        "schema and rejected"
    )
    design = _azure_scalar_design()
    design_findings: list = []
    VALIDATOR.validate_shape(matched[0].shape.root, design, "", "design", matched[0].shape.label, design_findings)
    assert design_findings == []


def test_azure_scalar_ai_source_fails_the_target_only_schema_with_no_skill() -> None:
    """The SAME scalar document, validated with no skill (shared contracts only), fails the
    target schema: additionalProperties:false on metadata plus missing
    ai_sources/gateways/regional_validation-shaped required fields."""
    manifest = VALIDATOR.load_manifest(MANIFEST_PATH)
    findings: list = []
    contracts = VALIDATOR.build_contracts(manifest, None, findings)
    matched = [c for c in contracts if c.artifact_glob == "aws-design-ai.json"]
    assert len(matched) == 1
    assert matched[0].json_schema is not None
    design = _azure_scalar_design()
    design_findings: list = []
    VALIDATOR.validate_json_schema(
        matched[0].json_schema, design, "", "design", matched[0].json_schema_path, design_findings
    )
    assert design_findings != []


# --------------------------------------------------------------------------- manifest shadowing (GCP)


def _gcp_scalar_design() -> dict:
    """A document matching GCP's CURRENT producer envelope — the shape `design-ai.md`'s own
    "top-level fields" table documents and `design-ai.md`'s Validation Checklist requires,
    not the canonical target shape with only `metadata` swapped. Per that table, `metadata`
    nests `phase`, `focus`, `ai_source`, `bedrock_models_selected`, and `timestamp` (GCP does
    NOT split those across the top level and `metadata` the way the canonical/Azure shape
    does), and `source_profile` stays top-level alongside `design_blocks`/`ai_architecture`/
    `regional_warnings`/`multi_model_warnings`/`agentic_design`. One `design_blocks[]` row
    uses a traditional-AI capability so `honest_assessment: "not_applicable"` is exercised
    (design-ai.md's Validation Checklist requires it on exactly those rows)."""
    return {
        "metadata": {
            "phase": "design",
            "focus": "ai",
            "ai_source": "gemini",
            "bedrock_models_selected": ["anthropic.claude-sonnet-5"],
            "timestamp": "2026-10-06T00:00:00Z",
        },
        "source_profile": "ai-workload-profile.json",
        "design_blocks": [
            {
                "workload_id": "wl_doc1",
                "model_id": "gemini-1.5-pro-vision",
                "target_bedrock_model": None,
                "target_aws_service": "textract",
                "capability": "document_extraction",
                "capability_confidence": "high",
                "rationale": "Traditional-AI capability swap, not a model migration.",
                "confidence_warning": None,
                "honest_assessment": "not_applicable",
            }
        ],
        "ai_architecture": {},
        "regional_warnings": [],
        "multi_model_warnings": [],
        "agentic_design": None,
    }


def test_gcp_scalar_ai_source_validates_under_the_gcp_shape_contract() -> None:
    """Validated AS skill=gcp-to-aws, the scalar document follows the GCP Shape contract at
    skills/gcp-to-aws/references/shared/schema-design-aws-ai.md and is accepted — GCP's own
    manifest entry shadows the shared target-only schema, mirroring Azure's entry."""
    manifest = VALIDATOR.load_manifest(MANIFEST_PATH)
    findings: list = []
    contracts = VALIDATOR.build_contracts(manifest, "gcp-to-aws", findings)
    matched = [c for c in contracts if c.artifact_glob == "aws-design-ai.json"]
    assert len(matched) == 1
    assert matched[0].shape is not None, (
        "gcp-to-aws must shadow the shared aws-design-ai.json schema with its own Shape "
        "contract, or GCP's actual scalar emission is validated against the target-only "
        "schema and rejected"
    )
    design = _gcp_scalar_design()
    design_findings: list = []
    VALIDATOR.validate_shape(matched[0].shape.root, design, "", "design", matched[0].shape.label, design_findings)
    assert design_findings == []


def test_gcp_scalar_ai_source_fails_the_target_only_schema_with_no_skill() -> None:
    """The SAME scalar document, validated with no skill (shared contracts only), fails the
    target schema: additionalProperties:false on metadata plus missing
    ai_sources/gateways/regional_validation-shaped required fields."""
    manifest = VALIDATOR.load_manifest(MANIFEST_PATH)
    findings: list = []
    contracts = VALIDATOR.build_contracts(manifest, None, findings)
    matched = [c for c in contracts if c.artifact_glob == "aws-design-ai.json"]
    assert len(matched) == 1
    assert matched[0].json_schema is not None
    design = _gcp_scalar_design()
    design_findings: list = []
    VALIDATOR.validate_json_schema(
        matched[0].json_schema, design, "", "design", matched[0].json_schema_path, design_findings
    )
    assert design_findings != []
