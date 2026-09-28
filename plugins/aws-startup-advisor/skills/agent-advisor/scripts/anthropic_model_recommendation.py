"""Deterministic Anthropic-to-Bedrock model/path recommendation for agent-advisor.

Provider module called by model_recommendation.py (the orchestrator): joint
(model, api_path) filtering/ranking over the dated Anthropic catalog, Claude
version-hop analysis, CRIS resolution without guessing geography, and the shared
downstream recommendation contract. Offline: no SDK imports at module load.
"""

import re


SUPPORTED_PATHS = {
    "mantle_messages",
    "mantle_openai_chat",
    "mantle_openai_responses",
    "runtime_converse",
    "runtime_invoke",
}
ANTHROPIC_PATHS = (
    "mantle_messages",
    "runtime_converse",
    "runtime_invoke",
)
# Sources this module can genuinely reason about. `none` and `unknown` belong here: a source with no
# detected provider is treated as Bedrock-native and gets the Anthropic pool. Any OTHER provider
# routed here (azure_openai, google_genai, bedrock) still gets a recommendation, but carries a
# `provider_module_pending` [BLOCKS] finding so it stays provisional until that provider's own module
# exists. The orchestrator sends everything non-OpenAI here, so this set is the real classification.
ANTHROPIC_POOL = frozenset({"anthropic", "none", "unknown"})

_PRIORITY_ORDER = {
    "quality": ["claude_opus_4_8", "claude_sonnet_5", "claude_haiku_4_5"],
    "balanced": ["claude_sonnet_5", "claude_opus_4_8", "claude_haiku_4_5"],
    "speed": ["claude_haiku_4_5", "claude_sonnet_5", "claude_opus_4_8"],
    "cost": ["claude_haiku_4_5", "claude_sonnet_5", "claude_opus_4_8"],
    "unknown": ["claude_sonnet_5", "claude_opus_4_8", "claude_haiku_4_5"],
}

_FEATURE_ORDER = {
    "agentic": [
        "claude_sonnet_5",
        "claude_opus_4_8",
        "claude_haiku_4_5",
    ],
}

_CAPABILITY_ALIASES = {"multimodal": "vision"}
_MODEL_CAPABILITIES = {
    "extended_thinking",
    "long_context",
    "tool_use",
    "vision",
}
_VERSION_SCAN_FEATURES = {
    "assistant_prefill",
    "budget_tokens",
    "max_tokens_headroom",
    "refusal_handling",
    "sampling_parameters",
    "tokenizer_rebaseline",
}
_REARCHITECTURE_FEATURES = {
    "agent_infra",
    "conversation_state",
    "fallbacks",
    "files_api",
    "message_batches",
    "server_tools",
    "url_sources",
}

_BLOCK_FINDINGS = {
    "budget_tokens": (
        "budget_tokens_removed",
        "`budget_tokens` is rejected by current Claude targets.",
        "Replace it with adaptive thinking and an explicit effort setting.",
    ),
    "sampling_parameters": (
        "sampling_parameters_removed",
        "Legacy temperature/top_p/top_k controls are rejected by current Claude targets.",
        "Remove them and calibrate behavior with the golden set.",
    ),
    "assistant_prefill": (
        "assistant_prefill_removed",
        "Assistant-prefill structured output is rejected by current Claude targets.",
        "Use a forced tool without strict and validate the resulting schema.",
    ),
    "server_tools": (
        "server_tools_not_portable",
        "First-party server tools are not provided by the selected Bedrock path.",
        "Implement an application-owned tool loop or select an external service.",
    ),
    "files_api": (
        "files_api_not_portable",
        "The first-party Files API is not available on Bedrock.",
        "Inline supported content within the 20 MB request cap or add object retrieval.",
    ),
    "url_sources": (
        "url_sources_not_portable",
        "First-party URL image and document sources are not available on Bedrock.",
        "Fetch, validate, and inline the content from the application.",
    ),
    "message_batches": (
        "message_batches_not_portable",
        "Anthropic Message Batches do not port directly to Bedrock.",
        "Use CreateModelInvocationJob and redesign job submission and result handling.",
    ),
    "models_api": (
        "models_api_not_portable",
        "The first-party Models API is not available on Bedrock.",
        "Use Bedrock model discovery and keep runtime invocability as a separate probe.",
    ),
    "fallbacks": (
        "fallbacks_not_portable",
        "Server-side model fallbacks are not available on the selected Bedrock path.",
        "Implement explicit client-side routing, retry limits, and fallback observability.",
    ),
    "conversation_state": (
        "conversation_state_not_portable",
        "Server-side conversation state is not available on the selected Bedrock path.",
        "Persist and resend conversation history from an application-owned store.",
    ),
    "agent_infra": (
        "agent_infra_rearchitecture",
        "First-party Anthropic agent infrastructure is not a portable inference-call feature.",
        "Redesign Skills, MCP connectors, and managed-agent dependencies on AWS.",
    ),
}

