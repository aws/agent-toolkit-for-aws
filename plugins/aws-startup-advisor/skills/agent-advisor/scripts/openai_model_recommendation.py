"""Deterministic OpenAI-to-Bedrock model/path recommendation for agent-advisor.

Factual baseline: the public Bedrock model cards (docs.aws.amazon.com/bedrock/latest/
userguide/model-card-openai-*.html, cited per catalog row with a read date) and the
shared Bedrock endpoint policy (skills/shared/ai/bedrock-endpoint-policy.md:
bedrock-runtime is the default endpoint; bedrock-mantle is selected only by a
mantle_selector). The engine is offline: no openai/boto3/token-generator imports at
module load. Rankings are only produced where the catalog provides evidence;
otherwise the engine returns an explicit decision or a provisional limitation rather
than inventing a comparative order.
"""

import re

import anthropic_model_recommendation
from anthropic_model_recommendation import MANTLE_SELECTORS

# --- Source model-family detection (ported from the reference compatibility matrix) ---
# Reasoning generation: gpt-5 / gpt-6 variants and o1/o3/o4.
_REASONING_PATTERNS = (
    re.compile(r"(?i)(^|[^a-z0-9])gpt[-_ ]?[56](\.\d+)?([^0-9]|$)"),
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
        "The built-in Web Search tool is a pre-configured server-side tool served only on "
        "bedrock-mantle; bedrock-runtime does not offer it. Model support is per model card "
        "(https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-server-side.html, "
        "https://docs.aws.amazon.com/bedrock/latest/userguide/web-search.html, read 2026-11-07).",
        "Keep the workload on bedrock-mantle with mantle_selector web_search and verify the "
        "tool on the selected model, or replace it with a client-side search tool / Bedrock "
        "AgentCore Gateway tool on bedrock-runtime.",
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


# Converse tier map: the cross-family fallback behind the same-model candidate on
# runtime Converse. A governance workload whose source has no cataloged same-model
# identity (see _SOURCE_MODEL_KEYS) keeps its capability tier when moving to Claude.
#   GPT-5.6 Sol (frontier)      -> Claude Opus 5.5
#   GPT-5.6 Terra / 6.1 Terra / 5.5 / 5.4 -> Claude Sonnet 5.5 (also the default tier; Sonnet 5
#                                  follows it as the forced tool_choice / Batch alternative)
#   GPT-5.6 Luna (fast/low-cost)-> Claude Haiku 5.5 (Haiku 4.5 stays an explicit alternative, last in the order)
_CONVERSE_TIER_DEFAULT = "anthropic_claude_sonnet_5_5"
_CONVERSE_TIER_ORDER = (
    "anthropic_claude_sonnet_5_5",
    "anthropic_claude_sonnet_5",
    "anthropic_claude_opus_5_5",
    "anthropic_claude_haiku_5_5",
    "anthropic_claude_haiku_4_5",
)


def _converse_tier_for_source(source):
    sid = _primary_source_id(source).lower()
    if "5.6-sol" in sid or "6-astra" in sid:
        return "anthropic_claude_opus_5_5"
    if "5.6-luna" in sid:
        return "anthropic_claude_haiku_5_5"
    # 5.6-terra, 5.5, 5.4, legacy, and unknown sources all map to the balanced tier.
    return _CONVERSE_TIER_DEFAULT


# Models whose cards document runtime JSON Schema output for non-streaming calls only, with the
# Converse request shape in the structured_output_text_format delta. Short names keep Astra's text.
_RUNTIME_JSON_SCHEMA_NON_STREAMING = {
    "openai_gpt_6_astra": "Astra",
    "openai_gpt_6_1_terra": "GPT-6.1 Terra",
}
_RUNTIME_JSON_SCHEMA_NON_STREAMING_NAMES = {
    "OpenAI GPT-6 Astra (on Bedrock)": "Astra",
    "OpenAI GPT-6.1 Terra (on Bedrock)": "GPT-6.1 Terra",
}

_SOURCE_MODEL_KEYS = {
    "gpt-5.6-sol": "openai_gpt_5_6_sol",
    "gpt-5.6-terra": "openai_gpt_5_6_terra",
    "gpt-5.6-luna": "openai_gpt_5_6_luna",
    "gpt-5.5": "openai_gpt_5_5",
    "gpt-5.4": "openai_gpt_5_4",
    "gpt-6-astra": "openai_gpt_6_astra",
    "gpt-6-sol": "openai_gpt_6_sol",
    "gpt-6-luna": "openai_gpt_6_luna",
    "gpt-6.1-sol": "openai_gpt_6_1_sol",
    "gpt-6.1-terra": "openai_gpt_6_1_terra",
}


def _same_model_catalog_key(source):
    """Return the exact catalog key for a recognized source model identity."""
    sid = re.sub(r"[_ ]", "-", _primary_source_id(source).lower())
    for identity in sorted(_SOURCE_MODEL_KEYS, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(identity)}(?![a-z0-9])", sid):
            return _SOURCE_MODEL_KEYS[identity]
    return None


def _same_model_runtime_key(source):
    """Return the exact source model when it has a runtime_converse path."""
    return _same_model_catalog_key(source)


# Sonnet 5.5 is adaptive-thinking only; a workload that disables thinking gets Sonnet 5 first,
# unless an explicit inference profile names Sonnet 5.5 (same scoped yield as the Anthropic module).
_CONVERSE_THINKING_YIELD = ("anthropic_claude_sonnet_5_5", "anthropic_claude_sonnet_5")


def _converse_candidate_order(source, requirements=None):
    requirements = requirements or {}
    tier = (
        "anthropic_claude_opus_5_5"
        if requirements.get("priority") == "quality"
        else _converse_tier_for_source(source)
    )
    order = [tier] + [k for k in _CONVERSE_TIER_ORDER if k != tier]
    preferred, alternative = _CONVERSE_THINKING_YIELD
    pinned = requirements.get("inference_profile_id") or ""
    if (requirements.get("thinking_enabled") is False and "claude-sonnet-5-5" not in pinned
            and preferred in order and alternative in order
            and order.index(preferred) < order.index(alternative)):
        order.remove(alternative)
        order.insert(order.index(preferred), alternative)
    same = _same_model_runtime_key(source)
    if same:
        # Same model outranks any cross-family tier: keeping the model removes
        # prompt-adaptation and behavior-delta risk entirely.
        order.insert(0, same)
    return order


def _mantle_path(source, requirements):
    """Mantle path preserving the source API: Chat for a Chat source whose API
    continuity is required/preferred/unknown (the candidate walk skips models whose
    Mantle Chat row is unavailable), Responses otherwise."""
    if (
        source.get("api_surface") == "chat_completions"
        and _api_continuity(requirements) in {"required", "preferred", "unknown"}
    ):
        return "mantle_openai_chat"
    return "mantle_openai_responses"


def _runtime_openai_path(surface):
    """bedrock-runtime path that preserves the source OpenAI API surface."""
    return "runtime_openai_chat" if surface == "chat_completions" else "runtime_openai_responses"


def _api_label(path):
    return "Chat Completions" if path.endswith("_chat") else "Responses"


def _logging_required(requirements):
    """Model invocation logging is captured only on bedrock-runtime (including its
    OpenAI-compatible APIs): model-invocation-logging.html, read 2026-11-08. CloudWatch
    metrics exist on both endpoints (AWS/BedrockMantle) and never constrain the path."""
    return "invocation_logging" in (requirements.get("governance") or [])


def _guardrails_required(requirements):
    return "guardrails" in (requirements.get("governance") or [])


def _application_profile_requested(requirements):
    """An application inference profile ARN is accepted by Converse only; the
    bedrock-runtime Responses and Chat Completions APIs reject it with HTTP 400
    (inference-responses-api.html, read 2026-11-08)."""
    return ":application-inference-profile/" in (requirements.get("inference_profile_id") or "")


def _guardrails_on_openai_api(catalog, source, openai_path):
    """True iff the recognized source model's catalog row for `openai_path` lists
    Guardrails on that API (per model card). Unrecognized sources keep Converse."""
    same = _same_model_catalog_key(source)
    if not same or not openai_path or catalog is None:
        return False
    row = catalog["models"].get(same, {}).get("paths", {}).get(openai_path, {})
    return row.get("guardrails_supported") is True


def _other_runtime_api_with_prompt_caching(catalog, source, path):
    """The recognized source model's OTHER bedrock-runtime OpenAI API when its
    catalog row carries `prompt_caching_supported: true` and the selected `path`
    row does not (GPT-5.5 / GPT-5.4 Chat sources: Responses caches, Chat does not).
    None when `path` is not a runtime OpenAI API or no such row exists."""
    if path not in {"runtime_openai_responses", "runtime_openai_chat"}:
        return None
    same = _same_model_catalog_key(source)
    if not same or catalog is None:
        return None
    paths = catalog["models"].get(same, {}).get("paths", {})
    other = (
        "runtime_openai_chat" if path == "runtime_openai_responses" else "runtime_openai_responses"
    )
    if (
        paths.get(path, {}).get("prompt_caching_supported") is False
        and paths.get(other, {}).get("available") is True
        and paths.get(other, {}).get("prompt_caching_supported") is True
    ):
        return other
    return None


def _converse_required(requirements, catalog=None, source=None, openai_path=None):
    """Converse is required by multi-model Converse, by an application inference
    profile, and by Guardrails when the source model's card scopes them to Converse
    (the GPT-6 Sol / GPT-6 Luna / GPT-6.1 Sol cards list Guardrails on some runtime
    OpenAI APIs, so those sources keep their API)."""
    return (
        bool(requirements.get("multi_model_converse", False))
        or _application_profile_requested(requirements)
        or (
            _guardrails_required(requirements)
            and not _guardrails_on_openai_api(catalog, source, openai_path)
        )
    )


def _converse_only_drivers(requirements, guardrails_on_api=False):
    """Human-readable list of the requirements that pin this workload to Converse."""
    drivers = []
    if _guardrails_required(requirements) and not guardrails_on_api:
        drivers.append("Guardrails, which the model card lists as Converse-only for this model")
    if _application_profile_requested(requirements):
        drivers.append(
            "the application inference profile, which bedrock-runtime accepts only on Converse"
        )
    if requirements.get("multi_model_converse"):
        drivers.append("multi-model Converse")
    return drivers


def _runtime_only_drivers(requirements):
    """Human-readable list of the governance requirements that pin bedrock-runtime."""
    drivers = []
    if _guardrails_required(requirements):
        drivers.append("Guardrails")
    if _logging_required(requirements):
        drivers.append("invocation logging")
    if _application_profile_requested(requirements):
        drivers.append("application inference profiles")
    if requirements.get("multi_model_converse"):
        drivers.append("multi-model Converse")
    return drivers


def _mantle_selector(workload, feature_assessment):
    """Explicit requirements.mantle_selector, else the derived web_search selector.
    in_region_processing is derived later, once the runtime candidate is known."""
    requirements = workload["requirements"]
    selector = requirements.get("mantle_selector")
    if selector is not None:
        if selector not in MANTLE_SELECTORS:
            raise ValueError(f"unsupported mantle_selector: {selector}")
        return selector
    if (
        feature_assessment.get("web_search") == "detected"
        or "web_search" in (requirements.get("critical_features") or [])
    ):
        return "web_search"
    return None


def _chat_responses_blocker(selector, requirements, detected):
    """The Responses-only feature a Chat Mantle path would drop.

    The primary selector is not the only input: a projects or server_side_tools
    selector must not hide critical or detected web_search / background_inference.
    """
    needed = set(requirements.get("critical_features") or []) | set(detected or [])
    if selector == "web_search" or "web_search" in needed:
        return "web_search"
    if selector == "background_inference" or "background_inference" in needed:
        return "background_inference"
    if selector == "server_side_tools":
        return "server_side_tools"
    return None


def _openai_candidate_order(catalog, source):
    """[same model] + OpenAI-generation models, same family as the source's GPT major
    first, then version descending, then catalog order. Sources with no parseable
    GPT major keep catalog order after the same model. Claude entries never enter an
    OpenAI-API path (they have no such path)."""
    same = _same_model_catalog_key(source)
    version = _openai_version(_primary_source_id(source))
    try:
        major = int(version.split(".")[0]) if version else None
    except ValueError:
        major = None
    openai_keys = [
        key for key, model in catalog["models"].items()
        if model.get("generation") != "bedrock_native" and key != same
    ]
    if major is not None:
        index = {key: position for position, key in enumerate(openai_keys)}

        def rank(key):
            model = catalog["models"][key]
            parsed = _version_tuple(model.get("version")) or (0, 0)
            return (
                0 if model.get("family") == f"openai_gpt_{major}" else 1,
                -parsed[0],
                -parsed[1],
                index[key],
            )

        openai_keys = sorted(openai_keys, key=rank)
    return ([same] if same else []) + openai_keys


def _hard_profile_requirement(requirements):
    """Whether runtime selection must prove a specific CRIS profile is callable."""
    residency = requirements.get("data_residency")
    return bool(
        requirements.get("inference_profile_id")
        or residency == "global_allowed"
        or (residency == "geo_required" and requirements.get("cris_geography"))
    )


_SERVER_SIDE_TOOL_SELECTORS = frozenset({"server_side_tools", "web_search"})
# Selectors served on the bedrock-mantle Responses API only: background inference
# (inference-responses-api.html) and the built-in Web Search tool (web-search.html),
# both read 2026-11-09. Chat Completions has neither, so a Chat source matched by
# one of these is an explicit reshape decision, never a same-API Mantle Chat row.
# server_side_tools joins this set: the documented Lambda/MCP server-tool flow uses
# Responses items (tool-use-server-side.html, read 2026-11-09). Client function tools
# are a capability, not this selector, and stay on Chat Completions.
_RESPONSES_ONLY_SELECTORS = frozenset({"background_inference", "web_search", "server_side_tools"})


def _catalog_model_for_path(catalog, path, detected_features=None, requirements=None,
                            candidate_order=None, region=None, selector=None,
                            enforce_guardrails=True):
    """Pick the first available catalog model for `path` whose capability evidence
    covers the required/detected text features (evidence-driven fallback: a newer
    model without feature-level evidence is skipped in favor of an older probed
    one). Mantle candidates with cataloged region availability are skipped outside
    that footprint; runtime Converse availability remains governed by CRIS resolution.
    When Guardrails are required, runtime rows whose card does not list Guardrails on
    that API are skipped (`enforce_guardrails=False` lets a decision option show the
    API that gives Guardrails up). A server-side-tool selector skips Mantle rows whose
    card lists server-side tools as unsupported (GPT-6.1 Sol).
    When no candidate covers the requirements, return the first available model together
    with its unmet-capability list so the caller can fail closed. Deterministic:
    iterates `candidate_order` when given (e.g. the Converse tier map), else
    catalog key order."""
    first = None
    first_unmet = None
    keys = candidate_order if candidate_order is not None else list(catalog["models"])
    guardrails = enforce_guardrails and _guardrails_required(requirements or {})
    for model_key in keys:
        model = catalog["models"].get(model_key)
        if model is None or not anthropic_model_recommendation.is_selectable(model):
            continue
        path_config = model["paths"].get(path, {})
        if path_config.get("available") is not True:
            continue
        if (
            guardrails
            and path.startswith("runtime_")
            and path_config.get("guardrails_supported") is not True
        ):
            continue
        if (
            selector in _SERVER_SIDE_TOOL_SELECTORS
            and path.startswith("mantle_")
            and path_config.get("server_side_tools_supported") is False
        ):
            continue
        if "capabilities" in path_config:
            model = {**model, "capabilities": path_config["capabilities"]}
        availability = model.get("region_availability")
        if path.startswith("mantle_") and region and region != "unknown" and availability:
            supported_regions = set(availability.get("commercial", []))
            supported_regions.update(availability.get("govcloud", []))
            if region not in supported_regions:
                continue
        if (
            path.startswith("runtime_")
            and path_config.get("requires_cris")
            and _hard_profile_requirement(requirements or {})
            and _resolve_invocation_model_id(
                path_config["model_id"], True, requirements or {}, model, region
            )
            is None
        ):
            continue
        unmet = _unsupported_required_capabilities(
            model, detected_features, requirements or {}, path_config
        )
        if first is None:
            first = (model_key, model, path_config)
            first_unmet = unmet
        if not unmet:
            return (model_key, model, path_config), []
    return first, first_unmet


_PROFILE_REQUIREMENT_KEYS = frozenset({"inference_profile_id", "data_residency", "cris_geography"})


def _profile_relaxed_hit(catalog, path, detected, requirements, candidate_order, region,
                         enforce_guardrails=True):
    """When every runtime candidate was skipped because no cataloged CRIS profile is
    callable from `region` under the stated residency, re-walk the path without the
    profile requirements so a decision can still show the candidate. The caller
    leaves its invocation id unresolved (None); a profile id is never fabricated."""
    if not (path.startswith("runtime_") and _hard_profile_requirement(requirements or {})):
        return None
    relaxed = {k: v for k, v in (requirements or {}).items() if k not in _PROFILE_REQUIREMENT_KEYS}
    hit, _ = _catalog_model_for_path(
        catalog, path, detected, relaxed, candidate_order=candidate_order, region=region,
        enforce_guardrails=enforce_guardrails,
    )
    return hit


def _unresolved_profile_suffix(path, path_config, invocation_model_id, requirements, region):
    """Reason suffix for a runtime option whose CRIS profile could not be resolved."""
    if (
        path.startswith("runtime_")
        and path_config["requires_cris"]
        and invocation_model_id is None
        and _hard_profile_requirement(requirements)
    ):
        return (
            f" No cataloged CRIS profile for this model is callable from {region} under "
            "the stated residency; resolve a profile before this option is implementable."
        )
    return ""


def _resolve_invocation_model_id(model_id, requires_cris, requirements, model=None, region=None):
    if (model or {}).get("inference_profiles"):
        return anthropic_model_recommendation._resolve_invocation_model_id(
            model_id, requires_cris, requirements, model, region
        )
    if not requires_cris:
        return model_id
    explicit = requirements.get("inference_profile_id")
    if explicit:
        # Without a cataloged profile matrix the explicit id cannot be verified, but a
        # bare `<prefix>.<model_id>` form that names a different model is never this
        # candidate's invocation id. ARNs are kept for the verifier to check.
        if explicit.startswith("arn:") or explicit.endswith(f".{model_id}"):
            return explicit
        return None
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


def _runtime_required(requirements, converse_required):
    """bedrock-runtime is pinned by anything Converse-only, by invocation logging
    (runtime-only capture) and by Guardrails (no Mantle row lists them). CloudWatch
    metrics exist on both endpoints and never pin the path."""
    return bool(
        converse_required
        or _logging_required(requirements)
        or _guardrails_required(requirements)
    )


def _model_identity(model_key, model, path_config, invocation_model_id=None):
    return {
        "model_key": model_key,
        "display_name": model["display_name"],
        "family": model["family"],
        "version": model["version"],
        "context_window": model["context_window"],
        "output_token_ceiling": model["output_token_ceiling"],
        "path_model_id": path_config["model_id"],
        "requires_cris": anthropic_model_recommendation._invocation_requires_cris(
            path_config, invocation_model_id
        ),
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
    if target_model.get("display_name") == "OpenAI GPT-6 Astra (on Bedrock)":
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


def _reasoning_findings(source, requirements, target_model, path, detected_features=()):
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
    if target_model and target_model.get("sampling_parameters_supported") is False:
        if target_model.get("adaptive_thinking_only"):
            # Opus 5.5 / Sonnet 5.5: thinking is always on, so the controls cannot come back by
            # disabling it.
            remediation = (
                "Remove temperature/top_p/top_k from requests to this target; do not rescale them "
                "or disable thinking. Route user-visible controls through the existing "
                "parameter_removed confirmation before changing them."
            )
            description = f"{target_name} does not support sampling controls with its required thinking mode."
        else:
            # Haiku 5.5 and similar: sampling controls are rejected whether adaptive thinking is on
            # or off (the model card lets it be turned off); never tell the user thinking is required.
            remediation = (
                "Remove temperature/top_p/top_k from requests to this target (including Converse "
                "inferenceConfig temperature/topP); do not rescale them. Route user-visible controls "
                "through the existing parameter_removed confirmation before changing them."
            )
            description = f"{target_name} does not support sampling controls in any thinking mode."
        finding = _finding(
            "sampling_parameters_removed",
            "[BLOCKS]" if "sampling_params" in detected_features else "[TUNE]",
            description,
            remediation,
        )
        (blocks if finding["tag"] == "[BLOCKS]" else tuning).append(finding)
        if "sampling_params" in detected_features:
            deltas.append(_delta("sampling_parameters_removed", "feature", remediation))
    elif path == "runtime_converse":
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
        elif target_model and target_model.get("display_name") == "OpenAI GPT-6 Astra (on Bedrock)":
            tuning.append(
                _finding(
                    "sampling_params_unverified", "[TUNE]",
                    "Astra's model card does not specify accepted sampling parameters.",
                    "Probe sampling and reasoning settings on the selected API; do not "
                    "inherit GPT-5.x parameter acceptance or rejection rules.",
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


def _feature_findings(detected_features, requirements, path=None, target_model=None):
    """Structured output, n, tools, state, and hosted-tool/modality impacts.

    Findings are path-aware: Mantle Responses keeps verified capabilities
    (responses.parse typed output, hosted store=True continuation) that a
    Bedrock-native Converse target does not."""
    detected = set(detected_features or [])
    detected.update(requirements.get("critical_features") or [])
    is_responses = path in {"mantle_openai_responses", "runtime_openai_responses"}
    is_chat = path in {"mantle_openai_chat", "runtime_openai_chat"}
    blocks, tuning, deltas, impacts = [], [], [], []

    if "structured_output_json" in detected:
        json_schema_name = _RUNTIME_JSON_SCHEMA_NON_STREAMING_NAMES.get((target_model or {}).get("display_name"))
        if path == "runtime_converse" and json_schema_name:
            deltas.append(
                _delta(
                    "structured_output_text_format",
                    "feature",
                    f"{json_schema_name} runtime JSON Schema output is documented for non-streaming calls. "
                    "Set outputConfig.textFormat.type=json_schema and put name plus schema "
                    "(encoded as a JSON string) in outputConfig.textFormat.structure.jsonSchema. "
                    "Also set additionalModelRequestFields.text.format.strict=true. Use an "
                    "object schema with all fields required and additionalProperties=false; "
                    "validate the schema and check refusal/incomplete responses before parsing.",
                )
            )
        elif path == "runtime_openai_responses":
            deltas.append(
                _delta(
                    "structured_output_text_format",
                    "feature",
                    "On bedrock-runtime Responses, keep typed structured output: text.format "
                    "json_schema (strict) is documented on the selected model's card; "
                    "client.responses.parse(..., text_format=Model) builds that request — "
                    "verify in the target account.",
                )
            )
        elif is_responses:
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
                    "For the selected non-Responses path, enforce the schema through that "
                    "path's supported request shape plus application validation; the OpenAI "
                    "Responses parse() helper is not available.",
                )
            )
    if requirements.get("uses_n") or "multiple_candidates_n" in detected:
        if is_chat:
            if target_model and target_model.get("display_name") == "OpenAI GPT-6 Astra (on Bedrock)":
                tuning.append(
                    _finding(
                        "multiple_candidates_n_unverified", "[TUNE]",
                        "Astra Chat Completions support for n has not been verified.",
                        "Probe n on the selected model and endpoint before preserving it; "
                        "if unsupported, request multiple candidates with repeated calls.",
                    )
                )
        else:
            deltas.append(
                _delta(
                    "responses_no_n",
                    "feature",
                    "The Responses API does not support n; request multiple candidates with "
                    "repeated calls.",
                )
            )
    if "tool_or_function_calling" in detected:
        if is_chat:
            tool_description = (
                "On Chat Completions, preserve assistant tool_calls and continue each "
                "result as a role: tool message with the matching tool_call_id; the "
                "application executes the tool."
            )
        else:
            tool_description = (
                "Tool calls continue via function_call_output on Responses; the application "
                "executes the tool."
            )
        deltas.append(_delta("tool_result_shape", "feature", tool_description))
    if "conversation_state" in detected or requirements.get("uses_hosted_state"):
        if target_model and target_model.get("display_name") == "OpenAI GPT-6 Astra (on Bedrock)":
            deltas.append(
                _delta(
                    "conversation_state_ownership",
                    "path",
                    "Astra's hosted state behavior has not been probed on this API. Verify "
                    "retention and continuation semantics; use application-owned history "
                    "until those requirements are confirmed.",
                )
            )
        elif path == "runtime_openai_responses":
            deltas.append(
                _delta(
                    "conversation_state_ownership",
                    "path",
                    "Verify store=True / previous_response_id continuation on bedrock-runtime "
                    "Responses in the target account before relying on it; application-owned "
                    "replay (store=False) is the portable default.",
                )
            )
        elif is_responses:
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
        elif is_chat:
            deltas.append(
                _delta(
                    "conversation_state_ownership",
                    "path",
                    "Chat Completions uses application-owned message history; replay "
                    "the prior user, assistant, tool-call, and tool-result messages on each "
                    "request.",
                )
            )
        else:
            deltas.append(
                _delta(
                    "conversation_state_ownership",
                    "path",
                    "This path does not use hosted Responses state; carry "
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


def _evidenced_capabilities(target_model, path_config):
    """The target's catalog capabilities for the selected row, plus `prompt_caching`
    when that row's `prompt_caching_supported` flag is true. Prompt caching is scoped
    per API by every GPT card (GPT-5.5 / GPT-5.4: implicit caching on the bedrock-runtime
    Responses API only; cards read 2026-11-09), so it is evidenced on the selected row
    only, never inherited from the model."""
    caps = set((target_model or {}).get("capabilities") or [])
    if (path_config or {}).get("prompt_caching_supported") is True:
        caps.add("prompt_caching")
    return caps


def _unsupported_required_capabilities(target_model, detected_features, requirements,
                                       path_config=None):
    """Required/detected text-model features NOT evidenced by the target's catalog
    capabilities on the selected path row. Hosted tools/modalities are handled as
    architecture impacts, not here."""
    if target_model is None:
        return []
    catalog_caps = _evidenced_capabilities(target_model, path_config)
    needed = set(requirements.get("critical_features") or [])
    needed.update(detected_features or [])
    checkable = needed.intersection(
        {
            "tool_or_function_calling",
            "structured_output_json",
            "streaming",
            "image_input_vision",
            "reasoning",
            "prompt_caching",
        }
    )
    return sorted(checkable - catalog_caps)


def _compatibility(detected_features, requirements, path, target_model=None, path_config=None):
    """native = only features the SELECTED target's catalog evidences on the selected
    path row; features needed but not evidenced go to unsupported (never derive native
    from the name)."""
    detected = set(detected_features or [])
    detected.update(requirements.get("critical_features") or [])
    text_features = detected.intersection(
        {
            "tool_or_function_calling", "structured_output_json", "streaming",
            "image_input_vision", "reasoning", "prompt_caching",
        }
    )
    catalog_caps = _evidenced_capabilities(target_model, path_config)
    native = sorted(text_features.intersection(catalog_caps)) if target_model else []
    unsupported = sorted(text_features - catalog_caps) if target_model else []
    hosted = detected.intersection(_HOSTED_TOOL_IMPACTS)
    portable_features = detected.intersection(_PORTABLE_FEATURES)
    if (path or "").startswith("mantle_") and path != "mantle_openai_chat" and "web_search" in hosted:
        # Web Search is a Mantle server-side tool: on a Mantle path it ports.
        hosted.discard("web_search")
        portable_features.add("web_search")
    rearchitecture = sorted(hosted)
    portable = sorted(portable_features)
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


def _verification(region, catalog, path, requires_cris, invocation_model_id, selected,
                  model=None, requirements=None):
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
    requires_cris = requires_cris and invocation_model_id != (model or {}).get(
        "paths", {}
    ).get(path, {}).get("model_id")
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
        **anthropic_model_recommendation._profile_verification(
            (model or {}).get("paths", {}).get(path, {}).get("model_id"),
            requires_cris, model, region, requirements,
        ),
    }


def _decision_options(catalog, workload, region, selector=None, openai_path=None):
    """Two-sided option set. Option A preserves the OpenAI SDK and the source API:
    the Mantle path when a mantle_selector exists, else the bedrock-runtime
    OpenAI path (`openai_path` overrides that choice). Option B is runtime Converse
    governance. An application inference profile is never emitted as the invocation
    id of an OpenAI-API option: bedrock-runtime Responses/Chat reject it with HTTP 400."""
    options = []
    source = workload["source"]
    requirements = workload["requirements"]
    detected = [feature for feature, status in _feature_assessment(workload).items()
                if status == "detected"]
    astra = _same_model_runtime_key(source) == "openai_gpt_6_astra"
    surface = source.get("api_surface")
    application_profile = _application_profile_requested(requirements)
    if openai_path:
        # Caller-fixed option path (an explicit runtime preference, or the Mantle
        # Responses reshape offered for background inference).
        pass
    elif selector:
        openai_path = _mantle_path(source, requirements)
        if astra:
            preferred = requirements.get("preferred_api_path")
            if preferred in {"mantle_openai_chat", "mantle_openai_responses"}:
                openai_path = preferred
            elif surface == "chat_completions":
                openai_path = "mantle_openai_chat"
            # A decision may offer changing an incompatible Chat preference to the
            # documented Mantle Responses caching path; it must not silently select it.
            needed = set(detected) | set(requirements.get("critical_features") or [])
            if "prompt_caching" in needed:
                openai_path = "mantle_openai_responses"
        if selector in _RESPONSES_ONLY_SELECTORS:
            # A Responses-only selector is never offered on a Mantle Chat row.
            openai_path = "mantle_openai_responses"
    else:
        openai_path = _runtime_openai_path(surface)
    candidate_order = (
        ["openai_gpt_6_astra"] if astra else _openai_candidate_order(catalog, source)
    )
    # The OpenAI-API option is the side of the decision that may give Guardrails up,
    # so the walk shows the source-preserving model rather than skipping it.
    openai_hit, _ = _catalog_model_for_path(
        catalog, openai_path, detected, requirements,
        candidate_order=candidate_order, region=region, selector=selector,
        enforce_guardrails=False,
    )
    requires_region_change = False
    if openai_hit is None and selector and region != "unknown":
        openai_hit, _ = _catalog_model_for_path(
            catalog, openai_path, detected, requirements,
            candidate_order=_openai_candidate_order(catalog, source),
            region="unknown", selector=selector, enforce_guardrails=False,
        )
        requires_region_change = openai_hit is not None
    if openai_hit is None and openai_path.startswith("runtime_openai_"):
        openai_hit = _profile_relaxed_hit(
            catalog, openai_path, detected, requirements, candidate_order, region,
            enforce_guardrails=False,
        )
    if openai_hit:
        model_key, model, path_config = openai_hit
        api_label = (
            "Chat Completions"
            if openai_path in {"mantle_openai_chat", "runtime_openai_chat"}
            else "Responses"
        )
        if openai_path.startswith("mantle_"):
            reason = (
                f"Preserves the OpenAI SDK and the {api_label} surface on bedrock-mantle, "
                f"selected by mantle_selector {selector}; gives up bedrock-runtime-only "
                "governance (Guardrails, invocation logging, application inference profiles)."
            )
        elif _guardrails_required(requirements) and path_config.get("guardrails_supported") is True:
            reason = (
                f"Keeps the OpenAI SDK and the {api_label} API on bedrock-runtime via a CRIS id "
                "(invocation logging included); Guardrails are listed on this API for this "
                "model (see its model card)."
            )
        else:
            reason = (
                "Keeps the OpenAI SDK and the source API on bedrock-runtime via a CRIS id "
                "(invocation logging included); Guardrails and application inference "
                "profiles are evidenced only on Converse for this model — see its card."
            )
        if requires_region_change:
            availability = model.get("region_availability") or {}
            supported_regions = sorted(
                set(availability.get("commercial", []))
                | set(availability.get("govcloud", []))
            )
            region_label = ", ".join(supported_regions) or "a catalog-supported region"
            reason += (
                f" Requires changing from {region} to a catalog-supported Mantle region "
                f"({region_label})."
            )
        if application_profile:
            invocation_model_id = None
            reason += (
                " Application inference profiles are rejected with HTTP 400 on the "
                "bedrock-runtime Responses and Chat Completions APIs "
                "(https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html, "
                "read 2026-11-08); Converse is the supported API for this profile."
            )
        else:
            invocation_model_id = _resolve_invocation_model_id(
                path_config["model_id"], path_config["requires_cris"], requirements, model,
                region,
            )
            reason += _unresolved_profile_suffix(
                openai_path, path_config, invocation_model_id, requirements, region
            )
        options.append(
            {
                "model_key": model_key,
                "model": path_config["model_id"],
                "api_path": openai_path,
                "invocation_model_id": invocation_model_id,
                "requires_cris": anthropic_model_recommendation._invocation_requires_cris(
                    path_config, invocation_model_id
                ),
                "reason": reason,
                "mantle_selector": selector if openai_path.startswith("mantle_") else None,
            }
        )
    converse_order = _converse_candidate_order(workload["source"], workload["requirements"])
    runtime, _ = _catalog_model_for_path(
        catalog, "runtime_converse", detected, workload["requirements"],
        candidate_order=converse_order, region=region,
    )
    if runtime is None:
        runtime = _profile_relaxed_hit(
            catalog, "runtime_converse", detected, workload["requirements"], converse_order,
            region,
        )
    if runtime:
        model_key, model, path_config = runtime
        invocation_model_id = _resolve_invocation_model_id(
            path_config["model_id"], path_config["requires_cris"], workload["requirements"],
            model, region,
        )
        same_model = model_key == _same_model_runtime_key(workload["source"])
        guardrails_on_openai_api = _guardrails_on_openai_api(
            catalog, source,
            openai_path if openai_path.startswith("runtime_openai_") else _runtime_openai_path(surface),
        )
        if same_model:
            reason = (
                "SAME-MODEL governance path: this OpenAI target runs on bedrock-runtime via a "
                "CRIS id — "
                + ("Guardrails" if guardrails_on_openai_api else "Guardrails (Converse API only)")
                + ", invocation logging and application inference profiles without a "
                "model change. Check the model's region/profile matrix and dated prices."
            )
        else:
            reason = (
                "Uses Bedrock-native Converse request/response shapes and a "
                "cross-family model; requires rewriting the OpenAI integration."
            )
        reason += _unresolved_profile_suffix(
            "runtime_converse", path_config, invocation_model_id, workload["requirements"],
            region,
        )
        options.append(
            {
                "model_key": model_key,
                "model": path_config["model_id"],
                "api_path": "runtime_converse",
                "invocation_model_id": invocation_model_id,
                "requires_cris": anthropic_model_recommendation._invocation_requires_cris(
                    path_config, invocation_model_id
                ),
                "reason": reason,
                "mantle_selector": None,
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
    preferred = requirements.get("preferred_api_path")
    # The bedrock-runtime OpenAI API this workload would keep: an explicit runtime
    # OpenAI preference, else the API that preserves the source surface. Guardrails
    # are checked against the source model's row for exactly this API.
    openai_path_default = (
        preferred if (preferred or "").startswith("runtime_openai_")
        else _runtime_openai_path(surface)
    )
    converse_required = _converse_required(requirements, catalog, source, openai_path_default)
    runtime_required = _runtime_required(requirements, converse_required)
    guardrails_on_api = _guardrails_required(requirements) and _guardrails_on_openai_api(
        catalog, source, openai_path_default
    )
    continuity_required = continuity == "required"

    feature_assessment = _feature_assessment(workload)
    # feature_status is authoritative: a feature is "effectively detected" only if
    # the merged assessment marks it detected. Explicit absent/unknown are excluded,
    # so downstream compatibility/deltas/targets never contradict the assessment.
    detected = [f for f, status in feature_assessment.items() if status == "detected"]
    selector = _mantle_selector(workload, feature_assessment)

    unknown_required = _unknown_required_features(feature_assessment, requirements)

    def _unresolved(
        reason_head, reasons, block, path_for_compat, decision_options=None
    ):
        # Shared assembly for results with no target selected. A real choice needs at least
        # two options (decision_required); with fewer (e.g. a reference_only pinned source, or
        # every option on one side filtered out) the result is blocked. Never invent options.
        options = (
            _decision_options(catalog, workload, region, selector)
            if decision_options is None
            else decision_options
        )
        status = "decision_required" if len(options) >= 2 else "blocked"
        rec = _base(workload, status)
        rec.update(
            {
                "source_analysis": _source_analysis(source, None),
                "feature_assessment": feature_assessment,
                "primary_model": None,
                "model_identity": None,
                "api_path": None,
                "invocation_model_id": None,
                "mantle_selector": None,
                "decision_options": options,
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
                    "strategy": status,
                    "gate": (
                        "Resolve the open decision before implementation."
                        if status == "decision_required"
                        else "Resolve each [BLOCKS] finding as its remediation says, then rerun."
                    ),
                },
                "verification": _verification(region, catalog, None, False, None, selected=False),
            }
        )
        return rec

    # --- Fail closed: Astra is pinned to itself, so a reference_only Astra has no target ---
    astra_entry = catalog["models"].get("openai_gpt_6_astra")
    if (_same_model_runtime_key(source) == "openai_gpt_6_astra" and astra_entry is not None
            and not anthropic_model_recommendation.is_selectable(astra_entry)):
        return _unresolved(
            "GPT-6 Astra sources stay on Astra, but the catalog marks Astra reference_only, "
            "so it is not an automatic-selection candidate.",
            ["No other model is substituted for an Astra source."],
            _finding(
                "model_not_selectable",
                "[BLOCKS]",
                "The source model GPT-6 Astra is marked reference_only in the model-selection "
                "catalog.",
                "Mark the Astra entry selectable once it is verified, or choose a target "
                "model explicitly, then rerun Model Recommend.",
            ),
            None,
            decision_options=[],
        )

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

    def _decision_conflict(reason_head, reasons, message, remediation, build_options):
        # `build_options(catalog)` assembles the two-sided option set the caller offers, so the
        # reference_only counterfactual below is built exactly like the real options.
        options = build_options(catalog)
        if len(options) < 2:
            # Blocked only when reference_only entries emptied the side: with them counted as
            # selectable (every other filter unchanged) both options exist. Otherwise the
            # requirement is unsatisfiable and the fail-closed raise is unchanged.
            counterfactual = build_options(
                anthropic_model_recommendation.with_all_selectable(catalog)
            )
            if len(counterfactual) < 2:
                raise ValueError(
                    f"catalog cannot supply both decision options for workload "
                    f"{workload['workload_id']}"
                )
            offered = {option["api_path"] for option in options}
            blamed = sorted(
                option["model_key"] for option in counterfactual
                if option["api_path"] not in offered
                and not anthropic_model_recommendation.is_selectable(catalog["models"][option["model_key"]])
            )
            return _unresolved(
                "Required OpenAI API continuity conflicts with a runtime-only Bedrock "
                "governance requirement, and one side has no selectable model.",
                [f"That side is available only from reference_only entries: {', '.join(blamed)}."],
                _finding(
                    "decision_option_unavailable",
                    "[BLOCKS]",
                    "One side of the continuity-versus-governance decision has no selectable "
                    f"catalog model; it is available only from reference_only entries: "
                    f"{', '.join(blamed)}.",
                    "Mark a verified model selectable for that path, or update the conflicting "
                    "requirement, then rerun Model Recommend.",
                ),
                "",
                decision_options=options,
            )
        return _unresolved(
            reason_head, reasons,
            _finding("model_path_decision_required", "[BLOCKS]", message, remediation),
            "", decision_options=options,
        )

    def _mantle_options(mantle_selector, cat=None):
        return [
            option for option in _decision_options(cat or catalog, workload, region, mantle_selector)
            if option["api_path"].startswith("mantle_")
        ]

    def _runtime_option(runtime_path):
        # The single bedrock-runtime option that keeps `runtime_path`.
        if runtime_path == "runtime_converse":
            candidates = _decision_options(catalog, workload, region, None)
        else:
            candidates = _decision_options(
                catalog, workload, region, None, openai_path=runtime_path
            )
        return [option for option in candidates if option["api_path"] == runtime_path][:1]

    def _preferred_path_conflict(mantle_selector, message):
        # An explicit bedrock-runtime preference cannot carry a Mantle selector
        # (explicit, web_search-derived or derived in_region_processing): the user
        # chooses between the Mantle option and the preferred runtime API.
        return _unresolved(
            "The explicit bedrock-runtime API preference conflicts with the recorded "
            "Mantle selector.",
            [],
            _finding(
                "preferred_api_path_conflict", "[BLOCKS]", message,
                "Keep the preference and drop the selector, or accept the Mantle option, "
                "then rerun Model Recommend.",
            ),
            preferred,
            decision_options=_mantle_options(mantle_selector) + _runtime_option(preferred),
        )

    # --- Provider mismatch: `workspaces` scopes the Anthropic Messages API ---
    if selector == "workspaces":
        return _unresolved(
            "mantle_selector workspaces does not apply to an OpenAI SDK workload.",
            [],
            _finding(
                "selector_provider_mismatch", "[BLOCKS]",
                "`workspaces` scopes the Anthropic Messages API (`anthropic-workspace-id`, "
                "https://docs.aws.amazon.com/bedrock/latest/userguide/workspaces.html); an "
                "OpenAI SDK workload has no Workspaces concept — the OpenAI equivalent is "
                "`projects` (`OpenAI-Project`, "
                "https://docs.aws.amazon.com/bedrock/latest/userguide/projects.html, "
                "read 2026-11-09).",
                "Record the applicable selector (or none) in Clarify and rerun Model Recommend.",
            ),
            openai_path_default,
            # Both options stay on bedrock-runtime: the source API, or Converse governance.
            decision_options=_decision_options(
                catalog, workload, region, None, openai_path=openai_path_default
            ),
        )

    # --- Hard conflict: a verified Mantle-only need AND bedrock-runtime-only governance ---
    if selector and runtime_required:
        drivers = ", ".join(_runtime_only_drivers(requirements))
        if converse_required:
            def options(cat):
                return _decision_options(cat, workload, region, selector)
        else:
            # Invocation logging and Guardrails listed on the OpenAI API are satisfied
            # on the bedrock-runtime OpenAI path, so the runtime option keeps the
            # source API rather than switching to Converse.
            def options(cat):
                return _mantle_options(selector, cat) + [
                    option for option in _decision_options(
                        cat, workload, region, None, openai_path=openai_path_default
                    )
                    if option["api_path"].startswith("runtime_openai_")
                ]
        return _decision_conflict(
            f"A verified Mantle-only need (mantle_selector {selector}) conflicts with a "
            f"bedrock-runtime-only governance requirement ({drivers}).",
            [
                "bedrock-mantle serves the selected capability; bedrock-runtime alone "
                "provides Guardrails, invocation logging and application inference "
                "profiles (bedrock-endpoint-policy.md; model-invocation-logging.html, read "
                "2026-11-08)."
            ],
            f"A verified Mantle-only need (mantle_selector {selector}) and "
            f"bedrock-runtime-only governance ({drivers}) cannot both be satisfied by one path.",
            "Choose the Mantle option or the bedrock-runtime governance option, update "
            "requirements, and rerun Model Recommend.",
            options,
        )

    # --- Hard conflict: OpenAI continuity required AND Converse-only governance ---
    if continuity_required and converse_required:
        drivers = "; ".join(_converse_only_drivers(requirements, guardrails_on_api))
        return _decision_conflict(
            f"Required OpenAI API continuity conflicts with Converse-only governance ({drivers}).",
            [
                "bedrock-runtime Responses/Chat Completions keep the OpenAI SDK and the "
                "source API via a CRIS id; runtime Converse provides Guardrails (where the "
                "model card lists them as Converse-only), application inference profiles "
                "and the multi-model surface and keeps an exact same-model runtime candidate "
                "when the catalog provides one."
            ],
            f"Required OpenAI API continuity and Converse-only governance ({drivers}) "
            "cannot both be satisfied by one bedrock-runtime API.",
            "Choose the bedrock-runtime OpenAI API option or the runtime Converse "
            "governance option, update requirements, and rerun Model Recommend.",
            lambda cat: _decision_options(
                cat, workload, region, None, openai_path=openai_path_default
            ),
        )

    # --- Select a path ---
    def _converse_selection():
        order = _converse_candidate_order(source, requirements)
        same = _same_model_runtime_key(source)
        if same and not anthropic_model_recommendation.is_selectable(catalog["models"].get(same, {})):
            same = None
        if same:
            head = (
                "Bedrock governance or multi-model requirements select runtime Converse; "
                f"the source model itself ({catalog['models'][same]['display_name']}) runs "
                "there via a CRIS id, so the same-model candidate leads, with the Claude "
                "tier as the cross-family fallback."
            )
        else:
            tier = _converse_tier_for_source(source)
            head = (
                "Bedrock governance or multi-model requirements select runtime Converse; "
                f"the source tier maps to {catalog['models'][tier]['display_name']} "
                "(capability-evidence fallback across Claude tiers). Sources without an "
                "exact runtime catalog identity require this family switch."
            )
        return order, head
    if converse_required:
        path = "runtime_converse"
        candidate_order, rationale_head = _converse_selection()
    elif selector:
        path = _mantle_path(source, requirements)
        candidate_order = _openai_candidate_order(catalog, source)
        rationale_head = (
            f"Mantle {_api_label(path)} selected by mantle_selector {selector} "
            "(bedrock-endpoint-policy.md); the exact source model is evaluated first."
        )
    elif guardrails_on_api:
        path = openai_path_default
        candidate_order = _openai_candidate_order(catalog, source)
        same_name = catalog["models"][_same_model_catalog_key(source)]["display_name"]
        rationale_head = (
            f"Guardrails are listed on {_api_label(path)} for {same_name} (model card, read "
            "2026-11-08), so the source API stays on bedrock-runtime; the exact source "
            "model is evaluated first and only candidates whose card lists Guardrails on "
            "this API are considered."
        )
    else:
        path = _runtime_openai_path(surface)
        candidate_order = _openai_candidate_order(catalog, source)
        rationale_head = (
            f"OpenAI source stays on bedrock-runtime {_api_label(path)} with the exact "
            "source model evaluated before capability and numeric fallbacks "
            "(bedrock-endpoint-policy.md default)."
        )

    # Astra's new paths must not inherit the older GPT-5.x defaults. Keep this
    # source on Astra and fail closed when the required path lacks evidence.
    astra = _same_model_runtime_key(source) == "openai_gpt_6_astra"
    if astra:
        candidate_order = ["openai_gpt_6_astra"]
        rationale_head = (
            "Keep GPT-6 Astra on Bedrock using the compatible explicit API preference, "
            "otherwise the source-compatible API or required runtime Converse path; "
            "apply Astra's own region and feature evidence."
        )
    if preferred:
        first = catalog["models"].get(candidate_order[0], {}) if candidate_order else {}
        available = first.get("paths", {}).get(preferred, {})
        if (available.get("available") is not True
                or runtime_required and not preferred.startswith("runtime_")
                or converse_required and preferred != "runtime_converse"
                or continuity_required and preferred == "runtime_converse"
                or preferred.startswith("mantle_") and not selector):
            return _unresolved(
                "The explicit API preference conflicts with the available paths, the "
                "endpoint policy, or required API/governance constraints.", [],
                _finding(
                    "preferred_api_path_conflict", "[BLOCKS]",
                    f"The requested {preferred} path cannot satisfy this workload."
                    + (
                        " A bedrock-mantle path needs a mantle_selector "
                        "(bedrock-endpoint-policy.md)."
                        if preferred.startswith("mantle_") and not selector
                        else ""
                    )
                    + (
                        " The requested application inference profile is accepted only on "
                        "Converse; the bedrock-runtime Responses and Chat Completions APIs "
                        "reject it with HTTP 400 (inference-responses-api.html, read 2026-11-08)."
                        if _application_profile_requested(requirements)
                        and preferred.startswith("runtime_openai_")
                        else ""
                    ),
                    "Choose a supported API or revise the conflicting requirements, "
                    "then rerun Model Recommend.",
                ), preferred,
            )
        if preferred.startswith("runtime_") and selector:
            return _preferred_path_conflict(
                selector,
                f"The requested {preferred} path cannot satisfy mantle_selector {selector}; "
                "that capability is served on bedrock-mantle only (bedrock-endpoint-policy.md).",
            )
        path = preferred
        if preferred == "runtime_converse" and not converse_required and not astra:
            # An explicit Converse preference on a source whose Guardrails are listed on its
            # OpenAI API: the rationale and walk are Converse's (same model, then Claude tier),
            # not the OpenAI-API Guardrails wording selected before the preference was read.
            candidate_order, rationale_head = _converse_selection()
    # A Chat Completions Mantle path cannot carry a Responses-only feature. Check the
    # retained features themselves, not only the primary selector: projects or
    # server_side_tools must not hide a required web_search or background_inference.
    blocker = _chat_responses_blocker(selector, requirements, detected)
    if path == "mantle_openai_chat" and blocker:
        if blocker == "web_search":
            message = (
                "Web Search is a server-side tool served on the bedrock-mantle Responses API "
                "(https://docs.aws.amazon.com/bedrock/latest/userguide/web-search.html, "
                "read 2026-11-09); Chat Completions has no `web_search` tool."
            )
            dropped = "Web Search"
        elif blocker == "background_inference":
            message = (
                "Background inference is a Responses API feature on bedrock-mantle; Chat "
                "Completions has no background mode "
                "(https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html, "
                "read 2026-11-08)."
            )
            dropped = "background inference"
        else:
            message = (
                "Server-side tools (Lambda-backed and MCP tools) use Responses request and "
                "response items on bedrock-mantle "
                "(https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-server-side.html, "
                "read 2026-11-09); Chat Completions has no server-side tool items. Client "
                "function tools stay on Chat Completions."
            )
            dropped = "server-side tools"
        if selector and selector != blocker:
            message += (
                f" mantle_selector {selector} does not satisfy this retained requirement."
            )
        option_selector = blocker if blocker in MANTLE_SELECTORS else selector
        return _unresolved(
            f"{blocker} conflicts with the Chat Completions API.",
            [],
            _finding(
                "selector_api_incompatible", "[BLOCKS]", message,
                "Accept the Mantle Responses reshape, or keep Chat Completions on "
                f"bedrock-runtime and drop {dropped}, then rerun Model Recommend.",
            ),
            path,
            decision_options=[
                option for option in _decision_options(
                    catalog, workload, region, option_selector, openai_path="mantle_openai_responses"
                )
                if option["api_path"] == "mantle_openai_responses"
            ] + _runtime_option("runtime_openai_chat"),
        )

    # Evidence-driven selection: pick the first candidate on the path whose catalog
    # capabilities cover the required/detected text features (a newer model without
    # feature-level evidence falls back to an older probed one). G02: fail closed
    # only when NO candidate on the path has the evidence.
    catalog_hit, unsupported = _catalog_model_for_path(
        catalog, path, detected, requirements, candidate_order=candidate_order,
        region=region, selector=selector,
    )
    if not catalog_hit:
        if path.startswith("mantle_"):
            return _unresolved(
                rationale_head,
                [
                    f"The catalog has no {path} candidate available in {region}; "
                    "select another region or migration path."
                ],
                _finding(
                    "mantle_region_unavailable",
                    "[BLOCKS]",
                    f"No in-region {path} model is available in {region}.",
                    "Choose a region in the selected model's Mantle footprint, choose "
                    "runtime Converse, or update the continuity requirement, then rerun "
                    "Model Recommend.",
                ),
                path,
            )
        emptied_by_reference_only = _hard_profile_requirement(requirements) and bool(
            _catalog_model_for_path(
                anthropic_model_recommendation.with_all_selectable(catalog), path, detected,
                requirements, candidate_order=candidate_order, region=region, selector=selector,
            )[0]
        )
        if _hard_profile_requirement(requirements) and not emptied_by_reference_only:
            # Every runtime candidate was skipped because its cataloged CRIS
            # profile matrix has no profile callable from this region under the
            # stated residency (e.g. an EU-Geo caller on models that publish
            # us./global. only). Fail closed with a decision rather than raising.
            return _unresolved(
                rationale_head,
                [
                    f"No {path} candidate publishes a CRIS profile callable from {region} "
                    "under the stated residency (data_residency / cris_geography / "
                    "inference_profile_id)."
                ],
                _finding(
                    "inference_profile_unverified",
                    "[BLOCKS]",
                    f"No {path} candidate has a cataloged CRIS profile for calls from "
                    f"{region} under the stated residency.",
                    "Choose a Geo or Global profile the selected model publishes for this "
                    "source region, change the region or geography, supply a verified "
                    "explicit inference_profile_id, or take the runtime Converse option, "
                    "then rerun Model Recommend.",
                ),
                path,
            )
        skipped = sorted(k for k in candidate_order or catalog["models"]
                         if not anthropic_model_recommendation.is_selectable(catalog["models"].get(k, {})))
        raise ValueError(
            f"catalog has no available model for path {path}"
            + (f" (reference_only entries skipped: {', '.join(skipped)})" if skipped else "")
        )
    model_key, model, path_config = catalog_hit
    # The cross-family sentence is written before selection. If that tier is
    # reference_only, name the model that was actually selected.
    if path == "runtime_converse" and "the source tier maps to" in rationale_head:
        tier = _converse_tier_for_source(source)
        tier_model = catalog["models"].get(tier, {})
        if not anthropic_model_recommendation.is_selectable(tier_model):
            rationale_head = (
                "Bedrock governance or multi-model requirements select runtime Converse; "
                f"{model['display_name']} is selected because the source tier is reference_only "
                "(capability-evidence fallback across Claude tiers). Sources without an "
                "exact runtime catalog identity require this family switch."
            )
    # Derived selector: strict in-Region processing on a CRIS-only runtime candidate
    # is a Mantle-only need (bedrock-endpoint-policy.md in_region_processing). An
    # explicit runtime preference or invocation logging turns it into a decision;
    # Converse-only governance keeps the runtime path (and its residency block).
    derivable = (
        path.startswith("runtime_")
        and requirements.get("data_residency") == "in_region_required"
        and path_config["requires_cris"]
        and not anthropic_model_recommendation._runtime_in_region_allowed(
            path_config["model_id"], model, region, requirements
        )
    )
    if derivable and preferred and preferred.startswith("runtime_"):
        return _preferred_path_conflict(
            "in_region_processing",
            f"The requested {preferred} path serves this model only through a CRIS profile, "
            "which conflicts with data_residency in_region_required (derived mantle_selector "
            "in_region_processing).",
        )
    if derivable and _logging_required(requirements) and not converse_required:
        return _decision_conflict(
            "Strict in-Region processing (derived mantle_selector in_region_processing) "
            "conflicts with invocation logging, which bedrock-runtime alone provides.",
            [
                f"bedrock-runtime serves this model from {region} only through a CRIS "
                "profile; model invocation logging is captured only on bedrock-runtime "
                "(model-invocation-logging.html, read 2026-11-08)."
            ],
            "in_region_processing and invocation logging cannot both be satisfied by one path.",
            "Choose the Mantle in-Region option or the bedrock-runtime logging option, "
            "update requirements, and rerun Model Recommend.",
            lambda cat: _mantle_options("in_region_processing", cat) + [
                option for option in _decision_options(
                    cat, workload, region, None, openai_path=openai_path_default
                )
                if option["api_path"].startswith("runtime_openai_")
            ],
        )
    if derivable and not runtime_required:
        selector = "in_region_processing"
        path = _mantle_path(source, requirements)
        candidate_order = ["openai_gpt_6_astra"] if astra else _openai_candidate_order(catalog, source)
        catalog_hit, unsupported = _catalog_model_for_path(
            catalog, path, detected, requirements, candidate_order=candidate_order,
            region=region, selector=selector,
        )
        if not catalog_hit:
            return _unresolved(
                rationale_head,
                [
                    f"The catalog has no {path} candidate available in {region}; "
                    "select another region or migration path."
                ],
                _finding(
                    "mantle_region_unavailable",
                    "[BLOCKS]",
                    f"No in-region {path} model is available in {region}.",
                    "Choose a region in the selected model's Mantle footprint, choose "
                    "runtime Converse, or update the continuity requirement, then rerun "
                    "Model Recommend.",
                ),
                path,
            )
        model_key, model, path_config = catalog_hit
        rationale_head = (
            "Strict in-Region processing was requested and bedrock-runtime serves this "
            f"model only through a CRIS profile; Mantle {_api_label(path)} keeps processing "
            "in-Region (mantle_selector in_region_processing)."
        )

    if path in {"mantle_openai_chat", "runtime_openai_chat"}:
        endpoint = "Mantle" if path.startswith("mantle_") else "bedrock-runtime"
        if model_key == _same_model_catalog_key(source):
            rationale_head = (
                "Chat Completions source lands on the exact same model through "
                f"{endpoint} Chat Completions"
                + (
                    f" (mantle_selector {selector})."
                    if path.startswith("mantle_")
                    else " (bedrock-endpoint-policy.md default)."
                )
            )
        elif (
            "prompt_caching" in (set(detected) | set(requirements.get("critical_features") or []))
            and _other_runtime_api_with_prompt_caching(catalog, source, path)
        ):
            same_name = catalog["models"][_same_model_catalog_key(source)]["display_name"]
            rationale_head = (
                f"{same_name} lists implicit prompt caching on the Responses API only on "
                "bedrock-runtime (model card, read 2026-11-09), so its Chat Completions row "
                f"cannot evidence the required prompt_caching; {model['display_name']} is the "
                f"same-family {endpoint} Chat Completions candidate whose card lists caching on "
                "this API."
            )
        else:
            rationale_head = (
                f"The exact source model is unavailable in {region}; "
                f"{model['display_name']} is the in-region {endpoint} Chat Completions fallback."
            )
    same_key = _same_model_catalog_key(source)
    if (
        path.startswith("mantle_")
        and selector in _SERVER_SIDE_TOOL_SELECTORS
        and same_key
        and model_key != same_key
        and catalog["models"][same_key]["paths"].get(path, {}).get("server_side_tools_supported")
        is False
    ):
        # The selector is never dropped: the source model's card lists server-side
        # system tools as unsupported on bedrock-mantle, so the same-family walk
        # supplies the model that serves them.
        rationale_head = (
            f"{catalog['models'][same_key]['display_name']} lists server-side system tools as "
            "unsupported on bedrock-mantle (model card, read 2026-11-08); "
            f"{model['display_name']} is the same-family Mantle {_api_label(path)} fallback "
            f"that serves mantle_selector {selector}."
        )
    if unsupported:
        message = (
            f"No {path} candidate is evidenced to support required features: "
            + ", ".join(unsupported)
        )
        remediation = (
            "Add dated capability evidence for a candidate, choose a different path/model, "
            "or drop the requirement, then rerun Model Recommend."
        )
        caching_api = _other_runtime_api_with_prompt_caching(catalog, source, path)
        if unsupported == ["prompt_caching"] and caching_api:
            # The source model does cache on its other bedrock-runtime OpenAI API: the
            # open decision is the API-continuity trade-off, not a missing model.
            same_name = catalog["models"][_same_model_catalog_key(source)]["display_name"]
            message += (
                f". {same_name} lists implicit prompt caching on the {_api_label(caching_api)} "
                f"API only on bedrock-runtime (model card, read 2026-11-09); keep "
                f"{_api_label(path)} without caching or reshape to {_api_label(caching_api)}."
            )
            remediation = (
                f"Keep {_api_label(path)} on bedrock-runtime and drop prompt_caching, or set "
                f"api_continuity to not_required (or preferred_api_path {caching_api}) to "
                f"reshape to {_api_label(caching_api)}, then rerun Model Recommend."
            )
        return _unresolved(
            rationale_head,
            [
                f"No {path} candidate has catalog capability evidence for: "
                + ", ".join(unsupported)
            ],
            _finding("unverified_capability", "[BLOCKS]", message, remediation),
            path,
        )

    needed = set(detected) | set(requirements.get("critical_features") or [])
    if (model_key in _RUNTIME_JSON_SCHEMA_NON_STREAMING
            and path in {"runtime_converse", "runtime_openai_responses", "runtime_openai_chat"}
            and {"structured_output_json", "streaming"} <= needed):
        return _unresolved(
            rationale_head, [],
            _finding(
                "structured_output_streaming_unverified", "[BLOCKS]",
                f"{_RUNTIME_JSON_SCHEMA_NON_STREAMING[model_key]} JSON Schema output on bedrock-runtime "
                "is documented only for non-streaming calls on Chat Completions, Responses and "
                "Converse (https://docs.aws.amazon.com/bedrock/latest/userguide/"
                f"model-card-{path_config['model_id'].replace('.', '-')}.html).",
                "Use non-streaming structured output or separate the streaming workload, "
                "then update requirements and rerun Model Recommend.",
            ), path,
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
        path_config["model_id"], path_config["requires_cris"], requirements, model, region
    )
    regions = path_config.get("supported_regions")
    profile_regions = path_config.get("inference_profile_regions")
    if regions is not None and region not in regions:
        return _unresolved(
            rationale_head, [],
            _finding(
                "model_region_unavailable", "[BLOCKS]",
                f"{model['display_name']} is not listed for {path} in {region}.",
                "Choose a supported region or a supported CRIS path with explicit "
                "data-residency consent, or evaluate a different model.",
            ), path,
        )
    if profile_regions is not None and (invocation_model_id is not None or _hard_profile_requirement(requirements)):
        profile_key = invocation_model_id
        if invocation_model_id and invocation_model_id.startswith("arn:"):
            match = re.fullmatch(
                r"arn:aws:bedrock:([^:]+):[0-9]{12}:inference-profile/([^/]+)",
                invocation_model_id,
            )
            profile_key = match.group(2) if match and match.group(1) == region else None
        if region not in profile_regions.get(profile_key, []):
            return _unresolved(
                rationale_head, [],
                _finding(
                    "inference_profile_unverified", "[BLOCKS]",
                    f"{invocation_model_id} has no catalog evidence for calls from {region}.",
                    "Select a cataloged profile available from this region, or verify an "
                    "application inference profile in the target account before proceeding.",
                ), path,
            )
    source_analysis = _source_analysis(source, model)

    # --- Findings (target- and path-derived) ---
    r_blocks, r_tuning, r_deltas = _reasoning_findings(source, requirements, model, path, detected)
    f_blocks, f_tuning, f_deltas, impacts = _feature_findings(detected, requirements, path, model)
    blocks = r_blocks + f_blocks
    tuning = r_tuning + f_tuning
    deltas = list(r_deltas)
    if model.get("adaptive_thinking_only"):
        finding = _finding(
            "adaptive_thinking_required",
            "[BLOCKS]" if requirements.get("thinking_enabled") is False else "[TUNE]",
            f"{anthropic_model_recommendation._short_name(model)} always uses adaptive thinking and does not support disabled thinking, manual budgets, or forced any/tool choice.",
            f"Set output_config.effort as needed (default {model.get('default_effort', 'medium')}), and size max_tokens "
            "for thinking plus response text. Use auto/none tool choice; a hard forced-tool "
            "requirement needs a verified compatible target. Verify billed usage on the workload.",
        )
        (blocks if finding["tag"] == "[BLOCKS]" else tuning).append(finding)

    if path.startswith("runtime_") and path_config["requires_cris"] and invocation_model_id is None:
        # GPT models on bedrock-runtime are CRIS-only — there is no in-region invocation
        # form. Unresolved residency, or a posture that forbids both Global and Geo
        # CRIS, leaves no resolvable invocation id; say so explicitly instead of
        # shipping a recommendation with an unresolvable invocation id.
        if requirements.get("data_residency", "unknown") == "unknown":
            blocks.append(
                _finding(
                    "cris_residency_unresolved",
                    "[BLOCKS]",
                    "This bedrock-runtime path is CRIS-only and data_residency is unresolved, "
                    "so no invocation id can be resolved.",
                    "Record data_residency (global_allowed, or geo_required with "
                    "cris_geography) or supply an explicit inference_profile_id, then rerun "
                    "Model Recommend.",
                )
            )
        else:
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

    if path in {"mantle_openai_responses", "runtime_openai_responses"} and surface == "chat_completions":
        endpoint = "Mantle" if path.startswith("mantle_") else "bedrock-runtime"
        deltas.extend(_chat_to_responses_deltas())
        blocks.append(
            _finding(
                "chat_completions_to_responses_required",
                "[BLOCKS]",
                (
                    f"The selected Astra {endpoint} Responses path requires reshaping the Chat source."
                    if model_key == "openai_gpt_6_astra"
                    else f"The selected {endpoint} Responses path requires reshaping the Chat source "
                    "to the Responses API (Chat Completions support is per-model: see the "
                    "selected model's Chat Completions catalog entry)."
                ),
                "Apply the request/response/tool/state reshape deltas before cutover.",
            )
        )
    if path in {"mantle_openai_chat", "runtime_openai_chat"} and surface == "responses":
        deltas.extend([
            _delta(
                "responses_to_chat_request", "path",
                "Map Responses input/instructions to Chat messages/system content and "
                "verify the selected model's output-budget parameters.",
            ),
            _delta(
                "responses_to_chat_response", "path",
                "Read choices[0].message.content instead of output_text; preserve Chat "
                "messages and tool_call_id rather than Responses output items.",
            ),
        ])
        blocks.append(_finding(
            "responses_to_chat_completions_required", "[BLOCKS]",
            (
                "The selected Astra Chat path requires reshaping the Responses source."
                if model_key == "openai_gpt_6_astra"
                else "The selected Chat Completions path requires reshaping the Responses source."
            ),
            "Apply the request/response/tool/state mapping before cutover.",
        ))
    deltas.extend(f_deltas)

    if path == "runtime_converse":
        same_model = model_key == _same_model_runtime_key(source)
        deltas.append(
            _delta(
                "openai_sdk_to_converse",
                "path",
                "The OpenAI SDK integration is rewritten to boto3 bedrock-runtime Converse; "
                + (
                    "the selected OpenAI model identity is preserved, while streaming moves "
                    "to ConverseStream event shapes."
                    if same_model
                    else "the selected model also changes families, and streaming moves to "
                    "ConverseStream event shapes."
                ),
            )
        )

    rationale = [rationale_head]
    if model["context_window"] == "unknown" or model["output_token_ceiling"] == "unknown":
        rationale.append(
            f"{model['display_name']} path is evidenced by the reference, but its context/output "
            "limits are unknown in the catalog and must be probed."
        )
    # Invariants: a set selector is only ever satisfied on a Mantle path (every other
    # combination returned a decision above), and a runtime path carries no selector.
    if selector and not path.startswith("mantle_"):
        raise ValueError(
            f"mantle_selector {selector} cannot be recommended on {path} for workload "
            f"{workload['workload_id']}"
        )
    if _application_profile_requested(requirements) and path != "runtime_converse":
        raise ValueError(
            f"an application inference profile cannot be recommended on {path} for workload "
            f"{workload['workload_id']}"
        )
    rec = _base(workload, "recommended")
    rec.update(
        {
            "source_analysis": source_analysis,
            "feature_assessment": feature_assessment,
            "primary_model": path_config["model_id"],
            "model_identity": _model_identity(model_key, model, path_config, invocation_model_id),
            "api_path": path,
            "invocation_model_id": invocation_model_id,
            "mantle_selector": selector if path.startswith("mantle_") else None,
            "decision_options": [],
            "alternatives": [],
            "rationale": rationale,
            "blocks": blocks,
            "tuning": tuning,
            "compatibility": _compatibility(detected, requirements, path, model, path_config),
            "architecture_impacts": impacts,
            "additional_targets": _additional_targets(detected, requirements),
            "migration_deltas": deltas,
            "evaluation": _evaluation(detected, requirements),
            "rollout": {
                "strategy": "canary",
                "gate": "Compare source and target on the golden set before percentage rollout.",
            },
            "verification": _verification(
                region, catalog, path, path_config["requires_cris"], invocation_model_id,
                selected=True, model=model, requirements=requirements,
            ),
        }
    )
    return rec
