"""Deterministic OpenAI-to-Bedrock model/path recommendation for agent-advisor.

Factual baseline: an internal OpenAI-to-Bedrock migration reference (2026-06 live
probes and its recorded feature-status notes). The engine is offline:
no openai/boto3/token-generator imports at module load. Rankings are only produced
where the reference provides evidence; otherwise the engine returns an explicit
decision or a provisional limitation rather than inventing a comparative order.
"""

import re


# --- Source model-family detection (ported from the reference compatibility matrix) ---
# Reasoning generation: gpt-5 / gpt5 / gpt-5.4 / openai.gpt-5.4, and o1/o3/o4.
_REASONING_PATTERNS = (
    re.compile(r"(?i)(^|[^a-z0-9])gpt[-_ ]?5(\.\d+)?([^0-9]|$)"),
    re.compile(r"(?i)(^|[^a-z0-9])o[134](-mini|-pro|-preview)?([^a-z0-9]|$)"),
)
# Legacy generation: gpt-4*, gpt-3.5 / gpt-35.
_LEGACY_PATTERNS = (
    re.compile(r"(?i)gpt[-_ ]?4o"),
    re.compile(r"(?i)gpt[-_ ]?4(?!\d)"),
    re.compile(r"(?i)gpt[-_ ]?4[-_ ]?32k"),
    re.compile(r"(?i)gpt[-_ ]?3\.?5"),
    re.compile(r"(?i)gpt[-_ ]?35"),
)
# GPT-5.2+ re-accepts sampling on Responses; earlier reasoning models differ.
_GPT5_MINOR = re.compile(r"(?i)gpt[-_ ]?5\.(\d+)")


def detect_family(model_id):
    """Return 'reasoning', 'legacy', or 'unknown'.

    Fails to 'unknown' for opaque deployment names (e.g. 'prod-default') so the
    engine never infers a model family from a deployment alias.
    """
    name = (model_id or "").strip()
    if not name:
        return "unknown"
    for pat in _REASONING_PATTERNS:
        if pat.search(name):
            return "reasoning"
    for pat in _LEGACY_PATTERNS:
        if pat.search(name):
            return "legacy"
    return "unknown"


def _gpt5_minor(model_id):
    match = _GPT5_MINOR.search(model_id or "")
    return int(match.group(1)) if match else None


def _primary_source_id(source):
    ids = source.get("model_ids") or []
    return ids[0] if ids else ""


def _source_family(source):
    """Family for the workload: reasoning if ANY id is reasoning, else legacy if
    any is legacy, else unknown (opaque deployment names stay unknown)."""
    families = [detect_family(mid) for mid in source.get("model_ids") or [""]]
    if "reasoning" in families:
        return "reasoning"
    if "legacy" in families:
        return "legacy"
    return "unknown"


def _finding(code, tag, message, remediation):
    return {"code": code, "tag": tag, "message": message, "remediation": remediation}


def _delta(code, category, description):
    return {"code": code, "category": category, "description": description}


# --- Feature vocabulary (provider-scoped; codes match scanner feature-catalog) ---
_HOSTED_TOOL_IMPACTS = {
    "web_search": (
        "Hosted web search does not execute live on Bedrock Mantle (verified passthrough: "
        "no query issued, no citations).",
        "Implement a client-side tool loop, or expose a server-side tool (MCP/Lambda) through "
        "Bedrock AgentCore Gateway; use Knowledge Bases for document retrieval.",
    ),
    "file_search_retrieval": (
        "Hosted file search / retrieval is not a drop-in on Bedrock.",
        "Re-platform retrieval onto Bedrock Knowledge Bases or application-owned retrieval.",
    ),
    "files_api": (
        "The OpenAI Files API and vector stores do not port directly.",
        "Redesign data ingestion and retrieval; use Knowledge Bases or application storage.",
    ),
    "vector_stores": (
        "OpenAI vector stores are not a Bedrock primitive.",
        "Move vectors to a Bedrock-supported store and retrieve from the application.",
    ),
    "assistants_threads": (
        "Assistants/Threads hosted state is not available on Bedrock.",
        "Redesign agent state, tools, and memory (e.g. Bedrock AgentCore).",
    ),
    "audio_modality": (
        "Audio is not a single-call text-model capability on Bedrock.",
        "Split into a verified STT/TTS service path (Amazon Transcribe / Polly).",
    ),
    "embeddings": (
        "Embeddings require a separate Bedrock embedding model, not the text model.",
        "Select a sourced Bedrock embedding model (e.g. Titan/Cohere) as a separate workload.",
    ),
    "images": (
        "Image generation/editing is a separate capability, not a text-model swap.",
        "Select a sourced Bedrock image model/service as a separate workload.",
    ),
}


