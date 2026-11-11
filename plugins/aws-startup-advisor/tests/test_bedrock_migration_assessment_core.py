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
    assert set(result) == {"ok", "schema_version", "ai_sources", "gateways", "models_extractable",
                           "ai_framework_detected", "ai_vision_detected"}


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
    for legacy in ("summary.ai_source", "models[].model_id", "integration.pattern", "integration.gateway_type",
                   "integration.frameworks", "confidence ≥ 0.8"):
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
    ("Q5", "| GPT-6.1 Terra"): '**Same model on Bedrock** | Use the model-specific endpoint and context-tier prices in the [GPT-6.1 Terra model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-1-terra.html); compare against measured source spend or verified source rates.',
}


def test_same_question_set_in_the_same_order() -> None:
    assert list(BMA_QUESTIONS) == list(GCP_QUESTIONS)


# Interpret lines that name the stored value explicitly; GCP leaves it implicit.
EXPLICIT_INTERPRET = {
    "Q6": 'Interpret → `ai_vision`: 1 → `"text-only"`, 2 → `"vision"`, 3 → `"audio"`. Default: 1 → `"text-only"` (no constraint).',
}


@pytest.mark.parametrize("qid", list(GCP_QUESTIONS))
def test_interpretation_is_identical(qid: str) -> None:
    if qid in EXPLICIT_INTERPRET:
        assert _interpret_lines(BMA_QUESTIONS[qid]) == [EXPLICIT_INTERPRET[qid]]
        assert _interpret_lines(GCP_QUESTIONS[qid]) == ["Interpret → `ai_vision`. Default: 1 → no constraint."]
        return
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


# --------------------------------------------------------------------------- gateway rows pair each model with its observed family

def _two_family_profile(gateway_families: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "ai_sources": [{
            "provider": "openai", "source_service": "openai_api", "model_families": ["gpt", "o_series"],
            "model_evidence": "observed", "models": ["gpt-4o", "o3"],
            "model_observations": [
                {"normalized_model": "gpt-4o", "raw_model": "openai/gpt-4o", "model_family": "gpt",
                 "evidence": [{"provenance": "usage_api", "confidence": "high"}]},
                {"normalized_model": "o3", "raw_model": "openai/o3", "model_family": "o_series",
                 "evidence": [{"provenance": "usage_api", "confidence": "high"}]},
            ],
        }],
        "gateways": [{
            "product": "openrouter", "type": "llm_router", "upstream_evidence": "observed",
            "upstreams": [{"provider": "openai", "source_service": "openai_api", "model_families": gateway_families}],
        }],
    }


def _row(family: str, models: list[str]) -> dict:
    return {"family": family, "model_evidence": "observed", "models": models}


def test_correctly_paired_two_family_gateway_is_accepted() -> None:
    profile = _two_family_profile([_row("gpt", ["gpt-4o"]), _row("o_series", ["o3"])])
    assert BMA_VALIDATOR.validate_profile(profile)["ok"] is True


@pytest.mark.parametrize("rows", [
    [_row("gpt", ["o3"]), _row("o_series", ["gpt-4o"])],
    [_row("gpt", ["gpt-4o", "o3"]), _row("o_series", ["gpt-4o", "o3"])],
], ids=["swapped", "duplicated"])
def test_gateway_rows_that_misplace_a_model_are_rejected(rows: list[dict]) -> None:
    assert _rejection(_two_family_profile(rows)) == "upstream_models_mismatch"


# --------------------------------------------------------------------------- Clarify takes extracted answers only from the profile

def test_only_q5_can_be_skipped_and_only_through_the_validator_summary() -> None:
    skippable = [qid for qid, body in BMA_QUESTIONS.items() if "_Skip when:_" in body]
    assert skippable == ["Q1", "Q5", "Q6"]
    assert "models_extractable: true" in BMA_QUESTIONS["Q5"]
    assert "non-null `ai_framework_detected`" in BMA_QUESTIONS["Q1"]
    assert "non-null `ai_vision_detected`" in BMA_QUESTIONS["Q6"]
    assert "_Never skipped:_" in BMA_QUESTIONS["Q7"]


def test_clarify_never_reads_project_files_or_usage_profiles() -> None:
    text = BMA_CLARIFY.read_text(encoding="utf-8")
    for forbidden in ("usage-profile.json", "scan IaC", "application code is available", "requirements.txt", "imports"):
        assert forbidden not in text, forbidden


def test_extracted_answers_must_cite_the_profile() -> None:
    schema = BMA_PREFERENCES_SCHEMA.read_text(encoding="utf-8")
    assert 'Required when `chosen_by` is `"extracted"` (prefix `ai-profile:`)' in schema
    for section in ("design_constraints", "ai_constraints", "startup_constraints"):
        for key, row in _load(RUN_FIXTURE / "preferences.json").get(section, {}).items():
            if row["chosen_by"] == "extracted":
                assert row["source"].startswith("ai-profile:"), key


