#!/usr/bin/env python3
"""Capture one exact read-only Render CLI 2.30.0 category."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

from render_common.atomic import PathBoundaryError, require_contained, write_json_atomic
from render_common.canonical import sha256_digest
from render_common.classifier import safe_literal, sanitize_config

SKILL_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = SKILL_ROOT / "references/shared/render-cli-contracts.json"
INDEX_SCHEMA_PATH = SKILL_ROOT / "references/shared/schema-ownership-index.json"
EXPECTED_VERSION = "2.30.0"
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION_RE = re.compile(rb"(?:render\s+)?v?([0-9]+\.[0-9]+\.[0-9]+)", re.I)
ALLOWED_ENV = {
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
}
SENSITIVE_KEY = re.compile(r"(?i)(password|passwd|token|secret|credential|api[_-]?key|private[_-]?key|databaseUser|email|sshAddress|dashboardUrl|dsn|uri|^(?:message|body|details|content|value|connectionInfo|connectionString)$)")


class CaptureError(ValueError):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def child_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Return the exact reviewed child environment; never inherit credentials."""
    source = os.environ if source is None else source
    result: dict[str, str] = {}
    for key in sorted(ALLOWED_ENV):
        value = source.get(key)
        if value is None or "\x00" in value:
            continue
        if key.lower().endswith("proxy"):
            parsed = urlsplit(value)
            if parsed.username is not None or parsed.password is not None:
                continue
        result[key] = value
    return result


def _contracts() -> dict[str, Any]:
    try:
        value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureError("contract_invalid") from exc
    if value.get("render_cli_version") != EXPECTED_VERSION or not isinstance(value.get("categories"), dict):
        raise CaptureError("contract_invalid")
    return value


