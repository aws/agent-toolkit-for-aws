#!/usr/bin/env python3
"""Validate a provider-neutral ai-workload-profile.json before any phase reads it."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL_ROOT / "references" / "contracts" / "ai-workload-profile.schema.json"

# Top-level keys of the GCP-shaped profile (gcp-to-aws schema-discover-ai.md); none exist in the neutral contract.
LEGACY_TOP_LEVEL_KEYS = (
    "metadata", "summary", "models", "integration", "infrastructure", "current_costs",
    "detection_signals", "workloads", "agentic_profile", "tool_manifest",
)
LEGACY_SOURCE_KEYS = ("model_id", "service", "detected_via", "capabilities_used", "usage_context")

_JSON_TYPES = {"object": dict, "array": list, "string": str}


class ProfileRejected(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _schema_errors(schema: dict, value: Any, root: dict, path: str = "$") -> list[str]:
    if "$ref" in schema:
        return _schema_errors(root["definitions"][schema["$ref"].rsplit("/", 1)[-1]], value, root, path)
    if "type" in schema and not isinstance(value, _JSON_TYPES[schema["type"]]):
        return [f"{path}: expected {schema['type']}"]
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        errors += [f"{path}: missing required {key!r}" for key in schema.get("required", []) if key not in value]
        if schema.get("additionalProperties") is False:
            errors += [f"{path}: unexpected key {key!r}" for key in value if key not in properties]
        for key, sub in properties.items():
            if key in value:
                errors += _schema_errors(sub, value[key], root, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            canonical = [json.dumps(item, sort_keys=True) for item in value]
            if len(set(canonical)) != len(canonical):
                errors.append(f"{path}: items are not unique")
        if "items" in schema:
            for index, item in enumerate(value):
                errors += _schema_errors(schema["items"], item, root, f"{path}[{index}]")
    if "oneOf" in schema:
        matches = sum(1 for branch in schema["oneOf"] if not _schema_errors(branch, value, root, path))
        if matches != 1:
            errors.append(f"{path}: matches {matches} oneOf branches, expected exactly 1")
    return errors


def _legacy_field(profile: dict) -> str | None:
    for key in LEGACY_TOP_LEVEL_KEYS:
        if key in profile:
            return key
    for index, source in enumerate(_items(profile, "ai_sources")):
        for key in LEGACY_SOURCE_KEYS:
            if isinstance(source, dict) and key in source:
                return f"ai_sources[{index}].{key}"
    return None


def _items(container: Any, key: str) -> list:
    value = container.get(key) if isinstance(container, dict) else None
    return value if isinstance(value, list) else []


def _confirmed_confidence_path(profile: dict) -> str | None:
    for i, source in enumerate(_items(profile, "ai_sources")):
        for j, observation in enumerate(_items(source, "model_observations")):
            for k, entry in enumerate(_items(observation, "evidence")):
                if isinstance(entry, dict) and entry.get("confidence") == "confirmed":
                    return f"ai_sources[{i}].model_observations[{j}].evidence[{k}].confidence"
    return None


def _check_semantics(profile: dict) -> None:
    sources: dict[tuple[str, str], dict] = {}
    for source in profile["ai_sources"]:
        key = (source["provider"], source["source_service"])
        if key in sources:
            raise ProfileRejected("duplicate_ai_source", f"{key[0]}/{key[1]} appears more than once")
        sources[key] = source
        observed = {item["normalized_model"] for item in source["model_observations"]}
        if len(observed) != len(source["model_observations"]) or observed != set(source["models"]):
            raise ProfileRejected(
                "observation_mismatch",
                f"{key[0]}/{key[1]}: model_observations {sorted(observed)} must match models {sorted(source['models'])} one-to-one",
            )
        for item in source["model_observations"]:
            if item["model_family"] not in source["model_families"]:
                raise ProfileRejected(
                    "observation_family_mismatch",
                    f"{key[0]}/{key[1]}: {item['normalized_model']} has family {item['model_family']!r} not in model_families",
                )
            for entry in item["evidence"]:
                if entry["provenance"] == "user_confirmed" and entry["confidence"] != "high":
                    raise ProfileRejected(
                        "user_confirmed_requires_high",
                        f"{key[0]}/{key[1]}: {item['normalized_model']} user_confirmed evidence must have confidence 'high'",
                    )

    for gateway in profile["gateways"]:
        resolved: set[tuple[str, str]] = set()
        for upstream in gateway["upstreams"]:
            if "source_service" in upstream:
                source = sources.get((upstream["provider"], upstream["source_service"]))
                if source is None:
                    raise ProfileRejected(
                        "unmatched_gateway_upstream",
                        f"{gateway['product']}: upstream {upstream['provider']}/{upstream['source_service']} has no ai_sources entry",
                    )
            else:
                candidates = [s for (provider, _), s in sources.items() if provider == upstream["provider"]]
                if len(candidates) != 1:
                    raise ProfileRejected(
                        "unmatched_gateway_upstream",
                        f"{gateway['product']}: service-less upstream {upstream['provider']} matches {len(candidates)} ai_sources entries, expected 1",
                    )
                source = candidates[0]
            key = (source["provider"], source["source_service"])
            if key in resolved:
                raise ProfileRejected("duplicate_gateway_upstream", f"{gateway['product']}: {key[0]}/{key[1]} appears more than once")
            resolved.add(key)

            families = {f["family"] for f in upstream["model_families"]}
            if len(families) != len(upstream["model_families"]) or families != set(source["model_families"]):
                raise ProfileRejected(
                    "upstream_family_mismatch",
                    f"{gateway['product']}: {key[0]}/{key[1]} families {sorted(families)} must match {sorted(source['model_families'])}",
                )
            models: set[str] = set()
            for family in upstream["model_families"]:
                if family["model_evidence"] != source["model_evidence"]:
                    raise ProfileRejected(
                        "upstream_family_mismatch",
                        f"{gateway['product']}: {key[0]}/{key[1]} family {family['family']} evidence differs from the source",
                    )
                models.update(family["models"])
            if models != set(source["models"]):
                raise ProfileRejected(
                    "upstream_models_mismatch",
                    f"{gateway['product']}: {key[0]}/{key[1]} models {sorted(models)} must match {sorted(source['models'])}",
                )


def _summary(profile: dict) -> dict:
    via: dict[tuple[str, str], list[str]] = {}
    sources_by_provider: dict[str, list[tuple[str, str]]] = {}
    for source in profile["ai_sources"]:
        sources_by_provider.setdefault(source["provider"], []).append((source["provider"], source["source_service"]))
    for gateway in profile["gateways"]:
        for upstream in gateway["upstreams"]:
            key = (upstream["provider"], upstream["source_service"]) if "source_service" in upstream else sources_by_provider[upstream["provider"]][0]
            via.setdefault(key, []).append(gateway["product"])

    ai_sources = []
    all_high = bool(profile["ai_sources"])
    for source in profile["ai_sources"]:
        key = (source["provider"], source["source_service"])
        models = []
        for item in source["model_observations"]:
            high = any(entry["confidence"] == "high" for entry in item["evidence"])
            all_high = all_high and high
            models.append({"model": item["normalized_model"], "raw_model": item["raw_model"], "high_confidence": high})
        all_high = all_high and source["model_evidence"] == "observed"
        ai_sources.append({
            "provider": source["provider"],
            "source_service": source["source_service"],
            "model_evidence": source["model_evidence"],
            "models": models,
            "via_gateways": sorted(set(via.get(key, []))),
        })
    return {
        "ok": True,
        "schema_version": profile["schema_version"],
        "ai_sources": ai_sources,
        "gateways": [
            {"product": g["product"], "type": g["type"], "upstream_evidence": g["upstream_evidence"]}
            for g in profile["gateways"]
        ],
        "models_extractable": all_high,
    }


def validate_profile(profile: Any, schema: dict | None = None) -> dict:
    if not isinstance(profile, dict):
        raise ProfileRejected("not_an_object", "the profile must be a JSON object")
    legacy = _legacy_field(profile)
    if legacy is not None:
        raise ProfileRejected(
            "legacy_profile_rejected",
            f"field {legacy!r} belongs to the GCP-shaped profile; supply the neutral contract "
            "(schema_version \"1.0\", ai_sources[], gateways[])",
        )
    confirmed = _confirmed_confidence_path(profile)
    if confirmed is not None:
        raise ProfileRejected(
            "confirmed_confidence_rejected",
            f"{confirmed} is 'confirmed'; record user confirmation as provenance 'user_confirmed' with confidence 'high'",
        )
    schema = schema if schema is not None else json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = _schema_errors(schema, profile, schema)
    if errors:
        raise ProfileRejected("schema_violation", "; ".join(errors[:5]))
    _check_semantics(profile)
    return _summary(profile)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path, help="path to ai-workload-profile.json")
    args = parser.parse_args(argv)
    try:
        try:
            profile = json.loads(args.profile.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ProfileRejected("not_found", str(args.profile))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProfileRejected("invalid_json", str(exc))
        except OSError as exc:
            raise ProfileRejected("not_readable", str(exc))
        result = validate_profile(profile)
    except ProfileRejected as exc:
        print(json.dumps({"ok": False, "error": exc.code, "detail": exc.detail}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