# Converse tier map: a governance workload keeps its capability tier when moving
# from the (Mantle-only) GPT-5.x family to Claude on runtime Converse.
#   GPT-5.6 Sol (frontier)      -> Claude Opus 4.8
#   GPT-5.6 Terra / 5.5 / 5.4   -> Claude Sonnet 5 (also the default tier)
#   GPT-5.6 Luna (fast/low-cost)-> Claude Haiku 4.5
_CONVERSE_TIER_DEFAULT = "anthropic_claude_sonnet_5"
_CONVERSE_TIER_ORDER = (
    "anthropic_claude_sonnet_5",
    "anthropic_claude_opus_4_8",
    "anthropic_claude_haiku_4_5",
)


def _converse_tier_for_source(source):
    sid = _primary_source_id(source).lower()
    if "5.6-sol" in sid:
        return "anthropic_claude_opus_4_8"
    if "5.6-luna" in sid:
        return "anthropic_claude_haiku_4_5"
    # 5.6-terra, 5.5, 5.4, legacy, and unknown sources all map to the balanced tier.
    return _CONVERSE_TIER_DEFAULT


def _same_model_runtime_key(source):
    """GPT-5.6 sources have a SAME-MODEL runtime_converse path via CRIS (verified
    2026-08-21) — governance requirements no longer force a family switch for
    them. Returns the catalog key, or None for every other source (5.5/5.4 and
    legacy have no runtime path, so their Converse candidates stay Claude)."""
    sid = _primary_source_id(source).lower()
    for marker, key in (("5.6-sol", "openai_gpt_5_6_sol"),
                        ("5.6-terra", "openai_gpt_5_6_terra"),
                        ("5.6-luna", "openai_gpt_5_6_luna")):
        if marker in sid:
            return key
    return None


def _converse_candidate_order(source):
    tier = _converse_tier_for_source(source)
    order = [tier] + [k for k in _CONVERSE_TIER_ORDER if k != tier]
    same = _same_model_runtime_key(source)
    if same:
        # Same model outranks any cross-family tier: keeping the model removes
        # prompt-adaptation and behavior-delta risk entirely, and on Global CRIS
        # it is also the cost-parity option.
        order.insert(0, same)
    return order


def _catalog_model_for_path(catalog, path, detected_features=None, requirements=None,
                            candidate_order=None):
    """Pick the first available catalog model for `path` whose capability evidence
    covers the required/detected text features (evidence-driven fallback: a newer
    model without feature-level evidence is skipped in favor of an older probed
    one). When no candidate covers them, return the first available model together
    with its unmet-capability list so the caller can fail closed. Deterministic:
    iterates `candidate_order` when given (e.g. the Converse tier map), else
    catalog key order."""
    first = None
    first_unmet = None
    keys = candidate_order if candidate_order is not None else list(catalog["models"])
    for model_key in keys:
        model = catalog["models"].get(model_key)
        if model is None:
            continue
        path_config = model["paths"].get(path, {})
        if path_config.get("available") is not True:
            continue
        unmet = _unsupported_required_capabilities(
            model, detected_features, requirements or {}
        )
        if first is None:
            first = (model_key, model, path_config)
            first_unmet = unmet
        if not unmet:
            return (model_key, model, path_config), []
    return first, first_unmet


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


def _api_continuity(requirements):
    """Provider-neutral continuity: required | preferred | not_required | unknown.

    Accepts the explicit `api_continuity` field; falls back to the OpenAI-specific
    `preserve_openai_api` boolean. Never reuses Anthropic's preserve_messages_api.
    """
    explicit = requirements.get("api_continuity")
    if explicit:
        return explicit
    if requirements.get("preserve_openai_api") is True:
        return "required"
    if requirements.get("preserve_openai_api") is False:
        return "not_required"
    return "unknown"


def _runtime_required(requirements):
    return bool(requirements.get("governance")) or requirements.get(
        "multi_model_converse", False
    )


