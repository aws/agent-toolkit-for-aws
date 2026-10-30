from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPT_DIR / "capture-render-cli.py"
FIXTURES = SCRIPT_DIR.parent / "fixtures/render-live-capture/cli"
spec = importlib.util.spec_from_file_location("capture_render_cli", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ATTEMPT = "12345678-1234-4234-9234-123456789abc"
DIGEST = "sha256:" + "a" * 64
REAL_POPEN = subprocess.Popen


def arguments(tmp_path: Path, category: str, **values: object) -> argparse.Namespace:
    defaults = dict(category=category, workspace_id="tea-safe", attempt_id=ATTEMPT, consent_digest=DIGEST, migration_dir=tmp_path, ownership_index=None, output=tmp_path / "out.json", resource_id=None, blueprint=None, workspace_root=None, start=None, end=None, limit=None, timeout_seconds=30, max_bytes=10 * 1024 * 1024)
    defaults.update(values)
    return argparse.Namespace(**defaults)


def write_index(tmp_path: Path) -> Path:
    path = tmp_path / "ownership.json"
    path.write_text(json.dumps({
        "schema_version": "1.0", "status": "active", "attempt_id": ATTEMPT,
        "workspace_id": "tea-safe", "consent_digest": DIGEST,
        "resources": [
            {"id": "prj-safe", "kind": "project", "workspace_id": "tea-safe", "parent_id": None},
            {"id": "srv-safe", "kind": "service", "workspace_id": "tea-safe", "parent_id": None},
            {"id": "wfl-safe", "kind": "workflow", "workspace_id": "tea-safe", "parent_id": None},
            {"id": "wfv-safe", "kind": "workflow_version", "workspace_id": "tea-safe", "parent_id": "wfl-safe"},
            {"id": "tsk-safe", "kind": "task", "workspace_id": "tea-safe", "parent_id": "wfv-safe"},
            {"id": "run-safe", "kind": "task_run", "workspace_id": "tea-safe", "parent_id": "tsk-safe"},
        ],
    }), encoding="utf-8")
    return path


class Process:
    def __init__(self, stdout: bytes, returncode: int, stderr: bytes = b"") -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: int) -> int:
        return self.returncode


def install_process(monkeypatch: pytest.MonkeyPatch, responses: list[tuple[bytes, int]]) -> list[dict]:
    calls: list[dict] = []

    def popen(argv: list[str], **kwargs: object) -> Process:
        calls.append({"argv": argv, "kwargs": kwargs})
        stdout, returncode = responses.pop(0)
        return Process(stdout, returncode, b"remote text")

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/local/bin/render")
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    return calls


def test_exact_table_shapes_and_no_secret_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    services = (FIXTURES / "services-populated.json").read_bytes()
    calls = install_process(monkeypatch, [(b"render 2.30.0\n", 0), (services, 0)])
    monkeypatch.setenv("RENDER_API_KEY", "never-child")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "never-child")
    result = module.capture(arguments(tmp_path, "services_list"))
    assert result["raw_shape"] == "array"
    assert result["data"][0]["service"]["ownerId"] == "tea-safe"
    assert calls[1]["argv"] == ["/usr/local/bin/render", "services", "--output", "json"]
    child = calls[1]["kwargs"]
    assert child["shell"] is False and child["stdin"] is subprocess.DEVNULL
    assert "RENDER_API_KEY" not in child["env"]
    assert "AWS_SECRET_ACCESS_KEY" not in child["env"]

    install_process(monkeypatch, [(b"render 2.30.0\n", 0), ((FIXTURES / "postgres-empty.json").read_bytes(), 0)])
    assert module.capture(arguments(tmp_path, "postgres_list"))["raw_shape"] == "data_array"

    install_process(monkeypatch, [(b"render 2.30.0\n", 0), ((FIXTURES / "projects-null.json").read_bytes(), 0)])
    assert module.capture(arguments(tmp_path, "projects_list"))["raw_shape"] == "null"