_TUNE_FINDINGS = {
    "refusal_handling": (
        "refusal_handling",
        "Current Claude targets can return stop_reason=refusal.",
        "Add explicit refusal handling and include refusal cases in evaluation.",
    ),
    "tokenizer_rebaseline": (
        "tokenizer_rebaseline",
        "Token counts change across Claude versions and Bedrock paths.",
        "Re-baseline context sizing, usage accounting, and truncation alerts.",
    ),
    "max_tokens_headroom": (
        "max_tokens_headroom",
        "Thinking tokens share max_tokens and framework defaults can truncate output.",
        "Preserve source intent and tune from output distributions and thinking headroom.",
    ),
    "prompt_caching": (
        "prompt_cache_validation",
        "Prompt caching is supported but cache-hit behavior must not be assumed.",
        "Verify writes, reads, TTL, minimum-token thresholds, and hit telemetry.",
    ),
}


def _finding(code, tag, message, remediation):
    return {
        "code": code,
        "tag": tag,
        "message": message,
        "remediation": remediation,
    }


def _delta(code, category, description):
    return {"code": code, "category": category, "description": description}


def _version_tuple(value):
    if not value:
        return None
    match = re.search(r"(\d+)\.(\d+)", value)
    return tuple(map(int, match.groups())) if match else None


def _source_version(source):
    patterns = (
        r"claude-(?:opus-|sonnet-|haiku-)?(\d+)[.-](\d+)",
        r"claude-(\d+)[.-](\d+)-(?:opus|sonnet|haiku)",
    )
    for model_id in source.get("model_ids", []):
        normalized = model_id.lower().replace("_", "-")
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                return f"{int(match.group(1))}.{int(match.group(2))}"
    return None


def _candidate_order(requirements):
    features = requirements.get("critical_features", [])
    for feature in ("agentic",):
        if feature in features:
            return _FEATURE_ORDER[feature], feature
    priority = requirements.get("priority", "unknown")
    return _PRIORITY_ORDER.get(priority, _PRIORITY_ORDER["unknown"]), priority


def _required_capabilities(requirements):
    capabilities = {
        _CAPABILITY_ALIASES.get(feature, feature)
        for feature in requirements.get("critical_features", [])
        if _CAPABILITY_ALIASES.get(feature, feature) in _MODEL_CAPABILITIES
    }
    if requirements.get("thinking_enabled"):
        capabilities.add("extended_thinking")
    return capabilities


