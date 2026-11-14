from __future__ import annotations

import argparse
import gzip
import importlib.util
import io
import json
import os
import urllib.error
from pathlib import Path
from typing import Any

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPT_DIR / "capture-render-api.py"
FIXTURES = SCRIPT_DIR.parent / "fixtures/render-live-capture/rest"
spec = importlib.util.spec_from_file_location("capture_render_api", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ATTEMPT = "12345678-1234-4234-9234-123456789abc"
DIGEST = "sha256:" + "a" * 64


class Response:
    def __init__(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}
        self.position = 0

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self.body) - self.position
        chunk = self.body[self.position : self.position + amount]
        self.position += len(chunk)
        return chunk


class Opener:
    def __init__(self, responses: list[Response | Exception]) -> None:
        self.responses = responses
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: int) -> Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def write_index(tmp_path: Path) -> Path:
    index = tmp_path / "ownership.json"
    index.write_text(json.dumps({
        "schema_version": "1.0", "status": "active", "attempt_id": ATTEMPT,
        "workspace_id": "tea-safe", "consent_digest": DIGEST,
        "resources": [
            {"id": "srv-safe-web", "kind": "service", "workspace_id": "tea-safe", "parent_id": None},
            {"id": "srv-safe-worker", "kind": "service", "workspace_id": "tea-safe", "parent_id": None},
            {"id": "prj-safe", "kind": "project", "workspace_id": "tea-safe", "parent_id": None},
            {"id": "evm-safe-prod", "kind": "environment", "workspace_id": "tea-safe", "parent_id": "prj-safe"},
            {"id": "wfl-safe", "kind": "workflow", "workspace_id": "tea-safe", "parent_id": None},
        ],
    }))
    return index


def arguments(tmp_path: Path, category: str, **values: object) -> argparse.Namespace:
    defaults = dict(category=category, workspace_id="tea-safe", attempt_id=ATTEMPT, consent_digest=DIGEST, ownership_index=write_index(tmp_path), migration_dir=tmp_path, output=tmp_path / "out.json", resource_id=None, start=None, end=None, resolution_seconds=None, event_type=None, limit=None)
    if category == "service_events":
        defaults.update(start="2026-10-21T11:00:00Z", end="2026-10-21T12:00:00Z")
    defaults.update(values)
    return argparse.Namespace(**defaults)


def body(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_events_positive_empty_and_closed_projection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "not-persisted")
    opener = Opener([Response(body("service-events-populated.json")), Response(body("service-events-empty.json"))])
    result = module.capture(arguments(tmp_path, "service_events", resource_id="srv-safe-web"), opener=opener, sleeper=lambda _: None)
    assert result["data"] == [{"id": "evt-safe-1", "resourceId": "srv-safe-web", "type": "deploy_live", "timestamp": "2026-10-21T12:00:00Z", "statusCode": 200}]
    assert result["captured_at"].endswith("Z")
    assert result["workspace_id"] == "tea-safe" and result["page_count"] == 2
    serialized = json.dumps(result)
    assert "not-persisted" not in serialized
    assert len(opener.requests) == 2
    assert all(request.get_method() == "GET" for request in opener.requests)
    assert all(request.full_url.startswith("https://api.render.com/v1/services/srv-safe-web/events?") for request in opener.requests)

    empty = module.capture(arguments(tmp_path, "service_events", resource_id="srv-safe-web"), opener=Opener([Response(body("service-events-empty.json"))]), sleeper=lambda _: None)
    assert empty["status"] == "successful_empty"


def test_events_http_400_is_retained_as_structured_unavailability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    error = urllib.error.HTTPError(
        "https://api.render.com/v1/services/srv-safe-web/events",
        400,
        "bad request",
        {},
        io.BytesIO(b'{"message":"query is not allowed for plan"}'),
    )
    result = module.capture(
        arguments(tmp_path, "service_events", resource_id="srv-safe-web"),
        opener=Opener([error]),
        sleeper=lambda _: None,
    )
    assert result["status"] == "unavailable_plan"
    assert result["raw_shapes"] == ["http_400"]
    assert result["data"] == []