# --------------------------------------------------------------------------- the assumption sheet obeys the Q5 gate

def _sheet() -> str:
    text = BMA_CLARIFY.read_text(encoding="utf-8")
    return text[text.index("## Step 1.75"):text.index("## Step 2")]


def test_sheet_shows_models_only_when_extractable_and_lists_all_of_them() -> None:
    sheet = _sheet()
    assert "only when the validator summary reports `models_extractable: true`, and list every observed model" in sheet
    assert "ask Q5 in Batch 1" in sheet


SHEET_ROW_QUESTIONS = {"Models": "Q5", "Framework": "Q1", "Input types": "Q6", "Usage volume": "Q7",
                       "Response speed": "Q8", "Task complexity": "Q9"}


def _sheet_rows() -> set[str]:
    return set(re.findall(r"^\| (" + "|".join(SHEET_ROW_QUESTIONS) + r") \|", _sheet(), flags=re.M))


def test_sheet_never_assumes_a_value() -> None:
    assert "Will be assumed" not in _sheet()
    assert _sheet_rows() == {"Models", "Framework", "Input types"}


def test_sheet_rows_and_asked_questions_are_disjoint_in_the_run_fixture() -> None:
    metadata = _load(RUN_FIXTURE / "preferences.json")["metadata"]
    asked = set(metadata["questions_asked"])
    resolved_on_sheet = set(metadata["questions_extracted"]) | {
        qid for qid in metadata["questions_defaulted"] if qid in SHEET_ROW_QUESTIONS.values()
    }
    assert not asked & resolved_on_sheet
    assert not asked & set(metadata["questions_defaulted"])
    assert "Q7" in asked


def test_q7_is_asked_unless_the_user_takes_defaults() -> None:
    q7 = BMA_QUESTIONS["Q7"]
    assert "do not fill this from a usage-profile file or from the assumption sheet" in q7
    assert 'Ask it unless the user says "use defaults for the rest"' in q7


def test_clarify_makes_no_infrastructure_or_design_claims() -> None:
    text = BMA_CLARIFY.read_text(encoding="utf-8")
    assert "no infrastructure artifacts" not in text
    assert "ready to design" not in text


def test_run_fixture_q5_matches_its_profile_evidence() -> None:
    summary = BMA_VALIDATOR.validate_profile(_load(RUN_FIXTURE / "ai-workload-profile.json"))
    preferences = _load(RUN_FIXTURE / "preferences.json")
    baseline = preferences["ai_constraints"]["ai_model_baseline"]
    observed = {m["model"] for s in summary["ai_sources"] for m in s["models"]}
    assert set(baseline["value"]) == observed
    if summary["models_extractable"]:
        assert baseline["chosen_by"] == "extracted"
    else:
        assert baseline["chosen_by"] != "extracted"
        assert "Q5" in preferences["metadata"]["questions_asked"]
        assert "Q5" not in preferences["metadata"]["questions_extracted"]


# --------------------------------------------------------------------------- restarts never reuse a stale draft

def _step0() -> str:
    text = BMA_CLARIFY.read_text(encoding="utf-8")
    return text[text.index("## Step 0"):text.index("## Step 1:")]


def test_fresh_restart_deletes_both_preference_files() -> None:
    assert "- If 2: delete `preferences.json` and `preferences-draft.json` (if present), continue to Step 1." in _step0()


def test_reusing_final_preferences_discards_a_leftover_draft() -> None:
    assert "- If 1: delete `preferences-draft.json` if it exists, then skip to Step 4" in _step0()


def test_assembly_merges_into_a_draft_only_when_it_was_resumed() -> None:
    text = BMA_CLARIFY.read_text(encoding="utf-8")
    step3 = text[text.index("## Step 3"):text.index("## Step 4")]
    assert "If `preferences-draft.json` exists and was resumed in Step 0 Case 2, use it as the base" in step3
    assert "- If 1: load the draft, skip Batch 1 in Step 2, present Batch 2 directly." in _step0()


# --------------------------------------------------------------------------- schema 1.1: integration, workloads, agents, tools

V11 = {name: _fixture(name) for name in ("v11-framework-vision", "v11-agentic-tools")}


def test_v11_fixtures_are_accepted_and_summarized() -> None:
    vision = BMA_VALIDATOR.validate_profile(V11["v11-framework-vision"])
    assert (vision["ai_framework_detected"], vision["ai_vision_detected"]) == (["framework"], "vision")
    agentic = BMA_VALIDATOR.validate_profile(V11["v11-agentic-tools"])
    assert (agentic["ai_framework_detected"], agentic["ai_vision_detected"]) == (None, None)


@pytest.mark.parametrize("fixture_path", PROFILE_FIXTURES, ids=lambda p: p.parent.name)
def test_v10_profiles_detect_nothing(fixture_path: Path) -> None:
    profile = _load(fixture_path)
    if profile["schema_version"] == "1.0":
        result = BMA_VALIDATOR.validate_profile(profile)
        assert (result["ai_framework_detected"], result["ai_vision_detected"]) == (None, None)


