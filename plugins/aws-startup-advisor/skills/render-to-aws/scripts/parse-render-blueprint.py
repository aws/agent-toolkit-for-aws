#!/usr/bin/env python3
"""Validate and deterministically normalize an untrusted Render Blueprint."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from render_common.atomic import PathBoundaryError, require_contained, write_json_atomic
from render_common.bounds import MAX_SOURCE_BYTES, BlueprintInputError, load_bounded_yaml
from render_common.canonical import (
    byte_sort_key,
    canonical_bytes,
    generated_id,
    nfc,
    sha256_digest,
)
from render_common.classifier import UnsafeIdentityError, safe_identity, safe_literal, sanitize_config
from render_common.plans import normalize_plan, plan_surface

SCHEMA_VERSION = "1.0"
DEFAULT_DISK_SIZE_GB = 10
SKILL_ROOT = Path(__file__).resolve().parent.parent
BLUEPRINT_SCHEMA = SKILL_ROOT / "references/render/render-yaml.schema.json"
BLUEPRINT_SCHEMA_METADATA = SKILL_ROOT / "references/render/render-yaml.schema-metadata.json"
SEMANTIC_SCHEMA = SKILL_ROOT / "references/shared/schema-blueprint-validation.json"


class BlueprintError(ValueError):
    """Stable, non-sensitive parser failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _json_pointer(parts: Iterable[str | int]) -> str:
    def escape(part: str | int) -> str:
        return str(part).replace("~", "~0").replace("/", "~1")

    return "/" + "/".join(escape(part) for part in parts)


def _load_json(path: Path, code: str, maximum: int = 2 * 1024 * 1024) -> Any:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BlueprintError(code) from exc
    if len(data) > maximum:
        raise BlueprintError(code)
    try:
        return json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BlueprintError(code) from exc


def _reject_symlink_chain(path: Path, root: Path, code: str) -> None:
    root_resolved = root.resolve(strict=True)
    candidate = path
    while candidate != root_resolved:
        if candidate.is_symlink():
            raise BlueprintError(code)
        candidate = candidate.parent
        if len(candidate.parts) < len(root_resolved.parts):
            raise BlueprintError(code)


def _read_source(source: Path, workspace_root: Path) -> bytes:
    if not source.is_absolute() or not workspace_root.is_absolute():
        raise BlueprintError("path_not_absolute")
    try:
        root_resolved = workspace_root.resolve(strict=True)
        source_resolved = source.resolve(strict=True)
        source_resolved.relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise BlueprintError("source_outside_workspace") from exc
    _reject_symlink_chain(source, root_resolved, "source_symlink_forbidden")
    if source.is_symlink() or not source.is_file():
        raise BlueprintError("source_not_regular_file")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise BlueprintError("source_open_failed") from exc
    try:
        before = os.fstat(descriptor)
        if before.st_size > MAX_SOURCE_BYTES:
            raise BlueprintError("source_too_large")
        chunks: list[bytes] = []
        remaining = MAX_SOURCE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if len(data) > MAX_SOURCE_BYTES:
        raise BlueprintError("source_too_large")
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise BlueprintError("source_changed_during_read")
    return data


def _load_pinned_schema() -> tuple[dict[str, Any], str]:
    schema = _load_json(BLUEPRINT_SCHEMA, "pinned_schema_invalid", 4 * 1024 * 1024)
    metadata = _load_json(BLUEPRINT_SCHEMA_METADATA, "schema_metadata_invalid")
    if not isinstance(schema, dict) or not isinstance(metadata, dict):
        raise BlueprintError("pinned_schema_invalid")
    actual = hashlib.sha256(BLUEPRINT_SCHEMA.read_bytes()).hexdigest()
    if metadata.get("sha256") != actual:
        raise BlueprintError("pinned_schema_digest_mismatch")
    Draft202012Validator.check_schema(schema)
    return schema, "sha256:" + actual


