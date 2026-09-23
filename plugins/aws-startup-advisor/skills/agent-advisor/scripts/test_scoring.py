import json
import pathlib

import pytest

import scoring
import score_units


def _write_profile(directory, profile):
    (directory / f"{profile['id']}.json").write_text(json.dumps(profile))


def _minimal(id_, status="ga"):
    return {
        "id": id_,
        "display_name": id_,
        "status": status,
        "service_card": f"{id_}.md",
        "hard_constraints": [],
        "affinities": {},
        "deployment_models": [],
        "volatile_facts": [],
    }


def test_load_profiles_filters_by_status_and_sorts(tmp_path):
    _write_profile(tmp_path, _minimal("ecs"))
    _write_profile(tmp_path, _minimal("agentcore"))
    _write_profile(tmp_path, _minimal("preview_rt", status="preview"))

    profiles = scoring.load_profiles(tmp_path)

    assert [p["id"] for p in profiles] == ["agentcore", "ecs"]


def test_load_profiles_rejects_bad_json(tmp_path):
    (tmp_path / "broken.json").write_text("{not json")

    with pytest.raises(ValueError, match="broken.json"):
        scoring.load_profiles(tmp_path)


def test_load_profiles_rejects_missing_key(tmp_path):
    (tmp_path / "x.json").write_text(json.dumps({"id": "x", "status": "ga"}))

    with pytest.raises(ValueError, match="x.json"):
        scoring.load_profiles(tmp_path)


def test_hard_constraint_scalar_match():
    profiles = [
        {**_minimal("agentcore"), "hard_constraints": [
            {"field": "session_duration", "value": "over_8hr", "reason": "8hr cap"}]},
        {**_minimal("ecs"), "hard_constraints": []},
    ]
    eliminated = scoring._apply_hard_constraints(
        {"session_duration": "over_8hr"}, profiles)
    assert eliminated == {"agentcore": "8hr cap"}


def test_hard_constraint_compliance_list_match():
    profiles = [
        {**_minimal("agentcore"), "hard_constraints": [
            {"field": "compliance", "value": "fedramp", "reason": "not FedRAMP"}]},
    ]
    eliminated = scoring._apply_hard_constraints(
        {"compliance": ["soc2", "fedramp"]}, profiles)
    assert eliminated == {"agentcore": "not FedRAMP"}


def test_hard_constraint_no_match():
    profiles = [
        {**_minimal("agentcore"), "hard_constraints": [
            {"field": "session_duration", "value": "over_8hr", "reason": "8hr cap"}]},
    ]
    eliminated = scoring._apply_hard_constraints(
        {"session_duration": "15min_to_8hr", "compliance": ["none"]}, profiles)
    assert eliminated == {}


_AWS_DOCS_SOURCE = "https://docs.aws.amazon.com/lambda/latest/dg/configuration-timeout.html"
_AGENTCORE_SESSION_SOURCE = "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html"
_AGENTCORE_GPU_SOURCE = "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-how-it-works.html"
_AGENTCORE_COMPUTE_SOURCE = "https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html"
_MICROVMS_SOURCE = "https://docs.aws.amazon.com/lambda/latest/dg/"


def _run_evidence(verifications, run_id="test-run"):
    return {
        "artifact_type": scoring.RUN_EVIDENCE_ARTIFACT_TYPE,
        "schema_version": scoring.RUN_EVIDENCE_SCHEMA_VERSION,
        "run_id": run_id,
        "verifications": verifications,
    }


def test_verification_required_constraint_is_deferred_and_provisional():
    profiles = [{**_minimal("agentcore"), "hard_constraints": [{
        "field": "session_duration", "value": "over_8hr", "reason": "8hr cap",
        "verification_required": True, "verification_key": "agentcore.session_cap",
        "verification_expected_value": "8h", "verification_sources": [_AWS_DOCS_SOURCE],
    }]}]
    result = scoring.score({"entry_point": "build_scratch", "answers": {
        "session_duration": "over_8hr"}}, profiles=profiles)
    assert result["eliminated"] == {}
    assert result["recommendation_status"] == "provisional"
    assert result["deferred_verification_requirements"] == [{
        "runtime": "agentcore", "field": "session_duration", "value": "over_8hr",
        "reason": "8hr cap", "verification_key": "agentcore.session_cap",
        "verification_expected_value": "8h",
        "verification_sources": [_AWS_DOCS_SOURCE],
    }]