def _path_constraints(workload):
    source = workload["source"]
    requirements = workload["requirements"]
    preferred = requirements.get("preferred_api_path")
    if preferred and preferred not in SUPPORTED_PATHS:
        raise ValueError(f"unsupported preferred_api_path: {preferred}")

    runtime_required = bool(requirements.get("governance")) or requirements.get(
        "multi_model_converse", False
    )
    native_required = requirements.get("requires_native_payload", False)
    messages_required = requirements.get("preserve_messages_api", False) or requirements.get(
        "newest_anthropic_betas", False
    )
    source_messages = (
        source["provider"] == "anthropic"
        and source.get("api_surface") == "messages"
        and requirements.get("preserve_messages_api") is not False
    )

    runtime_path = "runtime_invoke" if native_required else "runtime_converse"
    conflicts = []
    if messages_required and (runtime_required or native_required):
        conflicts.append("messages_vs_runtime")
    if preferred:
        if preferred.startswith("mantle_") and (runtime_required or native_required):
            conflicts.append("preferred_path_vs_runtime")
        if preferred.startswith("runtime_") and messages_required:
            conflicts.append("preferred_path_vs_messages")
        if native_required and preferred != "runtime_invoke":
            conflicts.append("preferred_path_vs_native_payload")

    if conflicts:
        return {
            "paths": [],
            "conflicts": sorted(set(conflicts)),
            "option_paths": ["mantle_messages", runtime_path],
            "rationale": [
                "Messages continuity or beta requirements conflict with required Bedrock runtime capabilities."
            ],
        }
    if preferred:
        return {
            "paths": [preferred],
            "conflicts": [],
            "option_paths": [],
            "rationale": [f"User selected the {preferred} API path."],
        }
    if native_required:
        return {
            "paths": ["runtime_invoke"],
            "conflicts": [],
            "option_paths": [],
            "rationale": ["InvokeModel is required for the provider-native Bedrock body."],
        }
    if runtime_required:
        return {
            "paths": ["runtime_converse"],
            "conflicts": [],
            "option_paths": [],
            "rationale": [
                "Converse is required by governance, logging, or multi-model requirements."
            ],
        }
    if messages_required:
        return {
            "paths": ["mantle_messages"],
            "conflicts": [],
            "option_paths": [],
            "rationale": [
                "Mantle is required to preserve Messages semantics or newest beta features."
            ],
        }
    if source_messages:
        return {
            "paths": list(ANTHROPIC_PATHS),
            "conflicts": [],
            "option_paths": [],
            "rationale": [
                "Mantle is preferred for an existing first-party Messages API call."
            ],
        }
    return {
        "paths": ["runtime_converse", "runtime_invoke", "mantle_messages"],
        "conflicts": [],
        "option_paths": [],
        "rationale": ["Converse is the default for a new governance-ready Bedrock workload."],
    }


def _build_candidates(catalog, paths, requirements):
    model_order, driver = _candidate_order(requirements)
    required_capabilities = _required_capabilities(requirements)
    min_context = requirements.get("min_context_tokens", 0)
    expected_output = requirements.get("expected_output_tokens", 0)
    candidates = []
    for path_rank, path in enumerate(paths):
        for model_rank, model_key in enumerate(model_order):
            model = catalog["models"][model_key]
            path_config = model["paths"].get(path, {})
            if path_config.get("available") is not True:
                continue
            if not required_capabilities.issubset(set(model["capabilities"])):
                continue
            if model["context_window"] < min_context:
                continue
            if model["output_token_ceiling"] < expected_output:
                continue
            candidates.append(
                {
                    "model_key": model_key,
                    "model": model,
                    "path": path,
                    "path_config": path_config,
                    "rank": (path_rank, model_rank),
                    "driver": driver,
                }
            )
    return sorted(candidates, key=lambda item: item["rank"])


def _candidate_summary(candidate, requirements, reason):
    model = candidate["model"]
    path_config = candidate["path_config"]
    invocation_model_id = _resolve_invocation_model_id(
        path_config["model_id"], path_config["requires_cris"], requirements
    )
    return {
        "model_key": candidate["model_key"],
        "model": path_config["model_id"],
        "api_path": candidate["path"],
        "invocation_model_id": invocation_model_id,
        "requires_cris": path_config["requires_cris"],
        "reason": reason,
    }


def _resolve_invocation_model_id(model_id, requires_cris, requirements):
    if not requires_cris:
        return model_id
    explicit = requirements.get("inference_profile_id")
    if explicit:
        return explicit
    residency = requirements.get("data_residency", "unknown")
    if residency == "global_allowed":
        return f"global.{model_id}"
    if residency == "geo_required" and requirements.get("cris_geography"):
        return f"{requirements['cris_geography']}.{model_id}"
    return None


def _decision_options(catalog, workload, option_paths):
    options = []
    for path in dict.fromkeys(option_paths):
        candidates = _build_candidates(catalog, [path], workload["requirements"])
        if not candidates:
            continue
        tradeoff = (
            "Preserves Messages code and beta access but gives up runtime-only governance."
            if path == "mantle_messages"
            else "Provides runtime governance but requires rewriting the Messages integration."
        )
        options.append(
            _candidate_summary(candidates[0], workload["requirements"], tradeoff)
        )
    return options