@pytest.mark.parametrize("fixture", ["service-events-secret-negative.json", "service-events-envelope-negative.json"])
def test_events_secret_and_unknown_envelopes_fail_closed(fixture: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    with pytest.raises(module.CaptureError):
        module.capture(arguments(tmp_path, "service_events", resource_id="srv-safe-web"), opener=Opener([Response(body(fixture))]), sleeper=lambda _: None)
    assert not (tmp_path / "out.json").exists()


def test_populated_build_source_and_capability_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    opener = Opener([Response(body("build-sources-populated.json")), Response(b"[]")])
    result = module.capture(arguments(tmp_path, "build_sources_list"), opener=opener, sleeper=lambda _: None)
    assert result["data"][0]["artifact"]["digest"].startswith("sha256:")
    assert result["data"][0]["buildEnvVarNames"] == ["BUILD_MODE"]
    with pytest.raises(module.CaptureError, match="capability_drift"):
        module.capture(arguments(tmp_path, "build_sources_list"), opener=Opener([Response(body("build-sources-capability-drift-negative.json"))]), sleeper=lambda _: None)


@pytest.mark.parametrize(
    "fixture",
    ["build-sources-credential-url-negative.json", "build-sources-inline-secret-negative.json"],
)
def test_build_source_allowed_fields_still_reject_secret_values(
    fixture: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    with pytest.raises(module.CaptureError, match="secret_bearing_response"):
        module.capture(
            arguments(tmp_path, "build_sources_list"),
            opener=Opener([Response(body(fixture))]),
            sleeper=lambda _: None,
        )
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize(
    ("category", "fixture", "values"),
    [
        ("services_list", "service-credential-repo-negative.json", {}),
        ("services_list", "service-inline-command-secret-negative.json", {}),
        ("services_list", "service-credential-image-negative.json", {}),
        ("workflows_list", "workflow-credential-repo-negative.json", {}),
        (
            "metric_cpu",
            "metric-inline-label-secret-negative.json",
            {
                "resource_id": "srv-safe-web",
                "start": "2026-10-21T11:00:00Z",
                "end": "2026-10-21T12:00:00Z",
                "resolution_seconds": 30,
            },
        ),
    ],
)
def test_all_retained_rest_strings_use_deny_first_classification(
    category: str,
    fixture: str,
    values: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    with pytest.raises(module.CaptureError, match="secret_bearing_response"):
        module.capture(
            arguments(tmp_path, category, **values),
            opener=Opener([Response(body(fixture))]),
            sleeper=lambda _: None,
        )
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_all_redirects_reject_before_target_request(code: int) -> None:
    handler = module.RejectRedirects()
    with pytest.raises(module.RedirectRejected, match="redirect_rejected"):
        handler.redirect_request(object(), object(), code, "redirect", {}, "https://attacker.example/collect")


def test_inactive_unreviewed_rest_contracts_use_cli_and_never_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDER_API_KEY", raising=False)
    for category in ("workspaces_list", "postgres_list", "keyvalues_list", "service_instances"):
        opener = Opener([])
        values = {"resource_id": "srv-safe-web"} if category == "service_instances" else {}
        with pytest.raises(module.CaptureError, match="unsupported_contract"):
            module.capture(arguments(tmp_path, category, **values), opener=opener, sleeper=lambda _: None)
        assert opener.requests == []
        assert not (tmp_path / "out.json").exists()


def test_row_specific_event_window_and_domain_query_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    opener = Opener([Response(b"[]")])
    result = module.capture(arguments(tmp_path, "custom_domains", resource_id="srv-safe-web"), opener=opener, sleeper=lambda _: None)
    assert result["status"] == "successful_empty"
    assert opener.requests[0].full_url == "https://api.render.com/v1/services/srv-safe-web/custom-domains"
    with pytest.raises(module.CaptureError, match="window_invalid"):
        module.capture(arguments(tmp_path, "service_events", resource_id="srv-safe-web", start="2026-10-19T11:00:00Z", end="2026-10-21T12:00:00Z"), opener=Opener([]), sleeper=lambda _: None)


def test_generic_active_projection_rejects_unknown_and_secret_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    unknown = [{"cursor": "end", "project": {"id": "prj-safe", "name": "safe", "ownerId": "tea-safe", "futureField": "x"}}]
    with pytest.raises(module.CaptureError, match="capability_drift"):
        module.capture(arguments(tmp_path, "projects_list"), opener=Opener([Response(json.dumps(unknown).encode())]), sleeper=lambda _: None)
    secret = [{"cursor": "end", "project": {"id": "prj-safe", "name": "safe", "ownerId": "tea-safe", "dsn": "postgres://user:pass@example"}}]
    with pytest.raises(module.CaptureError):
        module.capture(arguments(tmp_path, "projects_list"), opener=Opener([Response(json.dumps(secret).encode())]), sleeper=lambda _: None)


def test_every_active_rest_row_declares_exact_query_and_projection_contract() -> None:
    contract = module._contracts()
    for category, row in contract["categories"].items():
        assert isinstance(row["required_query"], list)
        assert isinstance(row["allowed_query"], list)
        assert set(row["required_query"]) <= set(row["allowed_query"])
        if row["active"]:
            assert row.get("strict_projection") in {*module.CORE_FIELDS, "event", "build_source", "metric"}, category


def test_query_and_ownership_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    with pytest.raises(module.CaptureError, match="resource_not_owned"):
        module.capture(arguments(tmp_path, "service_get", resource_id="srv-other"), opener=Opener([]), sleeper=lambda _: None)
    with pytest.raises(module.CaptureError, match="window_invalid"):
        module.capture(arguments(tmp_path, "metric_cpu", resource_id="srv-safe-web", start="2026-10-21T12:00:00Z", end="2026-10-21T11:00:00Z", resolution_seconds=30), opener=Opener([]), sleeper=lambda _: None)
    with pytest.raises(module.CaptureError, match="unsupported_category"):
        module.capture(arguments(tmp_path, "environment_values"), opener=Opener([]), sleeper=lambda _: None)


def test_child_rows_reject_cross_parent_objects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    cases = [
        ("environments_list", "prj-safe", [{"cursor": "end", "environment": {"id": "evm-other", "name": "other", "projectId": "prj-other"}}]),
        ("workflow_versions_list", "wfl-safe", [{"cursor": "end", "workflowVersion": {"id": "wfv-other", "workflowId": "wfl-other"}}]),
        ("workflow_tasks_list", "wfl-safe", [{"cursor": "end", "task": {"id": "tsk-other", "workflowId": "wfl-other"}}]),
        ("workflow_task_runs_list", "wfl-safe", [{"cursor": "end", "taskRun": {"id": "run-other", "workflowId": "wfl-other"}}]),
    ]
    for category, resource_id, payload in cases:
        with pytest.raises(module.CaptureError, match="ownership_mismatch"):
            module.capture(
                arguments(tmp_path, category, resource_id=resource_id),
                opener=Opener([Response(json.dumps(payload).encode())]),
                sleeper=lambda _: None,
            )


def test_metric_points_and_successful_empty_are_distinct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    payload = [{"labels": [{"field": "resource", "value": "srv-safe-web"}], "unit": "cpu", "values": [{"timestamp": "2026-10-21T12:00:00Z", "value": 0.5}]}]
    args = arguments(tmp_path, "metric_cpu", resource_id="srv-safe-web", start="2026-10-21T11:00:00Z", end="2026-10-21T12:00:00Z", resolution_seconds=30)
    points = module.capture(args, opener=Opener([Response(json.dumps(payload).encode())]), sleeper=lambda _: None)
    assert points["status"] == "ok" and points["data"][0]["values"][0]["value"] == 0.5
    empty = module.capture(args, opener=Opener([Response(b"[]")]), sleeper=lambda _: None)
    assert empty["status"] == "successful_empty"


def test_wire_decompression_depth_and_node_caps() -> None:
    limits = {"response_seconds": 30, "wire_bytes": 128, "decompressed_bytes": 64, "json_depth": 3, "json_nodes": 5}
    compressed = gzip.compress(b"x" * 100)
    with pytest.raises(module.CaptureError, match="decompressed_limit_exceeded"):
        module._read_bounded(Response(compressed, headers={"Content-Encoding": "gzip"}), limits)
    with pytest.raises(module.CaptureError, match="json_depth_limit_exceeded"):
        module._json_bounded(b'{"a":{"b":{"c":{"d":1}}}}', limits)
    with pytest.raises(module.CaptureError, match="json_node_limit_exceeded"):
        module._json_bounded(b"[1,2,3,4,5,6]", limits)


def test_endless_or_slow_body_fails_without_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Endless(Response):
        def read(self, amount: int = -1) -> bytes:
            return b"x" * amount

    ticks = iter([0.0, 0.0, 0.0, 31.0])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))
    limits = {"response_seconds": 30, "wire_bytes": 10 * 1024 * 1024, "decompressed_bytes": 12 * 1024 * 1024}
    with pytest.raises(module.CaptureError, match="response_timeout"):
        module._read_bounded(Endless(b""), limits)
    assert not (tmp_path / "out.json").exists()


def http_error(code: int, body: bytes = b"{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.render.com/v1/services/srv-safe-web",
        code,
        "test status",
        {},
        io.BytesIO(body),
    )


def test_direct_absence_and_authorization_statuses_are_distinct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    absent = module.capture(
        arguments(tmp_path, "service_get", resource_id="srv-safe-web"),
        opener=Opener([http_error(404)]),
        sleeper=lambda _: None,
    )
    assert absent["status"] == "absent"
    assert absent["raw_shapes"] == ["http_404"]
    assert absent["data"] == []
    from jsonschema import Draft202012Validator, FormatChecker

    validator = Draft202012Validator(json.loads((SCRIPT_DIR.parent / "references/shared/schema-render-rest-projections.json").read_text()), format_checker=FormatChecker())
    assert not list(validator.iter_errors(absent))
    # Unreviewed shapes and statuses stay rejected by the closed schema.
    for field, replacement in (("raw_shapes", ["http_500"]), ("status", "gone")):
        rejected = dict(absent, **{field: replacement})
        assert [error.json_path for error in validator.iter_errors(rejected)] == [f"$.{field}[0]" if field == "raw_shapes" else "$.status"]
    for code, expected in ((401, "authentication"), (403, "forbidden_unknown")):
        with pytest.raises(module.CaptureError, match=expected):
            module.capture(
                arguments(tmp_path, "service_get", resource_id="srv-safe-web"),
                opener=Opener([http_error(code)]),
                sleeper=lambda _: None,
            )


def test_http_400_requires_exact_reviewed_structured_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    args = arguments(tmp_path, "service_events", resource_id="srv-safe-web")
    for payload in (b'{"message":"another plan failed"}', b"not-json"):
        with pytest.raises(module.CaptureError, match="invalid_query"):
            module.capture(args, opener=Opener([http_error(400, payload)]), sleeper=lambda _: None)


def test_attempt_cap_counts_nested_non_json_files_and_output_root_is_fixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_API_KEY", "safe-test-key")
    attempt_root = tmp_path / "attempt"
    attempt_root.mkdir()
    nested = attempt_root / "nested"
    nested.mkdir()
    (nested / "prior.bin").write_bytes(b"x" * 1024)
    args = arguments(attempt_root, "projects_list", output=nested / "out.json")
    contract = module._contracts()
    contract["limits"]["attempt_bytes"] = sum(
        path.stat().st_size for path in attempt_root.rglob("*") if path.is_file()
    ) + 100
    monkeypatch.setattr(module, "_contracts", lambda: contract)
    with pytest.raises(module.CaptureError, match="attempt_output_limit_exceeded"):
        module.capture(args, opener=Opener([Response(b"[]")]), sleeper=lambda _: None)

    outside = tmp_path / "outside.json"
    with pytest.raises(module.CaptureError, match="output_outside_attempt_root"):
        module.capture(
            arguments(attempt_root, "projects_list", output=outside),
            opener=Opener([]),
            sleeper=lambda _: None,
        )