def test_seed_controlled_evidence_cannot_finalize_elimination():
    profiles = [{**_minimal("agentcore"), "hard_constraints": [{
        "field": "session_duration", "value": "over_8hr", "reason": "8hr cap",
        "verification_required": True, "verification_key": "agentcore.session_cap",
        "verification_expected_value": "8h", "verification_sources": [_AWS_DOCS_SOURCE],
    }]}]
    result = scoring.score({"entry_point": "build_scratch", "answers": {
        "session_duration": "over_8hr",
        "current_run_verifications": {
            "agentcore.session_cap": {
                "status": "verified", "verified_this_run": True,
                "source": _AWS_DOCS_SOURCE, "value": "8h",
            },
        },
    }}, profiles=profiles)
    assert result["eliminated"] == {}
    assert result["recommendation_status"] == "provisional"


@pytest.mark.parametrize("record", [
    {"status": "verified"},
    {"status": "verified", "source": _AWS_DOCS_SOURCE},
    {"status": "verified", "value": "8h"},
    {"status": "verified", "source": "https://example.com/agentcore", "value": "8h"},
])
def test_incomplete_run_materialized_evidence_cannot_finalize_elimination(record):
    profiles = [{**_minimal("agentcore"), "hard_constraints": [{
        "field": "session_duration", "value": "over_8hr", "reason": "8hr cap",
        "verification_required": True, "verification_key": "agentcore.session_cap",
        "verification_expected_value": "8h", "verification_sources": [_AWS_DOCS_SOURCE],
    }]}]
    result = scoring.score(
        {"entry_point": "build_scratch", "answers": {"session_duration": "over_8hr"}},
        profiles=profiles,
        run_evidence=_run_evidence({"agentcore.session_cap": record}),
    )
    assert result["eliminated"] == {}
    assert result["recommendation_status"] == "provisional"


def test_changed_lambda_value_cannot_apply_stale_elimination():
    profiles = [{**_minimal("lambda"), "hard_constraints": [{
        "field": "session_duration", "value": "15min_to_8hr", "reason": "15m cap",
        "verification_required": True, "verification_key": "lambda.timeout",
        "verification_expected_value": "15m", "verification_sources": [_AWS_DOCS_SOURCE],
    }]}]
    result = scoring.score(
        {"entry_point": "build_scratch", "answers": {"session_duration": "15min_to_8hr"}},
        profiles=profiles,
        run_evidence=_run_evidence({"lambda.timeout": {
            "status": "verified", "source": _AWS_DOCS_SOURCE, "value": "30m",
        }}),
    )
    assert result["eliminated"] == {}
    assert result["recommendation_status"] == "provisional"


def test_agentcore_compute_evidence_cannot_certify_gpu_constraint():
    profiles = [{**_minimal("agentcore"), "hard_constraints": [{
        "field": "compute_tier", "value": "gpu", "reason": "no GPU support",
        "verification_required": True, "verification_key": "agentcore.gpu_support",
        "verification_expected_value": "unsupported", "verification_sources": [_AGENTCORE_GPU_SOURCE],
    }]}]
    result = scoring.score(
        {"entry_point": "build_scratch", "answers": {"compute_tier": "gpu"}},
        profiles=profiles,
        run_evidence=_run_evidence({"agentcore.gpu_support": {
            "status": "verified", "source": _AGENTCORE_COMPUTE_SOURCE,
            "value": "unsupported",
        }}),
    )
    assert result["eliminated"] == {}
    assert result["recommendation_status"] == "provisional"


def test_source_backed_matching_run_materialized_evidence_finalizes_constraint():
    profiles = [{**_minimal("agentcore"), "hard_constraints": [{
        "field": "session_duration", "value": "over_8hr", "reason": "8hr cap",
        "verification_required": True, "verification_key": "agentcore.session_cap",
        "verification_expected_value": "8h", "verification_sources": [_AWS_DOCS_SOURCE],
    }]}]
    result = scoring.score(
        {"entry_point": "build_scratch", "answers": {"session_duration": "over_8hr"}},
        profiles=profiles,
        run_evidence=_run_evidence({"agentcore.session_cap": {
            "status": "verified", "source": _AWS_DOCS_SOURCE, "value": "8h",
        }}),
    )
    assert result["eliminated"] == {"agentcore": "8hr cap"}
    assert result["deferred_verification_requirements"] == []
    assert result["recommendation_status"] == "final"


def test_seed_schema_rejects_current_run_verifications():
    import jsonschema

    schema_path = pathlib.Path(scoring.__file__).parent / "schemas" / "seed.json"
    schema = json.loads(schema_path.read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"system": {"current_run_verifications": {}}}, schema)