def _model_identity(model_key, model, path_config):
    return {
        "model_key": model_key,
        "display_name": model["display_name"],
        "family": model["family"],
        "version": model["version"],
        "context_window": model["context_window"],
        "output_token_ceiling": model["output_token_ceiling"],
        "path_model_id": path_config["model_id"],
        "requires_cris": path_config["requires_cris"],
    }


def _numeric_requirement_conflict(model, requirements):
    """Fail closed: an unknown catalog limit cannot satisfy a hard numeric need."""
    conflicts = []
    for req_key, cat_key, label in (
        ("min_context_tokens", "context_window", "context window"),
        ("expected_output_tokens", "output_token_ceiling", "output ceiling"),
    ):
        need = requirements.get(req_key)
        if not need:
            continue
        have = model.get(cat_key)
        if have == "unknown" or not isinstance(have, int):
            conflicts.append(
                f"{label} for {model['display_name']} is unknown in the catalog; "
                f"a required {need}-token need cannot be confirmed"
            )
        elif have < need:
            conflicts.append(
                f"{label} for {model['display_name']} ({have}) is below the required {need}"
            )
    return conflicts


# Extracts a numeric OpenAI version (major or major.minor) from an id/version.
_OPENAI_VERSION = re.compile(r"(?i)gpt[-_ ]?(\d+(?:\.\d+)?)")


def _openai_version(text):
    match = _OPENAI_VERSION.search(text or "")
    return match.group(1) if match else None


def _version_tuple(value):
    if not value:
        return None
    parts = value.split(".")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        return None


def _target_accepts_sampling(target_model):
    """GPT-5.2+ re-accepts sampling params on Responses (verified for GPT-5.4).

    Returns True/False for an OpenAI target of known version, None when the
    target is not an OpenAI model or its version can't be parsed.
    """
    if target_model is None or target_model.get("generation") == "bedrock_native":
        return None
    version = _version_tuple(target_model.get("version"))
    if version is None:
        return None
    return version >= (5, 2)


def _source_analysis(source, target_model=None):
    """Source-side facts plus, when a target has been selected, target-derived
    version/generation change flags. Target fields stay null before selection."""
    source_id = _primary_source_id(source)
    family = _source_family(source)
    surface = source.get("api_surface")
    if target_model is None:
        target_version = None
        version_changed = None
        generation_changes = None
    else:
        target_version = target_model.get("version")
        target_generation = target_model.get("generation")
        if target_generation == "bedrock_native":
            # OpenAI source -> a Bedrock-native model is always a model change.
            version_changed = True
            generation_changes = True
        else:
            source_version = _openai_version(source_id)
            if source_version and target_version:
                version_changed = source_version != target_version
            else:
                # o-series / opaque source vs a specific GPT-5.x target: a move,
                # but we cannot pin the exact source version.
                version_changed = family in {"legacy", "reasoning"} or None
            generation_changes = family == "legacy" and target_generation == "reasoning"
    return {
        "detected_version": source_id or None,
        "target_version": target_version,
        "version_changed": version_changed,
        "source_family": family,
        "source_api_surface": surface,
        "model_generation_changes": generation_changes,
    }