def _feature_assessment(workload, source_version, target_version):
    detected = set(workload.get("detected_features", []))
    statuses = dict(workload.get("feature_status", {}))
    for feature in detected:
        statuses[feature] = "detected"
    source_tuple = _version_tuple(source_version)
    target_tuple = _version_tuple(target_version)
    if source_tuple and target_tuple and source_tuple < target_tuple and target_tuple >= (4, 7):
        for feature in _VERSION_SCAN_FEATURES:
            statuses.setdefault(feature, "unknown")
    return dict(sorted(statuses.items()))


def _source_analysis(source, target_version):
    source_version = _source_version(source)
    source_tuple = _version_tuple(source_version)
    target_tuple = _version_tuple(target_version)
    changed = (
        source_tuple != target_tuple
        if source_tuple is not None and target_tuple is not None
        else None
    )
    return {
        "detected_version": source_version,
        "target_version": target_version,
        "version_changed": changed,
    }


def _migration_deltas(source, source_analysis, path, feature_status, requirements):
    if source["provider"] != "anthropic":
        return []
    deltas = [
        _delta(
            "sdk_and_auth",
            "path",
            "Authentication and client construction change for the selected Bedrock path.",
        ),
        _delta(
            "model_id_shape",
            "path",
            "Mantle uses a clean path ID; runtime requires a verified CRIS profile.",
        ),
        _delta(
            "iam_action",
            "platform",
            "Mantle and runtime use different IAM actions and resource conditions.",
        ),
        _delta(
            "version_header",
            "path",
            "Mantle uses the HTTP version header; runtime uses the Bedrock body field.",
        ),
        _delta(
            "error_and_quota_surface",
            "platform",
            "Messages 400s, runtime ValidationException, and quota pools differ by path.",
        ),
    ]
    if source_analysis["version_changed"]:
        deltas.append(
            _delta(
                "claude_version_hop",
                "version",
                f"Claude {source_analysis['detected_version']} to "
                f"{source_analysis['target_version']} requires version migration checks.",
            )
        )
    detected = {
        feature for feature, status in feature_status.items() if status == "detected"
    }
    if "structured_output" in detected:
        deltas.append(
            _delta(
                "structured_output",
                "feature",
                "Use a forced tool without strict as the portable default; native fields "
                "are model, path, and region dependent.",
            )
        )
    if path == "runtime_converse" and (
        "extended_thinking" in requirements.get("critical_features", [])
        or "budget_tokens" in detected
    ):
        deltas.append(
            _delta(
                "additional_model_request_fields",
                "path",
                "Converse carries Anthropic thinking and effort fields through "
                "additionalModelRequestFields.",
            )
        )
    if "prompt_caching" in detected:
        deltas.append(
            _delta(
                "prompt_cache_shape",
                "path",
                "Mantle cache_control and Converse cachePoint use different request shapes.",
            )
        )
    return deltas


def _compatibility(feature_status, requirements, path):
    detected = {
        feature for feature, status in feature_status.items() if status == "detected"
    }
    native = {
        feature
        for feature in detected
        if feature in {"citations", "streaming", "tool_use", "vision"}
    }
    if "prompt_caching" in detected and path == "mantle_messages":
        native.add("prompt_caching")
    portable = detected.intersection(_VERSION_SCAN_FEATURES)
    portable.update(detected.intersection({"models_api", "structured_output"}))
    if "prompt_caching" in detected and path != "mantle_messages":
        portable.add("prompt_caching")
    rearchitecture = detected.intersection(_REARCHITECTURE_FEATURES)
    critical = set(requirements.get("critical_features", []))
    native.update(critical.intersection({"tool_use", "vision", "multimodal"}))
    return {
        "native": sorted(native),
        "portable": sorted(portable - rearchitecture),
        "rearchitecture": sorted(rearchitecture),
        "unsupported": [],
    }


def _architecture_impacts(feature_status):
    detected = {
        feature for feature, status in feature_status.items() if status == "detected"
    }
    impacts = []
    for feature in sorted(detected.intersection(_REARCHITECTURE_FEATURES)):
        _, message, remediation = _BLOCK_FINDINGS[feature]
        impacts.append(
            {
                "feature": feature,
                "impact": message,
                "recommendation": remediation,
            }
        )
    return impacts