def test_score_units_ignores_seed_evidence_and_uses_run_artifact(tmp_path, capsys):
    answers_path = tmp_path / "answers.json"
    answers_path.write_text(json.dumps({
        "entry_point": "build_scratch",
        "system": {"current_run_verifications": {"lambda.timeout": {
            "status": "verified", "verified_this_run": True,
            "source": _AWS_DOCS_SOURCE, "value": "15m",
        }}},
        "primary_unit": "primary-agent",
        "units": {"primary-agent": {
            "workload_class": "agent_session", "session_duration": "15min_to_8hr",
        }},
    }))

    assert score_units.main([str(answers_path)]) == 0
    seed_only = json.loads(capsys.readouterr().out)
    assert "lambda" not in seed_only["eliminated"]
    assert seed_only["recommendation_status"] == "provisional"

    (tmp_path / score_units.RUN_EVIDENCE_FILENAME).write_text(json.dumps(
        _run_evidence({"lambda.timeout": {
            "status": "verified", "source": _AWS_DOCS_SOURCE, "value": "15m",
        }}, run_id=tmp_path.name)
    ))
    assert score_units.main([str(answers_path)]) == 0
    materialized = json.loads(capsys.readouterr().out)
    assert "lambda" in materialized["eliminated"]
    assert materialized["recommendation_status"] == "final"


def test_score_units_rejects_evidence_from_another_run(tmp_path):
    answers_path = tmp_path / "answers.json"
    answers_path.write_text(json.dumps({"system": {}, "units": {}}))
    (tmp_path / score_units.RUN_EVIDENCE_FILENAME).write_text(json.dumps(
        _run_evidence({}, run_id="another-run")
    ))

    with pytest.raises(ValueError, match="run_id must match"):
        score_units.main([str(answers_path)])


def test_compute_scores_uses_affinity_and_neutral_default():
    profiles = [
        {**_minimal("agentcore"), "affinities": {
            "session_duration": {"15min_to_8hr": 5},
            "traffic_pattern": {"bursty": 5}}},
        {**_minimal("ecs"), "affinities": {
            "session_duration": {"15min_to_8hr": 3}}},
    ]
    answers = {"session_duration": "15min_to_8hr", "traffic_pattern": "bursty"}
    scores = scoring._compute_scores(answers, profiles, eliminated={})
    # agentcore: 5 + 5 + neutral(2) for each remaining dim
    # ecs: 3 + neutral(2) for each remaining dim
    assert scores["agentcore"] == 5 + 5 + scoring.NEUTRAL_SCORE * (len(scoring.DIMENSIONS) - 2)
    assert scores["ecs"] == 3 + scoring.NEUTRAL_SCORE * (len(scoring.DIMENSIONS) - 1)
    assert scores["agentcore"] > scores["ecs"]


def test_compute_scores_omits_eliminated():
    profiles = [{**_minimal("agentcore"), "affinities": {}}]
    scores = scoring._compute_scores({}, profiles, eliminated={"agentcore": "x"})
    assert scores == {}


def test_defaults_cover_all_dimensions():
    for dim in scoring.DIMENSIONS:
        assert dim in scoring.DEFAULTS


def test_verdict_single_winner():
    verdict, co = scoring._determine_verdict(
        {"agentcore": 30, "ecs": 20}, eliminated={})
    assert verdict == "agentcore"
    assert co == []


def test_verdict_co_recommend_within_threshold():
    verdict, co = scoring._determine_verdict(
        {"ecs": 30, "eks": 29, "lambda": 10}, eliminated={})
    assert verdict == "co_recommend"
    assert co == ["ecs", "eks"]


def test_verdict_no_viable_runtime():
    verdict, co = scoring._determine_verdict(
        {}, eliminated={"agentcore": "x", "lambda": "y"})
    assert verdict == "no_viable_runtime"
    assert co == []


def _agentcore_with_models():
    return {**_minimal("agentcore"),
            "deployment_models": ["harness", "framework_on_runtime"]}


def test_deployment_model_none_when_runtime_has_no_models():
    profiles = [{**_minimal("ecs"), "deployment_models": []}]
    assert scoring._select_deployment_model({}, "ecs", profiles) is None


def test_deployment_model_framework_for_multi_agent():
    profiles = [_agentcore_with_models()]
    dm = scoring._select_deployment_model(
        {"multi_agent": "yes", "framework": "none"}, "agentcore", profiles)
    assert dm == "framework_on_runtime"


