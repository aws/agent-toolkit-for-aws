#!/usr/bin/env python3
"""Deterministic contracts shared by direct and delegated BMA execution.

Direct preflight loads `scripts/bma-route-classifier.py`; route inventory uses
`references/runtime/bma-input-patterns.json`. The classifier is the only closure
validator used here, by delegated preflight, packaging, and reference lint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import types
from html import escape as html_escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

OWNER_DIRECT = "BEDROCK_MIGRATION_ASSESSMENT"
OWNER_DELEGATED = "GCP_TO_AWS"
BMA_OWNER = "bedrock-migration-assessment"
GCP_OWNER = "gcp-to-aws"
PHASES = ("discover", "clarify", "design", "estimate", "generate")

# Closed, canonical final-writer surface. Directory policies below cover only
# provider capture material and generated AI migration files.
WRITERS = {
    "direct": {
        ".phase-status.json": BMA_OWNER,
        ".gate-failures.json": BMA_OWNER,
        "migration-preview.json": BMA_OWNER,
        "ai-workload-profile.json": BMA_OWNER,
        "ai-workload-sidecar.json": BMA_OWNER,
        "openai-usage-profile.json": BMA_OWNER,
        "anthropic-usage-profile.json": BMA_OWNER,
        "openrouter-usage-profile.json": BMA_OWNER,
        "preferences-draft.json": BMA_OWNER,
        "preferences.json": BMA_OWNER,
        "aws-design-ai.json": BMA_OWNER,
        "estimation-ai.json": BMA_OWNER,
        "generation-ai.json": BMA_OWNER,
        "STARTUP_PROGRAMS.md": BMA_OWNER,
        "MIGRATION_GUIDE.md": BMA_OWNER,
        "README.md": BMA_OWNER,
        "decision-report.html": BMA_OWNER,
        "DECISION.md": BMA_OWNER,
        "migration-report.html": BMA_OWNER,
    },
    "delegated": {
        ".phase-status.json": GCP_OWNER,
        ".gate-failures.json": GCP_OWNER,
        "migration-preview.json": GCP_OWNER,
        # Public GCP artifact. It keeps the legacy GCP shape; BMA never writes it in a delegated run.
        "ai-workload-profile.json": GCP_OWNER,
        # Delegated BMA input in a hidden internal directory GCP does not publish. BMA discovery
        # (discover-app-code.md Step 8, usage-API Step 4) writes both through this boundary. The GCP
        # adapter also merges the converted legacy profile into them, by direct file write outside
        # this boundary.
        ".bma-input/ai-workload-profile.json": BMA_OWNER,
        ".bma-input/ai-workload-sidecar.json": BMA_OWNER,
        "openai-usage-profile.json": BMA_OWNER,
        "anthropic-usage-profile.json": BMA_OWNER,
        "openrouter-usage-profile.json": BMA_OWNER,
        "preferences-draft.json": GCP_OWNER,
        "preferences.json": GCP_OWNER,
        "aws-design-ai.json": BMA_OWNER,
        "estimation-ai.json": BMA_OWNER,
        "generation-ai.json": BMA_OWNER,
        "STARTUP_PROGRAMS.md": BMA_OWNER,
        "MIGRATION_GUIDE.md": GCP_OWNER,
        "README.md": GCP_OWNER,
        "decision-report.html": GCP_OWNER,
        "DECISION.md": GCP_OWNER,
        "migration-report.html": GCP_OWNER,
    },
}
MUTABLE_OUTPUTS = {
    ".phase-status.json", ".gate-failures.json", "migration-preview.json",
    "ai-workload-profile.json", ".bma-input/ai-workload-profile.json", ".bma-input/ai-workload-sidecar.json",
    "openai-usage-profile.json",
    "anthropic-usage-profile.json", "openrouter-usage-profile.json",
    "preferences-draft.json",
}
PREFERENCE_OUTPUTS = {"preferences-draft.json", "preferences.json"}
# Final documents a same-route rerun may replace, keyed to the phase that owns them. Replacement
# also needs the exact prior SHA-256 and phase authority (see WriteAudit._replacement_authorized).
REPLACEABLE_OUTPUTS = {
    "preferences.json": "clarify",
    "aws-design-ai.json": "design",
    "estimation-ai.json": "estimate",
    "DECISION.md": "estimate",
    "decision-report.html": "estimate",
    "generation-ai.json": "generate",
    "MIGRATION_GUIDE.md": "generate",
    "README.md": "generate",
    "migration-report.html": "generate",
}
DELEGATED_ROUTES = ("ai_only", "combined")
TRANSIENT_OUTPUTS = {".anthropic-admin-env", ".openai-admin-env", ".openrouter-key-env"}
CAPTURE_PREFIXES = ("openai-capture/", "anthropic-capture/", "openrouter-capture/")
GENERATED_PREFIX = "ai-migration/"


def resolve_region(compliance: list[str], explicit_regions: list[str], cross_cloud: str,
                   delegated_region: str | None = None) -> dict[str, Any]:
    values = sorted(set(explicit_regions))
    compliance_set = set(compliance)
    if "fedramp" in compliance_set:
        return {"region": "us-gov-west-1", "source": "compliance"}
    if "gdpr" in compliance_set:
        return {"region": "eu-west-1", "source": "compliance"}
    if "hipaa" in compliance_set:
        return {"region": "us-east-1", "source": "compliance"}
    if delegated_region:
        return {"region": delegated_region, "source": "delegated_source_region"}
    if len(values) > 1:
        return {"region": None, "source": "clarify_required", "candidates": values}
    if values:
        return {"region": values[0], "source": "application_region"}
    if cross_cloud == "latency-critical":
        return {"region": None, "source": "clarify_required", "candidates": []}
    return {"region": "us-east-1", "source": "fallback"}


def route(mode: str, has_ai_profile: bool, source_containing: bool,
          iac_route_signal: bool = False) -> dict[str, Any]:
    if mode not in {"direct", "delegated"}:
        raise ValueError("mode_invalid")
    active = has_ai_profile or iac_route_signal
    return {
        "mode": mode,
        "scan_neutral_source": source_containing,
        "ai_route_active": active,
        "owning_skill": OWNER_DIRECT if mode == "direct" else OWNER_DELEGATED,
        "telemetry_owner": None if mode == "direct" else GCP_OWNER,
    }


def state_decision(state: dict[str, Any], execute_requested: bool = False) -> dict[str, Any]:
    if not isinstance(state, dict) or not isinstance(state.get("phases"), dict):
        return {"action": "reconstruct", "phase": "discover", "write_state": False}
    phases = state["phases"]
    dirty = state.get("dirty_state")
    if isinstance(dirty, dict) and dirty.get("phase") == "generate":
        return {"action": "resume_dirty", "phase": "generate", "write_state": False}
    if state.get("stale_downstream"):
        return {"action": "confirm_reentry", "phase": state.get("current_phase"), "write_state": False}
    for phase in PHASES[:-1]:
        if phases.get(phase) != "completed":
            return {"action": "run", "phase": phase, "write_state": False}
    if phases.get("workshop") == "in_progress":
        return {"action": "resume_workshop", "phase": "workshop", "write_state": False}
    if phases.get("generate") == "completed":
        return {"action": "complete", "phase": None, "write_state": False}
    if state.get("run_mode") == "decide_and_execute" or execute_requested:
        return {"action": "run", "phase": "generate", "write_state": False}
    return {"action": "offer_generate", "phase": None, "write_state": False}


def next_phase(state: dict[str, Any], execute_requested: bool = False) -> str:
    decision = state_decision(state, execute_requested)
    return decision["phase"] or "complete"


def _replaceable_phase(relative: str) -> str | None:
    if relative in REPLACEABLE_OUTPUTS:
        return REPLACEABLE_OUTPUTS[relative]
    if relative.startswith(GENERATED_PREFIX):
        return "generate"
    return None


def _checked_route(mode: str, delegated_route: str | None) -> str | None:
    if delegated_route is None:
        return None
    if mode != "delegated" or delegated_route not in DELEGATED_ROUTES:
        raise ValueError("delegated_route_invalid")
    return delegated_route


def writer(mode: str, artifact: str, delegated_route: str | None = None) -> str:
    # The delegated AI-only route makes BMA the sole preferences writer. Combined
    # delegated preferences stay with the GCP assembler, the default when no route is given.
    if _checked_route(mode, delegated_route) == "ai_only" and artifact in PREFERENCE_OUTPUTS:
        return BMA_OWNER
    try:
        return WRITERS[mode][artifact]
    except KeyError as exc:
        if artifact.startswith(CAPTURE_PREFIXES) or artifact in TRANSIENT_OUTPUTS or artifact.startswith(GENERATED_PREFIX):
            return BMA_OWNER
        raise ValueError("writer_not_registered") from exc


def consent_decision(status: str, requests: int = 0, retry_pending: bool = False,
                     cost: int | float | None = None) -> dict[str, Any]:
    """Normalize provider-capture outcomes without converting unknown cost to zero."""
    if status not in {"declined", "all_failed", "succeeded"}:
        raise ValueError("consent_status_invalid")
    if not isinstance(requests, int) or requests < 0 or not isinstance(retry_pending, bool):
        raise ValueError("consent_request_invalid")
    if cost is not None and (not isinstance(cost, (int, float)) or isinstance(cost, bool)):
        raise ValueError("consent_cost_invalid")
    if status == "declined":
        if requests or retry_pending or cost is not None:
            raise ValueError("consent_decline_invalid")
        return {"status": status, "requests": 0, "profile_written": False,
                "retry_pending": False, "next": "continue", "cost": None}
    if status == "all_failed":
        if requests == 0 or cost is not None:
            raise ValueError("consent_failure_invalid")
        return {"status": status, "requests": requests, "profile_written": False,
                "retry_pending": retry_pending, "next": "retry" if retry_pending else "continue",
                "cost": None}
    if requests == 0 or retry_pending:
        raise ValueError("consent_success_invalid")
    return {"status": status, "requests": requests, "profile_written": True,
            "retry_pending": False, "next": "continue", "cost": cost}


MODEL_TARGETS = {
    "claude-3-haiku-20240307": ("anthropic.claude-haiku-4-5-20251001-v1:0", "anthropic_sdk", 0.25, 1.25),
    "gpt-4o": ("openai.gpt-6-luna", "direct_api", 0.11, 0.55),
    "gemini-2.5-pro": ("amazon.nova-pro-v1:0", "google_genai_sdk", 0.8, 3.2),
}
# Retirement status is read from the lifecycle registry at run time (references/vendored/ai/
# ai-model-lifecycle.md, its "Verified Active Models" table). Nothing here lists retired models.
LIFECYCLE_REGISTRY_RELATIVE = "references/vendored/ai/ai-model-lifecycle.md"
LIFECYCLE_SECTION = "## Verified Active Models"
# Source model IDs that are real provider model families, so a source with no target mapping can
# stay visible as lifecycle unverified. Anything else (for example "fabricated-model") is rejected.
SOURCE_MODEL_FAMILY = re.compile(r"^(gemini|imagen|embedding|text-embedding|gpt|claude|o[1-9])[a-z0-9.\-]{0,80}$")
LIFECYCLE_UNVERIFIED_LABEL = "lifecycle unverified"
OBSERVED_UNVERIFIED_BASIS = "observed, not priced from registry"
RETIREMENT_UNVERIFIED_NOTE = "retirement status unverified, check provider lifecycle"


def registered_active_models(bma_root: Path) -> frozenset[str]:
    """Model IDs the registry lists as Active. Read on every call; fail closed if unreadable."""
    try:
        text = (bma_root / LIFECYCLE_REGISTRY_RELATIVE).read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("lifecycle_registry_missing") from error
    if LIFECYCLE_SECTION not in text:
        raise ValueError("lifecycle_registry_invalid")
    section = text.split(LIFECYCLE_SECTION, 1)[1].split("\n## ", 1)[0]
    ids = set()
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[1].startswith("`") and cells[1].endswith("`"):
            ids.add(cells[1].strip("`"))
    if not ids:
        raise ValueError("lifecycle_registry_invalid")
    return frozenset(ids)

# #415 is the only AI profile contract BMA accepts. Its vendored copy sits beside this runtime.
AI_PROFILE_SCHEMA_RELATIVE = "references/contracts/ai-workload-profile.schema.json"
# Legacy top-level keys from the pre-#415 GCP-shaped profile, checked in this order.
LEGACY_PROFILE_KEYS = (
    "metadata", "summary", "models", "integration", "infrastructure", "current_costs",
    "detection_signals", "workloads", "agentic_profile", "tool_manifest",
)
LEGACY_SOURCE_KEYS = ("service", "detected_via", "evidence", "model_id", "capabilities_used", "usage_context")
# Temporary sidecar: workloads, agentic_profile, tool_manifest, observed costs, integration context,
# infrastructure, and per-model context have no #415 slot yet. Folding them into #415 under a new schema
# version is a follow-up (tracked against issue #389).
AI_SIDECAR_KEYS = {
    "schema_version", "kind", "workloads", "agentic_profile", "tool_manifest",
    "observed_costs", "integration_context", "infrastructure", "model_context", "profile_origin",
}
AI_SIDECAR_KIND = "BMA_GCP_AI_SIDECAR"


class BmaLegacyProfileRejected(ValueError):
    """Named rejection for legacy-shaped AI profile input. BMA has no legacy path."""


_JSON_TYPES = {"object": dict, "array": list, "string": str}


def _schema_errors(schema: dict[str, Any], value: Any, root: dict[str, Any], path: str = "$") -> list[str]:
    """Stdlib subset of Draft-07 covering the keywords used by #415 (no third-party dependency)."""
    if "$ref" in schema:
        return _schema_errors(root["definitions"][schema["$ref"].split("/")[-1]], value, root, path)
    errors: list[str] = []
    if "type" in schema and not isinstance(value, _JSON_TYPES[schema["type"]]):
        return [f"{path}: type"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: const")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: enum")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: pattern")
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: minLength")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        errors += [f"{path}: missing {key}" for key in schema.get("required", []) if key not in value]
        if schema.get("additionalProperties") is False:
            errors += [f"{path}.{key}: additional" for key in value if key not in properties]
        for key, sub in properties.items():
            if key in value:
                errors += _schema_errors(sub, value[key], root, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: minItems")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: maxItems")
        if schema.get("uniqueItems"):
            canon = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(canon)) != len(canon):
                errors.append(f"{path}: uniqueItems")
        for index, item in enumerate(value):
            if "items" in schema:
                errors += _schema_errors(schema["items"], item, root, f"{path}[{index}]")
    if "oneOf" in schema:
        matches = [branch for branch in schema["oneOf"] if not _schema_errors(branch, value, root, path)]
        if len(matches) != 1:
            errors.append(f"{path}: oneOf")
    return errors