def test_forbidden_and_injected_inputs_never_reach_popen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("Popen called")

    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/local/bin/render")
    with pytest.raises(module.CaptureError, match="unsupported_category"):
        module.capture(arguments(tmp_path, "services_create"))
    with pytest.raises(module.CaptureError, match="resource_id_invalid"):
        module.capture(arguments(tmp_path, "service_get", resource_id="srv-safe; rm -rf /"))
    assert called is False


def test_authoritative_auth_workspace_null_get_and_blueprint_contracts(tmp_path: Path) -> None:
    contract = module._contracts()
    args = arguments(tmp_path, "workspaces_list")
    argv, _ = module.build_argv(args, contract, "/render")
    assert argv == ["/render", "workspaces", "--output", "json"]
    argv, _ = module.build_argv(arguments(tmp_path, "auth_whoami"), contract, "/render")
    assert argv == ["/render", "whoami", "--output", "json"]
    assert module._shape({"data": None}, "data_nullable_object") == "data_null"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    blueprint = workspace / "render.yaml"
    blueprint.write_text('version: "1"\n')
    argv, _ = module.build_argv(arguments(tmp_path, "blueprint_validate", blueprint=blueprint, workspace_root=workspace), contract, "/render")
    assert str(blueprint) in argv
    outside = tmp_path / "outside.yaml"
    outside.write_text('version: "1"\n')
    with pytest.raises(module.CaptureError, match="blueprint_invalid"):
        module.build_argv(arguments(tmp_path, "blueprint_validate", blueprint=outside, workspace_root=workspace), contract, "/render")


def test_closed_cli_projection_rejects_unknown_and_secret_fields() -> None:
    with pytest.raises(module.CaptureError, match="capability_drift"):
        module._project_cli({"id": "srv-safe", "ownerId": "tea-safe", "futureField": "x"}, "service_get")
    projected = module._project_cli({"id": "srv-safe", "ownerId": "tea-safe", "email": "person@example.test"}, "service_get")
    assert "email" not in projected


def test_every_cli_contract_row_builds_only_its_frozen_argv(tmp_path: Path) -> None:
    contract = module._contracts()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    blueprint = workspace / "render.yaml"
    blueprint.write_text('version: "1"\n')
    for category, row in contract["categories"].items():
        values: dict[str, object] = {}
        if any("{resource_id}" == token for token in row["argv"]):
            values["resource_id"] = "srv-safe"
        if "{blueprint}" in row["argv"]:
            values.update(blueprint=blueprint, workspace_root=workspace)
        if "{start}" in row["argv"]:
            values.update(start="2026-10-21T11:00:00Z", end="2026-10-21T12:00:00Z")
        if "{limit}" in row["argv"]:
            values["limit"] = 20
        argv, shape = module.build_argv(arguments(tmp_path, category, **values), contract, "/render")
        assert argv[0] == "/render" and shape == row["shape"]
        assert not any(token.startswith("{") for token in argv)


def test_version_gate_stops_before_category_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install_process(monkeypatch, [(b"render 2.29.0\n", 0)])
    with pytest.raises(module.CaptureError, match="unsupported_version"):
        module.capture(arguments(tmp_path, "services_list"))
    assert len(calls) == 1


def test_closed_log_window_and_metadata_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stream = b'{"id":"log-1","timestamp":"2026-10-21T12:00:00Z","message":"attacker text","labels":[{"name":"resource","value":"srv-safe"}]}'
    install_process(monkeypatch, [(b"render 2.30.0\n", 0), (stream, 0)])
    result = module.capture(arguments(tmp_path, "log_metadata", resource_id="srv-safe", ownership_index=write_index(tmp_path), start="2026-10-21T11:00:00Z", end="2026-10-21T12:00:00Z", limit=20))
    assert result["data"] == [{"id": "log-1", "timestamp": "2026-10-21T12:00:00Z", "labels": [{"name": "resource", "value": "srv-safe"}]}]
    assert result["ownership_index_digest"] == module.sha256_digest((tmp_path / "ownership.json").read_bytes())
    assert result["status"] == "ok" and result["page_count"] is None
    assert result["captured_at"].endswith("Z")
    assert "attacker text" not in json.dumps(result)


