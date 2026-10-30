#!/usr/bin/env python3
"""Capture one bounded GET-only Render REST API category."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from render_common.atomic import PathBoundaryError, require_contained, write_json_atomic
from render_common.canonical import canonical_bytes, sha256_digest
from render_common.classifier import safe_literal

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = SKILL_ROOT / "references/shared/render-rest-contracts.json"
INDEX_SCHEMA_PATH = SKILL_ROOT / "references/shared/schema-ownership-index.json"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SENSITIVE_KEY = re.compile(r"(?i)(password|passwd|token|secret|credential|api[_-]?key|private[_-]?key|databaseUser|email|sshAddress|dashboardUrl|dsn|uri|^(?:message|body|details|content|value|connectionInfo|connectionString)$)")


class CaptureError(ValueError):
    def __init__(self, code: str, *, retryable: bool = False, retry_after: int | None = None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


class RedirectRejected(CaptureError):
    def __init__(self) -> None:
        super().__init__("redirect_rejected")


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Reject every redirect before urllib constructs or sends a target request."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        if code in {301, 302, 303, 307, 308}:
            raise RedirectRejected()
        raise RedirectRejected()


def _load_json(path: Path, maximum: int, code: str) -> tuple[Any, bytes]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CaptureError(code) from exc
    if len(data) > maximum:
        raise CaptureError(code)
    try:
        return json.loads(data.decode("utf-8", errors="strict")), data
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureError(code) from exc


def _contracts() -> dict[str, Any]:
    value, _ = _load_json(CONTRACT_PATH, 1024 * 1024, "contract_invalid")
    if not isinstance(value, dict) or value.get("origin") != "https://api.render.com":
        raise CaptureError("contract_invalid")
    return value


def _validate_uuid4(value: str) -> None:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise CaptureError("attempt_id_invalid") from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise CaptureError("attempt_id_invalid")


def _safe_id(value: str | None, code: str) -> str:
    if value is None or not ID_RE.fullmatch(value):
        raise CaptureError(code)
    return value


def _load_index(path: Path, migration_dir: Path, args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    try:
        require_contained(path, migration_dir, "ownership_index")
    except PathBoundaryError as exc:
        raise CaptureError(str(exc)) from exc
    value, data = _load_json(path, 2 * 1024 * 1024, "ownership_index_invalid")
    schema, _ = _load_json(INDEX_SCHEMA_PATH, 1024 * 1024, "ownership_schema_invalid")
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise CaptureError("ownership_index_invalid")
    if value["status"] != "active" or value["attempt_id"] != args.attempt_id or value["workspace_id"] != args.workspace_id or value["consent_digest"] != args.consent_digest:
        raise CaptureError("ownership_index_mismatch")
    seen: set[tuple[str, str]] = set()
    for item in value["resources"]:
        key = (item["kind"], item["id"])
        if key in seen or item["workspace_id"] != args.workspace_id:
            raise CaptureError("ownership_index_invalid")
        seen.add(key)
    return value, sha256_digest(data)


def _resource_owned(index: dict[str, Any], resource_id: str, allowed_kind: str) -> bool:
    return any(
        item["id"] == resource_id
        and item["workspace_id"] == index["workspace_id"]
        and (allowed_kind == "any" or item["kind"] in {allowed_kind, "any"})
        for item in index["resources"]
    )


def _parse_utc(value: str | None, code: str) -> datetime:
    if value is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise CaptureError(code)
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CaptureError(code) from exc


def _build_url(args: argparse.Namespace, contract: dict[str, Any], index: dict[str, Any], cursor: str | None = None) -> str:
    row = contract["categories"].get(args.category)
    if row is None:
        raise CaptureError("unsupported_category")
    if not row.get("active"):
        raise CaptureError("unsupported_contract")
    resource_id: str | None = None
    path = row["path"]
    scope = row["scope"]
    if "{resource_id}" in path or scope in {"resource", "metric", "workflow_child", "parent"}:
        resource_id = _safe_id(args.resource_id, "resource_id_invalid")
    elif args.resource_id is not None:
        raise CaptureError("argument_not_allowed")
    kind = row.get("resource_kind", "any")
    if scope in {"resource", "metric", "workflow_child"} and not _resource_owned(index, resource_id, kind):
        raise CaptureError("resource_not_owned")
    if "{resource_id}" in path:
        path = path.replace("{resource_id}", urllib.parse.quote(resource_id, safe=""))

    query: list[tuple[str, str]] = []
    if scope == "workspace":
        query.append(("ownerId", args.workspace_id))
    elif scope == "parent":
        if not _resource_owned(index, resource_id, "project"):
            raise CaptureError("resource_not_owned")
        query.append((row["parent_query"], resource_id))
    elif scope == "workflow_child":
        query.extend((("ownerId", args.workspace_id), ("workflowId", resource_id)))
    if scope == "metric" or args.category == "service_events":
        start = _parse_utc(args.start, "start_invalid")
        end = _parse_utc(args.end, "end_invalid")
        if start >= end or (end - start).total_seconds() > 24 * 60 * 60:
            raise CaptureError("window_invalid")
        query.extend((("startTime", args.start), ("endTime", args.end)))
        if scope == "metric":
            if args.resolution_seconds not in {30, 60, 300, 3600}:
                raise CaptureError("resolution_invalid")
            query.extend((("resource", resource_id), ("resolutionSeconds", str(args.resolution_seconds))))
        elif args.event_type is not None:
            if not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", args.event_type):
                raise CaptureError("event_type_invalid")
            query.append(("type", args.event_type))
    elif args.start is not None or args.end is not None or args.resolution_seconds is not None or args.event_type is not None:
        raise CaptureError("argument_not_allowed")

    allowed_query = set(row["allowed_query"])
    if args.limit is not None:
        if "limit" not in allowed_query:
            raise CaptureError("argument_not_allowed")
        if not 1 <= args.limit <= 100:
            raise CaptureError("limit_invalid")
        query.append(("limit", str(args.limit)))
    elif "limit" in allowed_query:
        query.append(("limit", "100"))
    if cursor is not None:
        if "cursor" not in allowed_query or not re.fullmatch(r"[A-Za-z0-9._~-]{1,512}", cursor):
            raise CaptureError("cursor_invalid")
        query.append(("cursor", cursor))
    names = {key for key, _ in query}
    if not set(row["required_query"]) <= names or names - allowed_query:
        raise CaptureError("query_contract_invalid")
    encoded = urllib.parse.urlencode(query, doseq=True)
    url = contract["origin"] + path + ("?" + encoded if encoded else "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.render.com" or not parsed.path.startswith("/v1/"):
        raise CaptureError("url_not_allowed")
    return url


def _read_bounded(response: Any, limits: dict[str, int]) -> bytes:
    started = time.monotonic()
    wire = bytearray()
    while True:
        if time.monotonic() - started > limits["response_seconds"]:
            raise CaptureError("response_timeout", retryable=True)
        chunk = response.read(64 * 1024)
        if not chunk:
            break
        wire.extend(chunk)
        if len(wire) > limits["wire_bytes"]:
            raise CaptureError("wire_limit_exceeded")
    encoding = (response.headers.get("Content-Encoding", "") or "").lower()
    try:
        if encoding in {"gzip", "deflate"}:
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS)
            output = bytearray()
            for offset in range(0, len(wire), 64 * 1024):
                output.extend(decompressor.decompress(wire[offset : offset + 64 * 1024], limits["decompressed_bytes"] + 1 - len(output)))
                if len(output) > limits["decompressed_bytes"] or decompressor.unconsumed_tail:
                    raise CaptureError("decompressed_limit_exceeded")
            output.extend(decompressor.flush(limits["decompressed_bytes"] + 1 - len(output)))
            data = bytes(output)
        elif encoding in {"", "identity"}:
            data = bytes(wire)
        else:
            raise CaptureError("content_encoding_unsupported")
    except zlib.error as exc:
        raise CaptureError("decompression_failed") from exc
    if len(data) > limits["decompressed_bytes"]:
        raise CaptureError("decompressed_limit_exceeded")
    return data


def _json_bounded(data: bytes, limits: dict[str, int]) -> Any:
    try:
        value = json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureError("invalid_json") from exc
    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > limits["json_nodes"]:
            raise CaptureError("json_node_limit_exceeded")
        if depth > limits["json_depth"]:
            raise CaptureError("json_depth_limit_exceeded")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def _owner_id(value: dict[str, Any]) -> str | None:
    if isinstance(value.get("ownerId"), str):
        return value["ownerId"]
    owner = value.get("owner")
    if isinstance(owner, dict) and isinstance(owner.get("id"), str):
        return owner["id"]
    return None


def _assert_no_sensitive(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if SENSITIVE_KEY.search(str(key)):
                raise CaptureError("secret_bearing_response")
            _assert_no_sensitive(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_sensitive(item)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _scrub(item) for key, item in value.items() if str(key) not in {"email", "dashboardUrl", "sshAddress"}}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _event(value: Any, resource_id: str) -> dict[str, Any]:
    allowed = {"id", "resourceId", "type", "timestamp", "statusCode"}
    if not isinstance(value, dict) or set(value) - allowed or not {"id", "resourceId", "type", "timestamp"} <= set(value):
        raise CaptureError("capability_drift")
    if value["resourceId"] != resource_id:
        raise CaptureError("ownership_mismatch")
    if not all(isinstance(value[key], str) for key in ("id", "resourceId", "type", "timestamp")):
        raise CaptureError("unexpected_envelope")
    if "statusCode" in value and not isinstance(value["statusCode"], int):
        raise CaptureError("unexpected_envelope")
    return _classify_retained_values({key: value[key] for key in ("id", "resourceId", "type", "timestamp", "statusCode") if key in value})


def _classify_retained_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _classify_retained_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_classify_retained_values(item) for item in value]
    if isinstance(value, str):
        classified = safe_literal(value)
        if classified == "[REDACTED]":
            raise CaptureError("secret_bearing_response")
        return classified
    return value


def _build_source(value: Any, workspace_id: str) -> dict[str, Any]:
    allowed = {"id", "name", "ownerId", "repo", "branch", "commit", "artifact", "buildCommand", "serviceIds", "environmentIds", "buildEnvVarNames", "runtimeEnvVarNames"}
    required = {"id", "name", "ownerId", "repo", "branch", "serviceIds"}
    if not isinstance(value, dict) or set(value) - allowed or not required <= set(value):
        raise CaptureError("capability_drift")
    if value["ownerId"] != workspace_id:
        raise CaptureError("ownership_mismatch")
    for key in required - {"serviceIds"}:
        if not isinstance(value[key], str):
            raise CaptureError("unexpected_envelope")
    for key in ("serviceIds", "environmentIds", "buildEnvVarNames", "runtimeEnvVarNames"):
        if key in value and (not isinstance(value[key], list) or not all(isinstance(item, str) for item in value[key])):
            raise CaptureError("unexpected_envelope")
    if "artifact" in value:
        artifact = value["artifact"]
        if not isinstance(artifact, dict) or set(artifact) - {"id", "digest"} or not {"id", "digest"} <= set(artifact) or not all(isinstance(item, str) for item in artifact.values()):
            raise CaptureError("capability_drift")
    return _classify_retained_values(_scrub(value))


def _metric_series(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CaptureError("unexpected_envelope")
    result = []
    for series in value:
        if not isinstance(series, dict) or set(series) != {"labels", "unit", "values"} or not isinstance(series["labels"], list) or not isinstance(series["values"], list) or not isinstance(series["unit"], str):
            raise CaptureError("unexpected_envelope")
        labels = []
        for label in series["labels"]:
            if not isinstance(label, dict) or set(label) != {"field", "value"} or not all(isinstance(item, str) for item in label.values()):
                raise CaptureError("unexpected_envelope")
            labels.append(label)
        points = []
        for point in series["values"]:
            if not isinstance(point, dict) or set(point) != {"timestamp", "value"} or not isinstance(point["timestamp"], str) or not isinstance(point["value"], (int, float)):
                raise CaptureError("unexpected_envelope")
            points.append(point)
        result.append({"labels": labels, "unit": series["unit"], "values": points})
    return _classify_retained_values(result)


def _unwrap(value: Any, envelope: str, args: argparse.Namespace) -> tuple[list[Any], str, str | None]:
    if envelope == "direct_array":
        if not isinstance(value, list):
            raise CaptureError("unexpected_envelope")
        return value, "array", None
    if envelope == "metric_series":
        return _metric_series(value), "metric_series", None
    if envelope == "cursor_workflow_or_null" and value is None:
        return [], "null", None
    if envelope in {"cursor_disk_or_empty", "cursor_build_source_or_empty"} and value == []:
        return [], "array", None
    if envelope.startswith("direct_"):
        if not isinstance(value, dict):
            raise CaptureError("unexpected_envelope")
        return [value], "object", None
    wrapper_by_envelope = {
        "cursor_owner": "owner", "cursor_project": "project", "cursor_environment": "environment",
        "cursor_service": "service", "cursor_postgres": "postgres", "cursor_key_value": "keyValue",
        "cursor_disk_or_empty": "disk", "cursor_deploy": "deploy", "cursor_event": "event",
        "cursor_build_source_or_empty": "buildSource", "cursor_env_group": "envGroup",
        "cursor_workflow_or_null": "workflow", "cursor_workflow_version": "workflowVersion",
        "cursor_task": "task", "cursor_task_run": "taskRun",
    }
    wrapper = wrapper_by_envelope.get(envelope)
    if wrapper is None or not isinstance(value, list):
        raise CaptureError("unexpected_envelope")
    items, cursors = [], []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"cursor", wrapper} or not isinstance(entry["cursor"], str) or not isinstance(entry[wrapper], dict):
            raise CaptureError("unexpected_envelope")
        cursors.append(entry["cursor"])
        items.append(entry[wrapper])
    return items, "cursor_array", cursors[-1] if cursors else None


CORE_FIELDS: dict[str, set[str]] = {
    "project": {"id", "name", "owner", "ownerId", "environmentIds", "createdAt", "updatedAt"},
    "environment": {"id", "name", "projectId", "protectedStatus", "networkIsolationEnabled", "ipAllowList", "serviceIds", "databasesIds", "redisIds", "envGroupIds", "createdAt", "updatedAt"},
    "service": {"id", "name", "owner", "ownerId", "type", "slug", "repo", "branch", "rootDir", "imagePath", "environmentId", "projectId", "region", "autoDeploy", "autoDeployTrigger", "createdAt", "updatedAt", "serviceDetails", "liveDeployId"},
    "disk": {"id", "name", "serviceId", "sizeGB", "mountPath", "createdAt", "updatedAt"},
    "domain": {"id", "name", "domain", "serverId", "serviceId", "redirectForName", "verificationStatus", "createdAt", "updatedAt"},
    "deploy": {"id", "serviceId", "status", "createdAt", "updatedAt", "startedAt", "finishedAt", "trigger", "commit", "image", "rollbackOfId"},
    "environment_group": {"id", "name", "ownerId", "environmentId", "serviceLinks", "createdAt", "updatedAt"},
    "workflow": {"id", "name", "owner", "ownerId", "type", "environmentId", "projectId", "region", "repo", "branch", "rootDir", "runtime", "startCommand", "trigger", "schedule", "createdAt", "updatedAt"},
    "workflow_version": {"id", "name", "ownerId", "workflowId", "version", "createdAt", "updatedAt"},
    "workflow_task": {"id", "name", "ownerId", "workflowId", "workflowVersionId", "parentTaskId", "runtime", "timeoutSeconds", "retry", "createdAt", "updatedAt"},
    "workflow_task_run": {"id", "name", "ownerId", "workflowId", "taskId", "status", "requestedAt", "startedAt", "finishedAt", "attempts", "createdAt", "updatedAt"},
}
NESTED_FIELDS = {
    "id", "name", "type", "ownerId", "field", "value", "cidrBlock", "description", "plan", "buildPlan", "env", "runtime", "envSpecificDetails", "buildCommand", "startCommand", "dockerCommand", "dockerContext", "dockerfilePath", "numInstances", "schedule", "openPorts", "port", "protocol", "url", "healthCheckPath", "previews", "pullRequestPreviewsEnabled", "renderSubdomainPolicy", "publishPath", "staticPublishPath", "disk", "sizeGB", "mountPath", "ref", "sha", "createdAt", "updatedAt", "status", "attempts", "taskRunId", "retry", "maxAttempts", "backoffSeconds",
}


def _closed_core(value: Any, projection: str) -> dict[str, Any]:
    cleaned = _scrub(value)
    if not isinstance(cleaned, dict) or set(cleaned) - CORE_FIELDS[projection]:
        raise CaptureError("capability_drift")

    def check_nested(item: Any) -> None:
        if isinstance(item, dict):
            if set(item) - NESTED_FIELDS:
                raise CaptureError("capability_drift")
            for child in item.values():
                check_nested(child)
        elif isinstance(item, list):
            for child in item:
                check_nested(child)

    for key, item in cleaned.items():
        if key not in {"id", "name", "ownerId", "type", "slug", "repo", "branch", "rootDir", "imagePath", "environmentId", "projectId", "region", "autoDeploy", "autoDeployTrigger", "createdAt", "updatedAt", "startedAt", "finishedAt", "trigger", "domain", "serverId", "serviceId", "redirectForName", "verificationStatus", "environmentIds", "serviceIds", "databasesIds", "redisIds", "envGroupIds", "workflowId", "workflowVersionId", "parentTaskId", "taskId", "status", "requestedAt", "version", "runtime", "startCommand", "schedule", "timeoutSeconds", "liveDeployId", "rollbackOfId"}:
            check_nested(item)
    _assert_no_sensitive(cleaned)
    return _classify_retained_values(cleaned)


def _project(items: list[Any], row: dict[str, Any], args: argparse.Namespace, index: dict[str, Any]) -> list[Any]:
    result: list[Any] = []
    for item in items:
        if row.get("strict_projection") == "event":
            result.append(_event(item, args.resource_id))
            continue
        if row.get("strict_projection") == "build_source":
            projected = _build_source(item, args.workspace_id)
            for service_id in projected["serviceIds"]:
                if not _resource_owned(index, service_id, "service"):
                    raise CaptureError("ownership_mismatch")
            result.append(projected)
            continue
        if row.get("envelope") == "metric_series":
            result.append(item)
            continue
        projection = row.get("strict_projection")
        if projection in CORE_FIELDS:
            projected = _closed_core(item, projection)
            owner_id = _owner_id(projected)
            owner_required = projection in {"project", "service", "environment_group", "workflow"}
            if owner_required and owner_id is None:
                raise CaptureError("ownership_unproven")
            if owner_id is not None and owner_id != args.workspace_id:
                raise CaptureError("ownership_mismatch")
            if projection == "disk":
                service_id = projected.get("serviceId")
                if not isinstance(service_id, str) or not _resource_owned(index, service_id, "service"):
                    raise CaptureError("ownership_mismatch")
            expected_parent: tuple[str, bool] | None = None
            if args.category == "environments_list":
                expected_parent = ("projectId", True)
            elif args.category in {"custom_domains", "deploys_list"}:
                expected_parent = ("serviceId", False)
            elif args.category in {"workflow_versions_list", "workflow_tasks_list", "workflow_task_runs_list"}:
                expected_parent = ("workflowId", True)
            if expected_parent is not None:
                parent_field, required = expected_parent
                actual_parent = projected.get(parent_field)
                if (required and not isinstance(actual_parent, str)) or (
                    actual_parent is not None and actual_parent != args.resource_id
                ):
                    raise CaptureError("ownership_mismatch")
            result.append(projected)
            continue
        raise CaptureError("projection_contract_missing")
    return result


def _http_status(error: urllib.error.HTTPError, row: dict[str, Any], data: bytes) -> tuple[str, list[Any]]:
    if error.code in {301, 302, 303, 307, 308}:
        raise RedirectRejected()
    if error.code == 404 and row.get("not_found_status") == "absent":
        return "absent", []
    if error.code == 400 and 400 in row.get("allowed_statuses", []):
        try:
            body = json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaptureError("invalid_query") from exc
        for adapter in row.get("status_400_adapters", []):
            if body == adapter.get("body"):
                return adapter["status"], []
        raise CaptureError("invalid_query")
    if error.code == 401:
        raise CaptureError("authentication")
    if error.code == 403:
        raise CaptureError("forbidden_unknown")
    if error.code == 429 or 500 <= error.code <= 599:
        retry_after: int | None = None
        raw_retry = error.headers.get("Retry-After") if error.headers is not None else None
        if isinstance(raw_retry, str) and raw_retry.isdigit():
            retry_after = int(raw_retry)
        raise CaptureError("transient_http", retryable=True, retry_after=retry_after)
    raise CaptureError("http_status_rejected")


def _open_once(opener: Any, request: urllib.request.Request, timeout: int, limits: dict[str, int], row: dict[str, Any]) -> tuple[int, bytes]:
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(response.getcode())
            if status in {301, 302, 303, 307, 308}:
                raise RedirectRejected()
            if status != 200:
                raise CaptureError("http_status_rejected")
            return status, _read_bounded(response, limits)
    except RedirectRejected:
        raise
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read(min(limits["wire_bytes"], 64 * 1024))
        except OSError:
            pass
        status_name, _ = _http_status(exc, row, body)
        return exc.code, status_name.encode()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CaptureError("transport_transient", retryable=True) from exc


def capture(args: argparse.Namespace, opener: Any | None = None, sleeper: Any = time.sleep) -> dict[str, Any]:
    contract = _contracts()
    limits = contract["limits"]
    _validate_uuid4(args.attempt_id)
    _safe_id(args.workspace_id, "workspace_id_invalid")
    if not DIGEST_RE.fullmatch(args.consent_digest):
        raise CaptureError("consent_digest_invalid")
    index, index_digest = _load_index(args.ownership_index, args.migration_dir, args)
    try:
        require_contained(args.output, args.ownership_index.parent, "output_outside_attempt_root")
    except PathBoundaryError as exc:
        raise CaptureError(str(exc)) from exc
    row = contract["categories"].get(args.category)
    if row is None:
        raise CaptureError("unsupported_category")
    if not row.get("active"):
        raise CaptureError("unsupported_contract")
    api_key = os.environ.get("RENDER_API_KEY")
    if not api_key or any(character in api_key for character in "\r\n\x00"):
        raise CaptureError("api_key_missing")
    opener = opener or urllib.request.build_opener(RejectRedirects())
    all_items: list[Any] = []
    raw_shapes: list[str] = []
    seen_cursors: set[str] = set()
    cursor: str | None = None
    status_name = "ok"
    page_count = 0
    for _page in range(limits["pages"]):
        url = _build_url(args, contract, index, cursor)
        request = urllib.request.Request(url, method="GET", headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "Accept-Encoding": "gzip"})
        last_error: CaptureError | None = None
        for retry in range(limits["retries"] + 1):
            try:
                status, data = _open_once(opener, request, limits["response_seconds"], limits, row)
                last_error = None
                break
            except CaptureError as exc:
                last_error = exc
                if not exc.retryable or retry >= limits["retries"]:
                    raise
                delay = exc.retry_after if exc.retry_after is not None else 2**retry
                sleeper(min(delay, limits["retry_after_seconds"]))
        if last_error is not None:
            raise last_error
        page_count += 1
        if status != 200:
            status_name = data.decode("ascii")
            raw_shapes.append(f"http_{status}")
            break
        value = _json_bounded(data, limits)
        items, raw_shape, next_cursor = _unwrap(value, row["envelope"], args)
        raw_shapes.append(raw_shape)
        projected = _project(items, row, args, index)
        all_items.extend(projected)
        if not items or next_cursor is None:
            break
        if next_cursor in seen_cursors:
            raise CaptureError("cursor_loop")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    else:
        raise CaptureError("page_limit_exceeded")
    if not all_items and status_name == "ok":
        status_name = "successful_empty"
    request_meta = {
        "resource_id": args.resource_id,
        "start": args.start,
        "end": args.end,
        "resolution_seconds": args.resolution_seconds,
        "event_type": args.event_type,
        "limit": args.limit or (100 if "limit" in row["allowed_query"] else None),
    }
    result = {
        "schema_version": "1.0", "transport": "render_rest_v1", "category": args.category,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "attempt_id": args.attempt_id, "workspace_id": args.workspace_id, "consent_digest": args.consent_digest,
        "ownership_index_digest": index_digest, "status": status_name, "page_count": page_count,
        "raw_shapes": raw_shapes, "request": request_meta, "data": all_items,
    }
    payload_size = len(canonical_bytes(result))
    if payload_size > limits["category_bytes"]:
        raise CaptureError("category_output_limit_exceeded")
    total = 0
    for candidate in args.ownership_index.parent.rglob("*"):
        if candidate == args.output or candidate.is_symlink() or not candidate.is_file():
            continue
        total += candidate.stat().st_size
        if total + payload_size > limits["attempt_bytes"]:
            raise CaptureError("attempt_output_limit_exceeded")
    if total + payload_size > limits["attempt_bytes"]:
        raise CaptureError("attempt_output_limit_exceeded")
    return result


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--consent-digest", required=True)
    parser.add_argument("--ownership-index", type=Path, required=True)
    parser.add_argument("--migration-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resource-id")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--resolution-seconds", type=int)
    parser.add_argument("--event-type")
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        if not args.migration_dir.is_absolute() or not args.migration_dir.is_dir() or args.migration_dir.is_symlink():
            raise CaptureError("migration_dir_invalid")
        require_contained(args.output, args.migration_dir, "output")
        result = capture(args)
        write_json_atomic(args.output, args.migration_dir, result)
    except (CaptureError, PathBoundaryError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, CaptureError) else str(exc)
        if not code or any(character.isspace() for character in code):
            code = "internal_validation_error"
        print(f"API_CAPTURE_FAIL | code={code}", file=sys.stderr)
        return 1
    print(f"API_CAPTURE_OK | category={args.category} | output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