def _legacy_profile_field(value: dict[str, Any]) -> str | None:
    for key in LEGACY_PROFILE_KEYS:
        if key in value:
            return key
    for index, source in enumerate(value.get("ai_sources", []) if isinstance(value.get("ai_sources"), list) else []):
        if isinstance(source, dict):
            for key in LEGACY_SOURCE_KEYS:
                if key in source:
                    return f"ai_sources[{index}].{key}"
    return None


def validate_ai_workload_profile(value: Any, bma_root: Path) -> dict[str, Any]:
    """Accept only a #415 ai-workload-profile document; reject legacy shape by name."""
    if not isinstance(value, dict):
        raise ValueError("ai_profile_invalid: json object required")
    legacy = _legacy_profile_field(value)
    if legacy is not None:
        raise BmaLegacyProfileRejected(
            f"BmaLegacyProfileRejected: legacy field '{legacy}' found. BMA input must be the #415 "
            "ai-workload-profile format (schema_version \"1.0\", ai_sources, gateways)."
        )
    schema = json.loads((bma_root / AI_PROFILE_SCHEMA_RELATIVE).read_text(encoding="utf-8"))
    errors = _schema_errors(schema, value, schema)
    if errors:
        raise ValueError(f"ai_profile_schema_invalid: {errors[0]}")
    keys: set[tuple[str, str]] = set()
    for source in value["ai_sources"]:
        key = (source["provider"], source["source_service"])
        if key in keys:
            raise ValueError("ai_profile_source_duplicate")
        keys.add(key)
        observed = [item["normalized_model"] for item in source["model_observations"]]
        if sorted(observed) != sorted(source["models"]) or any(
            item["model_family"] not in source["model_families"] for item in source["model_observations"]
        ):
            raise ValueError("ai_profile_observation_mismatch")
        # The mapping never derives "confirmed". The schema still lists it, so reject it here.
        for item in source["model_observations"]:
            if any(entry["confidence"] == "confirmed" for entry in item["evidence"]):
                raise ValueError("ai_profile_confidence_unsupported")
    return {"ok": True, "ai_sources": len(value["ai_sources"]), "gateways": len(value["gateways"])}