def validate_structural(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Return stable schema diagnostics without retaining schema prose."""
    schema, _ = _load_pinned_schema()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    diagnostics = []
    for error in sorted(validator.iter_errors(document), key=lambda item: tuple(str(p) for p in item.absolute_path)):
        diagnostics.append(
            {
                "code": f"schema_{error.validator}",
                "path": _json_pointer(error.absolute_path),
            }
        )
    return diagnostics


def _service_kind(service: dict[str, Any]) -> str:
    service_type = service.get("type")
    if service_type == "web" and service.get("runtime") == "static":
        return "render.static_site"
    return {
        "web": "render.web_service",
        "pserv": "render.private_service",
        "worker": "render.background_worker",
        "cron": "render.cron_job",
        "workflow": "render.workflow",
        "keyvalue": "render.key_value",
        "redis": "render.key_value",
    }.get(service_type, "render.unknown")


def _reference_service_kind(service_type: str) -> str:
    return {
        "web": "render.web_service",
        "static": "render.static_site",
        "pserv": "render.private_service",
        "worker": "render.background_worker",
        "cron": "render.cron_job",
        "workflow": "render.workflow",
        "keyvalue": "render.key_value",
        "redis": "render.key_value",
    }.get(service_type, "render.unknown")


def _resource_groups(document: dict[str, Any]) -> Iterable[tuple[dict[str, Any], str, str, list[str | int]]]:
    yield document, "_", "_", []
    ungrouped = document.get("ungrouped")
    if isinstance(ungrouped, dict):
        yield ungrouped, "_", "_", ["ungrouped"]
    for project_index, project in enumerate(document.get("projects", [])):
        project_name = safe_identity(project["name"])
        for environment_index, environment in enumerate(project.get("environments", [])):
            environment_name = safe_identity(environment["name"])
            yield environment, project_name, environment_name, ["projects", project_index, "environments", environment_index]


def _safe_resource_name(value: Any) -> str:
    return safe_identity(value)


def normalize_blueprint(document: dict[str, Any], source_path: str, source_digest: str, schema_digest: str) -> dict[str, Any]:
    resources: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    semantic_errors: list[dict[str, Any]] = []
    semantic_keys: set[tuple[str, str, str, str]] = set()
    ids: set[str] = set()
    by_scope: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    item_to_resource: dict[str, dict[str, Any]] = {}

    def add_resource(
        kind: str,
        name: str,
        project: str,
        environment: str,
        pointer_parts: list[str | int],
        config: dict[str, Any],
        *,
        strict_identity: bool = True,
    ) -> dict[str, Any]:
        normalized_name = _safe_resource_name(name) if strict_identity else safe_literal(nfc(name))
        pointer = _json_pointer(pointer_parts)
        semantic_key = (kind, project, environment, normalized_name)
        if semantic_key in semantic_keys:
            raise BlueprintError("duplicate_normalized_identity")
        semantic_keys.add(semantic_key)
        resource_id = generated_id("rbp", kind, project, environment, pointer, normalized_name)
        if resource_id in ids:
            raise BlueprintError("identity_collision")
        ids.add(resource_id)
        resource = {
            "id": resource_id,
            "kind": kind,
            "name": normalized_name,
            "blueprint_address": pointer,
            "project": None if project == "_" else project,
            "environment": None if environment == "_" else environment,
            "source": "render_blueprint",
            "source_digest": source_digest,
            "confidence": "deterministic",
            "config": sanitize_config(config),
        }
        resources.append(resource)
        by_scope[(kind, normalized_name)].append(resource)
        item_to_resource[pointer] = resource
        return resource

    for project_index, project in enumerate(document.get("projects", [])):
        project_name = safe_identity(project["name"])
        add_resource(
            "render.project",
            project_name,
            project_name,
            "_",
            ["projects", project_index],
            {key: value for key, value in project.items() if key not in {"name", "environments", "buildSources"}},
        )
        for environment_index, environment in enumerate(project.get("environments", [])):
            environment_name = safe_identity(environment["name"])
            add_resource(
                "render.environment",
                environment_name,
                project_name,
                environment_name,
                ["projects", project_index, "environments", environment_index],
                {key: value for key, value in environment.items() if key not in {"name", "services", "databases", "envVarGroups"}},
            )

    build_source_locations: list[tuple[list[Any], str, str, list[str | int]]] = []
    build_source_locations.append((document.get("buildSources", []), "_", "_", ["buildSources"]))
    if isinstance(document.get("ungrouped"), dict):
        build_source_locations.append((document["ungrouped"].get("buildSources", []), "_", "_", ["ungrouped", "buildSources"]))
    for project_index, project in enumerate(document.get("projects", [])):
        build_source_locations.append((project.get("buildSources", []), safe_identity(project["name"]), "_", ["projects", project_index, "buildSources"]))
    for collection, project, environment, base in build_source_locations:
        for index, build_source in enumerate(collection):
            source_resource = add_resource(
                "render.build_source",
                build_source["name"],
                project,
                environment,
                [*base, index],
                {key: value for key, value in build_source.items() if key != "name"},
            )
            artifact_resource = add_resource(
                "render.build_artifact",
                f"{safe_identity(build_source['name'])}-artifact",
                project,
                environment,
                [*base, index, "artifact"],
                {"identity_status": "resolved_at_build", "immutable_promotion_required": True},
            )
            edges.append(_edge("build_source_produces_artifact", source_resource["id"], artifact_resource["id"], {"declared": True}))

    for group, project, environment, base in _resource_groups(document):
        for index, database in enumerate(group.get("databases", [])):
            add_resource(
                "render.postgres",
                database["name"],
                project,
                environment,
                [*base, "databases", index],
                {key: value for key, value in database.items() if key != "name"},
            )
        for index, env_group in enumerate(group.get("envVarGroups", [])):
            add_resource(
                "render.environment_group",
                env_group["name"],
                project,
                environment,
                [*base, "envVarGroups", index],
                {"envVars": env_group.get("envVars", [])},
            )
        for index, service in enumerate(group.get("services", [])):
            pointer_parts = [*base, "services", index]
            kind = _service_kind(service)
            if kind == "render.unknown":
                raise BlueprintError("unsupported_service_type")
            service_config = {key: value for key, value in service.items() if key not in {"name", "disk", "domains", "domain"}}
            if "plan" in service:
                # The raw spelling is preserved; plan_normalized is the shared alias-table result
                # (None when the plan is unknown or unpriced) so Design/Estimate never guess.
                service_config["plan_normalized"] = normalize_plan(plan_surface(kind), service["plan"])
            service_resource = add_resource(
                kind,
                service["name"],
                project,
                environment,
                pointer_parts,
                service_config,
            )
            if isinstance(service.get("disk"), dict):
                disk = service["disk"]
                # The pinned Blueprint schema documents sizeGB as defaulting to 10 when omitted.
                size_gb = disk.get("sizeGB", DEFAULT_DISK_SIZE_GB)
                size_provenance = "declared" if "sizeGB" in disk else "schema_default"
                disk_resource = add_resource(
                    "render.persistent_disk",
                    disk["name"],
                    project,
                    environment,
                    [*pointer_parts, "disk"],
                    {**disk, "sizeGB": size_gb, "sizeGB_provenance": size_provenance},
                )
                edges.append(_edge("service_to_disk", service_resource["id"], disk_resource["id"], {"mountPath": disk["mountPath"], "sizeGB": size_gb, "sizeGB_provenance": size_provenance}))
            domains = list(service.get("domains", []))
            if service.get("domain") is not None:
                domains.append(service["domain"])
            for domain_index, domain in enumerate(domains):
                domain_name = safe_literal(nfc(str(domain)))
                if not domain_name or len(domain_name.encode("utf-8")) > 253 or any(ord(char) < 32 for char in domain_name):
                    raise BlueprintError("unsafe_domain_identity")
                domain_resource = add_resource(
                    "render.custom_domain",
                    domain_name,
                    project,
                    environment,
                    [*pointer_parts, "domains", domain_index],
                    {},
                    strict_identity=False,
                )
                edges.append(_edge("custom_domain_routes_to", domain_resource["id"], service_resource["id"], {}))

    if document.get("previews") is not None or document.get("previewsEnabled") is not None:
        add_resource(
            "render.preview_environment",
            "blueprint-previews",
            "_",
            "_",
            ["previews"],
            {
                "previews": document.get("previews"),
                "previewsEnabled": document.get("previewsEnabled"),
                "previewsExpireAfterDays": document.get("previewsExpireAfterDays"),
            },
        )

    def resolve(kind: str, name: str, project: str | None, environment: str | None) -> dict[str, Any] | None:
        candidates = by_scope.get((kind, name), [])
        exact = [item for item in candidates if item["project"] == project and item["environment"] == environment]
        if len(exact) == 1:
            return exact[0]
        project_matches = [item for item in candidates if item["project"] == project]
        if len(project_matches) == 1:
            return project_matches[0]
        return candidates[0] if len(candidates) == 1 else None

    for group, project_token, environment_token, base in _resource_groups(document):
        project = None if project_token == "_" else project_token
        environment = None if environment_token == "_" else environment_token
        for index, service in enumerate(group.get("services", [])):
            pointer_parts = [*base, "services", index]
            pointer = _json_pointer(pointer_parts)
            source = item_to_resource[pointer]
            if service.get("buildSource") is not None:
                target_name = safe_identity(service["buildSource"])
                target = resolve("render.build_source", target_name, project, None)
                _add_reference_or_error(edges, semantic_errors, source, target, "service_uses_build_source", "render.build_source", target_name, _json_pointer([*pointer_parts, "buildSource"]))
                artifact = resolve("render.build_artifact", f"{target_name}-artifact", project, None)
                if target is not None and artifact is not None and environment is not None:
                    environment_resource = resolve("render.environment", environment, project, environment)
                    if environment_resource is not None:
                        edges.append(_edge("environment_promotes_artifact", environment_resource["id"], artifact["id"], {}))
            for env_index, env_var in enumerate(service.get("envVars", [])):
                if "fromDatabase" in env_var:
                    target_name = safe_identity(env_var["fromDatabase"]["name"])
                    target_kind = "render.postgres"
                    edge_type = "service_to_postgres"
                elif "fromService" in env_var:
                    target_name = safe_identity(env_var["fromService"]["name"])
                    target_kind = _reference_service_kind(env_var["fromService"]["type"])
                    edge_type = "service_to_key_value" if target_kind == "render.key_value" else "service_to_service"
                elif "fromGroup" in env_var:
                    target_name = safe_identity(env_var["fromGroup"])
                    target_kind = "render.environment_group"
                    edge_type = "service_to_env_group"
                else:
                    continue
                target = resolve(target_kind, target_name, project, environment)
                _add_reference_or_error(edges, semantic_errors, source, target, edge_type, target_kind, target_name, _json_pointer([*pointer_parts, "envVars", env_index]))

    resources.sort(key=lambda item: byte_sort_key(item["id"]))
    edges.sort(key=lambda item: (byte_sort_key(item["type"]), byte_sort_key(item["from_id"]), byte_sort_key(item["to_id"]), byte_sort_key(item["id"])))
    semantic_errors.sort(key=lambda item: (byte_sort_key(item["path"]), byte_sort_key(item["source_name"]), byte_sort_key(item["target_name"])))
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "path": source_path,
            "digest": source_digest,
            "official_schema_digest": schema_digest,
        },
        "structural_validation": {"status": "valid", "schema_validated_before_normalization": True},
        "local_reference_validation": {
            "status": "valid" if not semantic_errors else "semantic_invalid",
            "errors": semantic_errors,
        },
        "resources": resources,
        "edges": edges,
    }


def _edge(edge_type: str, from_id: str, to_id: str, attributes: dict[str, Any]) -> dict[str, Any]:
    normalized_attributes = sanitize_config(attributes)
    attributes_input = canonical_bytes(normalized_attributes).decode("utf-8").rstrip("\n")
    return {
        "id": generated_id("rbe", edge_type, from_id, to_id, attributes_input),
        "type": edge_type,
        "from_id": from_id,
        "to_id": to_id,
        "attributes": normalized_attributes,
    }


def _add_reference_or_error(
    edges: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    source: dict[str, Any],
    target: dict[str, Any] | None,
    edge_type: str,
    target_kind: str,
    target_name: str,
    path: str,
) -> None:
    if target is not None:
        edges.append(_edge(edge_type, source["id"], target["id"], {}))
        return
    error = {
        "code": "broken_reference",
        "path": path,
        "line": 0,
        "column": 0,
        "source_kind": source["kind"],
        "source_name": safe_identity(source["name"]),
        "target_kind": safe_identity(target_kind),
        "target_name": safe_identity(target_name),
    }
    error["message"] = (
        f"{error['source_kind']} '{error['source_name']}' references missing "
        f"{error['target_kind']} '{error['target_name']}'."
    )
    errors.append(error)


def semantic_evidence_state(evidence_path: Path | None, migration_dir: Path, source_path: str, source_digest: str) -> dict[str, Any]:
    if evidence_path is None:
        return {"status": "not_provided", "requires_renewed_consent": True}
    try:
        require_contained(evidence_path, migration_dir, "semantic_evidence")
    except PathBoundaryError as exc:
        raise BlueprintError(str(exc)) from exc
    evidence = _load_json(evidence_path, "semantic_evidence_invalid")
    schema = _load_json(SEMANTIC_SCHEMA, "semantic_schema_invalid")
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(evidence))
    if errors:
        raise BlueprintError("semantic_evidence_invalid")
    if evidence["source_digest"] != source_digest or evidence["source_path"] != source_path:
        return {
            "status": "stale",
            "evidence_source_digest": evidence["source_digest"],
            "requires_renewed_consent": True,
        }
    if evidence["outcome"] != "valid" or evidence["errors"]:
        return {
            "status": "invalid",
            "outcome": evidence["outcome"],
            "attempt_id": evidence["attempt_id"],
            "workspace_id": evidence["workspace_id"],
            "consent_digest": evidence["consent_digest"],
            "manifest_digest": evidence["manifest_digest"],
            "errors": evidence["errors"],
            "requires_renewed_consent": True,
        }
    return {
        "status": "current",
        "outcome": evidence["outcome"],
        "source_path": evidence["source_path"],
        "manifest_digest": evidence["manifest_digest"],
        "attempt_id": evidence["attempt_id"],
        "workspace_id": evidence["workspace_id"],
        "consent_digest": evidence["consent_digest"],
        "validated_at": evidence["validated_at"],
        "errors": evidence["errors"],
        "requires_renewed_consent": False,
    }


def parse_blueprint(source: Path, workspace_root: Path, migration_dir: Path, semantic_evidence: Path | None = None) -> dict[str, Any]:
    data = _read_source(source, workspace_root)
    source_digest = sha256_digest(data)
    try:
        document = load_bounded_yaml(data)
    except BlueprintInputError as exc:
        raise BlueprintError(str(exc)) from exc
    diagnostics = validate_structural(document)
    if diagnostics:
        raise BlueprintError("schema_invalid")
    _, schema_digest = _load_pinned_schema()
    source_relative = source.resolve(strict=True).relative_to(workspace_root.resolve(strict=True)).as_posix()
    result = normalize_blueprint(document, source_relative, source_digest, schema_digest)
    result["semantic_validation"] = semantic_evidence_state(semantic_evidence, migration_dir, source_relative, source_digest)
    return result


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--migration-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--semantic-evidence", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        if not args.migration_dir.is_absolute() or not args.migration_dir.is_dir() or args.migration_dir.is_symlink():
            raise BlueprintError("migration_dir_invalid")
        require_contained(args.output, args.migration_dir, "output")
        result = parse_blueprint(args.source, args.workspace_root, args.migration_dir, args.semantic_evidence)
        write_json_atomic(args.output, args.migration_dir, result)
    except (BlueprintError, PathBoundaryError, UnsafeIdentityError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, BlueprintError) else str(exc)
        if not code or any(char.isspace() for char in code):
            code = "internal_validation_error"
        print(f"BLUEPRINT_FAIL | code={code}", file=sys.stderr)
        return 1
    print(f"BLUEPRINT_OK | output={args.output} | digest={result['source']['digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
