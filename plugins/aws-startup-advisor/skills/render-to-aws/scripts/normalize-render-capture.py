#!/usr/bin/env python3
"""Assemble active sanitized Render producers into canonical inventory."""

from __future__ import annotations

import argparse
import functools
import json
import math
import os
import re
import sys
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, Draft202012Validator, FormatChecker

from render_common.atomic import PathBoundaryError, require_contained
from render_common.canonical import byte_sort_key, canonical_bytes, generated_id, nfc, sha256_digest
from render_common.plans import normalize_plan, plan_surface

SKILL_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_SCHEMA = SKILL_ROOT / "references/shared/schema-live-capture-manifest.json"
INVENTORY_SCHEMA = SKILL_ROOT / "references/shared/schema-render-resource-inventory.json"
CLUSTER_SCHEMA = SKILL_ROOT / "references/shared/schema-render-resource-clusters.json"
AI_PROFILE_SCHEMA = SKILL_ROOT / "references/contracts/ai-workload-profile.schema.json"
AI_DISCOVERY_SCHEMA = SKILL_ROOT / "references/shared/schema-render-ai-discovery.json"
CLI_CONTRACTS = SKILL_ROOT / "references/shared/render-cli-contracts.json"
MAX_INPUT_BYTES = 12 * 1024 * 1024
SENSITIVE_KEY = re.compile(r"(?i)(password|passwd|token|secret|credential|api[_-]?key|private[_-]?key|databaseUser|email|sshAddress|dashboardUrl|^(?:message|body|details|content|value|connectionInfo|connectionString)$)")
RENDER_SECRET_LITERAL = re.compile(r"rnd_[A-Za-z0-9]{16,}")
METRIC_SERIES_KEYS = {"labels", "unit", "values"}
METRIC_LABEL_KEYS = {"field", "value"}
METRIC_POINT_KEYS = {"timestamp", "value"}
LOG_ENTRY_KEYS = {"id", "timestamp", "labels"}
LOG_LABEL_KEYS = {"name", "value"}
LOG_LABEL_NAMES = {"resource", "instance", "level", "type"}
SOURCE_RANK = {"render_blueprint": 1, "application": 1, "render_cli": 2, "render_rest": 3}
BLUEPRINT_INTENT_FIELDS = {
    "repo", "branch", "rootDir", "buildCommand", "startCommand", "preDeployCommand",
    "buildSource", "image", "imagePath", "dockerCommand", "dockerContext", "dockerfilePath",
    "publishPath", "staticPublishPath", "runtime", "envVars", "routes", "domains",
}
SOURCE_REASON = {
    "render_rest": "current_configuration_prefers_live_rest",
    "render_cli": "current_configuration_prefers_live_cli",
    "render_blueprint": "current_configuration_prefers_blueprint",
    "application": "application_inference_only",
}
SERVICE_KINDS = {
    "web": "render.web_service", "web_service": "render.web_service", "static": "render.static_site",
    "static_site": "render.static_site", "pserv": "render.private_service", "private_service": "render.private_service",
    "worker": "render.background_worker", "background_worker": "render.background_worker",
    "cron": "render.cron_job", "cron_job": "render.cron_job", "workflow": "render.workflow",
}
CATEGORY_KINDS = {
    "projects_list": "render.project", "environments_list": "render.environment",
    "postgres_list": "render.postgres", "postgres_get": "render.postgres",
    "keyvalues_list": "render.key_value", "keyvalue_get": "render.key_value",
    "disks_list": "render.persistent_disk", "disk_get": "render.persistent_disk",
    "custom_domains": "render.custom_domain", "build_sources_list": "render.build_source",
    "environment_groups_list": "render.environment_group", "workflows_list": "render.workflow",
    "workflow_get": "render.workflow", "workflow_versions_list": "render.workflow_version",
    "workflow_tasks_list": "render.workflow_task", "workflow_task_runs_list": "render.task_run",
    "workflow_task_run_show": "render.task_run",
}
SERVICE_RESOURCE_KINDS = {"render.web_service", "render.static_site", "render.private_service", "render.background_worker", "render.cron_job"}
LIFECYCLE_CATEGORIES = {"deploys_list", "service_events", "service_instances", "jobs_list", "log_metadata", "metric_cpu", "metric_memory", "metric_memory_limit", "metric_active_connections", "metric_bandwidth", "metric_http_requests"}
EDGE_TYPES = {"service_to_postgres", "service_to_key_value", "service_to_service", "service_to_env_group", "service_to_disk", "member_of_project", "member_of_environment", "shares_repository", "private_network_peer", "custom_domain_routes_to", "service_uses_build_source", "build_source_produces_artifact", "environment_promotes_artifact", "workflow_has_version", "workflow_version_has_task", "workflow_task_has_run", "task_run_has_attempt"}


class NormalizeError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _read_json(path: Path, root: Path, code: str) -> tuple[Any, bytes]:
    try:
        require_contained(path, root, code)
    except PathBoundaryError as exc:
        raise NormalizeError(str(exc)) from exc
    if path.is_symlink() or not path.is_file():
        raise NormalizeError(code)
    data = path.read_bytes()
    if len(data) > MAX_INPUT_BYTES:
        raise NormalizeError("input_too_large")
    try:
        return json.loads(data.decode("utf-8", errors="strict")), data
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizeError(code) from exc


