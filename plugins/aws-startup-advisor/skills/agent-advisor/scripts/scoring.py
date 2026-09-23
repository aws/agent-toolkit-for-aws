"""Deterministic, registry-driven runtime-scoring engine for agent-advisor.

Pure: answers dict -> recommendation dict. No network, no AWS. Runtime
knowledge lives in JSON profiles under references/runtimes/.
"""
import json
import pathlib

RUNTIMES_DIR = pathlib.Path(__file__).parent.parent / "references" / "runtimes"

_REQUIRED_PROFILE_KEYS = ("id", "status", "affinities", "hard_constraints")

NEUTRAL_SCORE = 2

DIMENSIONS = [
    "session_duration", "traffic_pattern", "platform_fit", "session_state",
    "ops_preference", "isolation", "memory_needs", "multi_agent", "framework",
    "existing_cluster", "multi_cloud", "idle_resume", "compute_tier",
    "launch_concurrency", "instance_type_requirement",
]

# Legal answer values per scoring dimension (the closed set the engine reasons about).
LEGAL_VALUES = {
    "session_duration": ["under_15min", "15min_to_8hr", "over_8hr", "unknown"],
    "traffic_pattern": ["bursty", "steady", "idle", "unknown"],
    "platform_fit": ["ecs", "eks", "lambda", "none", "unknown"],
    "session_state": ["stateless", "stateful", "hitl", "unknown"],
    "ops_preference": ["minimal", "moderate", "full_control", "unknown"],
    "isolation": ["required", "nice_to_have", "not_needed", "unknown"],
    "memory_needs": ["cross_session", "session_only", "none", "unknown"],
    "multi_agent": ["yes", "no", "unknown"],
    "framework": ["strands", "langgraph", "crewai", "custom", "none", "unknown"],
    "existing_cluster": ["eks", "ecs", "none", "unknown"],
    "multi_cloud": ["yes", "no", "unknown"],
    "idle_resume": ["process_level", "filesystem", "none", "unknown"],
    "compute_tier": ["light", "heavy_non_gpu", "gpu", "unknown"],
    "launch_concurrency": ["high", "moderate", "low", "unknown"],
    "instance_type_requirement": ["yes", "no", "unknown"],
}

DEFAULTS = {
    **{dim: "unknown" for dim in DIMENSIONS},
    "compliance": ["none"],
    "region": "unknown",
}

RUN_EVIDENCE_ARTIFACT_TYPE = "agent-advisor.current-run-verifications"
RUN_EVIDENCE_SCHEMA_VERSION = 1


def load_profiles(runtimes_dir=RUNTIMES_DIR, statuses=frozenset({"ga"})):
    """Load runtime profiles whose status is in `statuses`, sorted by id."""
    profiles = []
    for path in sorted(pathlib.Path(runtimes_dir).glob("*.json")):
        try:
            profile = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSON ({exc})") from exc
        missing = [k for k in _REQUIRED_PROFILE_KEYS if k not in profile]
        if missing:
            raise ValueError(f"{path}: missing required keys {missing}")
        if profile["status"] in statuses:
            profiles.append(profile)
    return sorted(profiles, key=lambda p: p["id"])


def _constraint_matches(answers, constraint):
    field, trigger = constraint["field"], constraint["value"]
    if field == "compliance":
        return trigger in answers.get("compliance", ["none"])
    return answers.get(field) == trigger


def _is_authoritative_aws_source(source):
    """Return whether source is a canonical public AWS documentation URL."""
    return isinstance(source, str) and source.startswith((
        "https://aws.amazon.com/", "https://docs.aws.amazon.com/"
    ))


def is_run_materialized_evidence(evidence):
    """Return whether an artifact satisfies the run-evidence schema contract."""
    if not (
        isinstance(evidence, dict)
        and set(evidence) == {"artifact_type", "schema_version", "run_id", "verifications"}
        and evidence.get("artifact_type") == RUN_EVIDENCE_ARTIFACT_TYPE
        and evidence.get("schema_version") == RUN_EVIDENCE_SCHEMA_VERSION
        and isinstance(evidence.get("run_id"), str)
        and bool(evidence["run_id"].strip())
        and isinstance(evidence.get("verifications"), dict)
    ):
        return False
    for record in evidence["verifications"].values():
        if not isinstance(record, dict) or not set(record) <= {"status", "source", "value"}:
            return False
        if record.get("status") not in {"verified", "not_verified", "failed"}:
            return False
        if record["status"] == "verified" and (
            not isinstance(record.get("source"), str)
            or not isinstance(record.get("value"), str)
            or not record["value"].strip()
        ):
            return False
    return True


def _has_current_run_evidence(record):
    """Require a source-backed, non-empty observation in a trusted artifact."""
    return (
        isinstance(record, dict)
        and record.get("status") == "verified"
        and _is_authoritative_aws_source(record.get("source"))
        and isinstance(record.get("value"), str)
        and bool(record["value"].strip())
    )


