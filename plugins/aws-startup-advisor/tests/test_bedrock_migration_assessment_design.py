"""Tests for bedrock-migration-assessment's Design phase: the plan, the aws-design-ai.json check, and the phase wiring."""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
FIXTURES = PLUGIN_ROOT / "fixtures"
DESIGN_FIXTURES = sorted(p.parent for p in FIXTURES.glob("bma-design-*/aws-design-ai.json"))
MANTLE_FIXTURE = FIXTURES / "bma-design-openai-mantle-and-runtime"
HIGH_VOLUME_FIXTURE = FIXTURES / "bma-design-anthropic-gemini-high-volume"
V10_FIXTURE = FIXTURES / "bma-design-v10-profile"
DESIGN_DOC = (BMA / "references/phases/design/design-ai.md").read_text(encoding="utf-8")
SKILL = (BMA / "SKILL.md").read_text(encoding="utf-8")


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, BMA / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


DESIGN = _module("bma_design_ai", "design-ai.py")


def _load(run: Path) -> tuple[dict, dict, dict]:
    return tuple(json.loads((run / name).read_text(encoding="utf-8"))
                 for name in ("aws-design-ai.json", "ai-workload-profile.json", "preferences.json"))


def _codes(design: dict, profile: dict, prefs: dict) -> set[str]:
    return {e["code"] for e in DESIGN.check_design(design, profile, prefs).get("errors", [])}


def _row(design: dict, aws_model_id: str) -> dict:
    return next(r for r in design["ai_architecture"]["bedrock_models"] if r["aws_model_id"] == aws_model_id)


def _plan_row(profile: dict, prefs: dict, workload_id: str) -> dict:
    return next(r for r in DESIGN.build_plan(profile, prefs)["rows"] if r["workload_id"] == workload_id)


def _with_mantle(prefs: dict, entries: list[dict]) -> dict:
    prefs = copy.deepcopy(prefs)
    prefs["ai_constraints"]["mantle_requirements"]["value"] = entries
    return prefs


def _openai_profile(sdk_method: str, model: str = "gpt-5.5", signals: list[dict] | None = None) -> dict:
    profile = copy.deepcopy(_load(MANTLE_FIXTURE)[1])
    profile["workloads"] = [w for w in profile["workloads"] if w["model"] == model][:1]
    profile["workloads"][0]["sdk_method"] = sdk_method
    profile["mantle_signals"] = signals or []
    return profile


# --------------------------------------------------------------------------- copies and wiring

def test_contract_copy_matches_the_canonical_schema() -> None:
    assert (BMA / "references/contracts/aws-design-ai.schema.json").read_bytes() == \
        (PLUGIN_ROOT / "scripts/contracts/aws-design-ai.schema.json").read_bytes()


def test_openai_fact_base_copy_matches_gcp_to_aws() -> None:
    assert (BMA / "references/shared/openai-on-bedrock.md").read_bytes() == \
        (PLUGIN_ROOT / "skills/gcp-to-aws/references/shared/openai-on-bedrock.md").read_bytes()


def test_every_guide_the_plan_can_name_ships_with_the_skill() -> None:
    names = [f"{DESIGN.GUIDE_DIR}/{g}" for g in DESIGN.ALWAYS_GUIDES]
    names += [f"{DESIGN.GUIDE_DIR}/{g}" for guides in DESIGN.PROVIDER_GUIDES.values() for g in guides]
    names += [f"{DESIGN.GUIDE_DIR}/ai-openrouter-to-bedrock.md", "references/shared/openai-on-bedrock.md"]
    for name in names:
        assert (BMA / name).is_file(), name


def test_skill_runs_design_after_clarify_and_stops_after_design() -> None:
    assert "## Step 3: Design" in SKILL and "references/phases/design/design-ai.md" in SKILL
    assert "This release stops after Design" in SKILL and "stops after Clarify" not in SKILL
    assert 'current_phase` to `"design"`' in SKILL
    clarify = (BMA / "references/phases/clarify/clarify-ai-only.md").read_text(encoding="utf-8")
    assert 'Set `current_phase` to `"design"`' in clarify and "continue to Design" in clarify
    discover = (BMA / "references/phases/discover/discover.md").read_text(encoding="utf-8")
    assert '"design": "pending"' in discover