def test_deployment_model_harness_for_single_agent_no_framework():
    profiles = [_agentcore_with_models()]
    dm = scoring._select_deployment_model(
        {"multi_agent": "no", "framework": "none"}, "agentcore", profiles)
    assert dm == "harness"


def test_deployment_preference_harness_overrides_multi_agent():
    # Explicit user preference for no-code Harness wins over the multi_agent inference.
    profiles = [_agentcore_with_models()]
    dm = scoring._select_deployment_model(
        {"multi_agent": "yes", "framework": "langgraph",
         "deployment_preference": "harness"}, "agentcore", profiles)
    assert dm == "harness"


def test_deployment_preference_framework_overrides_single_agent():
    profiles = [_agentcore_with_models()]
    dm = scoring._select_deployment_model(
        {"multi_agent": "no", "framework": "none",
         "deployment_preference": "framework"}, "agentcore", profiles)
    assert dm == "framework_on_runtime"


def test_deployment_preference_either_falls_back_to_inference():
    profiles = [_agentcore_with_models()]
    dm = scoring._select_deployment_model(
        {"multi_agent": "yes", "deployment_preference": "either"}, "agentcore", profiles)
    assert dm == "framework_on_runtime"  # inference (multi_agent) still applies


def test_services_always_on_baseline():
    assert scoring._select_agentcore_services({}) == [
        "identity", "observability", "evaluations", "optimization"]


def test_services_add_memory_and_policy_and_gateway():
    services = scoring._select_agentcore_services({
        "memory_needs": "cross_session", "isolation": "required",
        "multi_agent": "yes"})
    assert services[:4] == [
        "identity", "observability", "evaluations", "optimization"]
    assert services[4:] == ["memory", "policy", "gateway"]


def test_services_no_duplicate_memory():
    services = scoring._select_agentcore_services({
        "session_state": "hitl", "memory_needs": "cross_session"})
    assert services.count("memory") == 1


def test_model_selection_never_changes_verdict():
    # Independence invariant: model_* answers must not affect the runtime verdict/scores.
    base = {"session_duration": "15min_to_8hr", "traffic_pattern": "bursty",
            "session_state": "hitl", "ops_preference": "minimal"}
    profiles = scoring.load_profiles()
    ref = scoring.score({"entry_point": "build_scratch", "answers": base}, profiles=profiles)
    for mp, mf in [("cost", "speech"), ("quality", "extended_thinking"),
                   ("speed", "image_generation"), ("balanced", "long_context")]:
        a = dict(base, model_priority=mp, model_features=mf)
        r = scoring.score({"entry_point": "build_scratch", "answers": a}, profiles=profiles)
        assert r["verdict"] == ref["verdict"]
        assert r["scores"] == ref["scores"]


def test_assumptions_lists_unknown_dimensions():
    assumptions = scoring._collect_assumptions({"session_duration": "under_15min"})
    assert "session_duration defaulted to unknown" not in assumptions
    assert "traffic_pattern defaulted to unknown" in assumptions


def test_warning_fires_for_microvms_high_launch():
    warnings = scoring._collect_warnings(
        {"launch_concurrency": "high"}, {}, "lambda_microvms")
    assert len(warnings) == 1
    assert "current-run verification" in warnings[0]


def test_warning_fires_for_microvms_in_co_recommend():
    warnings = scoring._collect_warnings(
        {"launch_concurrency": "high"}, {}, "co_recommend",
        co_recommend=["agentcore", "lambda_microvms"])
    assert len(warnings) == 1
    assert "current-run verification" in warnings[0]


def test_no_warning_when_microvms_not_in_co_recommend():
    assert scoring._collect_warnings(
        {"launch_concurrency": "high"}, {}, "co_recommend",
        co_recommend=["ecs", "eks"]) == []


def test_no_warning_for_other_verdict():
    assert scoring._collect_warnings(
        {"launch_concurrency": "high"}, {}, "agentcore") == []