def _uuid4(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise CaptureError("attempt_id_invalid") from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise CaptureError("attempt_id_invalid")
    return str(parsed)


def _safe_id(value: str | None, code: str) -> str:
    if value is None or not ID_RE.fullmatch(value):
        raise CaptureError(code)
    return value


def _utc(value: str | None, code: str) -> datetime:
    if value is None or not value.endswith("Z"):
        raise CaptureError(code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CaptureError(code) from exc
    if parsed.microsecond:
        raise CaptureError(code)
    return parsed


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _run(argv: list[str], timeout: int, maximum: int, env: dict[str, str]) -> bytes:
    """Drain both child pipes concurrently and enforce one live combined cap."""
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
            env=env,
        )
    except OSError as exc:
        raise CaptureError("process_start_failed", retryable=True) from exc
    if process.stdout is None or process.stderr is None:
        _stop_process(process)
        raise CaptureError("process_pipe_failed")

    chunks: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
    state = {"bytes": 0, "overflow": False, "read_error": False}
    lock = threading.Lock()

    def drain(name: str, stream: Any) -> None:
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    chunk = chunk.encode("utf-8", errors="strict")
                with lock:
                    state["bytes"] += len(chunk)
                    if state["bytes"] > maximum:
                        state["overflow"] = True
                        return
                    chunks[name].append(chunk)
        except (OSError, UnicodeError):
            state["read_error"] = True

    threads = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    while any(thread.is_alive() for thread in threads) or process.poll() is None:
        if state["overflow"]:
            _stop_process(process)
            for thread in threads:
                thread.join(timeout=2)
            raise CaptureError("output_limit_exceeded")
        if time.monotonic() >= deadline:
            _stop_process(process)
            for thread in threads:
                thread.join(timeout=2)
            raise CaptureError("process_timeout", retryable=True)
        time.sleep(0.01)
    for thread in threads:
        thread.join(timeout=2)
    if state["overflow"]:
        if process.poll() is None:
            _stop_process(process)
        raise CaptureError("output_limit_exceeded")
    if state["read_error"]:
        raise CaptureError("process_read_failed", retryable=True)
    if process.returncode != 0:
        raise CaptureError("process_failed", retryable=False)
    return b"".join(chunks["stdout"])


def _parse_json(data: bytes) -> Any:
    try:
        return json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureError("invalid_json") from exc


def _parse_stream(data: bytes, limit: int) -> list[Any]:
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CaptureError("invalid_utf8") from exc
    decoder = json.JSONDecoder()
    position = 0
    values: list[Any] = []
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position == len(text):
            break
        try:
            value, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError as exc:
            raise CaptureError("invalid_json_stream") from exc
        values.append(value)
        if len(values) > limit:
            raise CaptureError("item_limit_exceeded")
    return values


def _shape(value: Any, expected: str) -> str:
    if expected == "direct_object" and isinstance(value, dict):
        return "object"
    if expected == "nullable_direct_object" and (value is None or isinstance(value, dict)):
        return "null" if value is None else "object"
    if expected == "array" and isinstance(value, list):
        return "array"
    if expected in {"nullable_array", "nullable_wrapper_array"} and (value is None or isinstance(value, list)):
        return "null" if value is None else "array"
    if expected == "data_array" and isinstance(value, dict) and set(value) == {"data"} and isinstance(value["data"], list):
        return "data_array"
    if expected in {"data_object", "data_nullable_object"} and isinstance(value, dict) and set(value) == {"data"}:
        if isinstance(value["data"], dict):
            return "data_object"
        if expected == "data_nullable_object" and value["data"] is None:
            return "data_null"
    if expected == "blueprint_validation" and isinstance(value, dict) and isinstance(value.get("valid"), bool):
        return "blueprint_validation"
    raise CaptureError("unexpected_envelope")


def _sanitize(value: Any, *, parent: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if SENSITIVE_KEY.search(key_text):
                continue
            if parent in {"envVars", "secretFiles"} or key_text in {"envVars", "secretFiles"}:
                if isinstance(item, list):
                    result[key_text] = [
                        {"key": entry["key"]} for entry in item
                        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
                    ]
                continue
            result[key_text] = _sanitize(item, parent=key_text)
        return sanitize_config(result)
    if isinstance(value, list):
        return [_sanitize(item, parent=parent) for item in value]
    return value


def _assert_closed_projection(value: Any) -> None:
    """Reject capability drift instead of persisting unreviewed response fields."""
    allowed = {
        "service", "postgres", "keyValue", "workflow", "data", "valid", "plan", "totalActions",
        "authenticated", "id", "name", "type", "owner", "ownerId", "ownerType", "slug",
        "projectId", "environmentId", "environmentIds", "workspaceId", "region", "status", "role",
        "createdAt", "updatedAt", "finishedAt", "startedAt", "requestedAt", "expiresAt", "suspended",
        "suspenders", "connectionPool", "highAvailabilityEnabled", "readReplicas", "diskAutoscalingEnabled",
        "ipAllowList", "cidrBlock", "description", "maxmemoryPolicy", "persistenceMode", "options",
        "repo", "branch", "rootDir", "imagePath", "image", "ref", "sha", "commit", "runtime",
        "autoDeploy", "autoDeployTrigger", "serviceDetails", "buildPlan", "env", "envSpecificDetails",
        "buildCommand", "startCommand", "dockerCommand", "dockerContext", "dockerfilePath", "numInstances",
        "schedule", "openPorts", "port", "protocol", "url", "healthCheckPath", "previews",
        "pullRequestPreviewsEnabled", "renderSubdomainPolicy", "publishPath", "staticPublishPath", "disk",
        "sizeGB", "mountPath", "serviceId", "deployId", "trigger", "live", "deactivatedAt", "attempts",
        "taskId", "taskRunId", "workflowId", "workflowVersionId", "version", "language", "timeoutSeconds",
        "retry", "stateRetention", "serviceIds", "databasesIds", "redisIds", "envGroupIds", "protectedStatus",
        "networkIsolationEnabled", "serviceLinks", "key", "envVars", "secretFiles", "labels", "field", "value",
    }
    if isinstance(value, dict):
        unknown = set(value) - allowed
        if unknown:
            raise CaptureError("capability_drift")
        for item in value.values():
            _assert_closed_projection(item)
    elif isinstance(value, list):
        for item in value:
            _assert_closed_projection(item)


def _project_cli(value: Any, category: str) -> Any:
    if category == "auth_whoami":
        if not isinstance(value, dict):
            raise CaptureError("unexpected_envelope")
        return {"authenticated": True}
    projected = _sanitize(value)
    _assert_closed_projection(projected)
    return projected


def _retained_log_string(value: str) -> str:
    sanitized = safe_literal(value)
    if sanitized == "[REDACTED]":
        raise CaptureError("secret_bearing_response")
    return sanitized


def _project_log_metadata(values: list[Any]) -> list[dict[str, Any]]:
    projected = []
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not isinstance(value.get("timestamp"), str):
            raise CaptureError("unexpected_envelope")
        labels = value.get("labels", [])
        if not isinstance(labels, list):
            raise CaptureError("unexpected_envelope")
        safe_labels = []
        for label in labels:
            if not isinstance(label, dict) or set(label) - {"name", "value"} or not isinstance(label.get("name"), str) or not isinstance(label.get("value"), str):
                raise CaptureError("unexpected_envelope")
            name = _retained_log_string(label["name"])
            label_value = _retained_log_string(label["value"])
            if name in {"resource", "instance", "level", "type"}:
                safe_labels.append({"name": name, "value": label_value})
        projected.append({
            "id": _retained_log_string(value["id"]),
            "timestamp": _retained_log_string(value["timestamp"]),
            "labels": safe_labels,
        })
    return projected


def build_argv(args: argparse.Namespace, contract: dict[str, Any], executable: str) -> tuple[list[str], str]:
    categories = contract["categories"]
    if args.category not in categories:
        raise CaptureError("unsupported_category")
    row = categories[args.category]
    required = {token[1:-1] for token in row["argv"] if token.startswith("{") and token.endswith("}")}
    values: dict[str, str] = {"workspace_id": _safe_id(args.workspace_id, "workspace_id_invalid")}
    if "resource_id" in required:
        values["resource_id"] = _safe_id(args.resource_id, "resource_id_invalid")
    elif args.resource_id is not None:
        raise CaptureError("argument_not_allowed")
    if "blueprint" in required:
        if args.blueprint is None or args.workspace_root is None or not args.workspace_root.is_absolute():
            raise CaptureError("blueprint_invalid")
        try:
            root = args.workspace_root.resolve(strict=True)
            resolved = args.blueprint.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise CaptureError("blueprint_invalid") from exc
        if args.workspace_root.is_symlink() or args.blueprint.is_symlink() or not args.blueprint.is_file() or args.blueprint.stat().st_size > 2 * 1024 * 1024:
            raise CaptureError("blueprint_invalid")
        values["blueprint"] = str(resolved)
    elif args.blueprint is not None or args.workspace_root is not None:
        raise CaptureError("argument_not_allowed")
    if {"start", "end"} & required:
        start = _utc(args.start, "start_invalid")
        end = _utc(args.end, "end_invalid")
        if start >= end or (end - start).total_seconds() > 24 * 60 * 60:
            raise CaptureError("window_invalid")
        values.update(start=args.start, end=args.end)
    elif args.start is not None or args.end is not None:
        raise CaptureError("argument_not_allowed")
    if "limit" in required:
        if args.limit is None or not 1 <= args.limit <= 100:
            raise CaptureError("limit_invalid")
        values["limit"] = str(args.limit)
    elif args.limit is not None:
        raise CaptureError("argument_not_allowed")
    argv = [executable]
    for token in row["argv"]:
        argv.append(values.get(token[1:-1], token) if token.startswith("{") else token)
    return argv, row["shape"]


CHILD_RESOURCE_KINDS = {
    "environments_list": "project",
    "service_get": "service",
    "service_instances": "service",
    "deploys_list": "service",
    "postgres_get": "postgres",
    "keyvalue_get": "key_value",
    "workflow_versions_list": "workflow",
    "workflow_tasks_list": "workflow_version",
    "workflow_task_runs_list": "task",
    "workflow_task_run_show": "task_run",
    "jobs_list": "service",
    "log_metadata": "service",
}


def _load_ownership_index(args: argparse.Namespace) -> tuple[dict[str, Any] | None, str | None]:
    expected_kind = CHILD_RESOURCE_KINDS.get(args.category)
    if args.ownership_index is None:
        if expected_kind is not None:
            raise CaptureError("ownership_index_required")
        return None, None
    try:
        require_contained(args.ownership_index, args.migration_dir, "ownership_index")
        raw = args.ownership_index.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
        schema = json.loads(INDEX_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (PathBoundaryError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaptureError("ownership_index_invalid") from exc
    if list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)):
        raise CaptureError("ownership_index_invalid")
    if (
        value["status"] != "active"
        or value["attempt_id"] != args.attempt_id
        or value["workspace_id"] != args.workspace_id
        or value["consent_digest"] != args.consent_digest
    ):
        raise CaptureError("ownership_index_mismatch")
    if expected_kind is not None:
        matches = [
            item for item in value["resources"]
            if item["id"] == args.resource_id
            and item["workspace_id"] == args.workspace_id
            and item["kind"] in {expected_kind, "any"}
        ]
        if len(matches) != 1:
            raise CaptureError("resource_not_owned")
    return value, sha256_digest(raw)


def _index_item(index: dict[str, Any], resource_id: str) -> dict[str, Any] | None:
    matches = [item for item in index["resources"] if item["id"] == resource_id]
    return matches[0] if len(matches) == 1 else None


def _validate_ownership(
    value: Any,
    category: str,
    workspace_id: str,
    requested_id: str | None,
    index: dict[str, Any] | None,
) -> None:
    items: list[Any]
    if value is None:
        return
    if isinstance(value, dict) and set(value) == {"data"}:
        items = value["data"] if isinstance(value["data"], list) else [value["data"]]
    elif isinstance(value, list):
        items = value
    else:
        items = [value]
    for item in items:
        if not isinstance(item, dict):
            continue
        if len(item) == 1 and next(iter(item)) in {"service", "postgres", "keyValue", "workflow"}:
            item = item[next(iter(item))]
        if not isinstance(item, dict):
            continue
        owner_id = item.get("ownerId")
        owner = item.get("owner")
        if owner_id is None and isinstance(owner, dict):
            owner_id = owner.get("id")
        if category == "workspace_current":
            owner_id = item.get("id")
        if owner_id is not None and owner_id != workspace_id:
            raise CaptureError("ownership_mismatch")
        if category in {"workspace_current", "projects_list", "services_list", "service_get", "postgres_list", "postgres_get", "keyvalues_list", "keyvalue_get", "workflows_list"} and owner_id is None:
            raise CaptureError("ownership_unproven")
        if requested_id is None:
            continue
        if category in {"service_get", "postgres_get", "keyvalue_get", "workflow_task_run_show"} and item.get("id") != requested_id:
            raise CaptureError("ownership_mismatch")
        parent_fields = {
            "environments_list": "projectId",
            "service_instances": "serviceId",
            "deploys_list": "serviceId",
            "workflow_versions_list": "workflowId",
            "workflow_tasks_list": "workflowVersionId",
            "workflow_task_runs_list": "taskId",
            "jobs_list": "serviceId",
        }
        parent_field = parent_fields.get(category)
        actual_parent = item.get(parent_field) if parent_field else None
        if actual_parent is not None and actual_parent != requested_id:
            raise CaptureError("ownership_mismatch")
        if category in {"environments_list", "workflow_versions_list", "workflow_tasks_list", "workflow_task_runs_list"} and actual_parent is None:
            raise CaptureError("ownership_unproven")
        if index is not None:
            for related_field, expected_kind in (("workflowId", "workflow"), ("workflowVersionId", "workflow_version"), ("taskId", "task"), ("serviceId", "service"), ("projectId", "project")):
                related_id = item.get(related_field)
                if related_id is None:
                    continue
                related = _index_item(index, related_id)
                if related is None or related["kind"] not in {expected_kind, "any"}:
                    raise CaptureError("ownership_mismatch")


def _validate_log_ownership(values: list[dict[str, Any]], requested_id: str, index: dict[str, Any]) -> None:
    if _index_item(index, requested_id) is None:
        raise CaptureError("resource_not_owned")
    for value in values:
        resource_labels = [label["value"] for label in value["labels"] if label["name"] == "resource"]
        if resource_labels and resource_labels != [requested_id]:
            raise CaptureError("ownership_mismatch")


def capture(args: argparse.Namespace) -> dict[str, Any]:
    contract = _contracts()
    _uuid4(args.attempt_id)
    _safe_id(args.workspace_id, "workspace_id_invalid")
    if not DIGEST_RE.fullmatch(args.consent_digest):
        raise CaptureError("consent_digest_invalid")
    if not 1 <= args.timeout_seconds <= 120:
        raise CaptureError("timeout_invalid")
    if not 1024 <= args.max_bytes <= DEFAULT_MAX_BYTES:
        raise CaptureError("max_bytes_invalid")
    executable = shutil.which("render")
    if executable is None:
        raise CaptureError("render_not_found")
    argv, expected_shape = build_argv(args, contract, executable)
    ownership_index, ownership_index_digest = _load_ownership_index(args)
    env = child_environment()
    if args.category != "version":
        version_data = _run([executable, "--version"], min(args.timeout_seconds, 10), 4096, env)
        match = VERSION_RE.search(version_data.strip())
        if match is None or match.group(1).decode() != EXPECTED_VERSION:
            raise CaptureError("unsupported_version")
    data = _run(argv, args.timeout_seconds, args.max_bytes, env)
    if expected_shape == "version_text":
        match = VERSION_RE.search(data.strip())
        if match is None or match.group(1).decode() != EXPECTED_VERSION:
            raise CaptureError("unsupported_version")
        raw_shape, projected = "version_text", {"version": EXPECTED_VERSION}
    elif expected_shape == "json_stream_metadata":
        values = _parse_stream(data, args.limit)
        raw_shape, projected = "json_stream", _project_log_metadata(values)
        assert args.resource_id is not None and ownership_index is not None
        _validate_log_ownership(projected, args.resource_id, ownership_index)
    else:
        parsed = _parse_json(data)
        raw_shape = _shape(parsed, expected_shape)
        projected = _project_cli(parsed, args.category)
        _validate_ownership(projected, args.category, args.workspace_id, args.resource_id, ownership_index)
    return {
        "schema_version": "1.0",
        "transport": "render_cli_2.30.0",
        "category": args.category,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "attempt_id": args.attempt_id,
        "workspace_id": args.workspace_id,
        "consent_digest": args.consent_digest,
        "ownership_index_digest": ownership_index_digest,
        "status": "ok",
        "page_count": None,
        "raw_shape": raw_shape,
        "command_digest": sha256_digest("\0".join(argv[1:]).encode()),
        "request": {
            "resource_id": args.resource_id,
            "start": args.start,
            "end": args.end,
            "limit": args.limit,
        },
        "data": projected,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--consent-digest", required=True)
    parser.add_argument("--migration-dir", type=Path, required=True)
    parser.add_argument("--ownership-index", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resource-id")
    parser.add_argument("--blueprint", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
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
        print(f"CLI_CAPTURE_FAIL | code={code}", file=sys.stderr)
        return 1
    print(f"CLI_CAPTURE_OK | category={args.category} | output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
