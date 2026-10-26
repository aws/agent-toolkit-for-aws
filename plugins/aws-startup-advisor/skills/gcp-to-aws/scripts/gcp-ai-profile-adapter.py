#!/usr/bin/env python3
"""Deterministic GCP boundary adapter: legacy GCP-shaped AI profile -> #415 ai-workload-profile.

The mapping table is documented in references/shared/gcp-ai-profile-415-mapping.md. The output
is validated against the vendored copy of the #415 schema (references/contracts/). Anything the
mapping cannot represent raises GcpProfileNotRepresentable and nothing is written. BMA never
imports or invokes this module.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "references/contracts/ai-workload-profile.schema.json"
GATEWAY_SERVICE = "openrouter_api"
SERVICE_SOURCES = {
    "vertex_ai_generative": ("google", "vertex_ai"),
    "vertex_ai_embeddings": ("google", "vertex_ai"),
    "openai_api": ("openai", "openai_api"),
    "azure_openai": ("openai", "azure_openai"),
    "anthropic_api": ("anthropic", "anthropic_api"),
}
AI_SOURCE_PROVIDER = {"gemini": "google", "openai": "openai", "anthropic": "anthropic"}
AI_SOURCE_SERVICE = {"gemini": "vertex_ai", "openai": "openai_api", "anthropic": "anthropic_api"}
AI_SOURCE_FAMILY = {"gemini": "gemini", "openai": "gpt", "anthropic": "claude"}
UPSTREAM_PREFIX = {
    "anthropic": ("anthropic", "anthropic_api"),
    "openai": ("openai", "openai_api"),
    "google": ("google", "vertex_ai"),
}
FAMILY_PREFIXES = (("claude", "claude"), ("gemini", "gemini"), ("gpt", "gpt"), ("o1", "gpt"), ("o3", "gpt"), ("text-embedding", "embedding"))
PROVENANCE = {"code": "code", "terraform": "iac", "live_gcloud": "live_api", "user_confirmed": "user_confirmed", "user": "user_confirmed"}
NORMALIZED_MODEL = re.compile(r"^(?!(?:both|unknown)$)[a-z0-9][a-z0-9._:/-]*$")
SIDECAR_KIND = "BMA_GCP_AI_SIDECAR"
# Legacy integration keys carried into the sidecar integration_context. Other keys are not carried.
SIDECAR_INTEGRATION_KEYS = ("pattern", "primary_sdk", "frameworks", "languages", "capabilities_summary")
MODEL_CONTEXT_KEYS = ("service", "model_id", "capabilities_used", "usage_context")


class GcpProfileNotRepresentable(ValueError):
    """Named fail-closed error. Carries the legacy field path that could not be represented."""

    def __init__(self, code: str, field_path: str, detail: str) -> None:
        self.code = code
        self.field_path = field_path
        super().__init__(f"GcpProfileNotRepresentable: {code} at {field_path}: {detail}")


def _fail(code: str, field_path: str, detail: str) -> GcpProfileNotRepresentable:
    return GcpProfileNotRepresentable(code, field_path, detail)


def _model_identity(model_id: Any, field_path: str) -> tuple[str, str]:
    """Return (normalized_model, model_family) or raise. Normalized model is the lowercased id."""
    if not isinstance(model_id, str) or not model_id:
        raise _fail("LEGACY_MODEL_ID_INVALID", field_path, "model_id must be a non-empty string")
    normalized = model_id.lower()
    if not NORMALIZED_MODEL.search(normalized):
        raise _fail("LEGACY_MODEL_ID_INVALID", field_path, f"{model_id!r} does not match the #415 normalizedModel pattern")
    for prefix, family in FAMILY_PREFIXES:
        if normalized.startswith(prefix):
            return normalized, family
    raise _fail("LEGACY_MODEL_FAMILY_UNKNOWN", field_path, f"no model family rule matches {model_id!r}")


def _provenance(method: Any, field_path: str) -> str:
    if isinstance(method, str) and method in PROVENANCE:
        return PROVENANCE[method]
    if isinstance(method, str) and method.endswith("_usage_api"):
        return "usage_api"
    raise _fail("LEGACY_PROVENANCE_UNKNOWN", field_path, f"detection method {method!r} has no #415 provenance")


def _signal_provenance(method: Any) -> str | None:
    if isinstance(method, str) and (method in PROVENANCE or method.endswith("_usage_api")):
        return _provenance(method, "")
    return None


def _band(score: float) -> str:
    if score >= 0.9:
        return "high"
    if score >= 0.7:
        return "medium"
    return "low"


def _detail(legacy_evidence: list[Any], provenance: str) -> str | None:
    for item in legacy_evidence:
        if not isinstance(item, dict) or _signal_provenance(item.get("source")) != provenance:
            continue
        if item.get("file") and item.get("line") is not None:
            return f"{item['file']}:{item['line']}"
        if item.get("resource"):
            return str(item["resource"])
    return None


def _observation_evidence(model: dict[str, Any], signals: list[Any], field_path: str) -> list[dict[str, Any]]:
    detected = model.get("detected_via")
    if not isinstance(detected, list) or not detected:
        raise _fail("LEGACY_PROVENANCE_UNKNOWN", f"{field_path}.detected_via", "detected_via must list at least one method")
    legacy_evidence = model.get("evidence") if isinstance(model.get("evidence"), list) else []
    entries: list[dict[str, Any]] = []
    for method in detected:
        provenance = _provenance(method, f"{field_path}.detected_via")
        scores = [
            item["confidence"] for item in signals
            if isinstance(item, dict) and _signal_provenance(item.get("method")) == provenance
            and isinstance(item.get("confidence"), (int, float)) and not isinstance(item.get("confidence"), bool)
        ]
        if not scores:
            raise _fail("LEGACY_CONFIDENCE_MISSING", f"{field_path}.detected_via", f"no numeric detection_signals confidence for {provenance}")
        entry: dict[str, Any] = {"provenance": provenance, "confidence": _band(max(scores))}
        detail = _detail(legacy_evidence, provenance)
        if detail:
            entry["detail"] = detail
        if entry not in entries:
            entries.append(entry)
    return entries


def _source(provider: str, source_service: str, group: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "provider": provider,
        "source_service": source_service,
        "model_families": sorted({item["model_family"] for item in group.values()}),
        "model_evidence": "observed",
        "models": sorted(group),
        "model_observations": [
            {
                "normalized_model": name,
                "raw_model": item["raw_model"],
                "model_family": item["model_family"],
                "evidence": item["evidence"],
            }
            for name, item in sorted(group.items())
        ],
    }


def _gateways(openrouter: list[tuple[int, dict[str, Any]]], integration: dict[str, Any]) -> list[dict[str, Any]]:
    if not openrouter:
        return []
    if integration.get("gateway_type") != "llm_router":
        raise _fail("LEGACY_GATEWAY_UNREPRESENTABLE", "$.integration.gateway_type", "openrouter models need gateway_type llm_router")
    resolved = True
    upstreams: dict[tuple[str, str], dict[str, set[str]]] = {}
    for index, model in openrouter:
        raw = model.get("model_id")
        prefix, separator, rest = raw.partition("/") if isinstance(raw, str) else ("", "", "")
        if not separator or prefix not in UPSTREAM_PREFIX:
            resolved = False
            continue
        normalized, family = _model_identity(rest, f"$.models[{index}].model_id")
        upstreams.setdefault(UPSTREAM_PREFIX[prefix], {}).setdefault(family, set()).add(normalized)
    entries = []
    if resolved:
        for (provider, source_service), families in sorted(upstreams.items()):
            entries.append({
                "provider": provider,
                "source_service": source_service,
                "model_families": [
                    {"family": family, "model_evidence": "observed", "models": sorted(models)}
                    for family, models in sorted(families.items())
                ],
            })
    return [{
        "product": "openrouter",
        "type": "llm_router",
        "upstream_evidence": "observed" if resolved else "unresolved",
        "upstreams": entries,
    }]


def _schema_errors(schema: dict[str, Any], value: Any, root: dict[str, Any], path: str = "$") -> list[str]:
    """Stdlib subset of Draft-07 covering the keywords #415 uses (no third-party dependency)."""
    if "$ref" in schema:
        return _schema_errors(root["definitions"][schema["$ref"].split("/")[-1]], value, root, path)
    types = {"object": dict, "array": list, "string": str}
    if "type" in schema and not isinstance(value, types[schema["type"]]):
        return [f"{path}: type"]
    errors: list[str] = []
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
        if "items" in schema:
            for index, item in enumerate(value):
                errors += _schema_errors(schema["items"], item, root, f"{path}[{index}]")
    if "oneOf" in schema:
        matches = [branch for branch in schema["oneOf"] if not _schema_errors(branch, value, root, path)]
        if len(matches) != 1:
            errors.append(f"{path}: oneOf")
    return errors