def _is_current_run_verified(
    verifications, verification_key, expected_value, verification_sources
):
    """Return whether run-materialized evidence exactly verifies a constraint."""
    record = verifications.get(verification_key)
    return (
        _has_current_run_evidence(record)
        and isinstance(expected_value, str)
        and bool(expected_value)
        and isinstance(verification_sources, list)
        and bool(verification_sources)
        and record["source"] in verification_sources
        and record["value"] == expected_value
    )


def _evaluate_hard_constraints(answers, profiles, verifications):
    """Return final eliminations and matched constraints awaiting valid evidence."""
    eliminated, deferred = {}, []
    for profile in profiles:
        for constraint in profile.get("hard_constraints", []):
            if not _constraint_matches(answers, constraint):
                continue
            if constraint.get("verification_required") and not _is_current_run_verified(
                verifications,
                constraint["verification_key"],
                constraint.get("verification_expected_value"),
                constraint.get("verification_sources"),
            ):
                deferred.append({
                    "runtime": profile["id"],
                    "field": constraint["field"],
                    "value": constraint["value"],
                    "reason": constraint["reason"],
                    "verification_key": constraint["verification_key"],
                    "verification_expected_value": constraint.get("verification_expected_value"),
                    "verification_sources": constraint.get("verification_sources"),
                })
                break
            eliminated[profile["id"]] = constraint["reason"]
            break
    return eliminated, deferred


def _apply_hard_constraints(answers, profiles, run_evidence=None):
    """Compatibility helper returning only final hard eliminations."""
    verifications = (
        run_evidence["verifications"]
        if is_run_materialized_evidence(run_evidence)
        else {}
    )
    return _evaluate_hard_constraints(answers, profiles, verifications)[0]


def _compute_scores(answers, profiles, eliminated):
    scores = {}
    for profile in profiles:
        if profile["id"] in eliminated:
            continue
        affinities = profile.get("affinities", {})
        total = 0
        for dim in DIMENSIONS:
            value = answers.get(dim, "unknown")
            total += affinities.get(dim, {}).get(value, NEUTRAL_SCORE)
        scores[profile["id"]] = total
    return scores


TIE_THRESHOLD = 2


def _determine_verdict(scores, eliminated):
    active = {r: s for r, s in scores.items() if r not in eliminated}
    if not active:
        return "no_viable_runtime", []
    max_score = max(active.values())
    top = sorted(r for r, s in active.items() if s >= max_score - TIE_THRESHOLD)
    if len(top) > 1:
        return "co_recommend", top
    return top[0], []


def _select_deployment_model(answers, verdict, profiles):
    profile = next((p for p in profiles if p["id"] == verdict), None)
    if profile is None:
        return None
    models = profile.get("deployment_models", [])
    if "harness" not in models or "framework_on_runtime" not in models:
        return None
    # Explicit user preference (Pass 2) overrides the inference below.
    pref = answers.get("deployment_preference", "unknown")
    if pref == "harness":
        return "harness"
    if pref == "framework":
        return "framework_on_runtime"
    # Inference (pref is "either" / "unknown"): multi-agent or a code framework → framework.
    if answers.get("multi_agent") == "yes":
        return "framework_on_runtime"
    if answers.get("framework") in ("langgraph", "crewai", "custom"):
        return "framework_on_runtime"
    return "harness"


# Answers that require the Instances compute type (AWS-managed EC2 via a capacity
# provider): sessions up to 14 days, GPU / heavy compute, and instance-type choice.
# Everything else runs on the default microVMs compute type (8h, 2 vCPU / 8 GB).
def _select_agentcore_compute_type(answers, verdict, co_recommend=None):
    agentcore_wins = (
        verdict == "agentcore"
        or (verdict == "co_recommend" and "agentcore" in (co_recommend or []))
    )
    if not agentcore_wins:
        return None
    needs_instances = (
        answers.get("session_duration") == "over_8hr"
        or answers.get("compute_tier") in ("gpu", "heavy_non_gpu")
        or answers.get("instance_type_requirement") == "yes"
    )
    return "instances" if needs_instances else "microvms"


AGENTCORE_ALWAYS_SERVICES = ["identity", "observability", "evaluations", "optimization"]


def _select_agentcore_services(answers):
    services = list(AGENTCORE_ALWAYS_SERVICES)

    def add(name):
        if name not in services:
            services.append(name)

    if answers.get("session_state") in ("hitl", "stateful"):
        add("memory")
    if answers.get("memory_needs") == "cross_session":
        add("memory")
    if answers.get("isolation") == "required":
        add("policy")
    if answers.get("multi_agent") == "yes":
        add("gateway")
    return services


def _collect_assumptions(raw_answers):
    out = []
    for dim in DIMENSIONS:
        if raw_answers.get(dim, "unknown") == "unknown":
            out.append(f"{dim} defaulted to unknown")
    return out


def _matching_selection_verification_requirements(
    answers, profiles, verdict, co_recommend
):
    """Return verification gates that apply only to the selected runtime(s)."""
    selected_runtimes = (
        set(co_recommend or [])
        if verdict == "co_recommend"
        else {verdict} if verdict != "no_viable_runtime" else set()
    )
    return [
        (profile["id"], requirement)
        for profile in profiles
        if profile["id"] in selected_runtimes
        for requirement in profile.get("selection_verification_requirements", [])
        if _constraint_matches(answers, requirement)
    ]