def _reasoning_findings(source, requirements, target_model, path):
    """Version- and surface-specific parameter findings, derived from the SELECTED
    target model and path — never from the source id, and never Anthropic's blanket
    sampling-removal rule."""
    blocks, tuning, deltas = [], [], []
    src_family = _source_family(source)
    src_id = _primary_source_id(source)
    target_generation = target_model.get("generation") if target_model else None
    target_name = target_model.get("display_name") if target_model else "the target model"

    if target_generation == "reasoning":
        tuning.append(
            _finding(
                "reasoning_token_headroom",
                "[TUNE]",
                "Reasoning models spend hidden thinking tokens against the output budget; "
                "too-small caps return status:incomplete.",
                "Size the output cap for reasoning output. The reference uses ~2.5x the legacy "
                "budget plus a 4096 floor as a STARTING heuristic, not a guaranteed value; "
                "tune from measured output distributions.",
            )
        )
    if src_family == "legacy" and target_generation == "reasoning":
        deltas.append(
            _delta(
                "model_generation_hop",
                "version",
                f"Source '{src_id}' is a GPT-4.x/legacy model migrating to a reasoning target "
                f"({target_name}): reasoning controls, token budget, and prompt behavior change.",
            )
        )

    # Sampling acceptance is a property of the TARGET model and the selected path.
    if path == "runtime_converse":
        tuning.append(
            _finding(
                "sampling_via_converse",
                "[TUNE]",
                f"On runtime Converse, sampling is set through inferenceConfig "
                f"(temperature/topP) on {target_name}, not OpenAI SDK kwargs.",
                "Move temperature/top_p into Converse inferenceConfig; penalties/logprobs/stop "
                "are not universally supported and must be verified.",
            )
        )
    else:
        accepts = _target_accepts_sampling(target_model)
        if accepts is True:
            tuning.append(
                _finding(
                    "sampling_params_accepted",
                    "[TUNE]",
                    f"{target_name} (GPT-5.2+) accepts temperature and top_p on the Responses "
                    "surface; do not strip them.",
                    "Keep temperature/top_p and calibrate against a golden set.",
                )
            )
            tuning.append(
                _finding(
                    "sampling_penalties_rejected",
                    "[TUNE]",
                    "frequency_penalty and presence_penalty were rejected as SDK kwargs on the "
                    "verified GPT-5.4 Responses probe.",
                    "Remove frequency_penalty/presence_penalty. logprobs, logit_bias, and stop "
                    "were NOT part of that probe and are version/endpoint-specific — verify each "
                    "for the exact target model rather than assuming acceptance or rejection.",
                )
            )
        elif accepts is False:
            tuning.append(
                _finding(
                    "sampling_params_version_specific",
                    "[TUNE]",
                    f"{target_name} predates GPT-5.2 and may reject sampling parameters on "
                    "Responses; behavior is version-specific.",
                    "Verify sampling acceptance for the exact target model and surface.",
                )
            )
    return blocks, tuning, deltas


def _chat_to_responses_deltas():
    return [
        _delta(
            "chat_to_responses_request",
            "path",
            "Chat Completions -> Responses: messages->input, system message->instructions, "
            "max_tokens->max_output_tokens.",
        ),
        _delta(
            "chat_to_responses_response",
            "path",
            "Read model output from output_text instead of the chat message content.",
        ),
        _delta(
            "chat_to_responses_tools",
            "feature",
            "Tool results move to function_call_output on the Responses surface.",
        ),
        _delta(
            "chat_to_responses_state",
            "path",
            "Replayed multi-turn context uses previous_response_id where appropriate, or "
            "application-owned state.",
        ),
    ]


def _feature_findings(detected_features, requirements, path=None):
    """Structured output, n, tools, state, and hosted-tool/modality impacts.

    Findings are path-aware: Mantle Responses keeps verified capabilities
    (responses.parse typed output, hosted store=True continuation) that a
    Bedrock-native Converse target does not."""
    detected = set(detected_features or [])
    detected.update(requirements.get("critical_features") or [])
    is_mantle = path == "mantle_openai_responses"
    blocks, tuning, deltas, impacts = [], [], [], []

    if "structured_output_json" in detected:
        if is_mantle:
            # Verified on Mantle: responses.parse(text_format=Model) returns a typed object.
            deltas.append(
                _delta(
                    "structured_output_text_format",
                    "feature",
                    "On Mantle Responses, keep typed structured output: "
                    "client.responses.parse(..., text_format=Model) is verified, or use raw "
                    "text.format json_schema.",
                )
            )
        else:
            deltas.append(
                _delta(
                    "structured_output_text_format",
                    "feature",
                    "For a Bedrock-native Converse target, enforce the schema via tool-use or "
                    "prompt + validation; the OpenAI parse() helper is not the selected path.",
                )
            )
    if requirements.get("uses_n") or "multiple_candidates_n" in detected:
        deltas.append(
            _delta(
                "responses_no_n",
                "feature",
                "The Responses API does not support n; request multiple candidates with "
                "repeated calls.",
            )
        )
    if "tool_or_function_calling" in detected:
        deltas.append(
            _delta(
                "tool_result_shape",
                "feature",
                "Tool calls continue via function_call_output on Responses; the application "
                "executes the tool.",
            )
        )
    if "conversation_state" in detected or requirements.get("uses_hosted_state"):
        if is_mantle:
            deltas.append(
                _delta(
                    "conversation_state_ownership",
                    "path",
                    "Two verified modes on Mantle Responses: server-hosted continuation "
                    "(store=True + previous_response_id) or manual replay (store=False with "
                    "application-owned history). Retention/compliance/availability are "
                    "verification questions, not a lost capability.",
                )
            )
        else:
            deltas.append(
                _delta(
                    "conversation_state_ownership",
                    "path",
                    "A Bedrock-native Converse target has no hosted Responses state; carry "
                    "conversation history in an application-owned store.",
                )
            )

    impacted = sorted(detected.intersection(_HOSTED_TOOL_IMPACTS))
    for feature in impacted:
        impact, remediation = _HOSTED_TOOL_IMPACTS[feature]
        impacts.append(
            {"feature": feature, "impact": impact, "recommendation": remediation}
        )
    return blocks, tuning, deltas, impacts