def test_score_end_to_end_with_fixture_profiles(tmp_path):
    _write_profile(tmp_path, {
        **_minimal("agentcore"),
        "deployment_models": ["harness", "framework_on_runtime"],
        "affinities": {"session_duration": {"15min_to_8hr": 5},
                       "traffic_pattern": {"bursty": 5}},
    })
    _write_profile(tmp_path, {
        **_minimal("lambda"),
        "hard_constraints": [{"field": "session_duration",
                              "value": "15min_to_8hr",
                              "reason": "Lambda has 15-minute timeout"}],
    })
    profiles = scoring.load_profiles(tmp_path)
    result = scoring.score({
        "entry_point": "build_scratch",
        "answers": {"session_duration": "15min_to_8hr",
                    "traffic_pattern": "bursty", "multi_agent": "no",
                    "framework": "none"}},
        profiles=profiles)

    assert result["verdict"] == "agentcore"
    assert result["eliminated"] == {"lambda": "Lambda has 15-minute timeout"}
    assert result["deployment_model"] == "harness"
    assert result["agentcore_services"][0] == "identity"
    assert "co_recommend" not in result
    assert "blocking_constraints" not in result


def test_score_no_viable_lists_blocking(tmp_path):
    _write_profile(tmp_path, {
        **_minimal("agentcore"),
        "hard_constraints": [{"field": "session_duration", "value": "over_8hr",
                              "reason": "8hr cap"}]})
    profiles = scoring.load_profiles(tmp_path)
    result = scoring.score(
        {"entry_point": "build_scratch",
         "answers": {"session_duration": "over_8hr"}}, profiles=profiles)
    assert result["verdict"] == "no_viable_runtime"
    assert result["blocking_constraints"] == ["agentcore: 8hr cap"]


def test_score_output_matches_schema(tmp_path):
    import jsonschema
    _write_profile(tmp_path, {**_minimal("agentcore"),
                              "deployment_models": ["harness", "framework_on_runtime"]})
    profiles = scoring.load_profiles(tmp_path)
    result = scoring.score(
        {"entry_point": "build_scratch", "answers": {}}, profiles=profiles)
    schema = json.loads(
        (pathlib.Path(scoring.__file__).parent / "schemas"
         / "scoring-result.json").read_text())
    # The schema describes the FILE clarify writes (the wrapper {units:{...}, ...primary mirror}),
    # not the bare per-unit score() result. Wrap it the way clarify.md Step 5 does before
    # validating — the scored variant requires a non-empty units map.
    wrapped = {**result, "units": {"primary-agent": result}}
    jsonschema.validate(wrapped, schema)


def _real_profiles():
    return scoring.load_profiles()  # default RUNTIMES_DIR


def _high_launch_microvms_evidence():
    return _run_evidence({
        "agentcore.max_compute": {
            "status": "verified",
            "source": _AGENTCORE_COMPUTE_SOURCE,
            "value": "2vCPU/8GB",
        },
        "lambda.timeout": {
            "status": "verified",
            "source": _AWS_DOCS_SOURCE,
            "value": "15m",
        },
    })


def _microvms_launch_capacity_requirement():
    return {
        "runtime": "lambda_microvms",
        "field": "launch_concurrency",
        "value": "high",
        "reason": "Lambda MicroVMs launch capacity must be verified before selection for high launch concurrency",
        "verification_key": "lambda_microvms.launch_tps",
        "verification_expected_value": "5 (not adjustable)",
        "verification_sources": [_MICROVMS_SOURCE],
    }


def test_golden_loads_five_ga_runtimes():
    ids = {p["id"] for p in _real_profiles()}
    assert ids == {"agentcore", "lambda_microvms", "ecs", "eks", "lambda"}


def test_golden_over_8hr_routes_agentcore_to_instances_not_elimination():
    """>8h no longer eliminates AgentCore: the Instances compute type (AWS-managed
    EC2 via capacity providers, launched 2026-08-06) supports sessions up to 14
    days. Without current-run evidence the Lambda-family caps are DEFERRED (the
    verification gating), not eliminated — but AgentCore appears in NEITHER list:
    its duration constraint was deleted outright, not gated, because Instances
    made it false as a constraint regardless of what the microVMs fact verifies
    to. The verdict carries agentcore_compute_type=instances plus the caveat
    warning so downstream phases never build the microVM shape for a multi-day
    workload."""
    result = scoring.score({
        "entry_point": "migrate",
        "answers": {"session_duration": "over_8hr"}}, profiles=_real_profiles())
    assert "agentcore" not in result["eliminated"]
    deferred_runtimes = {d["runtime"] for d in result["deferred_verification_requirements"]}
    assert "agentcore" not in deferred_runtimes
    assert {"lambda", "lambda_microvms"} <= deferred_runtimes
    assert result["agentcore_compute_type"] == "instances"
    assert any("14 days" in w for w in result["warnings"])