def _defer_unverified_selection_requirements(verifications, requirements):
    """Return unresolved selected-runtime gates without eliminating candidates."""
    deferred = []
    for runtime, requirement in requirements:
        if _is_current_run_verified(
            verifications,
            requirement["verification_key"],
            requirement["verification_expected_value"],
            requirement["verification_sources"],
        ):
            continue
        deferred.append({
            "runtime": runtime,
            "field": requirement["field"],
            "value": requirement["value"],
            "reason": requirement["reason"],
            "verification_key": requirement["verification_key"],
            "verification_expected_value": requirement["verification_expected_value"],
            "verification_sources": requirement["verification_sources"],
        })
    return deferred


def _collect_warnings(
    answers, verifications, verdict, co_recommend=None, selection_requirements=(),
    agentcore_compute_type=None,
):
    warnings = []
    microvms_is_winner = (
        verdict == "lambda_microvms"
        or (verdict == "co_recommend" and "lambda_microvms" in (co_recommend or []))
    )
    if microvms_is_winner and answers.get("launch_concurrency") == "high":
        launch_tps_requirements = [
            requirement
            for runtime, requirement in selection_requirements
            if runtime == "lambda_microvms"
            and requirement["verification_key"] == "lambda_microvms.launch_tps"
        ]
        launch_tps_verified = (
            all(
                _is_current_run_verified(
                    verifications,
                    requirement["verification_key"],
                    requirement["verification_expected_value"],
                    requirement["verification_sources"],
                )
                for requirement in launch_tps_requirements
            )
            if launch_tps_requirements
            else _has_current_run_evidence(
                verifications.get("lambda_microvms.launch_tps")
            )
        )
        if launch_tps_verified:
            warnings.append(
                "High launch concurrency requires capacity planning against the Lambda "
                "MicroVMs launch-rate value verified in this run.")
        else:
            warnings.append(
                "High launch concurrency requires current-run verification of Lambda "
                "MicroVMs launch capacity before selection.")
    if agentcore_compute_type == "instances":
        warnings.append(
            "AgentCore Instances compute type: sessions persist up to 14 days "
            "(not indefinitely — an always-on service is still a better fit for "
            "ECS/EKS); pricing is EC2 in your account (Savings Plans/ODCRs "
            "apply) plus an AgentCore management fee, NOT consumption-based; "
            "Linux only at launch; launch-region set is limited and volatile — "
            "verify current availability via MCP (volatile_facts."
            "instances_regions).")
    return warnings


def score(input_data, profiles=None, run_evidence=None):
    if profiles is None:
        profiles = load_profiles()
    entry_point = input_data.get("entry_point", "build_scratch")
    raw_answers = input_data.get("answers", {})
    verifications = (
        run_evidence["verifications"]
        if is_run_materialized_evidence(run_evidence)
        else {}
    )

    answers = dict(DEFAULTS)
    answers.update({k: v for k, v in raw_answers.items() if v is not None})
    answers["_entry_point"] = entry_point

    eliminated, deferred = _evaluate_hard_constraints(answers, profiles, verifications)
    scores = _compute_scores(answers, profiles, eliminated)
    verdict, co_recommend = _determine_verdict(scores, eliminated)
    selection_requirements = _matching_selection_verification_requirements(
        answers, profiles, verdict, co_recommend
    )
    deferred.extend(
        _defer_unverified_selection_requirements(
            verifications, selection_requirements
        )
    )

    deployment_model = None
    if verdict not in ("no_viable_runtime", "co_recommend"):
        deployment_model = _select_deployment_model(answers, verdict, profiles)
    elif verdict == "co_recommend":
        for rid in co_recommend:
            dm = _select_deployment_model(answers, rid, profiles)
            if dm is not None:
                deployment_model = dm
                break

    agentcore_compute_type = _select_agentcore_compute_type(answers, verdict, co_recommend)

    result = {
        "verdict": verdict,
        "scores": scores,
        "eliminated": eliminated,
        "deferred_verification_requirements": deferred,
        "recommendation_status": "provisional" if deferred else "final",
        "deployment_model": deployment_model,
        "agentcore_compute_type": agentcore_compute_type,
        "agentcore_services": _select_agentcore_services(answers),
        "assumptions_used": _collect_assumptions(raw_answers),
        "warnings": _collect_warnings(
            answers, verifications, verdict, co_recommend, selection_requirements,
            agentcore_compute_type,
        ),
    }
    if verdict == "co_recommend":
        result["co_recommend"] = co_recommend
    if verdict == "no_viable_runtime":
        result["blocking_constraints"] = [
            f"{r}: {reason}" for r, reason in sorted(eliminated.items())]
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="agent-advisor runtime scoring")
    parser.add_argument("answers", type=pathlib.Path, help="path to answers.json")
    args = parser.parse_args(argv)
    input_data = json.loads(args.answers.read_text())
    result = score(input_data)
    out_path = args.answers.parent / "scoring-result.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"RESULT=ok VERDICT={result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