def test_design_doc_runs_the_plan_and_the_check() -> None:
    assert "scripts/design-ai.py plan $MIGRATION_DIR" in DESIGN_DOC
    assert "scripts/design-ai.py check $MIGRATION_DIR" in DESIGN_DOC
    for lane in ("runtime", "mantle", "in_region_check", "api_conflict", "provider_mismatch", "no_mantle_path", "api_unknown"):
        assert f"| `{lane}`" in DESIGN_DOC, lane
    assert DESIGN.ASSUMPTION.format(ids="<ids>") in DESIGN_DOC


# --------------------------------------------------------------------------- fixtures

@pytest.mark.parametrize("run", DESIGN_FIXTURES, ids=lambda p: p.name)
def test_fixture_designs_pass_the_check(run: Path) -> None:
    assert DESIGN.check_design(*_load(run))["ok"] is True


@pytest.mark.parametrize("run", DESIGN_FIXTURES, ids=lambda p: p.name)
def test_cli_check_and_plan_succeed_on_fixtures(run: Path, tmp_path: Path, capsys) -> None:
    for name in ("aws-design-ai.json", "ai-workload-profile.json", "preferences.json"):
        shutil.copy(run / name, tmp_path / name)
    assert DESIGN.main(["check", str(tmp_path)]) == 0
    assert DESIGN.main(["plan", str(tmp_path)]) == 0
    plan = json.loads(capsys.readouterr().out.split("\n}\n", 1)[1])
    assert [r["workload_id"] for r in plan["rows"]] == [b["workload_id"] for b in _load(run)[0]["design_blocks"]]


def test_fixture_corpus_covers_mantle_disclosure_cross_family_and_v10() -> None:
    paths = {r["migration_path"] for run in DESIGN_FIXTURES for r in _load(run)[0]["ai_architecture"]["bedrock_models"]}
    assert {"mantle_openai_responses", "runtime_openai_cris", "runtime_messages", "converse", "direct"} <= paths
    assert _load(V10_FIXTURE)[1]["schema_version"] == "1.0"


# --------------------------------------------------------------------------- plan

@pytest.mark.parametrize(("method", "api"), [
    ("openai.responses.create", "responses"), ("openai.responses.stream", "responses"),
    ("openai.chat.completions.create", "chat_completions"), ("openai.chat.completions.parse", "chat_completions"),
    ("openai.beta.chat.completions.parse", "chat_completions"), ("openai.chat.completions.stream", "chat_completions"),
    ("openai.responses.parse", "responses"), ("anthropic.messages.stream", "messages"), ("anthropic.messages.parse", "messages"),
    ("genai.models.generateContent", "gemini"), ("google.generativeai.GenerativeModel.generate_content", "gemini"),
    ("langchain_anthropic.ChatAnthropic.invoke", "framework"), ("openai.beta.assistants.create", "framework"),
    ("openai.embeddings.create", "embeddings"), ("openai.images.generate", "images"),
    ("openai.audio.transcriptions.create", "audio"), ("anthropic.messages.create", "messages"),
    ("anthropic.beta.messages.create", "messages"), ("genai.models.generate_content", "gemini"),
    ("vertexai.GenerativeModel.generate_content", "gemini"), ("langchain_openai.ChatOpenAI.invoke", "framework"),
    ("agents.Runner.run", "framework"), (None, None),
])
def test_source_api_reads_the_sdk_method(method, api) -> None:
    assert DESIGN.source_api(method) == api


def test_plan_lists_guides_by_provider_and_gateway() -> None:
    _, profile, prefs = _load(HIGH_VOLUME_FIXTURE)
    guides = DESIGN.build_plan(profile, prefs)["guides"]
    assert any(g.endswith("ai-anthropic-to-bedrock.md") for g in guides)
    assert any(g.endswith("ai-gemini-to-bedrock.md") for g in guides)
    assert not any(g.endswith("ai-openai-to-bedrock.md") or g.endswith("openai-on-bedrock.md") for g in guides)
    _, openai_profile, openai_prefs = _load(MANTLE_FIXTURE)
    assert any(g.endswith("ai-anthropic-to-bedrock.md") for g in DESIGN.build_plan(openai_profile, openai_prefs)["guides"])
    assert not any(g.endswith("ai-openrouter-to-bedrock.md") for g in guides)
    gateway = copy.deepcopy(profile)
    gateway["gateways"] = [{"product": "openrouter", "type": "llm_router", "upstream_evidence": "unresolved", "upstreams": []}]
    assert any(g.endswith("ai-openrouter-to-bedrock.md") for g in DESIGN.build_plan(gateway, prefs)["guides"])