def _evaluation_requirements(workload, feature_status):
    detected = {
        feature for feature, status in feature_status.items() if status == "detected"
    }
    critical = set(workload["requirements"].get("critical_features", []))
    trajectory = bool(
        critical.intersection({"agentic", "tool_use"})
        or detected.intersection({"agent_infra", "server_tools"})
    )
    gates = [
        "Compare representative source and target outputs against a versioned golden set.",
        "Fail on refusal mishandling, truncation, or invalid structured output.",
    ]
    if trajectory:
        gates.extend(
            [
                "Verify the correct tool is called with valid arguments.",
                "Verify the agent loop terminates and guardrails remain effective.",
            ]
        )
    return {"mode": "trajectory" if trajectory else "prompt", "gates": gates}


def _base_findings(feature_status, source_analysis):
    detected = {
        feature for feature, status in feature_status.items() if status == "detected"
    }
    blocks = []
    tuning = []
    for feature in sorted(detected):
        if feature in _BLOCK_FINDINGS:
            code, message, remediation = _BLOCK_FINDINGS[feature]
            blocks.append(_finding(code, "[BLOCKS]", message, remediation))
        if feature in _TUNE_FINDINGS:
            code, message, remediation = _TUNE_FINDINGS[feature]
            tuning.append(_finding(code, "[TUNE]", message, remediation))
    unknown_version_features = sorted(
        feature
        for feature in _VERSION_SCAN_FEATURES
        if feature_status.get(feature) == "unknown"
    )
    if source_analysis["version_changed"] and unknown_version_features:
        blocks.append(
            _finding(
                "version_scan_incomplete",
                "[BLOCKS]",
                "The source-to-target Claude version hop has unverified breaking-change surfaces: "
                + ", ".join(unknown_version_features),
                "Scan the recorded source paths and mark every feature detected or absent.",
            )
        )
    if "structured_output" in detected:
        blocks.append(
            _finding(
                "structured_output_portable_pattern",
                "[BLOCKS]",
                "Native structured-output controls vary by model, path, and region.",
                "Use a forced tool without strict; validate the schema subset and do not "
                "combine structured output with citations.",
            )
        )
    if "structured_output" in detected and "citations" in detected:
        blocks.append(
            _finding(
                "structured_output_citations_conflict",
                "[BLOCKS]",
                "Structured output and citations are incompatible in the reference snapshot.",
                "Choose one output contract per call site and verify it live.",
            )
        )
    return blocks, tuning


def _verification(candidate, region, catalog, invocation_model_id):
    path = candidate["path"]
    checks = [
        "Probe the selected model through the selected API path in the target account and region.",
        "Verify path-specific IAM before code rewrite or POC generation.",
    ]
    if candidate["path_config"]["requires_cris"]:
        checks.insert(
            1,
            "Resolve and probe a Global or geography-scoped CRIS inference profile.",
        )
    return {
        "region": region,
        "catalog_verified_at": catalog["verified_at"],
        "verified_at": None,
        "probe_status": "not_run",
        "availability_claim": "provisional",
        "invocation_model_id": invocation_model_id,
        "required_checks": checks,
    }