def test_log_metadata_rejects_secret_bearing_retained_fields() -> None:
    with pytest.raises(module.CaptureError, match="secret_bearing_response"):
        module._project_log_metadata([{
            "id": "log-safe",
            "timestamp": "2026-10-21T12:00:00Z",
            "labels": [{"name": "level", "value": "token=topsecret"}],
        }])
    with pytest.raises(module.CaptureError, match="secret_bearing_response"):
        module._project_log_metadata([{
            "id": "token=topsecret",
            "timestamp": "2026-10-21T12:00:00Z",
            "labels": [],
        }])


@pytest.mark.parametrize("name", ["RENDER_API_KEY", "AWS_SESSION_TOKEN", "GITHUB_TOKEN", "DATABASE_PASSWORD", "GOOGLE_APPLICATION_CREDENTIALS"])
def test_child_environment_strips_credentials(name: str) -> None:
    source = {"PATH": "/bin", "HOME": "/tmp/home", "LANG": "C.UTF-8", name: "secret", "HTTPS_PROXY": "https://user:pass@example.test"}
    environment = module.child_environment(source)
    assert name not in environment
    assert "HTTPS_PROXY" not in environment
    assert set(environment) <= module.ALLOWED_ENV


def test_child_categories_require_owned_request_and_matching_response_parent_before_popen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("Popen called")

    monkeypatch.setattr(module.subprocess, "Popen", forbidden)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/local/bin/render")
    with pytest.raises(module.CaptureError, match="ownership_index_required"):
        module.capture(arguments(tmp_path, "environments_list", resource_id="prj-safe"))
    with pytest.raises(module.CaptureError, match="resource_not_owned"):
        module.capture(arguments(tmp_path, "deploys_list", resource_id="srv-other", ownership_index=write_index(tmp_path)))
    assert called is False

    index = write_index(tmp_path)
    cases = [
        ("environments_list", "prj-safe", [{"id": "evm-other", "projectId": "prj-other"}]),
        ("service_instances", "srv-safe", [{"id": "ins-other", "serviceId": "srv-other"}]),
        ("deploys_list", "srv-safe", [{"id": "dep-other", "serviceId": "srv-other"}]),
        ("workflow_versions_list", "wfl-safe", [{"id": "wfv-other", "workflowId": "wfl-other"}]),
        ("workflow_tasks_list", "wfv-safe", [{"id": "tsk-other", "workflowVersionId": "wfv-other"}]),
        ("workflow_task_runs_list", "tsk-safe", [{"id": "run-other", "taskId": "tsk-other"}]),
    ]
    for category, resource_id, payload in cases:
        monkeypatch.setattr(module.subprocess, "Popen", REAL_POPEN)
        install_process(monkeypatch, [(b"render 2.30.0\n", 0), (json.dumps(payload).encode(), 0)])
        with pytest.raises(module.CaptureError, match="ownership_mismatch"):
            module.capture(arguments(tmp_path, category, resource_id=resource_id, ownership_index=index))


def test_overflow_and_timeout_do_not_write_partial_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "out.json"
    output.write_text("existing\n")
    install_process(monkeypatch, [(b"render 2.30.0\n", 0), (b"x" * 2049, 0)])
    with pytest.raises(module.CaptureError, match="output_limit_exceeded"):
        module.capture(arguments(tmp_path, "services_list", max_bytes=2048))
    assert output.read_text() == "existing\n"

    monkeypatch.setattr(module.subprocess, "Popen", REAL_POPEN)
    with pytest.raises(module.CaptureError, match="process_timeout"):
        module._run([os.environ.get("PYTHON", os.sys.executable), "-c", "import time; time.sleep(5)"], 1, 2048, module.child_environment())


def test_live_combined_pipe_cap_stops_stdout_stderr_and_mixed_children() -> None:
    python = os.environ.get("PYTHON", os.sys.executable)
    programs = [
        "import os,time;\nwhile True: os.write(1,b'x'*1024)",
        "import os,time;\nwhile True: os.write(2,b'x'*1024)",
        "import os,time;\nwhile True: os.write(1,b'x'*512); os.write(2,b'y'*512)",
    ]
    for program in programs:
        with pytest.raises(module.CaptureError, match="output_limit_exceeded"):
            module._run([python, "-c", program], 5, 4096, module.child_environment())
