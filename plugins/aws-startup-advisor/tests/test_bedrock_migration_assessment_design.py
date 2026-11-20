"""Tests for bedrock-migration-assessment's Design phase: the plan, the aws-design-ai.json check, and the phase wiring."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
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


def test_openai_fact_base_is_the_vendored_shared_guide() -> None:
    canonical = (PLUGIN_ROOT / "skills/shared/ai/openai-on-bedrock.md").read_bytes()
    assert (BMA / "references/vendored/ai/openai-on-bedrock.md").read_bytes() == canonical
    assert not (BMA / "references/shared/openai-on-bedrock.md").exists()


def test_every_guide_the_plan_can_name_ships_with_the_skill() -> None:
    names = [f"{DESIGN.GUIDE_DIR}/{g}" for g in DESIGN.ALWAYS_GUIDES]
    names += [f"{DESIGN.GUIDE_DIR}/{g}" for guides in DESIGN.PROVIDER_GUIDES.values() for g in guides]
    names += [f"{DESIGN.GUIDE_DIR}/ai-openrouter-to-bedrock.md", f"{DESIGN.GUIDE_DIR}/openai-on-bedrock.md"]
    for name in names:
        assert (BMA / name).is_file(), name


def test_skill_runs_design_after_clarify_then_estimate() -> None:
    assert "## Step 3: Design" in SKILL and "references/phases/design/design-ai.md" in SKILL
    assert "## Step 4: Estimate" in SKILL and "## Step 5: Generate" in SKILL and "stops after Clarify" not in SKILL
    assert 'current_phase` to `"design"`' in SKILL and 'current_phase` to `"estimate"`' in SKILL
    clarify = (BMA / "references/phases/clarify/clarify-ai-only.md").read_text(encoding="utf-8")
    assert 'Set `current_phase` to `"design"`' in clarify and "continue to Design" in clarify
    discover = (BMA / "references/phases/discover/discover.md").read_text(encoding="utf-8")
    assert '"design": "pending", "estimate": "pending"' in discover


def _rule_for(status: dict) -> int:
    """The Step 0 rule a phase-status matches, read from SKILL.md's first-match list."""
    p = {"generate": "pending", **status["phases"]}
    if p.get("clarify") == "in_progress":
        return 1
    if p.get("design") == "in_progress" or (p.get("clarify") == "completed" and p.get("design", "pending") == "pending"):
        return 2
    if p.get("estimate") == "in_progress" or (p.get("design") == "completed" and p.get("estimate", "pending") == "pending"):
        return 3
    if p["generate"] == "in_progress":
        return 4
    if p.get("estimate") == "completed" and p["generate"] == "pending":
        return 5 if status.get("run_mode") == "decide_and_execute" else 6
    if p["generate"] == "completed":
        return 7
    if p.get("discover") == "completed" and p.get("clarify") == "pending":
        return 8
    return 9 if p.get("discover") == "in_progress" else 10


def test_resume_rules_put_an_active_earlier_phase_first() -> None:
    step0 = SKILL[SKILL.index("## Step 0"):SKILL.index("## Step 1:")]
    rules = [line for line in step0.splitlines() if line.split(". ", 1)[0] in {str(n) for n in range(1, 11)}]
    assert [r.split(".", 1)[0] for r in rules] == [str(n) for n in range(1, 11)]
    assert '`phases.clarify` set to `"in_progress"`, resume at Clarify, whatever the later phases say' in rules[0]
    assert "resume at Design" in rules[1] and "resume at Estimate" in rules[2] and "resume at Generate" in rules[3]
    assert 'If that file has `phases.estimate` set to `"completed"` and `phases.generate` `"pending"`' in rules[5]
    resets = step0.split("\n7. ", 1)[1].split("\n8. ", 1)[0]
    assert ('- Change answers: set `phases.clarify` to `"in_progress"`, `phases.design`, `phases.estimate`, and `phases.generate` to `"pending"`, '
            'and `current_phase` to `"clarify"`') in resets
    assert '- Design again: set `phases.design`, `phases.estimate`, and `phases.generate` to `"pending"` and `current_phase` to `"design"`' in resets
    assert '- Estimate again: set `phases.estimate` and `phases.generate` to `"pending"`' in resets
    assert '- Generate again: set `phases.generate` to `"in_progress"`' in resets
    assert "Use the first rule that matches, and never change `run_id`" in step0
    step2 = SKILL[SKILL.index("## Step 2: Clarify"):SKILL.index("## Step 3: Design")]
    assert 'Set `phases.design`, `phases.estimate`, and `phases.generate` to `"pending"` in the same write when any is `"in_progress"` or `"completed"`' in step2
    step3 = SKILL[SKILL.index("## Step 3: Design"):SKILL.index("## Step 4: Estimate")]
    assert 'and `phases.estimate` and `phases.generate` to `"pending"` when either is `"in_progress"` or `"completed"`, in one write' in step3