def test_golden_over_8hr_verified_evidence_finalizes_lambda_family_only():
    # Verified volatile caps make the Lambda-family eliminations FINAL — while the
    # same run supplying the old agentcore.session_cap evidence must not revive
    # the deleted AgentCore constraint.
    result = scoring.score(
        {"entry_point": "migrate", "answers": {"session_duration": "over_8hr"}},
        profiles=_real_profiles(),
        run_evidence=_run_evidence({
            "agentcore.session_cap": {"status": "verified",
                                      "source": _AGENTCORE_SESSION_SOURCE, "value": "8h"},
            "lambda_microvms.session_cap": {"status": "verified",
                                            "source": _MICROVMS_SOURCE, "value": "8h"},
            "lambda.timeout": {"status": "verified",
                               "source": _AWS_DOCS_SOURCE, "value": "15m"},
        }),
    )
    assert "agentcore" not in result["eliminated"]
    assert "lambda_microvms" in result["eliminated"]
    assert "lambda" in result["eliminated"]
    assert result["recommendation_status"] == "final"
    assert result["agentcore_compute_type"] == "instances"


def test_golden_microvms_wins_process_level_resume():
    result = scoring.score({
        "entry_point": "build_deploy",
        "answers": {"session_duration": "15min_to_8hr", "idle_resume": "process_level",
                    "session_state": "hitl", "ops_preference": "moderate"}},
        profiles=_real_profiles())
    assert result["verdict"] == "lambda_microvms"


def test_golden_microvms_wins_heavy_non_gpu():
    # heavy_non_gpu no longer eliminates AgentCore (Instances can size up), but
    # Lambda MicroVMs' heavy-compute affinity keeps it the winner here.
    result = scoring.score({
        "entry_point": "build_deploy",
        "answers": {"compute_tier": "heavy_non_gpu", "session_duration": "15min_to_8hr"}},
        profiles=_real_profiles())
    assert "agentcore" not in result["eliminated"]
    assert result["verdict"] == "lambda_microvms"


def test_golden_agentic_io_wait_favors_agentcore():
    result = scoring.score({
        "entry_point": "build_scratch",
        "answers": {"session_duration": "15min_to_8hr", "traffic_pattern": "bursty",
                    "session_state": "hitl", "ops_preference": "minimal",
                    "multi_agent": "no", "framework": "none"}},
        profiles=_real_profiles())
    assert result["verdict"] == "agentcore"
    assert result["deployment_model"] == "harness"


def test_golden_microvms_high_launch_requires_capacity_verification():
    result = scoring.score(
        {"entry_point": "build_deploy", "answers": {
            "compute_tier": "heavy_non_gpu", "session_duration": "15min_to_8hr",
            "launch_concurrency": "high",
        }},
        profiles=_real_profiles(),
        run_evidence=_high_launch_microvms_evidence(),
    )
    # Merged semantics: heavy compute no longer eliminates AgentCore (Instances),
    # so high-launch heavy work is a genuine co-recommendation — the MicroVMs
    # capacity-verification machinery below still applies while it is in the set.
    assert result["verdict"] == "co_recommend"
    assert set(result["co_recommend"]) == {"agentcore", "lambda_microvms"}
    assert result["agentcore_compute_type"] == "instances"
    assert result["recommendation_status"] == "provisional"
    assert result["deferred_verification_requirements"] == [
        _microvms_launch_capacity_requirement()]
    assert any("before selection" in warning for warning in result["warnings"])


@pytest.mark.parametrize("record", [
    {"status": "verified", "source": _AWS_DOCS_SOURCE, "value": "5 (not adjustable)"},
    {"status": "verified", "source": _MICROVMS_SOURCE, "value": "4"},
])
def test_golden_microvms_high_launch_rejects_wrong_capacity_evidence(record):
    evidence = _high_launch_microvms_evidence()
    evidence["verifications"]["lambda_microvms.launch_tps"] = record
    result = scoring.score(
        {"entry_point": "build_deploy", "answers": {
            "compute_tier": "heavy_non_gpu", "session_duration": "15min_to_8hr",
            "launch_concurrency": "high",
        }},
        profiles=_real_profiles(),
        run_evidence=evidence,
    )
    # Merged semantics: heavy compute no longer eliminates AgentCore (Instances),
    # so high-launch heavy work is a genuine co-recommendation — the MicroVMs
    # capacity-verification machinery below still applies while it is in the set.
    assert result["verdict"] == "co_recommend"
    assert set(result["co_recommend"]) == {"agentcore", "lambda_microvms"}
    assert result["agentcore_compute_type"] == "instances"
    assert result["recommendation_status"] == "provisional"
    assert result["deferred_verification_requirements"] == [
        _microvms_launch_capacity_requirement()]