def validate_ai_sidecar(value: Any) -> dict[str, Any]:
    """Closed check for the temporary sidecar that carries non-#415 AI context."""
    if not isinstance(value, dict) or set(value) - AI_SIDECAR_KEYS:
        raise ValueError("ai_sidecar_invalid")
    if value.get("schema_version") != 1 or value.get("kind") != AI_SIDECAR_KIND:
        raise ValueError("ai_sidecar_invalid")
    if not isinstance(value.get("workloads"), list):
        raise ValueError("ai_sidecar_invalid")
    for optional, expected in (
        ("agentic_profile", dict), ("tool_manifest", list),
        ("observed_costs", dict), ("integration_context", dict),
        ("infrastructure", list), ("model_context", list), ("profile_origin", dict),
    ):
        if optional in value and not isinstance(value[optional], expected):
            raise ValueError("ai_sidecar_invalid")
    origin = value.get("profile_origin")
    if origin is not None and (set(origin) != {"terraform_primary"} or not isinstance(origin["terraform_primary"], bool)):
        raise ValueError("ai_sidecar_invalid")
    return value


AI_CAPABILITY_MAP_RELATIVE = "references/vendored/ai/sdk-capability-map.json"
_UNCLASSIFIED = {"capability": "unknown", "capability_confidence": "low", "structured_output": False}
# Design-ai.md Part 1: image_generation -> Stability AI. Core is the cost-first default; Ultra is quality-first.
IMAGE_GENERATION_TARGETS = {"core": "stability.stable-image-core-v1:0", "ultra": "stability.stable-image-ultra-v1:0"}
# Design-ai.md Part 1: embedding -> Titan Text Embeddings v2, the default for OpenAI/Azure embedding workloads.
EMBEDDING_TARGET = "amazon.titan-embed-text-v2:0"


def design_target(capability: str, priority: str) -> dict[str, Any]:
    """Design-ai.md Part 1 target for a capability whose routing is deterministic: image_generation and embedding."""
    if capability == "embedding":
        return {"capability": capability, "target_aws_service": None, "target_bedrock_model": EMBEDDING_TARGET}
    if capability != "image_generation":
        raise ValueError("design_target_not_deterministic")
    model = IMAGE_GENERATION_TARGETS["ultra" if priority == "quality" else "core"]
    return {"capability": capability, "target_aws_service": None, "target_bedrock_model": model}


def _call_block(lines: list[str], index: int) -> str:
    """Text of the call that starts on lines[index], through its matching closing parenthesis."""
    text = "\n".join(lines[index:])
    depth = 0
    for position, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[: position + 1]
    return text


def classify_ai_call(source: Path, line: int, model_id: str, method: str, capability_map: Path) -> dict[str, Any]:
    """Discover Step 5B.2-5B.4 for one call site. Image output is checked before structured output and text."""
    cmap = json.loads(capability_map.read_text(encoding="utf-8"))
    if method not in cmap["entries"]:
        return dict(_UNCLASSIFIED)
    if method not in cmap["structured_output_trio"]:
        return {"capability": cmap["entries"][method], "capability_confidence": "high", "structured_output": False}
    lines = source.read_text(encoding="utf-8").splitlines()
    if not 1 <= line <= len(lines):
        raise ValueError("call_line_out_of_range")
    block = _call_block(lines, line - 1)
    if any(token in block for token in cmap["image_output_indicators"]) or any(
        pattern in model_id for pattern in cmap["image_output_model_patterns"]
    ):
        return {"capability": "image_generation", "capability_confidence": "high", "structured_output": False}
    if any(re.search(r"\b" + re.escape(ind) + r"\b", block) for ind in cmap["structured_output_indicators"]):
        return {"capability": "structured_output", "capability_confidence": "high", "structured_output": True}
    return {"capability": "text_generation", "capability_confidence": "medium", "structured_output": False}