# Text-model features that map to portable request-shape changes on any path.
_PORTABLE_FEATURES = {"max_tokens", "sampling_params", "sampling_params_accepted"}


# Separate-capability modalities that need their OWN target, not the text model.
# service = the Bedrock service family the reference names; candidate stays null
# (unresolved) because the reference does not pin a specific verified model ID.
_SEPARATE_MODALITY_TARGETS = {
    "embeddings": (
        "Amazon Bedrock embedding model (e.g. Titan/Cohere families)",
        "05_migrating_for_real.ipynb maps embeddings to a separate Bedrock embedding model",
    ),
    "images": (
        "Amazon Bedrock image model/service (e.g. Titan Image / Nova / Stability)",
        "03_reasoning_api_migration.ipynb maps images to a separate Bedrock image model",
    ),
    "audio_modality": (
        "Amazon Transcribe / Polly (STT/TTS)",
        "feature-catalog + notebooks map audio to Transcribe/Polly, not a text model",
    ),
}


def _additional_targets(detected_features, requirements):
    """Emit an explicit per-modality target contract; candidate stays null
    (unresolved) since the reference names a service family, not a verified ID (G06)."""
    detected = set(detected_features or [])
    detected.update(requirements.get("critical_features") or [])
    targets = []
    for capability in sorted(detected.intersection(_SEPARATE_MODALITY_TARGETS)):
        service, evidence = _SEPARATE_MODALITY_TARGETS[capability]
        targets.append(
            {
                "capability": capability,
                "status": "unresolved",
                "candidate": None,
                "service": service,
                "evidence": evidence
                + "; select and verify a specific model/service in the target account",
            }
        )
    return targets


def _feature_assessment(workload):
    """Merge detected_features and feature_status; feature_status is authoritative
    for detected/absent/unknown, so an explicit 'unknown' is preserved (G08)."""
    assessment = {}
    for feature in workload.get("detected_features") or []:
        assessment[feature] = "detected"
    for feature, status in (workload.get("feature_status") or {}).items():
        assessment[feature] = status
    return dict(sorted(assessment.items()))


def _unknown_required_features(feature_assessment, requirements):
    """Required features whose status is explicitly unknown (G08)."""
    required = set(requirements.get("critical_features") or [])
    return sorted(f for f in required if feature_assessment.get(f) == "unknown")


def _unsupported_required_capabilities(target_model, detected_features, requirements):
    """Required/detected text-model features NOT evidenced by the target's catalog
    capabilities. Hosted tools/modalities are handled as architecture impacts, not here."""
    if target_model is None:
        return []
    catalog_caps = set(target_model.get("capabilities") or [])
    needed = set(requirements.get("critical_features") or [])
    needed.update(detected_features or [])
    checkable = needed.intersection(
        {
            "tool_or_function_calling",
            "structured_output_json",
            "streaming",
            "image_input_vision",
            "reasoning",
        }
    )
    return sorted(checkable - catalog_caps)


def _compatibility(detected_features, requirements, path, target_model=None):
    """native = only features the SELECTED target's catalog evidences; features
    needed but not evidenced go to unsupported (never derive native from the name)."""
    detected = set(detected_features or [])
    detected.update(requirements.get("critical_features") or [])
    text_features = detected.intersection(
        {"tool_or_function_calling", "structured_output_json", "streaming", "image_input_vision", "reasoning"}
    )
    catalog_caps = set((target_model or {}).get("capabilities") or [])
    native = sorted(text_features.intersection(catalog_caps)) if target_model else []
    unsupported = sorted(text_features - catalog_caps) if target_model else []
    rearchitecture = sorted(detected.intersection(_HOSTED_TOOL_IMPACTS))
    portable = sorted(detected.intersection(_PORTABLE_FEATURES))
    return {
        "native": native,
        "portable": portable,
        "rearchitecture": rearchitecture,
        "unsupported": unsupported,
    }