def test_golden_microvms_high_launch_emits_verified_warning():
    evidence = _high_launch_microvms_evidence()
    evidence["verifications"]["lambda_microvms.launch_tps"] = {
        "status": "verified",
        "source": _MICROVMS_SOURCE,
        "value": "5 (not adjustable)",
    }
    result = scoring.score(
        {"entry_point": "build_deploy", "answers": {
            "compute_tier": "heavy_non_gpu", "session_duration": "15min_to_8hr",
            "launch_concurrency": "high",
        }},
        profiles=_real_profiles(),
        run_evidence=evidence,
    )
    # Merged semantics: heavy compute no longer eliminates AgentCore (Instances),
    # so high-launch heavy work is a genuine co-recommendation — the MicroVMs
    # capacity-verification machinery below still applies while it is in the set.
    assert result["verdict"] == "co_recommend"
    assert set(result["co_recommend"]) == {"agentcore", "lambda_microvms"}
    assert result["agentcore_compute_type"] == "instances"
    assert result["recommendation_status"] == "final"
    assert result["deferred_verification_requirements"] == []
    assert any("verified in this run" in warning for warning in result["warnings"])


VALID_STATUSES = {"ga", "preview", "coming_soon"}


@pytest.mark.parametrize("profile", scoring.load_profiles(
    statuses=frozenset({"ga", "preview", "coming_soon"})),
    ids=lambda p: p["id"])
def test_profile_is_well_formed(profile):
    assert profile["status"] in VALID_STATUSES
    for dim, value_map in profile["affinities"].items():
        assert dim in scoring.DIMENSIONS, f"unknown dimension {dim}"
        for value, points in value_map.items():
            assert isinstance(points, int), f"{dim}.{value} not an int"
            assert value in scoring.LEGAL_VALUES[dim], f"illegal value {dim}.{value}"
        # explicit-unknown authoring rule: a declared dimension must declare ALL legal
        # values (so the neutral fallback is never an accident of sparse data).
        declared = set(value_map)
        legal = set(scoring.LEGAL_VALUES[dim])
        assert declared == legal, (
            f"{profile['id']}.{dim} declares {sorted(declared)}, "
            f"must declare all of {sorted(legal)}")
    # Verification gates must name an answerable condition and a profile fact that can be checked.
    answerable = set(scoring.DIMENSIONS) | {"compliance"}
    verification_keys = {
        fact["verification_key"] for fact in profile["volatile_facts"]
        if "verification_key" in fact
    }
    for constraint in profile["hard_constraints"]:
        assert constraint["field"] in answerable
        assert "reason" in constraint and constraint["reason"]
        if constraint.get("verification_required"):
            assert constraint.get("verification_key") in verification_keys
    for requirement in profile.get("selection_verification_requirements", []):
        assert requirement["field"] in answerable
        assert "reason" in requirement and requirement["reason"]
        assert requirement["verification_key"] in verification_keys
        assert isinstance(requirement["verification_expected_value"], str)
        assert requirement["verification_expected_value"]
        assert isinstance(requirement["verification_sources"], list)
        assert requirement["verification_sources"]


# --- Drift detection: our model pool must stay Active vs the source lifecycle file ---

# The authoritative Active/Legacy/EOL list is the plugin-neutral canonical file under
# skills/shared/ai/ (vendored byte-identically into each consuming skill). From this
# scripts/ dir, .parent.parent.parent == the plugin's skills/ dir, then into shared/ai/.
_LIFECYCLE_FILE = (
    pathlib.Path(scoring.__file__).parent.parent.parent
    / "shared" / "ai" / "ai-model-lifecycle.md"
)

# Map each internal model id in our selection pool to a substring that identifies it
# in the lifecycle file's Legacy/EOL table (by model name or model-id fragment).
# The pool is the Model Recommend engine's selectable set: the priority ordering
# plus every model in the dated per-provider catalogs.
_POOL_LIFECYCLE_KEYS = {
    "claude_opus_4_8": "claude-opus-4-8",
    "claude_sonnet_5": "claude-sonnet-5",
    "claude_haiku_4_5": "claude-haiku-4-5",
    "openai_gpt_5_6_sol": "gpt-5.6-sol",
    "openai_gpt_5_6_terra": "gpt-5.6-terra",
    "openai_gpt_5_6_luna": "gpt-5.6-luna",
    "openai_gpt_5_5": "gpt-5.5",
    "openai_gpt_5_4": "gpt-5.4",
    "anthropic_claude_sonnet_5": "claude-sonnet-5",
    "anthropic_claude_opus_4_8": "claude-opus-4-8",
    "anthropic_claude_haiku_4_5": "claude-haiku-4-5",
}