def _decision_required(workload, region, catalog, constraints):
    feature_status = _feature_assessment(workload, _source_version(workload["source"]), None)
    decision_options = _decision_options(
        catalog, workload, constraints["option_paths"]
    )
    if len(decision_options) != len(set(constraints["option_paths"])):
        raise ValueError(
            "catalog has no candidate for every conflicting model/path option "
            f"for workload {workload['workload_id']}"
        )
    blocks = [
        _finding(
            "model_path_decision_required",
            "[BLOCKS]",
            "Messages continuity conflicts with required Bedrock runtime capabilities.",
            "Choose the Mantle continuity option or the runtime governance option, "
            "update requirements, and rerun Model Recommend.",
        )
    ]
    return {
        "workload_id": workload["workload_id"],
        "provider_module": "anthropic",
        "decision_status": "decision_required",
        "source": workload["source"],
        "source_analysis": {
            "detected_version": _source_version(workload["source"]),
            "target_version": None,
            "version_changed": None,
        },
        "feature_assessment": feature_status,
        "primary_model": None,
        "model_identity": None,
        "api_path": None,
        "invocation_model_id": None,
        "decision_options": decision_options,
        "alternatives": [],
        "rationale": constraints["rationale"],
        "blocks": blocks,
        "tuning": [],
        "compatibility": _compatibility(feature_status, workload["requirements"], ""),
        "architecture_impacts": _architecture_impacts(feature_status),
        "migration_deltas": [],
        "evaluation": _evaluation_requirements(workload, feature_status),
        "rollout": {
            "strategy": "decision_required",
            "gate": "Resolve the model/path conflict before implementation.",
        },
        "verification": {
            "region": region,
            "catalog_verified_at": catalog["verified_at"],
            "verified_at": None,
            "probe_status": "not_applicable",
            "availability_claim": "not_selected",
            "invocation_model_id": None,
            "required_checks": [
                "Resolve the model/path decision before running an availability probe."
            ],
        },
    }


def recommend_anthropic_workload(workload, region, catalog):
    constraints = _path_constraints(workload)
    if constraints["conflicts"]:
        return _decision_required(workload, region, catalog, constraints)

    candidates = _build_candidates(
        catalog, constraints["paths"], workload["requirements"]
    )
    if not candidates:
        raise ValueError(
            f"catalog has no model/path candidate satisfying workload "
            f"{workload['workload_id']} requirements"
        )
    chosen = candidates[0]
    model = chosen["model"]
    path = chosen["path"]
    path_config = chosen["path_config"]
    source_analysis = _source_analysis(workload["source"], model["version"])
    feature_status = _feature_assessment(
        workload,
        source_analysis["detected_version"],
        source_analysis["target_version"],
    )
    blocks, tuning = _base_findings(feature_status, source_analysis)
    provider = workload["source"]["provider"]
    provider_module = "anthropic" if provider in ANTHROPIC_POOL else "generic"
    if provider_module == "generic":
        blocks.append(
            _finding(
                "provider_module_pending",
                "[BLOCKS]",
                f"The {provider} to Bedrock compatibility module is not implemented yet.",
                "Keep this recommendation provisional until its provider module runs.",
            )
        )
    invocation_model_id = _resolve_invocation_model_id(
        path_config["model_id"],
        path_config["requires_cris"],
        workload["requirements"],
    )
    rationale = list(constraints["rationale"])
    rationale.append(
        f"{model['display_name']} is the highest-ranked {chosen['driver']} model "
        f"that satisfies the {path} constraints."
    )
    alternatives = [
        _candidate_summary(
            candidate,
            workload["requirements"],
            "Next compatible model/path candidate after hard-constraint filtering.",
        )
        for candidate in candidates[1:4]
    ]
    return {
        "workload_id": workload["workload_id"],
        "provider_module": provider_module,
        "decision_status": "recommended",
        "source": workload["source"],
        "source_analysis": source_analysis,
        "feature_assessment": feature_status,
        "primary_model": path_config["model_id"],
        "model_identity": {
            "model_key": chosen["model_key"],
            "display_name": model["display_name"],
            "family": model["family"],
            "version": model["version"],
            "context_window": model["context_window"],
            "output_token_ceiling": model["output_token_ceiling"],
            "path_model_id": path_config["model_id"],
            "requires_cris": path_config["requires_cris"],
        },
        "api_path": path,
        "invocation_model_id": invocation_model_id,
        "decision_options": [],
        "alternatives": alternatives,
        "rationale": rationale,
        "blocks": blocks,
        "tuning": tuning,
        "compatibility": _compatibility(
            feature_status, workload["requirements"], path
        ),
        "architecture_impacts": _architecture_impacts(feature_status),
        "migration_deltas": _migration_deltas(
            workload["source"],
            source_analysis,
            path,
            feature_status,
            workload["requirements"],
        ),
        "evaluation": _evaluation_requirements(workload, feature_status),
        "rollout": {
            "strategy": "canary",
            "gate": "Compare source and target on the golden set before percentage rollout.",
        },
        "verification": _verification(
            chosen, region, catalog, invocation_model_id
        ),
    }