def test_plan_for_a_v10_profile_has_one_low_confidence_row_per_observed_model() -> None:
    _, profile, prefs = _load(V10_FIXTURE)
    plan = DESIGN.build_plan(profile, prefs)
    assert [(r["workload_id"], r["capability"], r["capability_confidence"]) for r in plan["rows"]] == \
        [("openai_api.gpt-4o", "unknown", "low")]
    assert plan["rows"][0]["confidence_warning"] and plan["rows"][0]["source_api"] is None
    assert plan["not_designed"] == [{"provider": "anthropic", "source_service": "anthropic_api", "reason": "model not observed"}]
    assert plan["tiered_strategy_required"] is False and plan["quota_risk_floor"] is None


def test_plan_fills_documented_defaults_for_unanswered_keys() -> None:
    _, profile, prefs = _load(V10_FIXTURE)
    prefs = copy.deepcopy(prefs)
    del prefs["ai_constraints"]["ai_latency"], prefs["design_constraints"]["compliance"]
    constraints = DESIGN.build_plan(profile, prefs)["constraints"]
    assert constraints["ai_latency"] == {"value": "important", "chosen_by": "absent"}
    assert constraints["compliance"] == {"value": ["unknown"], "chosen_by": "absent"}


def test_plan_maps_an_unknown_capability_to_unknown_with_low_confidence() -> None:
    profile = _openai_profile("openai.responses.create")
    profile["workloads"][0]["capability"] = "moderation"
    row = DESIGN.build_plan(profile, _load(MANTLE_FIXTURE)[2])["rows"][0]
    assert (row["capability"], row["capability_confidence"]) == ("unknown", "low") and row["confidence_warning"]


def test_plan_rejects_preferences_not_written_by_ai_only_clarify() -> None:
    _, profile, prefs = _load(V10_FIXTURE)
    prefs = copy.deepcopy(prefs)
    prefs["metadata"]["migration_type"] = "full"
    with pytest.raises(DESIGN.DesignInputError) as err:
        DESIGN.build_plan(profile, prefs)
    assert err.value.code == "preferences_not_ai_only"