def _v11(name: str, mutate) -> dict:
    profile = copy.deepcopy(V11[name])
    mutate(profile)
    return profile


def _caps(**on) -> dict:
    caps = {k: False for k in V11["v11-framework-vision"]["integration"]["capabilities_summary"]}
    caps.update(on)
    return caps


@pytest.mark.parametrize(("gateways", "pattern", "frameworks", "expected"), [
    ([], "direct_sdk", [], ["direct"]),
    ([], "rest_api", [], ["direct"]),
    ([{"type": "llm_router"}], "direct_sdk", [], ["llm_router"]),
    ([], "framework", ["langchain"], ["framework"]),
    ([], "mixed", ["llama_index"], ["direct", "framework"]),
    ([{"type": "llm_router"}], "framework", ["langchain"], ["framework", "llm_router"]),
    ([], "framework", ["crewai"], None),
    ([{"type": "custom_proxy"}], "direct_sdk", [], None),
    ([], "framework", [], None),
], ids=["direct", "rest", "gateway", "langchain", "mixed", "framework-gateway", "agent-framework", "unknown-gateway", "framework-without-name"])
def test_framework_detection_is_conservative(gateways, pattern, frameworks, expected) -> None:
    profile = _v11("v11-framework-vision", lambda p: p["integration"].update(pattern=pattern, frameworks=frameworks))
    profile["gateways"] = [{"product": "openrouter", "type": g["type"], "upstream_evidence": "unresolved", "upstreams": []} for g in gateways]
    assert BMA_VALIDATOR.validate_profile(profile)["ai_framework_detected"] == expected


def test_agents_suppress_framework_detection() -> None:
    assert BMA_VALIDATOR.validate_profile(V11["v11-agentic-tools"])["ai_framework_detected"] is None


@pytest.mark.parametrize(("caps", "expected"), [
    ({"text_generation": True}, None),
    ({"vision": True}, "vision"),
    ({"vision": True, "speech_to_text": True}, "audio"),
], ids=["text", "vision", "audio-wins"])
def test_input_type_detection(caps, expected) -> None:
    profile = _v11("v11-framework-vision", lambda p: p["integration"].update(capabilities_summary=_caps(**caps)))
    assert BMA_VALIDATOR.validate_profile(profile)["ai_vision_detected"] == expected


@pytest.mark.parametrize(("name", "mutate", "code"), [
    ("v11-framework-vision", lambda p: p.update(schema_version="1.0"), "version_mismatch"),
    ("v11-framework-vision", lambda p: p["workloads"].append(copy.deepcopy(p["workloads"][0])), "schema_violation"),
    ("v11-framework-vision", lambda p: p["workloads"][1].update(workload_id="summarize"), "duplicate_workload"),
    ("v11-framework-vision", lambda p: p["workloads"][0].update(model="gpt-4.1"), "unmatched_workload"),
    ("v11-framework-vision", lambda p: p["workloads"][0].update(source_service="azure_openai"), "unmatched_workload"),
    ("v11-framework-vision", lambda p: p["workloads"][0]["call_sites"].clear(), "schema_violation"),
    ("v11-framework-vision", lambda p: p["workloads"][0]["call_sites"][0].update(line=True), "schema_violation"),
    ("v11-framework-vision", lambda p: p["integration"]["capabilities_summary"].pop("vision"), "schema_violation"),
    ("v11-agentic-tools", lambda p: p.pop("agentic_profile"), "tool_manifest_without_agents"),
    ("v11-agentic-tools", lambda p: p["agentic_profile"]["agents"][0].update(model="gpt-4o"), "unmatched_agent_model"),
    ("v11-agentic-tools", lambda p: p["tool_manifest"].pop(), "unmatched_agent_tool"),
    ("v11-agentic-tools", lambda p: p["tool_manifest"][0].update(used_by_agents=["planner"]), "unmatched_tool_agent"),
    ("v11-agentic-tools", lambda p: p["tool_manifest"][1].update(name="web_search"), "duplicate_tool"),
    ("v11-agentic-tools", lambda p: p["agentic_profile"]["agents"].append(
        {**copy.deepcopy(p["agentic_profile"]["agents"][0]), "line": 99}), "duplicate_agent"),
], ids=["fields-on-1.0", "duplicate-row", "duplicate-workload-id", "unobserved-workload-model", "wrong-workload-service",
        "no-call-sites", "boolean-line", "missing-capability", "tools-without-agents", "unobserved-agent-model",
        "agent-tool-not-listed", "tool-names-unknown-agent", "duplicate-tool", "duplicate-agent"])
def test_inconsistent_v11_profiles_are_rejected(name, mutate, code) -> None:
    assert _rejection(_v11(name, mutate)) == code


def test_gcp_shaped_keys_are_still_rejected_on_a_v11_profile() -> None:
    assert _rejection(_v11("v11-framework-vision", lambda p: p.update(summary={"ai_source": "openai"}))) == "legacy_profile_rejected"