GENERATED_FILES = {
    "anthropic_sdk": ["ai-migration/anthropic-adapter.ts"],
    "direct_api": ["ai-migration/bedrock-client.py"],
    "google_genai_sdk": ["ai-migration/gemini-adapter.py"],
    "vertex_adapter": ["ai-migration/vertex-adapter.py"],
    "openrouter_byok": ["ai-migration/openrouter-config.json", "ai-migration/model-map.json"],
}
REPORT_SCOPES = {
    "none": [],
    "decision": ["DECISION.md", "decision-report.html"],
    "full": ["DECISION.md", "decision-report.html", "MIGRATION_GUIDE.md", "README.md", "migration-report.html"],
    "migration": ["MIGRATION_GUIDE.md", "README.md", "migration-report.html"],
}


def _capture_outcome(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) not in (
        {"decision"}, {"decision", "attempts", "retry_pending", "observed_cost"},
    ):
        raise ValueError("trace_capture_invalid")
    if value["decision"] == "declined":
        return consent_decision("declined")
    attempts = value.get("attempts")
    retry_pending = value.get("retry_pending")
    if (value["decision"] != "approved" or not isinstance(attempts, list)
            or not attempts or not all(isinstance(item, bool) for item in attempts)
            or not isinstance(retry_pending, bool)):
        raise ValueError("trace_capture_invalid")
    succeeded = any(attempts)
    cost = value.get("observed_cost") if succeeded else None
    return consent_decision(
        "succeeded" if succeeded else "all_failed",
        requests=len(attempts), retry_pending=retry_pending, cost=cost,
    )


def semantic_trace(request: dict[str, Any]) -> dict[str, Any]:
    """Derive cross-phase outcomes under the following known limitation.

    The equivalence harness carries its own copy of model-mapping, pricing, generated-file, and report-section rules. The Markdown phase files the agent executes do not read those tables. The harness therefore proves the extracted runtime matches the selected base as of this change, but will NOT detect a future edit to the Markdown that changes mappings, prices, or report composition. Reviewers must check such edits by hand until the tables are moved into shared data files consumed by both (tracked as a follow-up to issue #389).
    """
    required = {
        "schema_version", "mode", "source_containing", "has_ai_profile",
        "iac_route_signal", "source_evidence", "state", "user_decisions",
        "capture_observations",
    }
    if not required <= set(request) <= required | {"delegated_route"} or request["schema_version"] != 2:
        raise ValueError("trace_request_invalid")
    mode = request["mode"]
    delegated_route = _checked_route(
        mode, request.get("delegated_route", "combined" if mode == "delegated" else None)
    )
    route_result = route(
        mode, request["has_ai_profile"], request["source_containing"],
        request["iac_route_signal"],
    )
    decisions = request["user_decisions"]
    if not isinstance(decisions, dict) or set(decisions) != {
        "execute_requested", "generate", "include_rollback", "report_scope"
    } or not all(isinstance(decisions[key], bool) for key in (
        "execute_requested", "generate", "include_rollback"
    )) or decisions["report_scope"] not in REPORT_SCOPES:
        raise ValueError("trace_decisions_invalid")
    evidence = request["source_evidence"]
    if not isinstance(evidence, list):
        raise ValueError("trace_request_invalid")
    registered = registered_active_models(Path(__file__).resolve().parents[1])
    associations = []
    mappings = []
    source_keys: set[tuple[str, str, str | None, str]] = set()
    source_costs = []
    target_costs = []
    migration_paths = []
    for source_order, row in enumerate(evidence):
        if not isinstance(row, dict) or set(row) != {
            "provider", "source_service", "gateway", "models", "call_sites",
            "observed_monthly_cost", "monthly_input_tokens", "monthly_output_tokens",
        }:
            raise ValueError("trace_source_invalid")
        models = row["models"]
        call_sites = row["call_sites"]
        if not isinstance(models, list) or not models or len(models) != len(set(models)):
            raise ValueError("trace_source_invalid")
        if not isinstance(call_sites, list):
            raise ValueError("trace_source_invalid")
        pairs = []
        for site in call_sites:
            if not isinstance(site, dict) or set(site) != {"file", "line"}:
                raise ValueError("trace_source_invalid")
            pair = (site["file"], site["line"])
            if (not isinstance(pair[0], str) or not pair[0] or pair[0].startswith(("/", "../"))
                    or not isinstance(pair[1], int) or pair[1] < 0):
                raise ValueError("trace_source_invalid")
            pairs.append(pair)
        if len(pairs) != len(set(pairs)):
            raise ValueError("trace_source_invalid")
        observed_cost = row["observed_monthly_cost"]
        if observed_cost is not None and (not isinstance(observed_cost, (int, float)) or isinstance(observed_cost, bool)):
            raise ValueError("trace_source_invalid")
        source_costs.append(observed_cost)
        token_values = (row["monthly_input_tokens"], row["monthly_output_tokens"])
        if any(value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0) for value in token_values):
            raise ValueError("trace_source_invalid")
        for model in models:
            source_key = (row["provider"], row["source_service"], row["gateway"], model)
            known_source = model in MODEL_TARGETS or (isinstance(model, str) and SOURCE_MODEL_FAMILY.match(model))
            if not isinstance(model, str) or source_key in source_keys:
                raise ValueError("trace_source_invalid")
            if not known_source:
                # Name the unrecognized ID so the rejection is never a silent, unexplained stop.
                raise ValueError(f"trace_source_invalid: source_model_unrecognized: {model}")
            source_keys.add(source_key)
            associations.append({
                "source_order": source_order, "provider": row["provider"],
                "source_service": row["source_service"], "gateway": row["gateway"],
                "model": model, "call_sites": call_sites,
                "lifecycle_label": LIFECYCLE_UNVERIFIED_LABEL if model not in registered else "lifecycle registered",
            })
            if model not in MODEL_TARGETS:
                # A real source model with no target mapping: visible, unpriced, never invented.
                mappings.append({
                    "source_model": model, "target_model": None, "migration_path": None,
                    "retirement_status": "unverified", "note": RETIREMENT_UNVERIFIED_NOTE,
                })
                target_costs.append(None)
                continue
            target, migration_path, input_rate, output_rate = MODEL_TARGETS[model]
            if row["gateway"] == "openrouter":
                migration_path = "openrouter_byok"
            elif row["source_service"] == "vertex_ai":
                migration_path = "vertex_adapter"
            # The target name stays visible. Its price and retirement_status come from the target's own
            # registry row: priced only when the target is listed as Active, otherwise unverified and unpriced.
            # The source's lifecycle is reported separately (associations[].lifecycle_label) and controls
            # only the baseline label and whether a delta is built.
            target_active = target in registered
            target_status = "active" if target_active else "unverified"
            mappings.append({
                "source_model": model, "target_model": target,
                "migration_path": migration_path,
                "retirement_status": target_status,
                **({"note": RETIREMENT_UNVERIFIED_NOTE} if not target_active else {}),
            })
            migration_paths.append(migration_path)
            if None in token_values or not target_active:
                target_costs.append(None)
            else:
                target_costs.append(round(
                    token_values[0] / 1_000_000 * input_rate
                    + token_values[1] / 1_000_000 * output_rate, 2
                ))
    source_monthly = None if not source_costs or any(value is None for value in source_costs) else round(sum(source_costs), 2)
    target_monthly = None if not target_costs or any(value is None for value in target_costs) else round(sum(target_costs), 2)
    source_label = None if not associations else (
        LIFECYCLE_UNVERIFIED_LABEL if any(row["lifecycle_label"] == LIFECYCLE_UNVERIFIED_LABEL for row in associations)
        else "lifecycle registered"
    )
    # An unverified source baseline is shown as observed only. A delta built on it would read as a verified comparison.
    source_unverified = source_label == LIFECYCLE_UNVERIFIED_LABEL
    source_basis = None if source_monthly is None else (
        OBSERVED_UNVERIFIED_BASIS if source_unverified else "observed"
    )
    delta = None if source_monthly is None or target_monthly is None or source_unverified else round(
        target_monthly - source_monthly, 2)
    if not route_result["ai_route_active"]:
        pricing_source = "not_applicable" if not request["source_containing"] else "unresolved"
    elif target_monthly is None:
        pricing_source = "unavailable"
    elif source_monthly == 0 and target_monthly == 0:
        pricing_source = "known_zero"
    else:
        pricing_source = "bedrock_cache"
    generation_route = "none"
    generated_files: list[str] = []
    if route_result["ai_route_active"] and decisions["generate"]:
        unique_paths = list(dict.fromkeys(migration_paths))
        if unique_paths:
            generation_route = unique_paths[0] if len(unique_paths) == 1 else "combined"
            for migration_path in unique_paths:
                generated_files.extend(GENERATED_FILES[migration_path])
            if decisions["include_rollback"]:
                generated_files.append("ai-migration/rollback.md")
    report_targets = REPORT_SCOPES[decisions["report_scope"]]
    captures = request["capture_observations"]
    if not isinstance(captures, list):
        raise ValueError("trace_capture_invalid")
    consent_trace = [_capture_outcome(value) for value in captures]
    active_artifacts = []
    if route_result["ai_route_active"]:
        active_artifacts = [
            "ai-workload-profile.json", "preferences.json", "aws-design-ai.json",
            "estimation-ai.json", "generation-ai.json",
        ]
    return {
        "schema_version": 2,
        "route": route_result,
        "associations": associations,
        "design_mappings": mappings,
        "estimate": {
            "source_monthly": source_monthly, "target_monthly": target_monthly,
            "monthly_delta": delta, "pricing_source": pricing_source,
            "source_lifecycle_label": source_label, "source_monthly_basis": source_basis,
            "evidence": {"observed_source_costs": source_costs},
        },
        "generation": {
            "route": generation_route, "files": generated_files,
            "writer": BMA_OWNER if generated_files else None,
        },
        "state_decision": state_decision(request["state"], decisions["execute_requested"]),
        "consent": consent_trace,
        "writers": {artifact: writer(mode, artifact, delegated_route) for artifact in active_artifacts},
        "report_writers": {target: writer(mode, target, delegated_route) for target in report_targets},
    }