def test_cli_reports_missing_preferences_and_rejected_profiles(tmp_path: Path, capsys) -> None:
    shutil.copy(V10_FIXTURE / "ai-workload-profile.json", tmp_path / "ai-workload-profile.json")
    assert DESIGN.main(["plan", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "preferences_not_found"
    (tmp_path / "ai-workload-profile.json").write_text(json.dumps({"schema_version": "1.0", "summary": {}}))
    shutil.copy(V10_FIXTURE / "preferences.json", tmp_path / "preferences.json")
    assert DESIGN.main(["plan", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "profile_legacy_profile_rejected"
    shutil.copy(V10_FIXTURE / "ai-workload-profile.json", tmp_path / "ai-workload-profile.json")
    assert DESIGN.main(["check", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "design_not_found"


SIGNAL = {"selector": "web_search", "provider": "openai", "source_service": "openai_api", "model": "gpt-5.5",
          "evidence": [{"provenance": "code", "confidence": "high", "detail": "app/x.py:3 web_search"}]}
DETECTED = {"workload_id": "*", "selector": "web_search", "source": "detected", "evidence": "app/x.py:3 web_search"}


@pytest.mark.parametrize(("method", "entries", "lane"), [
    ("openai.responses.create", [], "runtime"),
    ("openai.responses.create", [{"workload_id": "*", "selector": "none", "source": "user"}], "runtime"),
    ("openai.responses.create", [{"workload_id": "*", "selector": "none", "source": "none"}], "runtime"),
    ("openai.responses.create", [DETECTED], "mantle"),
    ("openai.chat.completions.create", [DETECTED], "api_conflict"),
    ("openai.chat.completions.create", [{"workload_id": "*", "selector": "projects", "source": "user"}], "mantle"),
    ("openai.responses.create", [{"workload_id": "*", "selector": "workspaces", "source": "user"}], "provider_mismatch"),
    ("openai.responses.create", [{"workload_id": "*", "selector": "in_region_processing", "source": "user", "region": "us-east-2"}], "in_region_check"),
    ("openai.embeddings.create", [{"workload_id": "*", "selector": "projects", "source": "user"}], "no_mantle_path"),
    ("langchain_openai.ChatOpenAI.invoke", [{"workload_id": "*", "selector": "projects", "source": "user"}], "api_unknown"),
])
def test_lane_per_requirement(method, entries, lane) -> None:
    profile = _openai_profile(method, signals=[SIGNAL])
    prefs = _with_mantle(_load(MANTLE_FIXTURE)[2], entries)
    assert DESIGN.build_plan(profile, prefs)["rows"][0]["mantle"]["lane"] == lane


@pytest.mark.parametrize(("provider", "method", "selector", "lane"), [
    ("anthropic", "openai.chat.completions.create", "workspaces", "api_conflict"),
    ("anthropic", "anthropic.messages.create", "workspaces", "mantle"),
    ("anthropic", "anthropic.messages.create", "web_search", "no_mantle_path"),
    ("anthropic", "anthropic.messages.create", "server_side_tools", "no_mantle_path"),
    ("openai", "openai.chat.completions.create", "server_side_tools", "api_conflict"),
    ("openai", "openai.responses.create", "server_side_tools", "mantle"),
    ("anthropic", "anthropic.messages.create", "projects", "provider_mismatch"),
    ("mistral", "openai.chat.completions.create", "projects", "no_mantle_path"),
])
def test_lane_depends_on_the_provider_and_its_api(provider, method, selector, lane) -> None:
    profile = _openai_profile(method)
    source, workload = profile["ai_sources"][0], profile["workloads"][0]
    source["provider"] = workload["provider"] = provider
    entry = {"workload_id": "*", "selector": selector, "source": "user"}
    row = DESIGN.build_plan(profile, _with_mantle(_load(MANTLE_FIXTURE)[2], [entry]))["rows"][0]
    assert row["mantle"]["lane"] == lane


def test_check_accepts_moving_a_gateway_anthropic_call_to_mantle_messages() -> None:
    def mutate(d, p, f):
        entry = {"workload_id": "*", "selector": "workspaces", "source": "user"}
        f["ai_constraints"]["mantle_requirements"]["value"] = [entry]
        for item in (p["ai_sources"][0], *p["workloads"]):
            item["provider"] = "anthropic"
        d["metadata"]["ai_sources"] = p["ai_sources"]
        d["ai_architecture"]["bedrock_models"] = [r for r in d["ai_architecture"]["bedrock_models"] if r["aws_model_id"] != MANTLE_ID]
        d["design_blocks"][0]["target_bedrock_model"] = RUNTIME_ID
        for row in d["ai_architecture"]["bedrock_models"]:
            row["capability_gaps"] = ["workspaces (user, Q10.5) stays unserved on bedrock-runtime"]
        row = _row(d, RUNTIME_ID)
        row.update(migration_path="mantle_messages", required_client_api="messages", mantle_selector="workspaces",
                   mantle_requirement=entry, capability_gaps=[])
        row.pop("endpoint_assumption")
        d["metadata"]["bedrock_models_selected"] = [RUNTIME_ID, EMB_ID]
    codes = _mutated(MANTLE_FIXTURE, mutate)
    assert codes == set(), codes
    wrong = _mutated(MANTLE_FIXTURE, lambda d, p, f: (mutate(d, p, f), _row(d, RUNTIME_ID).update(migration_path="mantle_openai_responses",
                                                                                               required_client_api="responses")))
    assert "mantle_path_api" in wrong


def test_gemini_workload_has_no_mantle_path() -> None:
    _, profile, prefs = _load(HIGH_VOLUME_FIXTURE)
    gemini = _plan_row(profile, prefs, "gemini_api.gemini-2.5-flash.genai.models.generate_content.plain")
    anthropic = _plan_row(profile, prefs, "anthropic_api.claude-sonnet-5.anthropic.messages.create.plain")
    assert gemini["mantle"]["lane"] == "no_mantle_path" and anthropic["mantle"]["lane"] == "runtime"


def test_detected_star_entry_applies_only_to_the_model_its_signal_names() -> None:
    _, profile, prefs = _load(MANTLE_FIXTURE)
    emb = _plan_row(profile, prefs, "openai_api.text-embedding-3-small.openai.embeddings.create.plain")
    resp = _plan_row(profile, prefs, "openai_api.gpt-5.5.openai.responses.create.plain")
    assert emb["mantle_requests"] == [] and resp["mantle_requests"] and resp["mantle"]["lane"] == "mantle"
    stale = _with_mantle(prefs, [dict(DETECTED, evidence="app/other.py:1 web_search")])
    assert _plan_row(profile, stale, resp["workload_id"])["mantle_requests"] == []


def test_user_star_entry_applies_to_every_workload_and_a_named_entry_to_one() -> None:
    _, profile, prefs = _load(MANTLE_FIXTURE)
    everyone = DESIGN.build_plan(profile, _with_mantle(prefs, [{"workload_id": "*", "selector": "projects", "source": "user"}]))
    assert all(r["mantle_requests"] for r in everyone["rows"])
    named = profile["workloads"][1]["workload_id"]
    one = DESIGN.build_plan(profile, _with_mantle(prefs, [{"workload_id": named, "selector": "projects", "source": "user"}]))
    assert [bool(r["mantle_requests"]) for r in one["rows"]] == [False, True, False]


def test_selectors_follow_policy_order_and_list_the_rest() -> None:
    profile = _openai_profile("openai.responses.create", signals=[SIGNAL])
    entries = [{"workload_id": "*", "selector": "projects", "source": "user"}, DETECTED,
               {"workload_id": "*", "selector": "background_inference", "source": "user"}]
    mantle = DESIGN.build_plan(profile, _with_mantle(_load(MANTLE_FIXTURE)[2], entries))["rows"][0]["mantle"]
    assert mantle["selector"] == "background_inference" and mantle["also_requested"] == ["web_search", "projects"]


def test_mixed_requests_fall_through_to_the_first_selector_the_source_api_can_use() -> None:
    profile = _openai_profile("openai.chat.completions.create", signals=[SIGNAL])
    entries = [DETECTED, {"workload_id": "*", "selector": "projects", "source": "user"}]
    mantle = DESIGN.build_plan(profile, _with_mantle(_load(MANTLE_FIXTURE)[2], entries))["rows"][0]["mantle"]
    assert (mantle["lane"], mantle["selector"], mantle["mantle_path"]) == ("mantle", "projects", "mantle_openai_chat")


@pytest.mark.parametrize(("volume", "required"), [("low", False), ("medium", False), ("high", True), ("very_high", True)])
def test_tiered_strategy_and_quota_floor_follow_volume(volume, required) -> None:
    _, profile, prefs = _load(V10_FIXTURE)
    prefs = copy.deepcopy(prefs)
    prefs["ai_constraints"]["ai_token_volume"]["value"] = volume
    plan = DESIGN.build_plan(profile, prefs)
    assert plan["tiered_strategy_required"] is required and (plan["quota_risk_floor"] == "high") is required


# --------------------------------------------------------------------------- check: negatives

def _mutated(run: Path, mutate) -> set[str]:
    design, profile, prefs = (copy.deepcopy(x) for x in _load(run))
    mutate(design, profile, prefs)
    return _codes(design, profile, prefs)


MANTLE_ID, RUNTIME_ID, EMB_ID = "openai.gpt-5.5", "us.openai.gpt-5.5", "amazon.titan-embed-text-v2:0"


def _set(d: dict, key: str, value) -> None:
    d[key] = value


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda d, p, f: d["metadata"]["ai_sources"][0]["models"].pop(), "projection_mismatch"),
    (lambda d, p, f: d["design_blocks"].reverse(), "design_blocks_mismatch"),
    (lambda d, p, f: _set(d["design_blocks"][2], "capability", "text_generation"), "design_block_field"),
    (lambda d, p, f: _set(d["design_blocks"][0], "confidence_warning", "review"), "confidence_warning"),
    (lambda d, p, f: d["metadata"]["bedrock_models_selected"].pop(), "models_selected_mismatch"),
    (lambda d, p, f: _row(d, MANTLE_ID).pop("mantle_selector"), "mantle_selector"),
    (lambda d, p, f: _set(_row(d, MANTLE_ID)["mantle_requirement"], "evidence", "app/elsewhere.py:1"), "mantle_requirement_unrecorded"),
    (lambda d, p, f: _set(_row(d, MANTLE_ID), "endpoint_assumption", "x"), "mantle_row_assumption"),
    (lambda d, p, f: _set(_row(d, MANTLE_ID)["mantle_requirement"], "region", "us-east-1"), "mantle_requirement_region"),
    (lambda d, p, f: _set(_row(d, RUNTIME_ID), "endpoint_assumption", DESIGN.ASSUMPTION.format(ids="wl_other")), "endpoint_assumption"),
    (lambda d, p, f: _set(_row(d, RUNTIME_ID), "capability_gaps", []), "selector_not_disclosed"),
    (lambda d, p, f: _set(_row(d, RUNTIME_ID), "mantle_selector", "web_search"), "runtime_row_selector"),
    (lambda d, p, f: _set(_row(d, RUNTIME_ID), "required_client_api", "messages"), "row_client_api_mismatch"),
    (lambda d, p, f: _set(_row(d, RUNTIME_ID), "migration_path", "mantle_messages"), "mantle_selector"),
    (lambda d, p, f: _set(_row(d, EMB_ID), "quota_risk", "extreme"), "row_bad_quota_risk"),
    (lambda d, p, f: _row(d, EMB_ID).pop("bedrock_price"), "row_missing_field"),
    (lambda d, p, f: _set(d["ai_architecture"], "honest_assessment", "strong_migrate"), "overall_assessment"),
    (lambda d, p, f: _set(d["ai_architecture"], "honest_assessment_reason", "cost"), "assessment_reason"),
    (lambda d, p, f: _set(d["ai_architecture"], "tiered_strategy", {"tiers": []}), "tiered_strategy"),
    (lambda d, p, f: d["ai_architecture"]["capability_mapping"].pop("embeddings"), "capability_mapping"),
    (lambda d, p, f: _set(d["ai_architecture"]["code_migration"], "primary_pattern", "framework"), "code_migration"),
    (lambda d, p, f: _set(d, "multi_model_warnings", []), "multi_model_warning_missing"),
    (lambda d, p, f: _set(d, "multi_model_warnings", [{"type": "reindex", "message": "x"}]), "multi_model_warning_shape"),
    (lambda d, p, f: _set(d, "regional_warnings", [{"service": "bedrock"}]), "regional_warning_shape"),
    (lambda d, p, f: _set(d, "agentic_design", {"migration_approach": "retarget"}), "agentic_design"),
    (lambda d, p, f: _set(d["ai_architecture"], "services_to_migrate", None), "architecture_list"),
    (lambda d, p, f: _set(d["ai_architecture"]["code_migration"], "dependency_changes", "App Runner"), "app_runner"),
    (lambda d, p, f: d["ai_architecture"]["bedrock_models"].append(dict(_row(d, EMB_ID), aws_model_id="cohere.embed-v4:0")), "row_without_block"),
    (lambda d, p, f: _set(d["design_blocks"][2], "target_bedrock_model", "cohere.embed-v4:0"), "block_without_row"),
    (lambda d, p, f: _set(d, "phase", "estimate"), "schema_violation"),
], ids=lambda v: v if isinstance(v, str) else "")
def test_check_rejects(mutate, code) -> None:
    assert code in _mutated(MANTLE_FIXTURE, mutate)


def test_check_rejects_a_bare_gpt_id_on_a_runtime_path() -> None:
    def mutate(d, p, f):
        _row(d, RUNTIME_ID)["aws_model_id"] = MANTLE_ID + "x"
        d["design_blocks"][1]["target_bedrock_model"] = MANTLE_ID + "x"
        d["metadata"]["bedrock_models_selected"][1] = MANTLE_ID + "x"
    assert "bare_gpt_id_on_runtime" in _mutated(MANTLE_FIXTURE, mutate)


def test_check_rejects_a_weaker_quota_risk_at_high_volume_and_a_missing_tiered_strategy() -> None:
    codes = _mutated(HIGH_VOLUME_FIXTURE, lambda d, p, f: (_set(d["ai_architecture"]["bedrock_models"][0], "quota_risk", "medium"),
                                                         _set(d["ai_architecture"], "tiered_strategy", None)))
    assert {"quota_risk_floor", "tiered_strategy"} <= codes


def test_check_rejects_an_unhonored_selector_on_a_cross_family_row_without_disclosure() -> None:
    codes = _mutated(HIGH_VOLUME_FIXTURE, lambda d, p, f: _set(d["ai_architecture"]["bedrock_models"][1], "capability_gaps", []))
    assert codes == {"selector_not_disclosed"}


def test_check_rejects_a_global_profile_under_gdpr() -> None:
    def mutate(d, p, f):
        f["design_constraints"]["compliance"]["value"] = ["gdpr"]
    assert "gdpr_profile" in _mutated(HIGH_VOLUME_FIXTURE, mutate)
    assert "gdpr_profile" not in _mutated(HIGH_VOLUME_FIXTURE, lambda d, p, f: None)


def test_check_rejects_a_recommend_stay_without_a_reason() -> None:
    def mutate(d, p, f):
        d["ai_architecture"]["bedrock_models"][0]["honest_assessment"] = "recommend_stay"
        d["ai_architecture"]["honest_assessment"] = "recommend_stay"
    assert "assessment_reason" in _mutated(V10_FIXTURE, mutate)


def test_check_treats_halt_as_not_complete() -> None:
    codes = _mutated(V10_FIXTURE, lambda d, p, f: _set(d, "halt", {"reason": "no observed model to design", "blocking": []}))
    assert codes == {"halted"}


def test_check_rejects_an_empty_design_when_nothing_was_observed() -> None:
    def mutate(d, p, f):
        p["ai_sources"] = [p["ai_sources"][1]]
        d["metadata"]["ai_sources"] = p["ai_sources"]
        d["design_blocks"], d["metadata"]["bedrock_models_selected"] = [], []
        d["ai_architecture"]["bedrock_models"] = []
    assert "nothing_to_design" in _mutated(V10_FIXTURE, mutate)


def test_check_requires_in_region_disclosure_on_a_cris_row() -> None:
    entry = {"workload_id": "*", "selector": "in_region_processing", "source": "user", "region": "us-east-1"}
    codes = _mutated(V10_FIXTURE, lambda d, p, f: f["ai_constraints"]["mantle_requirements"].update(value=[entry]))
    assert codes == {"in_region_unhonored"}
    warned = _mutated(V10_FIXTURE, lambda d, p, f: (f["ai_constraints"]["mantle_requirements"].update(value=[entry]),
                                                   d["regional_warnings"].append({"service": "bedrock-runtime", "target_region": "us-east-1",
                                                                                  "nearest_available": "bedrock-mantle us-east-1",
                                                                                  "impact": "GPT-5.6 Terra runs on runtime through a CRIS profile only"})))
    assert warned == set()


# --------------------------------------------------------------------------- check: accepted variants

def test_check_accepts_moving_an_api_conflict_to_mantle_responses() -> None:
    def mutate(d, p, f):
        row = _row(d, RUNTIME_ID)
        row.update(aws_model_id=MANTLE_ID + "-chat", migration_path="mantle_openai_responses", required_client_api="responses",
                   mantle_selector="web_search", mantle_requirement=copy.deepcopy(_row(d, MANTLE_ID)["mantle_requirement"]),
                   capability_gaps=[])
        row.pop("endpoint_assumption")
        d["design_blocks"][1]["target_bedrock_model"] = MANTLE_ID + "-chat"
        d["metadata"]["bedrock_models_selected"][1] = MANTLE_ID + "-chat"
    assert _mutated(MANTLE_FIXTURE, mutate) == set()


def test_check_rejects_a_same_api_mantle_row_for_a_responses_only_selector() -> None:
    def mutate(d, p, f):
        row = _row(d, RUNTIME_ID)
        row.update(aws_model_id=MANTLE_ID + "-chat", migration_path="mantle_openai_chat", mantle_selector="web_search",
                   mantle_requirement=copy.deepcopy(_row(d, MANTLE_ID)["mantle_requirement"]))
        row.pop("endpoint_assumption")
        d["design_blocks"][1]["target_bedrock_model"] = MANTLE_ID + "-chat"
        d["metadata"]["bedrock_models_selected"][1] = MANTLE_ID + "-chat"
    assert "mantle_path_api" in _mutated(MANTLE_FIXTURE, mutate)


def test_check_accepts_a_catalog_requirement_and_rejects_one_without_evidence() -> None:
    def catalog(evidence):
        def mutate(d, p, f):
            req = {"workload_id": d["design_blocks"][2]["workload_id"], "selector": "mantle_only_model_or_api", "source": "catalog"}
            if evidence:
                req["evidence"] = evidence
            row = _row(d, EMB_ID)
            row.update(migration_path="mantle_openai_responses", required_client_api="responses",
                       mantle_selector="mantle_only_model_or_api", mantle_requirement=req)
            row.pop("endpoint_assumption")
        return mutate
    assert _mutated(MANTLE_FIXTURE, catalog("openai-on-bedrock.md § Access Paths")) == set()
    assert "mantle_requirement_evidence" in _mutated(MANTLE_FIXTURE, catalog(None))


def test_check_names_every_workload_sharing_a_runtime_row() -> None:
    def mutate(d, p, f):
        f["ai_constraints"]["mantle_requirements"]["value"] = []
        d["design_blocks"][0]["target_bedrock_model"] = RUNTIME_ID
        d["metadata"]["bedrock_models_selected"] = [RUNTIME_ID, EMB_ID]
        d["ai_architecture"]["bedrock_models"] = [r for r in d["ai_architecture"]["bedrock_models"] if r["aws_model_id"] != MANTLE_ID]
        row = _row(d, RUNTIME_ID)
        row["capability_gaps"] = []
        row["endpoint_assumption"] = DESIGN.ASSUMPTION.format(ids=", ".join(b["workload_id"] for b in d["design_blocks"][:2]))
    assert _mutated(MANTLE_FIXTURE, mutate) == set()


def test_check_allows_one_mantle_and_one_runtime_row_for_the_same_model_and_target() -> None:
    def mutate(d, p, f):
        d["design_blocks"][1]["target_bedrock_model"] = MANTLE_ID
        d["metadata"]["bedrock_models_selected"] = [MANTLE_ID, EMB_ID]
        _row(d, RUNTIME_ID)["aws_model_id"] = MANTLE_ID
    codes = _mutated(MANTLE_FIXTURE, mutate)
    assert "duplicate_row" not in codes and "block_without_row" not in codes
    twice = _mutated(MANTLE_FIXTURE, lambda d, p, f: d["ai_architecture"]["bedrock_models"].append(copy.deepcopy(_row(d, MANTLE_ID))))
    assert "duplicate_row" in twice


@pytest.mark.parametrize(("service", "ok"), [("transcribe", True), ("polly", False), (None, True)])
def test_speech_rows_may_target_transcribe(service, ok) -> None:
    def mutate(d, p, f):
        p["workloads"][0].update(sdk_method="openai.audio.transcriptions.create", capability="speech_to_text", capability_confidence="high")
        d["design_blocks"][0].update(capability="speech_to_text", capability_confidence="high", confidence_warning=None)
        p["integration"]["capabilities_summary"]["speech_to_text"] = True
        d["ai_architecture"]["capability_mapping"]["speech_to_text"] = {"parity": "partial", "notes": "Amazon Transcribe"}
        d["multi_model_warnings"].append({"type": "speech_separate", "message": "Speech moves to Amazon Transcribe."})
        d["metadata"]["ai_sources"] = p["ai_sources"]
        f["ai_constraints"]["mantle_requirements"]["value"] = []
        d["ai_architecture"]["bedrock_models"] = [r for r in d["ai_architecture"]["bedrock_models"] if r["aws_model_id"] != MANTLE_ID]
        _row(d, RUNTIME_ID)["capability_gaps"] = []
        if service:
            d["design_blocks"][0].update(target_bedrock_model=None, target_aws_service=service)
            d["metadata"]["bedrock_models_selected"] = [RUNTIME_ID, EMB_ID]
        else:
            d["design_blocks"][0]["target_bedrock_model"] = RUNTIME_ID
            d["metadata"]["bedrock_models_selected"] = [RUNTIME_ID, EMB_ID]
            _row(d, RUNTIME_ID)["endpoint_assumption"] = DESIGN.ASSUMPTION.format(
                ids=", ".join(b["workload_id"] for b in d["design_blocks"][:2]))
    codes = _mutated(MANTLE_FIXTURE, mutate)
    assert (codes == set()) is ok, codes