def _check_schema(document: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = _schema_errors(schema, document, schema)
    if errors:
        field_path = errors[0].rsplit(": ", 1)[0]
        raise _fail("SCHEMA_415_INVALID", field_path, f"converted document fails #415 ({errors[0]})")


def convert_legacy_profile(legacy: Any) -> dict[str, Any]:
    """Convert a legacy GCP ai-workload-profile object into a validated #415 document."""
    if (not isinstance(legacy, dict) or "schema_version" in legacy or "ai_sources" in legacy
            or "gateways" in legacy or not isinstance(legacy.get("models"), list)):
        raise _fail("LEGACY_SHAPE_UNEXPECTED", "$", "a legacy GCP profile object with a models array is required")
    summary = legacy.get("summary") if legacy.get("summary") is not None else {}
    integration = legacy.get("integration") if legacy.get("integration") is not None else {}
    signals = legacy.get("detection_signals") if legacy.get("detection_signals") is not None else []
    if not isinstance(summary, dict) or not isinstance(integration, dict) or not isinstance(signals, list):
        raise _fail("LEGACY_SHAPE_UNEXPECTED", "$", "summary and integration must be objects and detection_signals an array")
    ai_source = summary.get("ai_source")

    direct: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    openrouter: list[tuple[int, dict[str, Any]]] = []
    for index, model in enumerate(legacy["models"]):
        field_path = f"$.models[{index}]"
        if not isinstance(model, dict):
            raise _fail("LEGACY_SHAPE_UNEXPECTED", field_path, "model entry must be an object")
        service = model.get("service")
        if service == GATEWAY_SERVICE:
            openrouter.append((index, model))
            continue
        if service not in SERVICE_SOURCES:
            raise _fail("LEGACY_SERVICE_UNMAPPED", f"{field_path}.service", f"service {service!r} has no #415 source mapping")
        provider, source_service = SERVICE_SOURCES[service]
        normalized, family = _model_identity(model.get("model_id"), f"{field_path}.model_id")
        evidence = _observation_evidence(model, signals, field_path)
        observation = direct.setdefault((provider, source_service), {}).setdefault(
            normalized, {"raw_model": model["model_id"], "model_family": family, "evidence": []},
        )
        for entry in evidence:
            if entry not in observation["evidence"]:
                observation["evidence"].append(entry)

    sources = [_source(provider, source_service, group) for (provider, source_service), group in sorted(direct.items())]
    observed_providers = {source["provider"] for source in sources}
    if ai_source is not None and ai_source not in AI_SOURCE_PROVIDER and ai_source not in ("both", "other"):
        raise _fail("LEGACY_AI_SOURCE_UNREPRESENTABLE", "$.summary.ai_source", f"unknown ai_source {ai_source!r}")
    if ai_source in AI_SOURCE_PROVIDER and observed_providers - {AI_SOURCE_PROVIDER[ai_source]}:
        raise _fail(
            "LEGACY_AI_SOURCE_UNREPRESENTABLE", "$.summary.ai_source",
            f"ai_source {ai_source!r} disagrees with model providers {sorted(observed_providers)}",
        )
    if not sources:
        if ai_source in AI_SOURCE_PROVIDER:
            # Declared family with no observed model (IaC-only or unresolved). Kept as not_observed.
            provider = AI_SOURCE_PROVIDER[ai_source]
            sources.append({
                "provider": provider,
                "source_service": AI_SOURCE_SERVICE[ai_source],
                "model_families": [AI_SOURCE_FAMILY[ai_source]],
                "model_evidence": "not_observed",
                "models": [],
                "model_observations": [],
            })
        elif ai_source in ("both", "other"):
            raise _fail("LEGACY_AI_SOURCE_UNREPRESENTABLE", "$.summary.ai_source", f"ai_source {ai_source!r} with no models cannot name a family")
        else:
            raise _fail("LEGACY_IAC_FAMILY_UNKNOWN", "$.summary.ai_source", "no models and no ai_source family to keep")

    document = {
        "schema_version": "1.0",
        "ai_sources": sources,
        "gateways": _gateways(openrouter, integration),
    }
    _check_schema(document)
    return document


def _profile_origin(legacy: dict[str, Any]) -> dict[str, bool] | None:
    """Reduce the legacy origin fields to the one boolean the Terraform-primary wording needs.

    Legacy rule: Terraform is primary when metadata.profile_source is iac_vertex or summary.inferred_from_iac
    is true. Returns None when the legacy profile states neither field.
    """
    metadata = legacy.get("metadata") if isinstance(legacy.get("metadata"), dict) else {}
    summary = legacy.get("summary") if isinstance(legacy.get("summary"), dict) else {}
    if "profile_source" not in metadata and "inferred_from_iac" not in summary:
        return None
    terraform_primary = metadata.get("profile_source") == "iac_vertex" or summary.get("inferred_from_iac") is True
    return {"terraform_primary": terraform_primary}


def convert_legacy_sidecar(legacy: dict[str, Any], existing: Any = None) -> dict[str, Any] | None:
    """Build the GCP-owned temporary sidecar that carries observed spend and integration context.

    Returns None when there is nothing to carry and no sidecar exists. An existing sidecar (for
    example one holding app-code workloads) is kept, and only observed_costs and integration_context
    are replaced by the legacy values.
    """
    if existing is not None and (
        not isinstance(existing, dict) or existing.get("schema_version") != 1
        or existing.get("kind") != SIDECAR_KIND or not isinstance(existing.get("workloads"), list)
    ):
        raise _fail("LEGACY_SIDECAR_INVALID", "$", "existing ai-workload-sidecar.json is not a BMA_GCP_AI_SIDECAR v1 document")
    carried: dict[str, Any] = {}
    costs = legacy.get("current_costs")
    if costs is not None:
        if not isinstance(costs, dict):
            raise _fail("LEGACY_SHAPE_UNEXPECTED", "$.current_costs", "current_costs must be an object")
        carried["observed_costs"] = costs
    integration = legacy.get("integration") if legacy.get("integration") is not None else {}
    context = {key: integration[key] for key in SIDECAR_INTEGRATION_KEYS if key in integration}
    if context:
        carried["integration_context"] = context
    infrastructure = legacy.get("infrastructure")
    if infrastructure is not None:
        if not isinstance(infrastructure, list):
            raise _fail("LEGACY_SHAPE_UNEXPECTED", "$.infrastructure", "infrastructure must be an array")
        if infrastructure:
            carried["infrastructure"] = copy.deepcopy(infrastructure)
    # Per-model capabilities and usage context have no #415 slot. They travel as model_context, keyed by
    # the legacy service and model_id so BMA can match them to the #415 model observations.
    model_context = [
        {key: model[key] for key in MODEL_CONTEXT_KEYS if key in model}
        for model in legacy["models"] if "capabilities_used" in model or "usage_context" in model
    ]
    if model_context:
        carried["model_context"] = model_context
    origin = _profile_origin(legacy)
    if origin is not None:
        carried["profile_origin"] = origin
    if not carried and existing is None:
        return None
    sidecar = copy.deepcopy(existing) if existing is not None else {"schema_version": 1, "kind": SIDECAR_KIND, "workloads": []}
    sidecar.update(carried)
    return sidecar


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    convert = commands.add_parser("convert", help="Convert a legacy profile to a #415 document and its GCP sidecar")
    convert.add_argument("--legacy", type=Path, required=True)
    convert.add_argument("--out", type=Path, required=True)
    convert.add_argument("--sidecar", type=Path, required=True, help=".bma-input/ai-workload-sidecar.json (read if present, then written)")
    args = parser.parse_args(argv)
    try:
        legacy = json.loads(args.legacy.read_text(encoding="utf-8"))
        document = convert_legacy_profile(legacy)
        existing = json.loads(args.sidecar.read_text(encoding="utf-8")) if args.sidecar.exists() else None
        sidecar = convert_legacy_sidecar(legacy, existing)
    except GcpProfileNotRepresentable as exc:
        print(json.dumps({
            "error": "GcpProfileNotRepresentable", "code": exc.code,
            "field_path": exc.field_path, "message": str(exc),
        }, sort_keys=True), file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if sidecar is not None:
        args.sidecar.parent.mkdir(parents=True, exist_ok=True)
        args.sidecar.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": True, "ai_sources": len(document["ai_sources"]), "gateways": len(document["gateways"]),
        "sidecar": sidecar is not None,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