def validate_clarify_result(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != {"schema_version", "kind", "constraints", "workloads", "question_metadata"}:
        raise ValueError("clarify_result_schema_invalid")
    if value["schema_version"] != 1 or value["kind"] != "BMA_AI_CLARIFY_RESULT":
        raise ValueError("clarify_result_schema_invalid")
    if not isinstance(value["constraints"], dict) or not isinstance(value["workloads"], list) or not isinstance(value["question_metadata"], dict):
        raise ValueError("clarify_result_schema_invalid")
    ids = [row.get("workload_id") for row in value["workloads"]]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("clarify_result_workload_invalid")
    for row in value["workloads"]:
        sites = row.get("call_sites", [])
        pairs = [(site.get("file"), site.get("line")) for site in sites]
        if any(not file or str(file).startswith(("/", "../")) or not isinstance(line, int) or line < 0 for file, line in pairs):
            raise ValueError("clarify_result_call_site_invalid")
        if len(pairs) != len(set(pairs)):
            raise ValueError("clarify_result_call_site_invalid")
    return value


CONTRIBUTION_KINDS = {
    "DECISION.md": {"callout", "subsection", "table_row"},
    "decision-report.html": {"callout", "subsection", "table_row"},
    "MIGRATION_GUIDE.md": {"callout", "rollback_addition", "step", "subsection", "table_row"},
    "README.md": {"callout", "catalog_row", "subsection", "table_row"},
    "migration-report.html": {"callout", "subsection", "table_row"},
}
CONTRIBUTION_FIELDS = {"id", "bucket", "source_order", "target", "kind", "content", "section"}
SECTION_ID = re.compile(r"^[a-z][a-z0-9-]*$")
ASSEMBLY_FIELDS = {"phase", "target", "contributions", "document", "report_mode"}
HTML_TARGETS = {"decision-report.html": {"decision"}, "migration-report.html": {"full", "ai_only"}}
# Section IDs the validator requires per report mode. Keep in sync with validate-migration-report.py.
DOCUMENT_SECTIONS = {
    "full": [
        "decision-summary", "exec-assumptions", "exec-services", "exec-costs", "exec-timeline",
        "exec-risks", "appendix-services", "appendix-costs", "appendix-steps", "appendix-artifacts",
    ],
    "ai_only": [
        "decision-summary", "exec-assumptions", "exec-risks", "appendix-ai", "appendix-artifacts",
        "appendix-config", "appendix-glossary",
    ],
    "decision": [
        "decision-summary", "exec-assumptions", "exec-services", "exec-costs", "exec-timeline",
        "exec-risks", "decision-cta",
    ],
}
DOCUMENT_ANCHOR = re.compile(r"<!-- bma-contributions:([a-z][a-z0-9-]*) -->")
CONTENT_FIELDS = {"text", "links", "traceability"}
TRACEABILITY_FIELDS = {"provider", "source_service", "model", "call_sites"}
MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]*\]\s*\(")
MARKDOWN_LINK_DEFINITION = re.compile(r"(?m)^[ \t]*\[[^\]\n]+\]:")
MARKDOWN_HEADING = re.compile(
    r"(?m)^[ \t]{0,3}(?:#{1,6}(?:[ \t]|$)|(?:=+|-+)[ \t]*$)"
)
RAW_URL = re.compile(r"(?i)(?:https?://|www\.)")
TRACE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
LINK_LABEL = re.compile(r"^[^<>\[\]\r\n]+$")
HTTPS_LINK = re.compile(r"^https://[^\s/@:?#]+(?::[0-9]+)?(?:/[^\s]*)?$")
FRAGMENT_LINK = re.compile(r"^#[a-z0-9][a-z0-9-]*$")


def _validate_link(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"label", "href"}:
        raise ValueError("contribution_link_invalid")
    label, href = value["label"], value["href"]
    if not isinstance(label, str) or not LINK_LABEL.fullmatch(label):
        raise ValueError("contribution_link_invalid")
    if not isinstance(href, str) or any(character.isspace() for character in href):
        raise ValueError("contribution_link_invalid")
    if FRAGMENT_LINK.fullmatch(href):
        return
    parsed = urlsplit(href)
    if (not HTTPS_LINK.fullmatch(href) or parsed.scheme != "https" or not parsed.netloc
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("contribution_link_invalid")


def _validate_traceability(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != TRACEABILITY_FIELDS:
        raise ValueError("contribution_traceability_invalid")
    if any(not isinstance(value[field], str) or not TRACE_TOKEN.fullmatch(value[field])
           for field in ("provider", "source_service", "model")):
        raise ValueError("contribution_traceability_invalid")
    sites = value["call_sites"]
    if not isinstance(sites, list) or not sites:
        raise ValueError("contribution_traceability_invalid")
    identities = []
    for site in sites:
        if not isinstance(site, dict) or set(site) != {"file", "line"}:
            raise ValueError("contribution_traceability_invalid")
        file, line = site["file"], site["line"]
        if (not isinstance(file, str) or not file or Path(file).is_absolute()
                or ".." in Path(file).parts or Path(file).as_posix() != file
                or not isinstance(line, int) or isinstance(line, bool) or line < 0):
            raise ValueError("contribution_traceability_invalid")
        identities.append((file, line))
    if len(identities) != len(set(identities)):
        raise ValueError("contribution_traceability_invalid")


def _validate_content(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != CONTENT_FIELDS:
        raise ValueError("contribution_content_invalid")
    text, links = value["text"], value["links"]
    if (not isinstance(text, str) or not text or "<" in text or ">" in text
            or MARKDOWN_HEADING.search(text) or MARKDOWN_LINK.search(text)
            or MARKDOWN_LINK_DEFINITION.search(text) or RAW_URL.search(text)
            or any(ord(character) < 32 and character not in "\n\t" for character in text)):
        raise ValueError("contribution_content_invalid")
    if not isinstance(links, list):
        raise ValueError("contribution_link_invalid")
    for link in links:
        _validate_link(link)
    _validate_traceability(value["traceability"])


def order_contributions(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        raise ValueError("contribution_schema_invalid")
    identities = [value.get("id") if isinstance(value, dict) else None for value in values]
    orders = [(value.get("bucket"), value.get("source_order"), value.get("id"))
              if isinstance(value, dict) else (None, None, None) for value in values]
    if any(not isinstance(identity, str) or not identity.startswith("ai.") for identity in identities):
        raise ValueError("contribution_id_invalid")
    if len(identities) != len(set(identities)) or len(orders) != len(set(orders)):
        raise ValueError("contribution_duplicate")
    for value in values:
        if set(value) != CONTRIBUTION_FIELDS:
            raise ValueError("contribution_schema_invalid")
        target = value["target"]
        if (target not in CONTRIBUTION_KINDS or value["kind"] not in CONTRIBUTION_KINDS[target]
                or not isinstance(value["bucket"], int) or isinstance(value["bucket"], bool)
                or not isinstance(value["source_order"], int) or isinstance(value["source_order"], bool)):
            raise ValueError("contribution_schema_invalid")
        if not isinstance(value["section"], str) or not SECTION_ID.fullmatch(value["section"]):
            raise ValueError("contribution_section_invalid")
        _validate_content(value["content"])
    return sorted(values, key=lambda value: (value["bucket"], value["source_order"], value["id"].encode("utf-8")))


def _payload_bytes(payload: Any) -> bytes:
    if isinstance(payload, (dict, list)):
        return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    if isinstance(payload, str):
        return payload.encode()
    raise ValueError("write_payload_invalid")


def _relative_path(relative: str) -> Path:
    if not isinstance(relative, str):
        raise ValueError("write_path_invalid")
    path = Path(relative)
    if not relative or path.is_absolute() or ".." in path.parts or path.as_posix() != relative or "." in path.parts:
        raise ValueError("write_path_invalid")
    return path


def _assert_no_follow(root: Path, path: Path) -> None:
    """Reject every existing symlink component and resolved containment escape."""
    current = root
    for part in path.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError("write_path_invalid")
    try:
        (root / path).resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError("write_path_invalid") from exc


class WriteAudit:
    """Closed one-writer guard with staged, rollback-safe publication."""

    def __init__(self, run_dir: Path, mode: str, scenario: str, delegated_route: str | None = None,
                 state: dict[str, Any] | None = None):
        if mode not in WRITERS or not run_dir.is_dir() or run_dir.is_symlink():
            raise ValueError("write_context_invalid")
        self.run_dir = run_dir.resolve()
        self.mode = mode
        self.scenario = scenario
        self.delegated_route = _checked_route(mode, delegated_route)
        self.state = state if state is not None else {}
        self.operations: list[dict[str, str]] = []
        self._prepared: list[dict[str, Any]] = []
        self._paths: set[str] = set()

    def prepare(self, phase: str, relative: str, payload: Any,
                logical_owner: str | None = None,
                expected_sha256: str | None = None) -> None:
        path = _relative_path(relative)
        if not isinstance(phase, str) or not phase:
            raise ValueError("write_request_invalid")
        selected = writer(self.mode, relative, self.delegated_route)
        if logical_owner is not None and logical_owner != selected:
            raise ValueError("writer_owner_invalid")
        if relative in self._paths:
            raise ValueError("duplicate_final_write")
        _assert_no_follow(self.run_dir, path)
        target = self.run_dir / path
        exists = target.exists()
        mutable = relative in MUTABLE_OUTPUTS or relative.startswith(CAPTURE_PREFIXES) or relative in TRANSIENT_OUTPUTS
        if exists:
            if target.is_dir():
                raise ValueError("duplicate_final_write")
            replaceable = _replaceable_phase(relative)
            if replaceable is not None and expected_sha256 is not None:
                if phase != replaceable:
                    raise ValueError("write_phase_invalid")
                if not self._replacement_authorized(replaceable):
                    raise ValueError("replacement_not_authorized")
                if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
                    raise ValueError("expected_prior_hash_required")
                if hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha256:
                    raise ValueError("expected_prior_hash_mismatch")
            elif replaceable is not None or not mutable:
                raise ValueError("duplicate_final_write")
            else:
                if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
                    raise ValueError("expected_prior_hash_required")
                if hashlib.sha256(target.read_bytes()).hexdigest() != expected_sha256:
                    raise ValueError("expected_prior_hash_mismatch")
        elif expected_sha256 is not None:
            raise ValueError("expected_prior_hash_unexpected")
        data = _payload_bytes(payload)
        self._paths.add(relative)
        self._prepared.append({
            "phase": phase, "relative": relative, "path": path, "target": target,
            "owner": selected, "data": data, "replace": exists,
        })

    def _replacement_authorized(self, owner_phase: str) -> bool:
        """Replacement needs stale downstream state, or no completed phase after the owner."""
        state = self.state
        if not isinstance(state, dict) or not isinstance(state.get("phases"), dict):
            return False
        if state.get("stale_downstream"):
            return True
        later = PHASES[PHASES.index(owner_phase) + 1:]
        return all(state["phases"].get(phase) != "completed" for phase in later)

    def write(self, phase: str, relative: str, payload: Any,
              logical_owner: str | None = None,
              expected_sha256: str | None = None) -> None:
        """Compatibility helper: prepare and publish one fully validated row."""
        self.prepare(phase, relative, payload, logical_owner, expected_sha256)
        self.publish()

    def publish(self) -> None:
        if not self._prepared:
            return
        stage = Path(tempfile.mkdtemp(prefix=".bma-stage-", dir=self.run_dir))
        backups = stage / "backups"
        created_dirs: list[Path] = []
        published: list[dict[str, Any]] = []
        try:
            staged_files: list[Path] = []
            for index, item in enumerate(self._prepared):
                staged = stage / f"payload-{index}"
                staged.write_bytes(item["data"])
                staged_files.append(staged)
            for item, staged in zip(self._prepared, staged_files):
                _assert_no_follow(self.run_dir, item["path"])
                parent = item["target"].parent
                missing: list[Path] = []
                cursor = parent
                while cursor != self.run_dir and not cursor.exists():
                    missing.append(cursor)
                    cursor = cursor.parent
                _assert_no_follow(self.run_dir, item["path"].parent)
                for directory in reversed(missing):
                    directory.mkdir()
                    created_dirs.append(directory)
                _assert_no_follow(self.run_dir, item["path"])
                backup = None
                if item["replace"]:
                    backups.mkdir(exist_ok=True)
                    backup = backups / f"original-{len(published)}"
                    os.replace(item["target"], backup)
                try:
                    os.replace(staged, item["target"])
                except Exception:
                    if backup is not None and backup.exists():
                        os.replace(backup, item["target"])
                    raise
                published.append({**item, "backup": backup})
            self.operations.extend({
                "scenario": self.scenario, "phase": item["phase"],
                "logical_owner": item["owner"], "path": item["relative"],
                "operation": "write", "sha256": hashlib.sha256(item["data"]).hexdigest(),
            } for item in self._prepared)
            self._prepared = []
        except Exception:
            for item in reversed(published):
                try:
                    if item["target"].exists() and not item["target"].is_symlink():
                        item["target"].unlink()
                    if item["backup"] is not None and item["backup"].exists():
                        os.replace(item["backup"], item["target"])
                except OSError:
                    pass
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def _check_document(target: str, document: Any, report_mode: str | None) -> None:
    """Preflight the controller-supplied complete document before any contribution is placed."""
    if not isinstance(document, str) or not document.strip():
        raise ValueError("document_required")
    if target in HTML_TARGETS:
        if report_mode not in HTML_TARGETS[target]:
            raise ValueError("report_mode_invalid")
        structural = (
            re.match(r"\s*<!doctype html>", document, re.IGNORECASE),
            re.search(r'<html[^>]*\blang="[A-Za-z-]+"', document),
            len(re.findall(r"<h1[\s>]", document)) == 1,
            "<style" in document,
            re.search(r'<nav class="toc"', document),
        )
        if not all(structural):
            raise ValueError("document_structure_invalid")
        for section_id in DOCUMENT_SECTIONS[report_mode]:
            if not re.search(r'<section id="%s"' % re.escape(section_id), document):
                raise ValueError("document_structure_invalid")
    elif report_mode is not None:
        raise ValueError("report_mode_invalid")
    anchors = DOCUMENT_ANCHOR.findall(document)
    if len(anchors) != len(set(anchors)):
        raise ValueError("document_structure_invalid")


def _render_contribution(value: dict[str, Any], html: bool) -> str:
    text = value["content"]["text"]
    links = value["content"]["links"]
    if not html:
        if links:
            text += "\n" + " ".join(f'[{link["label"]}]({link["href"]})' for link in links)
        return text
    # HTML targets get escaped paragraphs only; the runtime never emits table or list markup.
    body = html_escape(text, quote=False)
    if links:
        body += " " + " ".join(
            f'<a href="{html_escape(link["href"])}">{html_escape(link["label"], quote=False)}</a>'
            for link in links
        )
    css = ' class="callout"' if value["kind"] == "callout" else ""
    return f"<p{css}>{body}</p>"


def _assembly_payload(target: str, contributions: list[dict[str, Any]], document: Any,
                      report_mode: str | None = None) -> str:
    ordered = order_contributions(contributions)
    if target not in CONTRIBUTION_KINDS or any(value["target"] != target for value in ordered):
        raise ValueError("contribution_target_invalid")
    _check_document(target, document, report_mode)
    anchors = set(DOCUMENT_ANCHOR.findall(document))
    rows: dict[str, list[str]] = {}
    for value in ordered:
        if value["section"] not in anchors:
            raise ValueError("contribution_anchor_missing")
        rows.setdefault(value["section"], []).append(_render_contribution(value, target in HTML_TARGETS))
    # One final writer: each anchor is replaced by its section's rows, or removed when it has none.
    return DOCUMENT_ANCHOR.sub(lambda match: "\n".join(rows.get(match.group(1), [])), document)


def assemble_contributions(audit: WriteAudit, phase: str, target: str,
                           contributions: list[dict[str, Any]], document: Any,
                           report_mode: str | None = None) -> None:
    audit.write(phase, target, _assembly_payload(target, contributions, document, report_mode))


def _generate_owned(value: Any) -> bool:
    """True for a write or assembly that belongs to the Generate phase (phase or target path)."""
    if not isinstance(value, dict):
        return False
    if value.get("phase") == "generate":
        return True
    path = value.get("path", value.get("target"))
    return isinstance(path, str) and _replaceable_phase(path) == "generate"


def _replaces_existing(run_dir: Any, value: Any) -> bool:
    """True when a write or assembly targets a path that already exists under the run directory."""
    if not isinstance(value, dict) or not isinstance(run_dir, str) or not run_dir:
        return False
    relative = value.get("path", value.get("target"))
    if not isinstance(relative, str):
        return False
    try:
        return (Path(run_dir) / _relative_path(relative)).exists()
    except ValueError:
        return False


def execute_contract(request: dict[str, Any]) -> dict[str, Any]:
    """Prevalidate a complete phase request, then publish it rollback-safely."""
    allowed = {"schema_version", "mode", "scenario", "run_dir", "state", "delegated_route",
               "execute_requested", "consent", "clarify_result", "writes", "assemblies"}
    if set(request) - allowed or request.get("schema_version") != 1:
        raise ValueError("execution_request_invalid")
    mode = request.get("mode")
    scenario = request.get("scenario")
    if mode not in WRITERS or not isinstance(scenario, str) or not scenario:
        raise ValueError("execution_request_invalid")
    result: dict[str, Any] = {
        "schema_version": 1,
        "scenario": scenario,
        "mode": mode,
        "state_decision": state_decision(request.get("state", {}), bool(request.get("execute_requested", False))),
        "consent": [],
        "clarify_result": None,
        "operations": [],
    }
    if request.get("clarify_result") is not None:
        result["clarify_result"] = validate_clarify_result(request["clarify_result"])
    consent = request.get("consent", [])
    if not isinstance(consent, list):
        raise ValueError("consent_request_invalid")
    for value in consent:
        if not isinstance(value, dict) or set(value) != {"status", "requests", "retry_pending", "cost"}:
            raise ValueError("consent_request_invalid")
        result["consent"].append(consent_decision(**value))
    writes = request.get("writes", [])
    assemblies = request.get("assemblies", [])
    if not isinstance(writes, list) or not isinstance(assemblies, list):
        raise ValueError("execution_request_invalid")
    if result["state_decision"]["action"] == "offer_generate" and any(
        _generate_owned(value) for value in writes + assemblies
    ):
        raise ValueError("generate_not_requested")
    if result["state_decision"]["action"] == "confirm_reentry" and any(
        _replaces_existing(request.get("run_dir", ""), value) for value in writes + assemblies
    ):
        raise ValueError("reentry_confirmation_required")
    delegated_route = _checked_route(mode, request.get("delegated_route"))
    if mode == "delegated" and delegated_route is None and any(
        isinstance(value, dict) and value.get("path") in PREFERENCE_OUTPUTS for value in writes
    ):
        raise ValueError("delegated_route_required")
    if writes or assemblies:
        run_dir = Path(request.get("run_dir", ""))
        audit = WriteAudit(run_dir, mode, scenario, delegated_route, request.get("state", {}))
        for value in writes:
            if not isinstance(value, dict) or set(value) not in (
                {"phase", "path", "payload", "logical_owner"},
                {"phase", "path", "payload", "logical_owner", "expected_sha256"},
            ):
                raise ValueError("write_request_invalid")
            audit.prepare(value["phase"], value["path"], value["payload"],
                          value["logical_owner"], value.get("expected_sha256"))
        for value in assemblies:
            if isinstance(value, dict) and "document" not in value:
                raise ValueError("document_required")
            if (not isinstance(value, dict) or set(value) - ASSEMBLY_FIELDS
                    or not {"phase", "target", "contributions"} <= set(value)):
                raise ValueError("assembly_request_invalid")
            audit.prepare(value["phase"], value["target"],
                          _assembly_payload(value["target"], value["contributions"],
                                            value["document"], value.get("report_mode")))
        audit.publish()
        result["operations"] = audit.operations
    return result


def closure_preflight(base: Path) -> dict[str, Any]:
    classifier = base / "scripts/bma-route-classifier.py"
    module = types.ModuleType("bma_route_classifier")
    exec(compile(classifier.read_text(encoding="utf-8"), str(classifier), "exec"), module.__dict__)
    events: list[dict[str, str]] = []
    result = module.validate_closure(base, events)
    return {**result, "mutation_count": 0, "audit": events}


def _json_input(path: str) -> dict[str, Any]:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("json_object_required")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    region = commands.add_parser("resolve-region")
    region.add_argument("--compliance", default="none")
    region.add_argument("--regions", default="")
    region.add_argument("--cross-cloud", default="latency-acceptable")
    region.add_argument("--delegated-region")
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--bma-base", type=Path, required=True)
    execute = commands.add_parser("execute")
    execute.add_argument("--request", required=True, help="JSON request path, or - for stdin")
    trace = commands.add_parser("trace")
    trace.add_argument("--request", required=True, help="Raw semantic-trace request path, or - for stdin")
    validate = commands.add_parser("validate-profile", help="Gate every AI phase: #415 profile, optional sidecar")
    validate.add_argument("--profile", type=Path, required=True)
    validate.add_argument("--sidecar", type=Path)
    classify = commands.add_parser("classify-ai-call", help="Discover Step 5B capability for one AI call site")
    classify.add_argument("--source", type=Path, required=True)
    classify.add_argument("--line", type=int, required=True)
    classify.add_argument("--model", required=True)
    classify.add_argument("--method", required=True)
    target = commands.add_parser("design-target", help="Design Part 1 target for a deterministic capability")
    target.add_argument("--capability", required=True)
    target.add_argument("--priority", default="balanced")
    args = parser.parse_args()
    if args.command == "design-target":
        try:
            output = design_target(args.capability, args.priority)
        except ValueError as exc:
            print(json.dumps({"error": "ValueError", "message": str(exc)}, sort_keys=True), file=sys.stderr)
            return 1
        print(json.dumps(output, sort_keys=True))
        return 0
    if args.command == "validate-profile":
        try:
            output = validate_ai_workload_profile(
                json.loads(args.profile.read_text(encoding="utf-8")), Path(__file__).resolve().parents[1]
            )
            if args.sidecar is not None:
                validate_ai_sidecar(json.loads(args.sidecar.read_text(encoding="utf-8")))
        except ValueError as exc:
            error = "BmaLegacyProfileRejected" if isinstance(exc, BmaLegacyProfileRejected) else "ValueError"
            print(json.dumps({"error": error, "message": str(exc)}, sort_keys=True), file=sys.stderr)
            return 1
        print(json.dumps(output, sort_keys=True))
        return 0
    if args.command == "resolve-region":
        output = resolve_region(args.compliance.split(","), [x for x in args.regions.split(",") if x], args.cross_cloud, args.delegated_region)
    elif args.command == "preflight":
        output = closure_preflight(args.bma_base)
    elif args.command == "trace":
        output = semantic_trace(_json_input(args.request))
    elif args.command == "classify-ai-call":
        output = classify_ai_call(args.source, args.line, args.model, args.method,
                                  Path(__file__).resolve().parents[1] / AI_CAPABILITY_MAP_RELATIVE)
    else:
        output = execute_contract(_json_input(args.request))
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
