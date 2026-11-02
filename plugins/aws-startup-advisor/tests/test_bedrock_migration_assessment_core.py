"""Contract tests for the bedrock-migration-assessment skill: profile intake, independence, and Clarify parity."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
BMA = SKILLS / "bedrock-migration-assessment"
GCP_CLARIFY = SKILLS / "gcp-to-aws" / "references" / "phases" / "clarify" / "clarify-ai-only.md"
BMA_CLARIFY = BMA / "references" / "phases" / "clarify" / "clarify-ai-only.md"
BMA_PREFERENCES_SCHEMA = BMA / "references" / "shared" / "schema-preferences.md"
CANONICAL_PROFILE_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "ai-workload-profile.schema.json"
CANONICAL_DESIGN_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "aws-design-ai.schema.json"
LEGACY_PROFILE_DOC = SKILLS / "gcp-to-aws" / "references" / "shared" / "schema-discover-ai.md"
PROFILE_FIXTURES = sorted((PLUGIN_ROOT / "fixtures" / "ai-workload-profiles").glob("*/ai-workload-profile.json"))
RUN_FIXTURE = PLUGIN_ROOT / "fixtures" / "bma-ai-only-clarify"
VALIDATOR_SCRIPT = BMA / "scripts" / "validate-ai-profile.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BMA_VALIDATOR = _load_module("bma_validate_ai_profile", VALIDATOR_SCRIPT)
ARTIFACT_VALIDATOR = _load_module("bma_core__artifact_validator", PLUGIN_ROOT / "scripts" / "validate-artifacts.py")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fixture(name: str) -> dict:
    return _load(PLUGIN_ROOT / "fixtures" / "ai-workload-profiles" / name / "ai-workload-profile.json")


def _rejection(profile) -> str:
    with pytest.raises(BMA_VALIDATOR.ProfileRejected) as info:
        BMA_VALIDATOR.validate_profile(profile)
    return info.value.code


# --------------------------------------------------------------------------- contract and the confirmed decision

def test_skill_schema_copy_is_byte_identical_to_canonical() -> None:
    assert BMA_VALIDATOR.SCHEMA_PATH.read_bytes() == CANONICAL_PROFILE_SCHEMA.read_bytes()


@pytest.mark.parametrize("schema_path", [CANONICAL_PROFILE_SCHEMA, CANONICAL_DESIGN_SCHEMA], ids=lambda p: p.name)
def test_confirmed_is_not_a_confidence_level(schema_path: Path) -> None:
    confidence = _load(schema_path)["definitions"]["confidence"]
    assert confidence["enum"] == ["high", "medium", "low"]
    assert "user_confirmed" in _load(schema_path)["definitions"]["provenance"]["enum"]


def test_confirmed_confidence_is_rejected_by_name() -> None:
    profile = _fixture("ai-only-multi-direct")
    profile["ai_sources"][0]["model_observations"][0]["evidence"][0]["confidence"] = "confirmed"
    assert _rejection(profile) == "confirmed_confidence_rejected"


def test_user_confirmed_evidence_must_be_high_confidence() -> None:
    profile = _fixture("ai-only-multi-direct")
    evidence = profile["ai_sources"][0]["model_observations"][0]["evidence"][0]
    evidence.update({"provenance": "user_confirmed", "confidence": "medium"})
    assert _rejection(profile) == "user_confirmed_requires_high"
    evidence["confidence"] = "high"
    assert BMA_VALIDATOR.validate_profile(profile)["ok"] is True


# --------------------------------------------------------------------------- accepted profiles

@pytest.mark.parametrize("fixture_path", PROFILE_FIXTURES, ids=lambda p: p.parent.name)
def test_every_neutral_fixture_is_accepted_without_a_sidecar(fixture_path: Path) -> None:
    result = BMA_VALIDATOR.validate_profile(_load(fixture_path))
    assert result["ok"] is True
    assert set(result) == {"ok", "schema_version", "ai_sources", "gateways", "models_extractable"}


@pytest.mark.parametrize("fixture_path", PROFILE_FIXTURES, ids=lambda p: p.parent.name)
def test_skill_validator_agrees_with_the_plugin_schema_validator(fixture_path: Path) -> None:
    findings: list = []
    schema = _load(CANONICAL_PROFILE_SCHEMA)
    ARTIFACT_VALIDATOR.validate_json_schema(schema, _load(fixture_path), "", "profile", "schema", findings)
    assert findings == []
    assert BMA_VALIDATOR._schema_errors(schema, _load(fixture_path), schema) == []


def test_openrouter_multi_upstream_summary_keeps_every_association() -> None:
    result = BMA_VALIDATOR.validate_profile(_fixture("openrouter-multi-upstream"))
    by_key = {(s["provider"], s["source_service"]): s for s in result["ai_sources"]}
    assert set(by_key) == {("anthropic", "anthropic_api"), ("google", "vertex_ai"), ("openai", "openai_api")}
    assert all(s["via_gateways"] == ["openrouter"] for s in by_key.values())
    claude = [m["model"] for m in by_key[("anthropic", "anthropic_api")]["models"]]
    assert claude == ["claude-3-5-sonnet-20240620", "claude-3-haiku-20240307"]
    assert result["models_extractable"] is False


def test_direct_and_azure_openai_stay_distinct() -> None:
    result = BMA_VALIDATOR.validate_profile(_fixture("openai-direct-and-azure-openai"))
    services = sorted(s["source_service"] for s in result["ai_sources"] if s["provider"] == "openai")
    assert services == ["azure_openai", "openai_api"]


def test_unresolved_gateway_is_reported_as_unresolved() -> None:
    result = BMA_VALIDATOR.validate_profile(_fixture("openrouter-unresolved"))
    assert result["gateways"] == [{"product": "openrouter", "type": "llm_router", "upstream_evidence": "unresolved"}]


def test_models_are_extractable_only_when_every_model_has_high_confidence_evidence() -> None:
    profile = _fixture("ai-only-multi-direct")
    assert BMA_VALIDATOR.validate_profile(profile)["models_extractable"] is True
    for entry in profile["ai_sources"][0]["model_observations"][0]["evidence"]:
        entry["confidence"] = "medium"
    assert BMA_VALIDATOR.validate_profile(profile)["models_extractable"] is False


def test_not_observed_models_are_never_extractable() -> None:
    profile = {"schema_version": "1.0", "gateways": [], "ai_sources": [{
        "provider": "openai", "source_service": "openai_api", "model_families": ["gpt"],
        "model_evidence": "not_observed", "models": [], "model_observations": [],
    }]}
    assert BMA_VALIDATOR.validate_profile(profile)["models_extractable"] is False


# --------------------------------------------------------------------------- rejected profiles

def test_legacy_gcp_profile_from_its_own_contract_document_is_rejected_by_name() -> None:
    blocks = re.findall(r"```json\n(.*?)```", LEGACY_PROFILE_DOC.read_text(encoding="utf-8"), re.S)
    legacy = json.loads(blocks[0])
    with pytest.raises(BMA_VALIDATOR.ProfileRejected) as info:
        BMA_VALIDATOR.validate_profile(legacy)
    assert info.value.code == "legacy_profile_rejected"
    assert "'metadata'" in info.value.detail


def test_legacy_field_inside_a_neutral_source_is_rejected_by_path() -> None:
    profile = _fixture("ai-only-multi-direct")
    profile["ai_sources"][1]["model_id"] = "gemini-pro"
    with pytest.raises(BMA_VALIDATOR.ProfileRejected) as info:
        BMA_VALIDATOR.validate_profile(profile)
    assert info.value.code == "legacy_profile_rejected"
    assert "ai_sources[1].model_id" in info.value.detail


def _with(fixture: str, mutate) -> dict:
    profile = _fixture(fixture)
    mutate(profile)
    return profile


@pytest.mark.parametrize(
    ("fixture", "mutate", "code"),
    [
        ("ai-only-multi-direct", lambda p: p["ai_sources"].append(
            {**copy.deepcopy(p["ai_sources"][0]), "model_families": ["claude", "claude-next"]}), "duplicate_ai_source"),
        ("ai-only-multi-direct", lambda p: p["ai_sources"][0]["models"].append("claude-3-opus-20240229"), "observation_mismatch"),
        ("ai-only-multi-direct", lambda p: p["ai_sources"][0]["model_observations"][0].update(model_family="gpt"),
         "observation_family_mismatch"),
        ("openrouter-multi-upstream", lambda p: p["gateways"][0]["upstreams"][0].update(source_service="bedrock"),
         "unmatched_gateway_upstream"),
        ("openrouter-multi-upstream", lambda p: p["gateways"][0]["upstreams"].append(
            {k: v for k, v in copy.deepcopy(p["gateways"][0]["upstreams"][0]).items() if k != "source_service"}),
         "duplicate_gateway_upstream"),
        ("openrouter-multi-upstream", lambda p: p["gateways"][0]["upstreams"][0]["model_families"][0]["models"].pop(),
         "upstream_models_mismatch"),
        ("openrouter-multi-upstream", lambda p: p["gateways"][0]["upstreams"][0]["model_families"][0].update(family="gpt"),
         "upstream_family_mismatch"),
        ("ai-only-multi-direct", lambda p: p["ai_sources"][0].update(provider="openrouter"), "schema_violation"),
        ("ai-only-multi-direct", lambda p: p.update(schema_version="2.0"), "schema_violation"),
        ("openrouter-unresolved", lambda p: p["gateways"][0].update(upstream_evidence="observed"), "schema_violation"),
    ],
    ids=["duplicate-source", "unobserved-model", "wrong-family", "unmatched-upstream", "overlapping-upstream",
         "dropped-upstream-model", "wrong-upstream-family", "openrouter-as-provider", "wrong-version",
         "observed-gateway-without-upstreams"],
)
def test_inconsistent_profiles_are_rejected(fixture: str, mutate, code: str) -> None:
    assert _rejection(_with(fixture, mutate)) == code


def test_cli_prints_json_and_exits_non_zero_on_rejection(tmp_path: Path) -> None:
    def run(path: Path) -> tuple[int, dict]:
        proc = subprocess.run([sys.executable, str(VALIDATOR_SCRIPT), str(path)], capture_output=True, text=True, check=False)
        return proc.returncode, json.loads(proc.stdout)

    assert run(PROFILE_FIXTURES[0])[0] == 0
    assert run(tmp_path / "missing.json") == (1, {"ok": False, "error": "not_found", "detail": str(tmp_path / "missing.json")})
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    code, out = run(bad)
    assert (code, out["error"]) == (1, "invalid_json")
    code, out = run(tmp_path)
    assert (code, out["error"]) == (1, "not_readable")


@pytest.mark.parametrize("profile", [
    {"schema_version": "1.0", "ai_sources": 5, "gateways": []},
    {"schema_version": "1.0", "ai_sources": [{"model_observations": 7}], "gateways": []},
    {"schema_version": "1.0", "ai_sources": [{"model_observations": [{"evidence": "x"}]}], "gateways": []},
    [],
], ids=["non-list-sources", "non-list-observations", "non-list-evidence", "top-level-array"])
def test_malformed_containers_are_rejected_not_crashed(profile) -> None:
    assert _rejection(profile) in {"schema_violation", "not_an_object"}


# --------------------------------------------------------------------------- independence from infrastructure skills

def _skill_text_files() -> list[Path]:
    return [p for p in BMA.rglob("*") if p.is_file() and p.suffix in {".md", ".py", ".json"}]


def test_skill_never_reaches_into_another_skill() -> None:
    forbidden = re.compile(r"gcp-to-aws/|azure-to-aws/|heroku-to-aws/|render-to-aws/|\$GCP_BASE|\$ASSESS_BASE|\.\./")
    offenders = [
        f"{p.relative_to(BMA)}:{n}"
        for p in _skill_text_files()
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if forbidden.search(line)
    ]
    assert offenders == []


def test_clarify_reads_no_legacy_profile_field() -> None:
    text = BMA_CLARIFY.read_text(encoding="utf-8")
    for legacy in ("summary.ai_source", "models[].model_id", "integration.", "capabilities_summary", "confidence ≥ 0.8"):
        assert legacy not in text, legacy


def test_run_fixture_passes_the_artifact_contracts() -> None:
    proc = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "validate-artifacts.py"), "--run-dir", str(RUN_FIXTURE),
         "--skill", "bedrock-migration-assessment", "--no-baseline", "--json"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout
    assert BMA_VALIDATOR.validate_profile(_load(RUN_FIXTURE / "ai-workload-profile.json"))["ok"] is True


# --------------------------------------------------------------------------- Clarify answers keep their meaning

def _question_sections(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^## (Q[0-9.]+) — .*$", text, flags=re.M)
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}
    for qid, body in sections.items():
        sections[qid] = re.split(r"^(?:### Batch|## Step )", body, flags=re.M)[0]
    return sections


def _interpret_lines(body: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith("Interpret →")]


def _option_lines(body: str) -> list[str]:
    return [line for line in body.splitlines() if re.match(r"^> (?:1\\\)|\d+\. )", line)]


def _table_rows(body: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith("| ") and not line.startswith("| ---")]


GCP_QUESTIONS = _question_sections(GCP_CLARIFY)
BMA_QUESTIONS = _question_sections(BMA_CLARIFY)

# Rows whose wording was made provider-neutral; the decision they record is unchanged.
NEUTRALIZED_ROWS = {
    ("Q1.5", "| GDPR"): "document cross-border transfer from your current EU provider",
    ("Q4", "| Latency critical"): "closest region to current deployment",
}


def test_same_question_set_in_the_same_order() -> None:
    assert list(BMA_QUESTIONS) == list(GCP_QUESTIONS)


@pytest.mark.parametrize("qid", list(GCP_QUESTIONS))
def test_interpretation_is_identical(qid: str) -> None:
    assert _interpret_lines(BMA_QUESTIONS[qid]) == _interpret_lines(GCP_QUESTIONS[qid])
    assert _interpret_lines(GCP_QUESTIONS[qid]), f"{qid} has no Interpret line to compare"


@pytest.mark.parametrize("qid", list(GCP_QUESTIONS))
def test_answer_options_are_identical(qid: str) -> None:
    bma = _option_lines(BMA_QUESTIONS[qid])
    for line in _option_lines(GCP_QUESTIONS[qid]):
        assert line in bma, f"{qid}: answer options changed: {line}"


@pytest.mark.parametrize("qid", list(GCP_QUESTIONS))
def test_answer_impacts_are_identical_except_neutralized_wording(qid: str) -> None:
    bma_rows = _table_rows(BMA_QUESTIONS[qid])
    for row in _table_rows(GCP_QUESTIONS[qid]):
        neutral = next((text for (q, prefix), text in NEUTRALIZED_ROWS.items() if q == qid and row.startswith(prefix)), None)
        if neutral is None:
            assert row in bma_rows, f"{qid}: impact row changed: {row[:80]}"
        else:
            assert any(r.startswith(row.split("|")[0] + "|" + row.split("|")[1]) and neutral in r for r in bma_rows)


def _step3_fields(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    table = text[text.index("## Step 3"):text.index("## Step 4")]
    return dict(re.findall(r"^\| `([a-z_]+)`\s*\| `([a-z_.]+)`", table, flags=re.M))


def test_preferences_fields_and_paths_are_identical_except_capabilities() -> None:
    gcp = _step3_fields(GCP_CLARIFY)
    bma = _step3_fields(BMA_CLARIFY)
    assert gcp.pop("ai_capabilities_required") == "ai_constraints.ai_capabilities_required"
    assert bma == gcp


def _catalog() -> dict[str, tuple[str, str]]:
    text = BMA_PREFERENCES_SCHEMA.read_text(encoding="utf-8")
    table = text[text.index("## Constraint catalog"):text.index("## Validation")]
    return {key: (section, qid) for key, section, qid in re.findall(r"^\| `([a-z_]+)`\s*\| `([a-z_]+)`\s*\| ([^|]+?)\s*\|", table, flags=re.M)}


def test_every_written_field_is_in_the_preferences_catalog_at_its_path() -> None:
    catalog = _catalog()
    for field, path in _step3_fields(BMA_CLARIFY).items():
        if path.startswith("metadata."):
            continue
        section, key = path.split(".")
        assert key == field
        assert catalog[field][0] == section, field


def test_catalog_question_ids_match_the_clarify_sources() -> None:
    text = BMA_CLARIFY.read_text(encoding="utf-8")
    table = text[text.index("## Step 3"):text.index("## Step 4")]
    sources = dict(re.findall(r"^\| `([a-z_]+)`\s*\|[^|]+\| From (Q[0-9.]+)", table, flags=re.M))
    catalog = _catalog()
    assert sources
    for field, qid in sources.items():
        assert catalog[field][1] == qid, field


def test_run_fixture_uses_only_catalog_keys_with_matching_question_ids() -> None:
    preferences = _load(RUN_FIXTURE / "preferences.json")
    catalog = _catalog()
    for section in ("design_constraints", "ai_constraints", "startup_constraints"):
        for key, row in preferences.get(section, {}).items():
            assert catalog[key][0] == section, key
            if "question_id" in row:
                assert row["question_id"] == catalog[key][1], key
            if row["chosen_by"] == "default":
                assert row["source"] == f"default:{row['question_id']}", key
            if row["chosen_by"] == "extracted":
                assert row["source"].startswith("ai-profile:"), key