@pytest.mark.parametrize(("phases", "rule"), [
    ({"discover": "completed", "clarify": "in_progress", "design": "completed", "estimate": "completed"}, 1),
    ({"discover": "completed", "clarify": "in_progress", "design": "pending"}, 1),
    ({"discover": "completed", "clarify": "completed", "design": "pending", "estimate": "completed"}, 2),
    ({"discover": "completed", "clarify": "completed"}, 2),
    ({"discover": "completed", "clarify": "completed", "design": "in_progress"}, 2),
    ({"discover": "completed", "clarify": "completed", "design": "completed"}, 3),
    ({"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "pending"}, 3),
    ({"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "in_progress"}, 3),
    ({"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed"}, 6),
    ({"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed", "generate": "in_progress"}, 4),
    ({"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed", "generate": "completed"}, 7),
    ({"discover": "completed", "clarify": "pending"}, 8),
    ({"discover": "in_progress", "clarify": "pending"}, 9),
])
def test_interrupted_reentry_resumes_the_active_phase(phases, rule) -> None:
    assert _rule_for({"phases": phases}) == rule


@pytest.mark.parametrize("estimate", ["pending", "in_progress", "completed"])
@pytest.mark.parametrize("generate", ["pending", "in_progress", "completed", None])
@pytest.mark.parametrize("run_mode", [None, "decide", "decide_and_execute"])
def test_resume_rules_give_one_answer_for_every_late_phase_state(estimate, generate, run_mode) -> None:
    phases = {"discover": "completed", "clarify": "completed", "design": "completed", "estimate": estimate}
    if generate is not None:
        phases["generate"] = generate
    status = {"phases": phases, **({"run_mode": run_mode} if run_mode else {})}
    rule = _rule_for(status)
    if estimate != "completed":
        assert rule == 3
    elif generate == "in_progress":
        assert rule == 4
    elif generate == "completed":
        assert rule == 7
    else:
        assert rule == (5 if run_mode == "decide_and_execute" else 6)


def test_reentry_after_changing_answers_runs_clarify_design_then_estimate() -> None:
    status = {"phases": {"discover": "completed", "clarify": "completed", "design": "completed", "estimate": "completed", "generate": "completed"}}
    assert _rule_for(status) == 7
    status["phases"].update(clarify="in_progress", design="pending", estimate="pending", generate="pending")
    assert _rule_for(status) == 1
    status["phases"]["clarify"] = "completed"
    assert _rule_for(status) == 2
    status["phases"]["design"] = "completed"
    assert _rule_for(status) == 3


def test_design_runs_again_without_changing_answers() -> None:
    status = {"phases": {"discover": "completed", "clarify": "completed", "design": "pending", "estimate": "pending"}}
    assert _rule_for(status) == 2


def test_design_doc_runs_the_plan_and_the_check() -> None:
    assert "scripts/design-ai.py plan $MIGRATION_DIR" in DESIGN_DOC
    assert "scripts/design-ai.py check $MIGRATION_DIR" in DESIGN_DOC
    for lane in ("runtime", "mantle", "in_region_check", "api_conflict", "provider_mismatch", "no_mantle_path", "api_unknown"):
        assert f"| `{lane}`" in DESIGN_DOC, lane
    assert DESIGN.ASSUMPTION.format(ids="<ids>") in DESIGN_DOC
    assert "Do not redirect it to a file: this phase writes nothing outside `$MIGRATION_DIR`" in DESIGN_DOC
    assert "a Responses source on GPT-6.1 Sol that needs Guardrails uses `converse`" in DESIGN_DOC


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


CLARIFY = (BMA / "references/phases/clarify/clarify-ai-only.md").read_text(encoding="utf-8")
PINNED_QUESTIONS = {"ai_priority": "Q2", "ai_vision": "Q6", "ai_token_volume": "Q7", "ai_latency": "Q8",
                    "ai_complexity": "Q9", "ai_critical_feature": "Q10"}
PINNED = {
    "ai_priority": ("quality", "speed", "cost", "balanced"),
    "ai_latency": ("critical", "important", "flexible"),
    "ai_complexity": ("simple", "moderate", "complex"),
    "ai_token_volume": ("low", "medium", "high", "very_high"),
    "ai_vision": ("text-only", "vision", "audio"),
    "ai_critical_feature": ("function_calling", "ultra_long_context", "extended_thinking", "prompt_caching", "rag",
                            "agentic", "realtime_speed", "image_generation", "speech", "none"),
}


def _interpret(key: str) -> tuple[dict[int, str], tuple[int, str]]:
    line = next(l for l in CLARIFY.splitlines() if l.startswith(f"Interpret → `{key}`"))
    mapping, _, default = line.partition("Default:")
    pairs = {int(n): v for n, v in re.findall(r"(\d+) → `\"([a-z_-]+)\"`", mapping)}
    n, value = re.search(r"(\d+) → `\"([a-z_-]+)\"`", default).groups()
    return pairs, (int(n), value)


def _with_value(prefs: dict, key: str, value) -> dict:
    prefs = copy.deepcopy(prefs)
    prefs["ai_constraints"][key] = {"value": value, "chosen_by": "user"}
    return prefs


def test_design_pins_the_clarify_values_with_a_listed_default() -> None:
    assert DESIGN.PREFERENCE_VALUES == PINNED
    for key, values in PINNED.items():
        assert DESIGN.DEFAULTS[key] in values, key


def test_token_volume_values_come_from_the_tier_table() -> None:
    tiers = json.loads((BMA / "references/vendored/ai/token-volume-tiers.json").read_text(encoding="utf-8"))
    assert PINNED["ai_token_volume"] == tuple(t["value"] for t in tiers["tiers"])


@pytest.mark.parametrize(("key", "value"), [(k, v) for k, vs in PINNED.items() for v in vs])
def test_plan_accepts_and_copies_every_pinned_value(key, value) -> None:
    _, profile, prefs = _load(V10_FIXTURE)
    assert DESIGN.build_plan(profile, _with_value(prefs, key, value))["constraints"][key] == {"value": value, "chosen_by": "user"}


@pytest.mark.parametrize(("key", "value"), [
    ("ai_priority", "fastest"), ("ai_priority", "Balanced"), ("ai_priority", ["balanced"]), ("ai_latency", "low"),
    ("ai_complexity", "hard"), ("ai_token_volume", "huge"), ("ai_vision", "image"), ("ai_vision", ["vision"]),
    ("ai_critical_feature", "long_context"), ("ai_critical_feature", ""), ("ai_critical_feature", None)])
def test_plan_rejects_an_off_list_value_and_names_the_allowed_ones(key, value) -> None:
    _, profile, prefs = _load(V10_FIXTURE)
    with pytest.raises(DESIGN.DesignInputError) as err:
        DESIGN.build_plan(profile, _with_value(prefs, key, value))
    assert err.value.code == "preferences_invalid" and key in err.value.detail
    assert all(v in err.value.detail for v in PINNED[key])


def test_unpinned_keys_keep_their_free_form_values() -> None:
    _, profile, prefs = _load(V10_FIXTURE)
    prefs = _with_value(_with_value(prefs, "cross_cloud", "egress-concerned"), "ai_framework", ["direct", "langchain"])
    assert DESIGN.build_plan(profile, prefs)["constraints"]["cross_cloud"]["value"] == "egress-concerned"


@pytest.mark.parametrize("key", list(PINNED_QUESTIONS))
def test_clarify_interpret_line_writes_exactly_the_pinned_values(key) -> None:
    pairs, (_, default) = _interpret(key)
    assert set(pairs.values()) == set(PINNED[key]) and default == DESIGN.DEFAULTS[key]


@pytest.mark.parametrize("key", list(PINNED_QUESTIONS))
def test_clarify_interpret_line_maps_every_answer_option(key) -> None:
    section = CLARIFY[CLARIFY.index(f"## {PINNED_QUESTIONS[key]} — "):]
    options = next(l for l in section.splitlines() if re.match(r"^> 1\\\)", l))
    count = len(re.findall(r"(?:^> |\| )(\d+)\\\)", options))
    pairs, (n, value) = _interpret(key)
    dont_know = {"ai_token_volume": 5}.get(key)
    assert sorted(pairs) == [i for i in range(1, count + 1) if i != dont_know] and pairs.get(n, value) == value


def test_clarify_maps_specialized_and_dont_know_priority_to_balanced() -> None:
    pairs, _ = _interpret("ai_priority")
    assert (pairs[4], pairs[5], pairs[6]) == ("balanced", "balanced", "balanced")
    line = next(l for l in CLARIFY.splitlines() if l.startswith("Interpret → `ai_priority`"))
    assert "Q10 decides" in line


def test_design_keeps_an_eligible_same_model_for_every_priority() -> None:
    item = DESIGN_DOC[DESIGN_DOC.index("   2. The same model on Bedrock"):DESIGN_DOC.index("   3. `ai_priority`")]
    assert "No `ai_priority` moves it to another family" in item
    assert all(f"`{p}`" in item for p in ("quality", "speed", "cost"))


def test_clarify_q5_agrees_that_a_priority_never_moves_a_same_model_source() -> None:
    q5 = CLARIFY[CLARIFY.index("## Q5 — "):CLARIFY.index("### Batch 1 → Save Draft")]
    assert "Q10 special features > the same model on Bedrock > Q2 priority" in q5
    assert "GPT-5.5 + Q2=cost → GPT-5.5" in q5 and "GPT-5.5 + Q2=cost → Sonnet 5" not in q5


def test_design_reads_guide_volume_sections_by_tier_name() -> None:
    step2 = DESIGN_DOC[DESIGN_DOC.index("## Step 2"):DESIGN_DOC.index("## Step 3")]
    assert "by tier name" in step2 and "token-volume-tiers.json" in step2 and "per-day" in step2


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


@pytest.mark.parametrize("volume", PINNED["ai_token_volume"])
@pytest.mark.parametrize("tiered", [True, False])
def test_check_enforces_the_volume_rules_for_every_tier(volume, tiered) -> None:
    def mutate(d, p, f):
        f["ai_constraints"]["ai_token_volume"]["value"] = volume
        d["ai_architecture"]["tiered_strategy"] = {"tiers": [], "note": "60/30/10"} if tiered else None
        for row in d["ai_architecture"]["bedrock_models"]:
            row["quota_risk"] = "high" if tiered else "low"
    codes = _mutated(MANTLE_FIXTURE, mutate) & {"tiered_strategy", "quota_risk_floor"}
    high = volume in ("high", "very_high")
    assert codes == (set() if tiered == high else {"tiered_strategy", "quota_risk_floor"} if high else {"tiered_strategy"})


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


@pytest.mark.parametrize(("price", "ok"), [
    ("2.20/13.20 per 1M tokens", True), ("$5.50/$33.00 per 1M tokens (In-Region)", True), ("0.02 per 1M tokens", True),
    ("0.04 per image", True), ("unverified (the model card publishes no Geo price)", True),
    ("$2.20 input, $13.20 output", False), ("about 10% more", False), ("2.20 / 13.20 per million", False),
])
def test_check_requires_the_price_grammar_estimate_reads(price, ok) -> None:
    for key in ("bedrock_price", "source_provider_price"):
        codes = _mutated(MANTLE_FIXTURE, lambda d, p, f: _set(_row(d, EMB_ID), key, price))
        assert ("row_bad_price" not in codes) is ok, (key, price, codes)


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


W_RESP, W_CHAT = "openai_api.gpt-5.5.openai.responses.create.plain", "openai_api.gpt-5.5.openai.chat.completions.create.plain"
CHAT = "openai.chat.completions.create"


def _two_gpt_workloads(d: dict, p: dict, f: dict, first_method: str, mantle: list[dict]) -> None:
    """Both GPT-5.5 workloads on one target; the embedding row stays as it is."""
    p["workloads"][0]["sdk_method"] = first_method
    f["ai_constraints"]["mantle_requirements"]["value"] = mantle
    d["ai_architecture"]["bedrock_models"] = [r for r in d["ai_architecture"]["bedrock_models"] if r["aws_model_id"] == EMB_ID]


def _runtime_row(ids: list[str], api: str) -> dict:
    base = copy.deepcopy(_load(MANTLE_FIXTURE)[0]["ai_architecture"]["bedrock_models"][1])
    base.update(required_client_api=api, capability_gaps=[], endpoint_assumption=DESIGN.ASSUMPTION.format(ids=", ".join(ids)))
    return base


def _mantle_row(path: str, api: str, req: dict) -> dict:
    base = copy.deepcopy(_load(MANTLE_FIXTURE)[0]["ai_architecture"]["bedrock_models"][0])
    base.update(aws_model_id=RUNTIME_ID, migration_path=path, required_client_api=api, mantle_selector=req["selector"], mantle_requirement=req)
    return base


def _same_target(d: dict, rows: list[dict]) -> None:
    for block in d["design_blocks"][:2]:
        block["target_bedrock_model"] = RUNTIME_ID
    d["metadata"]["bedrock_models_selected"] = [RUNTIME_ID, EMB_ID]
    d["ai_architecture"]["bedrock_models"] = rows + d["ai_architecture"]["bedrock_models"]


def test_check_names_every_workload_sharing_a_runtime_row() -> None:
    def mutate(d, p, f):
        _two_gpt_workloads(d, p, f, CHAT, [])
        _same_target(d, [_runtime_row([W_RESP, W_CHAT], "chat_completions")])
    assert _mutated(MANTLE_FIXTURE, mutate) == set()


def test_check_rejects_a_shared_row_that_changes_one_workloads_api() -> None:
    def mutate(d, p, f):
        _two_gpt_workloads(d, p, f, "openai.responses.create", [])
        _same_target(d, [_runtime_row([W_RESP, W_CHAT], "chat_completions")])
    assert _mutated(MANTLE_FIXTURE, mutate) == {"client_api_changed"}


def test_check_accepts_split_runtime_rows_for_responses_and_chat_on_one_target() -> None:
    def mutate(d, p, f):
        _two_gpt_workloads(d, p, f, "openai.responses.create", [])
        _same_target(d, [_runtime_row([W_RESP], "responses"), _runtime_row([W_CHAT], "chat_completions")])
    assert _mutated(MANTLE_FIXTURE, mutate) == set()


def test_check_accepts_projects_mantle_rows_that_keep_each_workloads_api() -> None:
    req = {"workload_id": "*", "selector": "projects", "source": "user"}
    def mutate(d, p, f):
        _two_gpt_workloads(d, p, f, "openai.responses.create", [req])
        _row(d, EMB_ID)["capability_gaps"] = ["projects (user, Q10.5): embeddings have no bedrock-mantle path"]
        _same_target(d, [_mantle_row("mantle_openai_responses", "responses", req), _mantle_row("mantle_openai_chat", "chat_completions", req)])
    assert _mutated(MANTLE_FIXTURE, mutate) == set()
    def one_row(d, p, f):
        mutate(d, p, f)
        d["ai_architecture"]["bedrock_models"].pop(1)
    assert "mantle_path_api" in _mutated(MANTLE_FIXTURE, one_row)


def test_check_honours_distinct_named_mantle_requirements_on_one_target() -> None:
    first = {"workload_id": W_RESP, "selector": "projects", "source": "user"}
    second = {"workload_id": W_CHAT, "selector": "projects", "source": "user"}
    def mutate(d, p, f):
        _two_gpt_workloads(d, p, f, "openai.responses.create", [first, second])
        _same_target(d, [_mantle_row("mantle_openai_responses", "responses", first), _mantle_row("mantle_openai_chat", "chat_completions", second)])
    assert _mutated(MANTLE_FIXTURE, mutate) == set()
    def dropped(d, p, f):
        mutate(d, p, f)
        d["ai_architecture"]["bedrock_models"][1]["mantle_requirement"] = first
    assert "block_without_row" in _mutated(MANTLE_FIXTURE, dropped)
    def one_row(d, p, f):
        mutate(d, p, f)
        d["ai_architecture"]["bedrock_models"].pop(1)
    assert "mantle_requirement_unrecorded" in _mutated(MANTLE_FIXTURE, one_row)


def test_check_allows_one_mantle_and_one_runtime_row_for_the_same_model_and_target() -> None:
    def mutate(d, p, f):
        d["design_blocks"][1]["target_bedrock_model"] = MANTLE_ID
        d["metadata"]["bedrock_models_selected"] = [MANTLE_ID, EMB_ID]
        _row(d, RUNTIME_ID)["aws_model_id"] = MANTLE_ID
    codes = _mutated(MANTLE_FIXTURE, mutate)
    assert "duplicate_row" not in codes and "block_without_row" not in codes
    twice = _mutated(MANTLE_FIXTURE, lambda d, p, f: d["ai_architecture"]["bedrock_models"].append(copy.deepcopy(_row(d, MANTLE_ID))))
    assert "duplicate_row" in twice


def _runtime_web_search(target: str, path: str, api: str):
    def mutate(d, p, f):
        row = _row(d, MANTLE_ID)
        row.update(aws_model_id=target, migration_path=path, required_client_api=api,
                   capability_gaps=["web_search (detected, app/research.py:14) stays on bedrock-runtime"],
                   endpoint_assumption=DESIGN.ASSUMPTION.format(ids=W_RESP), model_change=path == "converse")
        row.pop("mantle_selector"); row.pop("mantle_requirement")
        d["design_blocks"][0]["target_bedrock_model"] = target
        d["metadata"]["bedrock_models_selected"][0] = target
    return mutate


def test_check_rejects_a_same_protocol_runtime_row_that_only_mentions_the_mantle_selector() -> None:
    codes = _mutated(MANTLE_FIXTURE, _runtime_web_search("us.openai.gpt-5.5x", "runtime_openai_cris", "responses"))
    assert codes == {"mantle_requirement_unhonored"}


@pytest.mark.parametrize("change", [False, True])
def test_check_rejects_a_same_model_target_relabelled_converse_on_a_mantle_lane(change) -> None:
    def mutate(d, p, f):
        _runtime_web_search("us.openai.gpt-5.5x", "converse", "converse")(d, p, f)
        _row(d, "us.openai.gpt-5.5x")["model_change"] = change
    assert _mutated(MANTLE_FIXTURE, mutate) == {"mantle_requirement_unhonored"}


@pytest.mark.parametrize(("provider", "target", "same"), [
    ("openai", "openai.gpt-5.5", True), ("openai", "us.openai.gpt-6-sol", True), ("openai", "global.openai.gpt-5.6-terra", True),
    ("openai", "openai.gpt-oss-120b-1:0", False), ("openai", "us.anthropic.claude-sonnet-5-5", False),
    ("anthropic", "us.anthropic.claude-sonnet-5", True), ("anthropic", "anthropic.claude-haiku-5-5", True),
    ("anthropic", "us.openai.gpt-5.5", False), ("google", "us.anthropic.claude-haiku-5-5", False),
])
def test_same_family_reads_the_target_id(provider, target, same) -> None:
    assert DESIGN._same_family(provider, target) is same


def test_check_accepts_a_cross_family_runtime_row_that_discloses_the_selector() -> None:
    assert _mutated(MANTLE_FIXTURE, _runtime_web_search("us.anthropic.claude-sonnet-5-5", "converse", "converse")) == set()


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda d: d["ai_architecture"]["bedrock_models"].append(copy.deepcopy(d["ai_architecture"]["bedrock_models"][1])), "duplicate_row"),
    (lambda d: d["ai_architecture"]["bedrock_models"].append("row"), "row_not_object"),
    (lambda d: d["ai_architecture"]["bedrock_models"].append(None), "row_not_object"),
    (lambda d: d["ai_architecture"]["bedrock_models"][1].update(capability_gaps="web_search"), "row_bad_list"),
    (lambda d: d["ai_architecture"]["bedrock_models"][0].update(mantle_requirement="web_search"), "row_bad_type"),
    (lambda d: d["ai_architecture"]["bedrock_models"][0].update(aws_model_id=7), "row_bad_type"),
    (lambda d: d["ai_architecture"]["capability_mapping"].update(text_generation="full"), "capability_mapping"),
    (lambda d: d["ai_architecture"].update(tiered_strategy=[]), "tiered_strategy"),
    (lambda d: d["multi_model_warnings"].append({"type": ["x"], "message": "m"}), "multi_model_warning_shape"),
], ids=["duplicate-same-lane", "string-row", "null-row", "gaps-string", "requirement-string", "id-number",
        "mapping-string", "tiered-list", "warning-type-list"])
def test_cli_returns_structured_errors_for_malformed_rows(mutate, code, tmp_path: Path, capsys) -> None:
    for name in ("ai-workload-profile.json", "preferences.json"):
        shutil.copy(MANTLE_FIXTURE / name, tmp_path / name)
    design = copy.deepcopy(_load(MANTLE_FIXTURE)[0])
    mutate(design)
    (tmp_path / "aws-design-ai.json").write_text(json.dumps(design))
    assert DESIGN.main(["check", str(tmp_path)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and code in {e["code"] for e in out["errors"]}


@pytest.mark.parametrize("mutate", [
    lambda f: f.update(metadata="x"),
    lambda f: f.update(ai_constraints=[]),
    lambda f: f["ai_constraints"].update(ai_priority="balanced"),
    lambda f: f["ai_constraints"]["ai_token_volume"].update(value=["high"]),
    lambda f: f["ai_constraints"]["mantle_requirements"].update(value="none"),
    lambda f: f["ai_constraints"]["mantle_requirements"].update(value=["web_search"]),
    lambda f: f["design_constraints"]["compliance"].update(value="gdpr"),
], ids=["metadata", "section", "entry", "volume-list", "requirements-string", "requirement-entry", "compliance-string"])
def test_cli_rejects_malformed_preferences_with_json(mutate, tmp_path: Path, capsys) -> None:
    for name in ("ai-workload-profile.json", "aws-design-ai.json"):
        shutil.copy(MANTLE_FIXTURE / name, tmp_path / name)
    prefs = copy.deepcopy(_load(MANTLE_FIXTURE)[2])
    mutate(prefs)
    (tmp_path / "preferences.json").write_text(json.dumps(prefs))
    for command in ("plan", "check"):
        assert DESIGN.main([command, str(tmp_path)]) == 1
        assert json.loads(capsys.readouterr().out)["error"] == "preferences_invalid"


def _old_run(tmp_path: Path, mutate) -> Path:
    prefs = copy.deepcopy(_load(MANTLE_FIXTURE)[2])
    mutate(prefs)
    (tmp_path / "preferences.json").write_text(json.dumps(prefs))
    return tmp_path


@pytest.mark.parametrize(("mutate", "error", "named"), [
    (lambda f: f["ai_constraints"]["ai_priority"].update(value="fastest"), "preferences_invalid", "ai_constraints.ai_priority"),
    (lambda f: f["ai_constraints"]["ai_token_volume"].update(value="huge"), "preferences_invalid", "ai_constraints.ai_token_volume"),
    (lambda f: f["ai_constraints"].update(ai_vision="image"), "preferences_invalid", "ai_constraints.ai_vision"),
    (lambda f: f["metadata"].update(migration_type="full"), "preferences_not_ai_only", "migration_type"),
    (lambda f: f.update(metadata=[]), "preferences_invalid", "metadata"),
], ids=["old-priority", "old-volume", "bare-entry", "not-ai-only", "metadata"])
def test_clarify_preferences_check_rejects_what_plan_rejects_without_a_profile(mutate, error, named, tmp_path: Path, capsys) -> None:
    run = _old_run(tmp_path, mutate)
    assert not (run / "ai-workload-profile.json").exists()
    assert DESIGN.main(["preferences", str(run)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error"] == error and named in out["detail"]
    shutil.copy(MANTLE_FIXTURE / "ai-workload-profile.json", run / "ai-workload-profile.json")
    assert DESIGN.main(["plan", str(run)]) == 1 and json.loads(capsys.readouterr().out)["error"] == error


def test_clarify_preferences_check_passes_a_file_once_the_named_question_is_answered_again(tmp_path: Path, capsys) -> None:
    run = _old_run(tmp_path, lambda f: f["ai_constraints"].update(
        ai_priority={"value": "fastest", "chosen_by": "default"}, ai_latency={"value": "low", "chosen_by": "user"}))
    assert DESIGN.main(["preferences", str(run)]) == 1
    assert "ai_constraints.ai_priority" in json.loads(capsys.readouterr().out)["detail"]
    prefs = json.loads((run / "preferences.json").read_text())
    prefs["ai_constraints"]["ai_priority"] = {"value": "speed", "chosen_by": "user"}
    (run / "preferences.json").write_text(json.dumps(prefs))
    assert DESIGN.main(["preferences", str(run)]) == 1
    assert "ai_constraints.ai_latency" in json.loads(capsys.readouterr().out)["detail"]
    prefs["ai_constraints"]["ai_latency"] = {"value": "critical", "chosen_by": "user"}
    (run / "preferences.json").write_text(json.dumps(prefs))
    assert DESIGN.main(["preferences", str(run)]) == 0 and json.loads(capsys.readouterr().out) == {"ok": True}


def test_clarify_preferences_check_reports_a_missing_file(tmp_path: Path, capsys) -> None:
    assert DESIGN.main(["preferences", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "preferences_not_found"


def test_clarify_step_4_runs_the_preferences_check_before_completing_and_names_each_question() -> None:
    step0 = CLARIFY[CLARIFY.index("## Step 0"):CLARIFY.index("## Step 1:")]
    step4 = CLARIFY[CLARIFY.index("## Step 4"):]
    assert "skip to Step 4, which checks the existing `preferences.json`" in step0
    command = "python3 <SKILL_BASE>/scripts/design-ai.py preferences $MIGRATION_DIR"
    assert step4.index(command) < step4.index('Set `phases.clarify` to `"completed"`')
    assert 'Do not complete Clarify until it prints `"ok": true`' in step4
    table = dict(re.findall(r"^\| `([a-z_]+)` +\| (Q[0-9.]+) +\|$", step4, re.M))
    assert table == PINNED_QUESTIONS
    for key, qid in table.items():
        section = re.split(r"^## Q[0-9.]+ — ", CLARIFY[CLARIFY.index(f"## {qid} — "):], flags=re.M)[1]
        assert f"Interpret → `{key}`" in section, (key, qid)
    lines = re.findall(r"^\d\. (.+)$", step4, re.M)
    assert len(lines) == 2 and lines[1].startswith("Otherwise") and "continue to Step 1" in lines[1]
    assert '4 → `"balanced"` (Q10 decides)' in CLARIFY and "When the new Q2 answer is 4 (Specialized capability), ask Q10" in lines[0]


def test_design_and_estimate_send_an_invalid_value_back_to_a_clarify_path_that_can_finish() -> None:
    estimate = (BMA / "references/phases/estimate/estimate-ai.md").read_text(encoding="utf-8")
    for doc in (DESIGN_DOC, estimate):
        row = next(l for l in doc.splitlines() if l.startswith("| `preferences_invalid`"))
        assert "choose Start fresh, or re-use the answers and re-answer the question Clarify Step 4 names" in row


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


def test_design_drops_two_option_choices_that_cannot_serve_the_critical_feature() -> None:
    text = (BMA / "references" / "phases" / "design" / "design-ai.md").read_text(encoding="utf-8")
    step2 = text[text.index("   1. A Q10 `ai_critical_feature`"):]
    assert "For `rag`, Bedrock Knowledge Bases needs a Claude or Nova target via Converse" in step2.splitlines()[0]
    assert "Present only options that serve the item 2.1 feature" in step2