def _schema(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NormalizeError("schema_invalid") from exc
    if not isinstance(value, dict):
        raise NormalizeError("schema_invalid")
    return value


def _validate_uuid4(value: str) -> None:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise NormalizeError("attempt_id_invalid") from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise NormalizeError("attempt_id_invalid")


def _safe_tree(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = nfc(str(key))
            if SENSITIVE_KEY.search(key_text):
                raise NormalizeError("secret_bearing_input")
            if key_text in output:
                raise NormalizeError("duplicate_normalized_key")
            output[key_text] = _safe_tree(item)
        return output
    if isinstance(value, list):
        return [_safe_tree(item) for item in value]
    if isinstance(value, str):
        if "-----BEGIN " in value or re.search(r"AKIA[0-9A-Z]{16}", value):
            raise NormalizeError("secret_bearing_input")
        return nfc(value)
    return value


def _closed_string(value: Any, code: str) -> str:
    """String leaf inside a closed projection: shape error -> `code`; secret content still deny-first."""
    if not isinstance(value, str):
        raise NormalizeError(code)
    if RENDER_SECRET_LITERAL.search(value):
        raise NormalizeError("secret_bearing_input")
    return _safe_tree(value)


def _metric_series_projection(data: Any) -> list[dict[str, Any]]:
    """Exact REST metric shape (`capture-render-api.py::_metric_series`); `value` keys are numeric points or label text here."""
    if not isinstance(data, list):
        raise NormalizeError("metric_series_invalid")
    projected: list[dict[str, Any]] = []
    for series in data:
        if not isinstance(series, dict) or set(series) != METRIC_SERIES_KEYS or not isinstance(series["labels"], list) or not isinstance(series["values"], list):
            raise NormalizeError("metric_series_invalid")
        labels: list[dict[str, str]] = []
        for label in series["labels"]:
            if not isinstance(label, dict) or set(label) != METRIC_LABEL_KEYS:
                raise NormalizeError("metric_series_invalid")
            labels.append({"field": _closed_string(label["field"], "metric_series_invalid"), "value": _closed_string(label["value"], "metric_series_invalid")})
        points: list[dict[str, Any]] = []
        for point in series["values"]:
            if not isinstance(point, dict) or set(point) != METRIC_POINT_KEYS:
                raise NormalizeError("metric_series_invalid")
            number = point["value"]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise NormalizeError("metric_series_invalid")
            points.append({"timestamp": _closed_string(point["timestamp"], "metric_series_invalid"), "value": number})
        projected.append({"labels": labels, "unit": _closed_string(series["unit"], "metric_series_invalid"), "values": points})
    return projected


def _log_metadata_projection(data: Any) -> list[dict[str, Any]]:
    """Exact CLI log-metadata shape (`capture-render-cli.py::_project_log_metadata`); label names are a closed set."""
    if not isinstance(data, list):
        raise NormalizeError("log_metadata_invalid")
    projected: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict) or set(entry) != LOG_ENTRY_KEYS or not isinstance(entry["labels"], list):
            raise NormalizeError("log_metadata_invalid")
        labels: list[dict[str, str]] = []
        for label in entry["labels"]:
            if not isinstance(label, dict) or set(label) != LOG_LABEL_KEYS or label["name"] not in LOG_LABEL_NAMES:
                raise NormalizeError("log_metadata_invalid")
            labels.append({"name": label["name"], "value": _closed_string(label["value"], "log_metadata_invalid")})
        projected.append({"id": _closed_string(entry["id"], "log_metadata_invalid"), "timestamp": _closed_string(entry["timestamp"], "log_metadata_invalid"), "labels": labels})
    return projected


def _metric_window(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or not isinstance(request.get("start"), str) or not isinstance(request.get("end"), str):
        raise NormalizeError("metric_window_invalid")
    resolution = request.get("resolution_seconds")
    if resolution is not None and (isinstance(resolution, bool) or not isinstance(resolution, int)):
        raise NormalizeError("metric_window_invalid")
    return {"start": request["start"], "end": request["end"], "resolution_seconds": resolution}


def _capture_path(root: Path, manifest_path: Path, relative: str) -> Path:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise NormalizeError("capture_path_invalid")
    candidate = manifest_path.parent / relative
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise NormalizeError("capture_path_invalid") from exc
    return candidate


@functools.cache
def _cli_nullable_categories() -> frozenset[str]:
    """Categories whose reviewed CLI contract shape admits `null` (bare or inside the `{"data": ...}` envelope)."""
    categories = _schema(CLI_CONTRACTS).get("categories")
    if not isinstance(categories, dict):
        raise NormalizeError("schema_invalid")
    return frozenset(name for name, row in categories.items() if isinstance(row, dict) and "nullable" in str(row.get("shape", "")))


def _iter_cli_data(category: str, data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and set(data) == {"data"}:
        data = data["data"]
    if data is None:
        if category in _cli_nullable_categories():
            return []
        raise NormalizeError("capture_data_invalid")
    if isinstance(data, dict):
        return [data]
    if not isinstance(data, list):
        raise NormalizeError("capture_data_invalid")
    output = []
    for item in data:
        if not isinstance(item, dict):
            raise NormalizeError("capture_data_invalid")
        wrappers = set(item) & {"service", "postgres", "keyValue", "workflow"}
        if wrappers:
            if len(wrappers) != 1 or len(item) != 1:
                raise NormalizeError("capture_envelope_invalid")
            output.append(item[next(iter(wrappers))])
        else:
            output.append(item)
    return output


def _kind(category: str, item: dict[str, Any]) -> str | None:
    if category in {"services_list", "service_get"}:
        identifier = str(item.get("id", ""))
        if identifier.startswith("wfl-") or item.get("type") == "workflow":
            return "render.workflow"
        if identifier.startswith("dpg-"):
            return "render.postgres"
        if identifier.startswith("red-"):
            return "render.key_value"
        resource_type = item.get("type")
        kind = SERVICE_KINDS.get(resource_type)
        if kind is None and item.get("serviceDetails", {}).get("runtime") == "static":
            kind = "render.static_site"
        return kind
    return CATEGORY_KINDS.get(category)


def _identity_fields(item: dict[str, Any], kind: str) -> tuple[str | None, str, str | None, str | None, str | None]:
    render_id = item.get("id")
    if render_id is not None and not isinstance(render_id, str):
        raise NormalizeError("resource_id_invalid")
    name = item.get("name") or item.get("domain") or render_id
    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 256:
        raise NormalizeError("resource_name_invalid")
    project_id = item.get("projectId")
    environment_id = item.get("environmentId")
    region = item.get("region")
    for value in (project_id, environment_id, region):
        if value is not None and not isinstance(value, str):
            raise NormalizeError("resource_identity_invalid")
    if kind == "render.environment" and project_id is None:
        project_id = item.get("project_id")
    return render_id, nfc(name), project_id, environment_id, region


PLAN_KINDS = {"render.web_service", "render.private_service", "render.background_worker", "render.cron_job", "render.key_value", "render.workflow"}


def _config(item: dict[str, Any], kind: str | None = None) -> dict[str, Any]:
    excluded = {"id", "name", "domain", "owner", "ownerId", "workspaceId", "projectId", "environmentId", "region", "createdAt", "updatedAt", "type"}
    config = {key: value for key, value in item.items() if key not in excluded}
    if kind in PLAN_KINDS:
        # Live captures spell the plan under serviceDetails.plan (services) or plan (Key Value,
        # workflows). The raw value stays where it was; plan_normalized mirrors the Blueprint
        # parser so both sources resolve through the same alias table.
        details = item.get("serviceDetails")
        raw_plan = details.get("plan") if isinstance(details, dict) and "plan" in details else item.get("plan")
        if raw_plan is not None:
            config["plan_normalized"] = normalize_plan(plan_surface(kind), raw_plan)
    return _safe_tree(config)


def _edge(edge_type: str, from_id: str, to_id: str, attributes: dict[str, Any]) -> dict[str, Any]:
    if edge_type not in EDGE_TYPES:
        raise NormalizeError("edge_type_invalid")
    safe_attributes = _safe_tree(attributes)
    encoded = canonical_bytes(safe_attributes).decode("utf-8").rstrip("\n")
    return {"id": generated_id("re", "edge", edge_type, from_id, to_id, encoded), "type": edge_type, "from_id": from_id, "to_id": to_id, "attributes": safe_attributes}


def _source_name(transport: str) -> str:
    return {"cli": "render_cli", "rest": "render_rest", "blueprint": "render_blueprint", "application": "application", "billing": "billing"}[transport]


def _manifest_identity_digest(value: dict[str, Any]) -> str:
    return sha256_digest(canonical_bytes({
        "schema_version": value["schema_version"],
        "status": value["status"],
        "identity_scope": value["identity_scope"],
        "attempt_id": value["attempt_id"],
        "workspace_id": value["workspace_id"],
        "local_identity": value["local_identity"],
        "consent_digest": value["consent_digest"],
        "ownership_index_digest": value["ownership_index_digest"],
    }))


def _ordered_for_field(group: list[dict[str, Any]], field: str) -> tuple[list[dict[str, Any]], str]:
    available = [item for item in group if field in item["config"]]
    if field in BLUEPRINT_INTENT_FIELDS and any(item["source"] == "render_blueprint" for item in available):
        ordered = sorted(
            available,
            key=lambda item: (item["source"] != "render_blueprint", -SOURCE_RANK[item["source"]], byte_sort_key(item["source_ref"])),
        )
        return ordered, "declared_repository_intent_prefers_blueprint"
    ordered = sorted(available, key=lambda item: (-SOURCE_RANK[item["source"]], byte_sort_key(item["source_ref"])))
    return ordered, SOURCE_REASON[ordered[0]["source"]]


def normalize(migration_dir: Path, manifest_path: Path, attempt_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    _validate_uuid4(attempt_id)
    manifest, _ = _read_json(manifest_path, migration_dir, "manifest_invalid")
    errors = list(Draft202012Validator(_schema(MANIFEST_SCHEMA), format_checker=FormatChecker()).iter_errors(manifest))
    if errors or manifest.get("attempt_id") != attempt_id or manifest.get("status") != "active":
        raise NormalizeError("manifest_invalid")
    identity_scope = manifest["identity_scope"]
    manifest_workspace_id = manifest["workspace_id"]
    local_identity = manifest["local_identity"]
    consent_digest = manifest["consent_digest"]
    ownership_index_digest = manifest["ownership_index_digest"]
    live_transports = {entry["transport"] for entry in manifest["captures"]} & {"cli", "rest"}
    if identity_scope == "live":
        if not isinstance(manifest_workspace_id, str) or local_identity is not None or not isinstance(consent_digest, str) or not isinstance(ownership_index_digest, str):
            raise NormalizeError("manifest_identity_invalid")
        workspace_id = manifest_workspace_id
    else:
        if live_transports or manifest_workspace_id is not None or consent_digest is not None or ownership_index_digest is not None or not isinstance(local_identity, str):
            raise NormalizeError("manifest_identity_invalid")
        workspace_id = "local:" + local_identity.removeprefix("sha256:")
    manifest_identity_digest = _manifest_identity_digest(manifest)
    seen_manifest: set[tuple[str, str, str]] = set()
    candidates: list[dict[str, Any]] = []
    blueprint_edges: list[dict[str, Any]] = []
    lifecycle: defaultdict[str, dict[str, Any]] = defaultdict(dict)
    discovery_sources: set[str] = set()
    billing: dict[str, Any] | None = None
    ai_profile: dict[str, Any] | None = None
    ai_discovery: dict[str, Any] | None = None

    for entry in manifest["captures"]:
        manifest_key = (entry["transport"], entry["category"], entry["path"])
        if manifest_key in seen_manifest:
            raise NormalizeError("duplicate_manifest_entry")
        seen_manifest.add(manifest_key)
        path = _capture_path(migration_dir, manifest_path, entry["path"])
        value, raw = _read_json(path, migration_dir, "capture_invalid")
        if sha256_digest(raw) != entry["digest"]:
            raise NormalizeError("capture_digest_mismatch")
        transport, category = entry["transport"], entry["category"]
        if entry["workspace_id"] != manifest_workspace_id:
            raise NormalizeError("capture_evidence_mismatch")
        source = _source_name(transport)
        discovery_sources.add(source)
        if transport in {"cli", "rest"}:
            if identity_scope != "live" or not isinstance(value, dict) or value.get("attempt_id") != attempt_id or value.get("workspace_id") != workspace_id or value.get("consent_digest") != consent_digest:
                raise NormalizeError("capture_attempt_mismatch")
            expected_transport = "render_cli_2.30.0" if transport == "cli" else "render_rest_v1"
            if value.get("transport") != expected_transport or value.get("category") != category:
                raise NormalizeError("capture_transport_mismatch")
            if (
                entry["captured_at"] != value.get("captured_at")
                or entry["status"] != value.get("status")
                or entry["page_count"] != value.get("page_count")
                or entry["ownership_index_digest"] != ownership_index_digest
                or value.get("ownership_index_digest") != ownership_index_digest
            ):
                raise NormalizeError("capture_evidence_mismatch")
        elif entry["status"] != "ok" or entry["page_count"] is not None or entry["ownership_index_digest"] is not None:
            raise NormalizeError("capture_evidence_mismatch")
        if transport == "blueprint":
            if not isinstance(value, dict) or value.get("schema_version") != "1.0":
                raise NormalizeError("blueprint_capture_invalid")
            if value.get("local_reference_validation") != {"status": "valid", "errors": []}:
                raise NormalizeError("blueprint_local_references_invalid")
            semantic = value.get("semantic_validation")
            if not isinstance(semantic, dict):
                raise NormalizeError("blueprint_semantic_validation_invalid")
            semantic_status = semantic.get("status")
            if semantic_status == "current":
                if semantic.get("outcome") != "valid" or semantic.get("errors") != []:
                    raise NormalizeError("blueprint_semantic_validation_invalid")
                if semantic.get("attempt_id") != attempt_id or semantic.get("workspace_id") != workspace_id or semantic.get("consent_digest") != consent_digest or semantic.get("manifest_digest") != manifest_identity_digest or semantic.get("source_path") != value.get("source", {}).get("path"):
                    raise NormalizeError("blueprint_semantic_binding_mismatch")
            elif semantic_status in {"not_provided", "stale"}:
                if semantic.get("requires_renewed_consent") is not True:
                    raise NormalizeError("blueprint_semantic_validation_invalid")
            else:
                raise NormalizeError("blueprint_semantic_validation_invalid")
            for resource in value.get("resources", []):
                if not isinstance(resource, dict) or not isinstance(resource.get("id"), str):
                    raise NormalizeError("blueprint_capture_invalid")
                candidates.append({"source": source, "source_ref": f"blueprint:{resource['id']}", "blueprint_id": resource["id"], "kind": resource["kind"], "render_id": None, "name": resource["name"], "workspace_id": workspace_id, "project_id": resource.get("project"), "environment_id": resource.get("environment"), "region": resource.get("config", {}).get("region"), "config": _safe_tree(resource.get("config", {})), "confidence": resource.get("confidence", "deterministic")})
            blueprint_edges.extend(value.get("edges", []))
            continue
        if transport == "application":
            if not isinstance(value, dict) or value.get("schema_version") != "1.0" or not isinstance(value.get("signals"), list):
                raise NormalizeError("application_capture_invalid")
            ai_profile = value.get("ai_profile")
            ai_discovery = value.get("ai_discovery")
            if (ai_profile is None) != (ai_discovery is None):
                raise NormalizeError("application_capture_invalid")
            continue
        if transport == "billing":
            if not isinstance(value, dict) or value.get("schema_version") != "1.0" or "monthly_total" not in value:
                raise NormalizeError("billing_capture_invalid")
            billing = _safe_tree(value)
            continue
        data = value.get("data")
        request = value.get("request", {})
        if category in LIFECYCLE_CATEGORIES:
            parent_id = request.get("resource_id")
            if not isinstance(parent_id, str):
                raise NormalizeError("lifecycle_parent_invalid")
            key = {
                "deploys_list": "deploy_history", "service_events": "events", "service_instances": "instance_lifecycle",
                "jobs_list": "run_history", "log_metadata": "log_metadata",
            }.get(category, "metrics")
            if key == "metrics":
                # Every 24h window is retained with its outcome and provenance; Estimate needs the full seven-day span.
                lifecycle[parent_id].setdefault("metrics", {}).setdefault(category, []).append({
                    "outcome": value.get("status"), "window": _metric_window(request), "captured_at": value.get("captured_at"),
                    "source_ref": f"{transport}:{category}", "series": _metric_series_projection(data),
                })
            elif key == "log_metadata":
                lifecycle[parent_id][key] = _log_metadata_projection(data)
            else:
                lifecycle[parent_id][key] = _safe_tree(data)
            continue
        items = _iter_cli_data(category, data) if transport == "cli" else data
        if not isinstance(items, list):
            raise NormalizeError("capture_data_invalid")
        seen_capture_ids: set[tuple[str, str]] = set()
        for item in items:
            if not isinstance(item, dict):
                raise NormalizeError("capture_data_invalid")
            kind = _kind(category, item)
            if kind is None:
                raise NormalizeError("resource_kind_unknown")
            normalized_item = dict(item)
            if kind == "render.custom_domain" and isinstance(request.get("resource_id"), str):
                normalized_item.setdefault("serviceId", request["resource_id"])
            render_id, name, project_id, environment_id, region = _identity_fields(normalized_item, kind)
            if render_id is None:
                raise NormalizeError("live_resource_id_missing")
            duplicate_key = (kind, render_id)
            if duplicate_key in seen_capture_ids:
                raise NormalizeError("duplicate_resource_identity")
            seen_capture_ids.add(duplicate_key)
            candidates.append({"source": source, "source_ref": f"{transport}:{category}", "blueprint_id": None, "kind": kind, "render_id": render_id, "name": name, "workspace_id": workspace_id, "project_id": project_id, "environment_id": environment_id, "region": region, "config": _config(normalized_item, kind), "confidence": "inferred"})
            if kind == "render.task_run" and "attempts" in normalized_item:
                attempts = normalized_item["attempts"]
                if not isinstance(attempts, list):
                    raise NormalizeError("task_attempts_invalid")
                for attempt in attempts:
                    if not isinstance(attempt, dict) or not isinstance(attempt.get("id"), str):
                        raise NormalizeError("task_attempts_invalid")
                    attempt_item = dict(attempt)
                    attempt_item.setdefault("taskRunId", render_id)
                    attempt_render_id, attempt_name, _, _, _ = _identity_fields(attempt_item, "render.task_attempt")
                    candidates.append({"source": source, "source_ref": f"{transport}:{category}:attempt", "blueprint_id": None, "kind": "render.task_attempt", "render_id": attempt_render_id, "name": attempt_name, "workspace_id": workspace_id, "project_id": project_id, "environment_id": environment_id, "region": region, "config": _config(attempt_item), "confidence": "inferred"})
            if kind == "render.build_source" and isinstance(normalized_item.get("artifact"), dict):
                artifact = normalized_item["artifact"]
                artifact_id = artifact.get("id") or artifact.get("digest")
                if not isinstance(artifact_id, str):
                    raise NormalizeError("artifact_identity_missing")
                candidates.append({"source": source, "source_ref": f"{transport}:{category}:artifact", "blueprint_id": None, "kind": "render.build_artifact", "render_id": artifact_id, "name": artifact_id, "workspace_id": workspace_id, "project_id": project_id, "environment_id": environment_id, "region": None, "config": _safe_tree(artifact), "confidence": "deterministic", "build_source_id": render_id})

    for lifecycle_data in lifecycle.values():
        for category, windows in lifecycle_data.get("metrics", {}).items():
            windows.sort(key=lambda item: (byte_sort_key(item["window"]["start"]), byte_sort_key(item["window"]["end"]), byte_sort_key(str(item["captured_at"]))))
            seen_windows: set[tuple[str, str]] = set()
            for item in windows:
                window_key = (item["window"]["start"], item["window"]["end"])
                if window_key in seen_windows:
                    raise NormalizeError("duplicate_metric_window")
                seen_windows.add(window_key)

    live_by_name: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    live_environments_by_name: defaultdict[str, list[tuple[str | None, str]]] = defaultdict(list)
    for candidate in candidates:
        if candidate["render_id"] is None:
            continue
        if candidate["kind"] == "render.environment":
            live_environments_by_name[candidate["name"]].append((candidate["project_id"], candidate["render_id"]))
        else:
            live_by_name[(candidate["kind"], candidate["name"])].append(candidate["render_id"])
    grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    blueprint_to_group: dict[str, tuple[str, str]] = {}

    def _group(candidate: dict[str, Any], identity: str) -> None:
        key = (candidate["kind"], identity)
        grouped[key].append(candidate)
        if candidate.get("blueprint_id"):
            blueprint_to_group[candidate["blueprint_id"]] = key

    # Blueprint environments are grouped after project aliases exist, so their match is project-qualified.
    deferred_environments: list[dict[str, Any]] = []
    for candidate in candidates:
        identity = candidate["render_id"]
        if identity is None:
            if candidate["kind"] == "render.environment":
                deferred_environments.append(candidate)
                continue
            live_matches = sorted(set(live_by_name[(candidate["kind"], candidate["name"])]), key=byte_sort_key)
            identity = live_matches[0] if len(live_matches) == 1 else f"blueprint:{candidate['blueprint_id']}"
        _group(candidate, identity)

    project_aliases: dict[str, str] = {}
    for (kind, _identity), group in grouped.items():
        live_ids = sorted({item["render_id"] for item in group if item["render_id"] is not None}, key=byte_sort_key)
        if len(live_ids) != 1 or kind != "render.project":
            continue
        for item in group:
            for alias in (item["name"], item.get("blueprint_id")):
                if alias and project_aliases.setdefault(alias, live_ids[0]) != live_ids[0]:
                    raise NormalizeError("ambiguous_membership_identity")
    live_project_ids = {candidate["render_id"] for candidate in candidates if candidate["kind"] == "render.project" and candidate["render_id"] is not None}

    for candidate in deferred_environments:
        project = project_aliases.get(candidate["project_id"], candidate["project_id"])
        owned = live_environments_by_name[candidate["name"]]
        if project in live_project_ids:
            live_matches = sorted({render_id for owner, render_id in owned if project_aliases.get(owner, owner) == project}, key=byte_sort_key)
        else:
            # No resolvable project context: only a workspace-unique name may match.
            live_matches = sorted({render_id for _owner, render_id in owned}, key=byte_sort_key)
        _group(candidate, live_matches[0] if len(live_matches) == 1 else f"blueprint:{candidate['blueprint_id']}")

    environment_aliases: dict[tuple[str | None, str], str] = {}
    for (kind, _identity), group in grouped.items():
        live_items = [item for item in group if item["render_id"] is not None]
        live_ids = sorted({item["render_id"] for item in live_items}, key=byte_sort_key)
        if len(live_ids) != 1 or kind != "render.environment":
            continue
        owners = {project_aliases.get(item["project_id"], item["project_id"]) for item in live_items}
        for owner in owners:
            for item in group:
                for alias in (item["name"], item.get("blueprint_id")):
                    if alias and environment_aliases.setdefault((owner, alias), live_ids[0]) != live_ids[0]:
                        raise NormalizeError("ambiguous_membership_identity")
    environment_alias_owners: defaultdict[str, set[str | None]] = defaultdict(set)
    for owner, alias in environment_aliases:
        environment_alias_owners[alias].add(owner)

    for candidate in candidates:
        project_id = project_aliases.get(candidate["project_id"], candidate["project_id"])
        candidate["project_id"] = project_id
        environment_id = candidate["environment_id"]
        if environment_id is None:
            continue
        resolved = environment_aliases.get((project_id, environment_id))
        if resolved is None and project_id not in live_project_ids:
            owners = environment_alias_owners.get(environment_id, set())
            if len(owners) == 1:
                resolved = environment_aliases[(next(iter(owners)), environment_id)]
        candidate["environment_id"] = environment_id if resolved is None else resolved

    live_kind_by_id: dict[str, str] = {}
    for candidate in candidates:
        render_id = candidate["render_id"]
        if render_id is None:
            continue
        previous_kind = live_kind_by_id.setdefault(render_id, candidate["kind"])
        if previous_kind != candidate["kind"]:
            raise NormalizeError("membership_kind_conflict")
    membership_fields = {
        "serviceIds": SERVICE_RESOURCE_KINDS | {"render.workflow"},
        "databasesIds": {"render.postgres"},
        "redisIds": {"render.key_value"},
        "envGroupIds": {"render.environment_group"},
    }
    reverse_membership: dict[str, dict[str, str]] = {}
    for environment in (item for item in candidates if item["kind"] == "render.environment" and item["render_id"] is not None):
        environment_id = environment["render_id"]
        project_id = environment["project_id"]
        for field, allowed_kinds in membership_fields.items():
            references = environment["config"].get(field, [])
            if not isinstance(references, list) or any(not isinstance(reference, str) for reference in references):
                raise NormalizeError("environment_membership_invalid")
            if len(references) != len(set(references)):
                raise NormalizeError("environment_membership_duplicate")
            for reference in references:
                kind = live_kind_by_id.get(reference)
                if kind is None:
                    raise NormalizeError("environment_membership_unresolved")
                if kind not in allowed_kinds:
                    raise NormalizeError("environment_membership_wrong_kind")
                membership = {
                    "environment_id": environment_id,
                    "project_id": project_id,
                    "source_ref": environment["source_ref"],
                }
                previous = reverse_membership.setdefault(reference, membership)
                if previous["environment_id"] != environment_id or previous["project_id"] != project_id:
                    raise NormalizeError("environment_membership_conflict")
    for candidate in candidates:
        render_id = candidate["render_id"]
        membership = reverse_membership.get(render_id) if render_id is not None else None
        if membership is None:
            continue
        if candidate["environment_id"] not in {None, membership["environment_id"]}:
            raise NormalizeError("environment_membership_conflict")
        if candidate["project_id"] not in {None, membership["project_id"]}:
            raise NormalizeError("environment_membership_conflict")
        candidate["environment_id"] = membership["environment_id"]
        candidate["project_id"] = membership["project_id"]
        candidate["membership_source_ref"] = membership["source_ref"]

    resources: list[dict[str, Any]] = []
    group_to_canonical: dict[tuple[str, str], str] = {}
    render_to_canonical: dict[str, str] = {}
    drift: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    selected_candidates: dict[str, list[dict[str, Any]]] = {}
    for key, group in grouped.items():
        kind, identity = key
        canonical_id = generated_id("rr", "resource", kind, identity)
        if canonical_id in seen_ids:
            raise NormalizeError("identity_collision")
        seen_ids.add(canonical_id)
        group_to_canonical[key] = canonical_id
        live_ids = sorted({item["render_id"] for item in group if item["render_id"] is not None}, key=byte_sort_key)
        if len(live_ids) > 1:
            raise NormalizeError("duplicate_normalized_identity")
        render_id = live_ids[0] if live_ids else None
        if render_id:
            if render_id in render_to_canonical:
                raise NormalizeError("duplicate_render_id")
            render_to_canonical[render_id] = canonical_id
        ordered = sorted(group, key=lambda item: (-SOURCE_RANK[item["source"]], byte_sort_key(item["source_ref"])))
        selected_candidates[canonical_id] = ordered
        selected = ordered[0]
        config: dict[str, Any] = {}
        provenance: dict[str, str] = {}
        fields = sorted({field for item in group for field in item["config"]}, key=byte_sort_key)
        for field in fields:
            available, selection_reason = _ordered_for_field(group, field)
            winner = available[0]
            config[field] = winner["config"][field]
            provenance[f"config.{field}"] = winner["source_ref"]
            for loser in available[1:]:
                if loser["config"][field] != winner["config"][field]:
                    drift.append({"resource_id": canonical_id, "field": f"config.{field}", "selected_value": winner["config"][field], "selected_source": winner["source_ref"], "other_value": loser["config"][field], "other_source": loser["source_ref"], "selection_reason": selection_reason})
        for field in ("name", "project_id", "environment_id", "region"):
            values = [item for item in ordered if item[field] is not None]
            if values:
                provenance[field] = values[0].get("membership_source_ref", values[0]["source_ref"]) if field in {"project_id", "environment_id"} else values[0]["source_ref"]
                selection_reason = SOURCE_REASON[values[0]["source"]]
                for loser in values[1:]:
                    if loser[field] != values[0][field]:
                        drift.append({"resource_id": canonical_id, "field": field, "selected_value": values[0][field], "selected_source": values[0]["source_ref"], "other_value": loser[field], "other_source": loser["source_ref"], "selection_reason": selection_reason})
        if render_id in lifecycle:
            lifecycle_data = lifecycle[render_id]
            deploys = lifecycle_data.get("deploy_history")
            if isinstance(deploys, list):
                safe_deploys = [item for item in deploys if isinstance(item, dict)]
                live = [item for item in safe_deploys if item.get("status") == "live"]
                lifecycle_data["live_deploy_id"] = sorted((item.get("id") for item in live if isinstance(item.get("id"), str)), key=byte_sort_key)[-1] if live else None
                newest = sorted(safe_deploys, key=lambda item: (str(item.get("createdAt", "")).encode(), str(item.get("id", "")).encode()))
                lifecycle_data["newest_deploy_id"] = newest[-1].get("id") if newest else None
            config["lifecycle_evidence"] = lifecycle_data
            provenance["config.lifecycle_evidence"] = "live_capture"
        resource = {"id": canonical_id, "kind": kind, "render_id": render_id, "name": selected["name"], "workspace_id": workspace_id, "project_id": next((item["project_id"] for item in ordered if item["project_id"] is not None), None), "environment_id": next((item["environment_id"] for item in ordered if item["environment_id"] is not None), None), "region": next((item["region"] for item in ordered if item["region"] is not None), None), "config": config, "provenance": provenance, "confidence": selected["confidence"], "accounting_disposition": "inventory"}
        resources.append(resource)

    edges: list[dict[str, Any]] = []
    blueprint_disk_attachments: dict[str, dict[str, Any]] = {}
    for raw_edge in blueprint_edges:
        if not isinstance(raw_edge, dict) or raw_edge.get("type") not in EDGE_TYPES:
            raise NormalizeError("blueprint_edge_invalid")
        from_group = blueprint_to_group.get(raw_edge.get("from_id"))
        to_group = blueprint_to_group.get(raw_edge.get("to_id"))
        if from_group is None or to_group is None:
            raise NormalizeError("blueprint_edge_unresolved")
        canonical_from = group_to_canonical[from_group]
        canonical_to = group_to_canonical[to_group]
        if raw_edge["type"] == "service_to_disk":
            attachment = {
                "service_id": canonical_from,
                "attributes": _safe_tree(raw_edge.get("attributes", {})),
            }
            previous = blueprint_disk_attachments.setdefault(canonical_to, attachment)
            if previous != attachment:
                raise NormalizeError("disk_attachment_conflict")
            continue
        edges.append(_edge(raw_edge["type"], canonical_from, canonical_to, raw_edge.get("attributes", {})))
        target_resource = next(item for item in resources if item["id"] == canonical_to)
        if raw_edge["type"] == "service_to_service" and target_resource["kind"] == "render.private_service":
            target_config = target_resource["config"]
            details = target_config.get("serviceDetails", {}) if isinstance(target_config.get("serviceDetails"), dict) else {}
            ports = details.get("openPorts", [])
            attributes = {"hostname_provenance": "blueprint_reference", "ports": ports}
            edges.append(_edge("private_network_peer", canonical_from, canonical_to, attributes))

    repository_members: defaultdict[str, list[str]] = defaultdict(list)
    service_kinds = {"render.web_service", "render.static_site", "render.private_service", "render.background_worker", "render.cron_job"}
    for resource in resources:
        if resource["kind"] not in service_kinds:
            continue
        repo = resource["config"].get("repo")
        if isinstance(repo, str) and repo:
            repository_members[repo].append(resource["id"])
    for repo, members in repository_members.items():
        ordered_members = sorted(set(members), key=byte_sort_key)
        for index, left in enumerate(ordered_members):
            for right in ordered_members[index + 1:]:
                edges.append(_edge("shares_repository", left, right, {"repository_fingerprint": sha256_digest(repo.encode("utf-8"))}))

    by_kind: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for resource in resources:
        by_kind[resource["kind"]].append(resource)
    for resource in resources:
        render_id = resource["render_id"]
        if resource["project_id"] in render_to_canonical:
            edges.append(_edge("member_of_project", resource["id"], render_to_canonical[resource["project_id"]], {}))
        if resource["environment_id"] in render_to_canonical:
            edges.append(_edge("member_of_environment", resource["id"], render_to_canonical[resource["environment_id"]], {}))
        ordered = selected_candidates[resource["id"]]
        selected_raw = ordered[0]["config"]
        if resource["kind"] == "render.persistent_disk":
            blueprint_attachment = blueprint_disk_attachments.get(resource["id"])
            live_service_id = selected_raw.get("serviceId")
            live_owner_id = render_to_canonical.get(live_service_id) if isinstance(live_service_id, str) else None
            blueprint_owner_id = blueprint_attachment["service_id"] if blueprint_attachment else None
            if live_service_id is not None and live_owner_id is None:
                raise NormalizeError("disk_owner_unresolved")
            if live_owner_id is not None and blueprint_owner_id is not None and live_owner_id != blueprint_owner_id:
                raise NormalizeError("disk_attachment_conflict")
            owner_id = live_owner_id or blueprint_owner_id
            if owner_id is None:
                raise NormalizeError("disk_owner_unresolved")
            owner = next((item for item in resources if item["id"] == owner_id), None)
            if owner is None:
                raise NormalizeError("disk_owner_unresolved")
            declared_attributes = blueprint_attachment["attributes"] if blueprint_attachment else {}
            mount_path = selected_raw.get("mountPath", declared_attributes.get("mountPath"))
            size_gb = selected_raw.get("sizeGB", declared_attributes.get("sizeGB"))
            # Live captures always report the provisioned size; a Blueprint may rely on the
            # schema default, which the parser records as sizeGB_provenance "schema_default".
            if "sizeGB" in selected_raw:
                size_provenance = selected_raw.get("sizeGB_provenance", "declared")
            else:
                size_provenance = declared_attributes.get("sizeGB_provenance", "declared")
            if not isinstance(mount_path, str) or not mount_path.startswith("/") or not isinstance(size_gb, int) or isinstance(size_gb, bool) or size_gb <= 0:
                raise NormalizeError("disk_attachment_invalid")
            if size_provenance not in {"declared", "schema_default"}:
                raise NormalizeError("disk_attachment_invalid")
            if resource["region"] is not None and owner["region"] is not None and resource["region"] != owner["region"]:
                raise NormalizeError("disk_region_conflict")
            resource["region"] = owner["region"]
            resource["provenance"]["region"] = f"owning_service:{owner['id']}:{owner['provenance'].get('region', 'unknown')}"
            attributes = {
                "mountPath": mount_path,
                "sizeGB": size_gb,
                "sizeGB_provenance": size_provenance,
                "capacity_unit": "GB",
                "region": owner["region"],
                "region_provenance": resource["provenance"]["region"],
                "source": "live" if live_owner_id is not None else "declared",
            }
            edges.append(_edge("service_to_disk", owner_id, resource["id"], attributes))
        if resource["kind"] == "render.custom_domain":
            parent_id = next((entry["request"].get("resource_id") for entry in []), None)
            service_id = selected_raw.get("serviceId") or selected_raw.get("serverId") or parent_id
            if service_id in render_to_canonical:
                edges.append(_edge("custom_domain_routes_to", resource["id"], render_to_canonical[service_id], {}))
        if resource["kind"] == "render.build_source" and render_id:
            for service_id in selected_raw.get("serviceIds", []):
                if service_id not in render_to_canonical:
                    raise NormalizeError("build_source_service_unresolved")
                edges.append(_edge("service_uses_build_source", render_to_canonical[service_id], resource["id"], {}))
            artifact_candidates = [candidate for candidate in resources if any(item.get("build_source_id") == render_id for item in candidates if item["kind"] == candidate["kind"] and item["render_id"] == candidate["render_id"])]
            for artifact in artifact_candidates:
                edges.append(_edge("build_source_produces_artifact", resource["id"], artifact["id"], {"immutable": True}))
                for environment_id in selected_raw.get("environmentIds", []):
                    if environment_id in render_to_canonical:
                        edges.append(_edge("environment_promotes_artifact", render_to_canonical[environment_id], artifact["id"], {}))
        parent_edge = {
            "render.workflow_version": ("workflowId", "workflow_has_version"),
            "render.workflow_task": ("workflowVersionId", "workflow_version_has_task"),
            "render.task_run": ("taskId", "workflow_task_has_run"),
            "render.task_attempt": ("taskRunId", "task_run_has_attempt"),
        }.get(resource["kind"])
        if parent_edge:
            parent_id = selected_raw.get(parent_edge[0])
            if parent_id in render_to_canonical:
                edges.append(_edge(parent_edge[1], render_to_canonical[parent_id], resource["id"], {}))

    edge_ids: set[str] = set()
    unique_edges = []
    for edge in sorted(edges, key=lambda item: (byte_sort_key(item["type"]), byte_sort_key(item["from_id"]), byte_sort_key(item["to_id"]), byte_sort_key(item["id"]))):
        if edge["id"] in edge_ids:
            continue
        if edge["from_id"] not in seen_ids or edge["to_id"] not in seen_ids:
            raise NormalizeError("edge_endpoint_unresolved")
        edge_ids.add(edge["id"])
        unique_edges.append(edge)
    resources.sort(key=lambda item: byte_sort_key(item["id"]))
    drift.sort(key=lambda item: (byte_sort_key(item["resource_id"]), byte_sort_key(item["field"]), byte_sort_key(item["selected_source"]), byte_sort_key(item["other_source"])))
    inventory = {"schema_version": "1.0", "attempt_id": attempt_id, "workspace_id": workspace_id, "resources": resources, "edges": unique_edges, "drift": drift, "discovery_sources": sorted(discovery_sources, key=byte_sort_key), "accounting": {"resource_count": len(resources), "accounted_resource_ids": [item["id"] for item in resources]}, "billing": billing}

    adjacency: defaultdict[str, set[str]] = defaultdict(set)
    for edge in unique_edges:
        adjacency[edge["from_id"]].add(edge["to_id"])
        adjacency[edge["to_id"]].add(edge["from_id"])
    seed_groups: defaultdict[str, set[str]] = defaultdict(set)
    unseeded: set[str] = set()
    live_environment_ids = {candidate["render_id"] for candidate in candidates if candidate["kind"] == "render.environment" and candidate["render_id"] is not None}
    for resource in resources:
        environment_id = resource["environment_id"]
        if environment_id and environment_id not in live_environment_ids and resource["project_id"]:
            # Unresolved Blueprint environment names are only unique within their project.
            seed = f"{resource['project_id']}/{environment_id}"
        else:
            seed = environment_id or resource["project_id"]
        if seed:
            seed_groups[seed].add(resource["id"])
        else:
            unseeded.add(resource["id"])
    changed = True
    while changed:
        changed = False
        for resource_id in sorted(tuple(unseeded), key=byte_sort_key):
            matching = [seed for seed, members in seed_groups.items() if adjacency[resource_id] & members]
            if len(matching) == 1:
                seed_groups[matching[0]].add(resource_id)
                unseeded.remove(resource_id)
                changed = True
    clusters = []
    for seed, members in seed_groups.items():
        member_ids = sorted(members, key=byte_sort_key)
        clusters.append({"id": generated_id("rcl", "cluster", *member_ids), "seed": seed, "member_ids": member_ids})
    clusters.sort(key=lambda item: byte_sort_key(item["id"]))
    inventory_fingerprint = sha256_digest(canonical_bytes(inventory))
    cluster_output = {"schema_version": "1.0", "inventory_fingerprint": inventory_fingerprint, "clusters": clusters, "unclustered_resource_ids": sorted(unseeded, key=byte_sort_key)}
    accounted = [member for cluster in clusters for member in cluster["member_ids"]] + cluster_output["unclustered_resource_ids"]
    if sorted(accounted, key=byte_sort_key) != [item["id"] for item in resources] or len(accounted) != len(set(accounted)):
        raise NormalizeError("cluster_accounting_invalid")

    for schema_path, output in ((INVENTORY_SCHEMA, inventory), (CLUSTER_SCHEMA, cluster_output)):
        if list(Draft202012Validator(_schema(schema_path), format_checker=FormatChecker()).iter_errors(output)):
            raise NormalizeError("output_schema_invalid")
    if ai_profile is not None:
        if list(Draft7Validator(_schema(AI_PROFILE_SCHEMA)).iter_errors(ai_profile)):
            raise NormalizeError("ai_profile_invalid")
        if list(Draft202012Validator(_schema(AI_DISCOVERY_SCHEMA), format_checker=FormatChecker()).iter_errors(ai_discovery)):
            raise NormalizeError("ai_discovery_invalid")
    return inventory, cluster_output, ai_profile, ai_discovery


def ai_profile_digest(profile: dict[str, Any]) -> str:
    """SHA-256 of the exact bytes written to ai-workload-profile.json (canonical JSON)."""
    return sha256_digest(canonical_bytes(profile))


def _write_generation(outputs: list[tuple[Path, Any | None]]) -> None:
    """Stage all outputs and restore the complete prior generation on failure."""
    staged: dict[Path, Path] = {}
    previous: dict[Path, bytes | None] = {}
    try:
        for path, value in outputs:
            previous[path] = path.read_bytes() if path.exists() else None
            if value is None:
                continue
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.generation.", delete=False) as handle:
                handle.write(canonical_bytes(value))
                handle.flush()
                os.fsync(handle.fileno())
                staged[path] = Path(handle.name)
        for path, value in outputs:
            if value is None:
                path.unlink(missing_ok=True)
            else:
                os.replace(staged.pop(path), path)
        for directory in {path.parent for path, _ in outputs}:
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except Exception:
        for path, payload in previous.items():
            if payload is None:
                path.unlink(missing_ok=True)
                continue
            with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.rollback.", delete=False) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                rollback = handle.name
            os.replace(rollback, path)
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration-dir", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-inventory", type=Path, required=True)
    parser.add_argument("--output-clusters", type=Path, required=True)
    parser.add_argument("--output-ai-profile", type=Path, required=True)
    parser.add_argument("--output-ai-discovery", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        if not args.migration_dir.is_absolute() or not args.migration_dir.is_dir() or args.migration_dir.is_symlink():
            raise NormalizeError("migration_dir_invalid")
        for output in (args.output_inventory, args.output_clusters, args.output_ai_profile, args.output_ai_discovery):
            require_contained(output, args.migration_dir, "output")
        inventory, clusters, ai_profile, ai_discovery = normalize(args.migration_dir, args.manifest, args.attempt_id)
        # Both AI paths are always part of the transaction: absent AI evidence removes stale files atomically.
        _write_generation([
            (args.output_inventory, inventory),
            (args.output_clusters, clusters),
            (args.output_ai_profile, ai_profile),
            (args.output_ai_discovery, ai_discovery),
        ])
    except (NormalizeError, PathBoundaryError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, NormalizeError) else str(exc)
        if not code or any(character.isspace() for character in code):
            code = "internal_validation_error"
        print(f"NORMALIZE_FAIL | code={code}", file=sys.stderr)
        return 1
    print(f"NORMALIZE_OK | inventory={args.output_inventory} | clusters={args.output_clusters}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