def _evaluation(detected_features, requirements):
    detected = set(detected_features or [])
    detected.update(requirements.get("critical_features") or [])
    trajectory = bool(
        detected.intersection(
            {"tool_or_function_calling", "assistants_threads", "web_search", "file_search_retrieval"}
        )
        or "agentic" in (requirements.get("critical_features") or [])
    )
    gates = [
        "Build a deterministic discovery inventory of clients, APIs, model IDs, and features.",
        "Compare viable path/model candidates on a representative golden set.",
        "Size quota for peak traffic and reasoning-output tokens.",
        "Fail on refusal mishandling, truncation, or invalid structured output.",
    ]
    if trajectory:
        gates.extend(
            [
                "Verify correct tool selection, valid tool arguments, and tool-result continuation.",
                "Verify loop termination and structured-output validity.",
            ]
        )
    return {"mode": "trajectory" if trajectory else "prompt", "gates": gates}


def _verification(region, catalog, path, requires_cris, invocation_model_id, selected):
    if not selected:
        return {
            "region": region,
            "catalog_verified_at": catalog["verified_at"],
            "verified_at": None,
            "probe_status": "not_applicable",
            "availability_claim": "not_selected",
            "invocation_model_id": None,
            "required_checks": [
                "Resolve the model/path decision before running an availability probe."
            ],
        }
    checks = [
        "Probe the selected model through the selected API path in the target account and region.",
        "Verify path-specific IAM, model access, and quota before code rewrite or POC generation.",
    ]
    if requires_cris:
        checks.insert(
            1, "Resolve and probe a Global or geography-scoped CRIS inference profile."
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


def _decision_options(catalog, workload, region):
    """Two-sided option set: Mantle Responses continuity vs runtime Converse governance."""
    options = []
    detected = workload.get("detected_features") or []
    mantle, _ = _catalog_model_for_path(
        catalog, "mantle_openai_responses", detected, workload["requirements"]
    )
    if mantle:
        model_key, model, path_config = mantle
        options.append(
            {
                "model_key": model_key,
                "model": path_config["model_id"],
                "api_path": "mantle_openai_responses",
                "invocation_model_id": _resolve_invocation_model_id(
                    path_config["model_id"], path_config["requires_cris"], workload["requirements"]
                ),
                "requires_cris": path_config["requires_cris"],
                "reason": "Preserves the OpenAI SDK and Responses surface; gives up runtime-only "
                "Bedrock governance.",
            }
        )
    runtime, _ = _catalog_model_for_path(
        catalog, "runtime_converse", detected, workload["requirements"],
        candidate_order=_converse_candidate_order(workload["source"]),
    )
    if runtime:
        model_key, model, path_config = runtime
        options.append(
            {
                "model_key": model_key,
                "model": path_config["model_id"],
                "api_path": "runtime_converse",
                "invocation_model_id": _resolve_invocation_model_id(
                    path_config["model_id"], path_config["requires_cris"], workload["requirements"]
                ),
                "requires_cris": path_config["requires_cris"],
                "reason": (
                    "SAME-MODEL governance path: this GPT-5.6 target runs on bedrock-runtime via a "
                    "CRIS id — Guardrails (Converse API only), invocation logging, and cost parity "
                    "on Global CRIS (1.10x on Geo/In-Region pricing), without a model change."
                    if model_key == _same_model_runtime_key(workload["source"])
                    else "Uses Bedrock-native Converse request/response shapes and a Bedrock-native "
                    "model; requires rewriting the OpenAI integration."
                ),
            }
        )
    return options


def _base(workload, decision_status):
    return {
        "workload_id": workload["workload_id"],
        "provider_module": "openai",
        "decision_status": decision_status,
        "source": workload["source"],
    }


def recommend_openai_workload(workload, region, catalog):
    """Return a recommendation dict in the shared downstream contract shape."""
    source = workload["source"]
    requirements = workload["requirements"]
    surface = source.get("api_surface")
    continuity = _api_continuity(requirements)
    runtime_required = _runtime_required(requirements)
    continuity_required = continuity == "required"

    feature_assessment = _feature_assessment(workload)
    # feature_status is authoritative: a feature is "effectively detected" only if
    # the merged assessment marks it detected. Explicit absent/unknown are excluded,
    # so downstream compatibility/deltas/targets never contradict the assessment.
    detected = [f for f, status in feature_assessment.items() if status == "detected"]

    unknown_required = _unknown_required_features(feature_assessment, requirements)

    def _unresolved(reason_head, reasons, block, path_for_compat):
        # Shared decision_required assembly (no target selected).
        rec = _base(workload, "decision_required")
        rec.update(
            {
                "source_analysis": _source_analysis(source, None),
                "feature_assessment": feature_assessment,
                "primary_model": None,
                "model_identity": None,
                "api_path": None,
                "invocation_model_id": None,
                "decision_options": _decision_options(catalog, workload, region),
                "alternatives": [],
                "rationale": [reason_head] + reasons,
                "blocks": [block],
                "tuning": [],
                "compatibility": _compatibility(detected, requirements, path_for_compat),
                "architecture_impacts": _feature_findings(detected, requirements, path_for_compat)[3],
                "additional_targets": _additional_targets(detected, requirements),
                "migration_deltas": [],
                "evaluation": _evaluation(detected, requirements),
                "rollout": {
                    "strategy": "decision_required",
                    "gate": "Resolve the open decision before implementation.",
                },
                "verification": _verification(region, catalog, None, False, None, selected=False),
            }
        )
        return rec

    # --- Fail closed: a required feature with unknown status is not ready (G08) ---
    if unknown_required:
        return _unresolved(
            "Required features are unresolved (status unknown): "
            + ", ".join(unknown_required),
            [
                "The scan did not confirm these required features as detected or absent, so "
                "readiness cannot be asserted."
            ],
            _finding(
                "feature_scan_incomplete",
                "[BLOCKS]",
                "Required features are unresolved (status unknown): "
                + ", ".join(unknown_required),
                "Scan the recorded source paths and mark each required feature detected or "
                "absent, then rerun Model Recommend.",
            ),
            "",
        )

    # --- Hard conflict: OpenAI continuity required AND runtime-only governance ---
    if continuity_required and runtime_required:
        options = _decision_options(catalog, workload, region)
        if len(options) < 2:
            raise ValueError(
                f"catalog cannot supply both decision options for workload "
                f"{workload['workload_id']}"
            )
        return _unresolved(
            "Required OpenAI API continuity conflicts with a runtime-only Bedrock "
            "governance requirement.",
            [
                "Mantle preserves the OpenAI SDK/Responses surface; runtime Converse provides "
                "Bedrock-native governance with a Bedrock-native model."
            ],
            _finding(
                "model_path_decision_required",
                "[BLOCKS]",
                "OpenAI API continuity and runtime-only governance cannot both be satisfied "
                "by one path.",
                "Choose the Mantle continuity option or the runtime governance option, "
                "update requirements, and rerun Model Recommend.",
            ),
            "",
        )

    # --- Select a path ---
    candidate_order = None
    if runtime_required:
        path = "runtime_converse"
        candidate_order = _converse_candidate_order(source)
        same = _same_model_runtime_key(source)
        if same:
            rationale_head = (
                "Bedrock governance or multi-model requirements select runtime Converse; "
                f"the source model itself ({catalog['models'][same]['display_name']}) runs "
                "there via a CRIS id (verified 2026-08-21), so the same-model candidate "
                "leads, with the Claude tier as the cross-family fallback."
            )
        else:
            tier = _converse_tier_for_source(source)
            rationale_head = (
                "Bedrock governance or multi-model requirements select runtime Converse; "
                f"the source tier maps to {catalog['models'][tier]['display_name']} "
                "(capability-evidence fallback across Claude tiers). GPT-5.5/5.4 sources "
                "have no runtime path, so governance implies this family switch."
            )
    else:
        path = "mantle_openai_responses"
        rationale_head = (
            "OpenAI source with API continuity lands on Mantle Responses (GPT-5.x is "
            "Responses-only on Mantle)."
        )

    # Evidence-driven selection: pick the first candidate on the path whose catalog
    # capabilities cover the required/detected text features (a newer model without
    # feature-level evidence falls back to an older probed one). G02: fail closed
    # only when NO candidate on the path has the evidence.
    catalog_hit, unsupported = _catalog_model_for_path(
        catalog, path, detected, requirements, candidate_order=candidate_order
    )
    if not catalog_hit:
        raise ValueError(f"catalog has no available model for path {path}")
    model_key, model, path_config = catalog_hit
    if unsupported:
        return _unresolved(
            rationale_head,
            [
                f"No {path} candidate has catalog capability evidence for: "
                + ", ".join(unsupported)
            ],
            _finding(
                "unverified_capability",
                "[BLOCKS]",
                f"No {path} candidate is evidenced to support required features: "
                + ", ".join(unsupported),
                "Add dated capability evidence for a candidate, choose a different path/model, "
                "or drop the requirement, then rerun Model Recommend.",
            ),
            path,
        )

    numeric_conflicts = _numeric_requirement_conflict(model, requirements)
    if numeric_conflicts:
        return _unresolved(
            rationale_head,
            numeric_conflicts,
            _finding(
                "unverified_capacity",
                "[BLOCKS]",
                "; ".join(numeric_conflicts),
                "Source the missing capability data from a dated reference, or reduce the "
                "hard numeric requirement, then rerun Model Recommend.",
            ),
            path,
        )

    invocation_model_id = _resolve_invocation_model_id(
        path_config["model_id"], path_config["requires_cris"], requirements
    )
    source_analysis = _source_analysis(source, model)

    # --- Findings (target- and path-derived) ---
    r_blocks, r_tuning, r_deltas = _reasoning_findings(source, requirements, model, path)
    f_blocks, f_tuning, f_deltas, impacts = _feature_findings(detected, requirements, path)
    blocks = r_blocks + f_blocks
    tuning = r_tuning + f_tuning
    deltas = list(r_deltas)

    if path == "runtime_converse" and path_config["requires_cris"] and invocation_model_id is None:
        # GPT-5.6 on bedrock-runtime is CRIS-only — there is no in-region invocation
        # form. A residency posture that forbids both Global and Geo CRIS makes the
        # same-model governance path unusable; say so explicitly instead of shipping
        # a recommendation with an unresolvable invocation id.
        blocks.append(
            _finding(
                "cris_residency_unresolved",
                "[BLOCKS]",
                "This runtime path is CRIS-only, and the stated data-residency posture "
                "permits neither Global nor Geo cross-region inference, so no invocation "
                "id can be resolved.",
                "Relax residency to Global or a Geo CRIS geography, supply an explicit "
                "inference_profile_id, or take the Claude cross-family Converse path.",
            )
        )

    if path == "mantle_openai_responses" and surface == "chat_completions":
        deltas.extend(_chat_to_responses_deltas())
        blocks.append(
            _finding(
                "chat_completions_to_responses_required",
                "[BLOCKS]",
                "GPT-5.x on Mantle rejects Chat Completions; the source must reshape to the "
                "Responses API.",
                "Apply the request/response/tool/state reshape deltas before cutover; do not "
                "target mantle_openai_chat for GPT-5.x.",
            )
        )
    deltas.extend(f_deltas)

    if path == "runtime_converse":
        deltas.append(
            _delta(
                "openai_sdk_to_converse",
                "path",
                "The OpenAI SDK integration is rewritten to boto3 bedrock-runtime Converse with a "
                "Bedrock-native model; streaming moves to ConverseStream event shapes.",
            )
        )

    rationale = [rationale_head]
    if model["context_window"] == "unknown" or model["output_token_ceiling"] == "unknown":
        rationale.append(
            f"{model['display_name']} path is evidenced by the reference, but its context/output "
            "limits are unknown in the catalog and must be probed."
        )
    rec = _base(workload, "recommended")
    rec.update(
        {
            "source_analysis": source_analysis,
            "feature_assessment": feature_assessment,
            "primary_model": path_config["model_id"],
            "model_identity": _model_identity(model_key, model, path_config),
            "api_path": path,
            "invocation_model_id": invocation_model_id,
            "decision_options": [],
            "alternatives": [],
            "rationale": rationale,
            "blocks": blocks,
            "tuning": tuning,
            "compatibility": _compatibility(detected, requirements, path, model),
            "architecture_impacts": impacts,
            "additional_targets": _additional_targets(detected, requirements),
            "migration_deltas": deltas,
            "evaluation": _evaluation(detected, requirements),
            "rollout": {
                "strategy": "canary",
                "gate": "Compare source and target on the golden set before percentage rollout.",
            },
            "verification": _verification(
                region, catalog, path, path_config["requires_cris"], invocation_model_id, selected=True
            ),
        }
    )
    return rec