def _pool_models():
    import anthropic_model_recommendation as amr
    import model_recommendation as mr
    pool = {m for order in amr._PRIORITY_ORDER.values() for m in order}
    pool.update(mr.load_catalog()["models"])
    pool.update(mr.load_openai_catalog()["models"])
    return pool


def test_pool_keys_cover_every_selectable_model():
    # Guard: if a new model enters the selection pool, it must have a lifecycle key
    # so the drift test below actually checks it.
    missing = _pool_models() - set(_POOL_LIFECYCLE_KEYS)
    assert not missing, f"models missing a lifecycle key: {sorted(missing)}"


def _legacy_or_excluded_rows():
    """Every line in the lifecycle file that marks a model as unsafe to select:
    a pipe-table row tagged `legacy`/`excluded`, OR a bulleted entry in the
    **Removed** section. Removed models are past EOL — a stronger violation
    than "excluded" (the file's own text: "Never recommend or invoke a model
    listed in Removed") — so they must be caught here too, not just the two
    still-in-the-table statuses. A model that ages out of the table entirely
    into Removed must not silently stop being flagged."""
    text = _LIFECYCLE_FILE.read_text().lower()
    lines = text.splitlines()
    rows = [line for line in lines
            if line.strip().startswith("|") and ("legacy" in line or "excluded" in line)]
    in_removed = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("**removed"):
            in_removed = True
            continue
        if in_removed and stripped.startswith(">"):
            # The "AWS page lag" blockquote follows the Removed bullets and ends
            # the section — stop before any later, unrelated bulleted list.
            in_removed = False
            continue
        if in_removed and stripped.startswith("- "):
            rows.append(line)
    return rows


def test_drift_mechanism_actually_fires_on_a_known_legacy_model():
    # Self-proof: the file lists Claude Opus 4.1 as legacy (still in the table).
    # The matcher MUST see its id fragment — otherwise a 0-match "pass" below
    # would be vacuous (Active models are simply absent from the legacy table,
    # so the check only means something if it can actually match a legacy id
    # when one appears).
    if not _LIFECYCLE_FILE.exists():
        pytest.xfail("lifecycle file not reachable — drift check skipped")
    bad_rows = _legacy_or_excluded_rows()
    assert any("claude-opus-4-1" in r for r in bad_rows), (
        "expected Claude Opus 4.1 in a legacy row — lifecycle file format changed; "
        "the drift matcher may no longer work and needs updating")


def test_drift_mechanism_actually_fires_on_a_known_removed_model():
    # Self-proof for the Removed section specifically (distinct from the table
    # self-proof above): the file lists Nova Sonic v1 as Removed (past EOL, no
    # longer even in the table). The matcher MUST see its id fragment there too
    # — this is the exact case that silently stopped being caught when a model
    # ages out of the table into the bulleted Removed list.
    if not _LIFECYCLE_FILE.exists():
        pytest.xfail("lifecycle file not reachable — drift check skipped")
    bad_rows = _legacy_or_excluded_rows()
    assert any("nova-sonic-v1" in r for r in bad_rows), (
        "expected Nova Sonic v1 in a Removed row — lifecycle file format changed; "
        "the Removed-section matcher may no longer work and needs updating")


def test_no_pool_model_is_legacy_or_excluded():
    if not _LIFECYCLE_FILE.exists():
        pytest.xfail(f"lifecycle file not reachable at {_LIFECYCLE_FILE} "
                     "(gcp-to-aws sibling skill not found) — drift check skipped")
    bad_rows = _legacy_or_excluded_rows()
    for model in _pool_models():
        key = _POOL_LIFECYCLE_KEYS[model]
        offending = [r for r in bad_rows if key in r]
        assert not offending, (
            f"model '{model}' (key '{key}') appears Legacy/excluded in the lifecycle "
            f"file — update the selection pool. Row: {offending[0].strip()}")


def test_runtimes_dir_points_at_skill_references():
    # After the move, the default profiles dir must resolve to the skill's
    # references/runtimes (one level up from scripts/, then into references/).
    from scoring import RUNTIMES_DIR
    parts = RUNTIMES_DIR.parts
    assert parts[-2:] == ("references", "runtimes"), RUNTIMES_DIR
    assert parts[-3] == "agent-advisor", RUNTIMES_DIR
