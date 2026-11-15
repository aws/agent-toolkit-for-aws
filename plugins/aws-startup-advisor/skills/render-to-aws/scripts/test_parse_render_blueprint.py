from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
FIXTURES = SKILL_ROOT / "fixtures/render-blueprint"
SCRIPT = SCRIPT_DIR / "parse-render-blueprint.py"

spec = importlib.util.spec_from_file_location("parse_render_blueprint", SCRIPT)
assert spec and spec.loader
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


def run_parser(workspace: Path, migration: Path, source: Path, output: Path, evidence: Path | None = None) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        "--source", str(source),
        "--workspace-root", str(workspace),
        "--migration-dir", str(migration),
        "--output", str(output),
    ]
    if evidence:
        command.extend(["--semantic-evidence", str(evidence)])
    return subprocess.run(command, text=True, capture_output=True, check=False)


def copy_fixture(tmp_path: Path, name: str) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    migration = tmp_path / "migration"
    workspace.mkdir()
    migration.mkdir()
    source = workspace / "render.yaml"
    source.write_bytes((FIXTURES / name).read_bytes())
    return source, migration


def test_pinned_official_schema_metadata_and_fixture_compatibility() -> None:
    schema_path = SKILL_ROOT / "references/render/render-yaml.schema.json"
    metadata = json.loads((SKILL_ROOT / "references/render/render-yaml.schema-metadata.json").read_text())
    schema = json.loads(schema_path.read_text())
    assert metadata["source_url"] == "https://render.com/schema/render.yaml.json"
    assert metadata["sha256"] == hashlib.sha256(schema_path.read_bytes()).hexdigest()
    Draft202012Validator.check_schema(schema)
    valid = yaml.safe_load((FIXTURES / "valid-full.yaml").read_text())
    assert not list(Draft202012Validator(schema).iter_errors(valid))
    invalid = yaml.safe_load((FIXTURES / "schema-invalid.yaml").read_text())
    assert list(Draft202012Validator(schema).iter_errors(invalid))


def test_full_blueprint_normalizes_all_placements_and_resource_types(tmp_path: Path) -> None:
    source, migration = copy_fixture(tmp_path, "valid-full.yaml")
    output = migration / "blueprint.json"
    result = run_parser(source.parent, migration, source, output)
    assert result.returncode == 0, result.stderr
    artifact = json.loads(output.read_text())
    assert artifact["structural_validation"] == {
        "schema_validated_before_normalization": True,
        "status": "valid",
    }
    kinds = {item["kind"] for item in artifact["resources"]}
    assert {
        "render.project", "render.environment", "render.build_source", "render.postgres",
        "render.environment_group", "render.web_service", "render.static_site",
        "render.private_service", "render.background_worker", "render.cron_job",
        "render.workflow", "render.key_value", "render.persistent_disk",
        "render.custom_domain", "render.preview_environment",
    } <= kinds
    assert any(item["blueprint_address"].startswith("/projects/") for item in artifact["resources"])
    assert any(item["blueprint_address"].startswith("/ungrouped/") for item in artifact["resources"])
    edge_types = {edge["type"] for edge in artifact["edges"]}
    assert {"service_to_postgres", "service_to_key_value", "service_to_service", "service_to_env_group", "service_to_disk", "service_uses_build_source", "build_source_produces_artifact", "environment_promotes_artifact", "custom_domain_routes_to"} <= edge_types
    serialized = output.read_text()
    assert "super-secret-literal" not in serialized
    assert "redacted_literal" in serialized
    assert artifact["semantic_validation"] == {"requires_renewed_consent": True, "status": "not_provided"}


def write_blueprint(tmp_path: Path, content: str) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    migration = tmp_path / "migration"
    workspace.mkdir()
    migration.mkdir()
    source = workspace / "render.yaml"
    source.write_text(content)
    return source, migration


def disk_and_edge(artifact: dict) -> tuple[dict, dict]:
    disk = next(item for item in artifact["resources"] if item["kind"] == "render.persistent_disk")
    edge = next(edge for edge in artifact["edges"] if edge["type"] == "service_to_disk")
    return disk, edge


def test_omitted_disk_size_applies_schema_default_with_provenance(tmp_path: Path) -> None:
    source, migration = write_blueprint(tmp_path, """services:
  - type: web
    name: api
    runtime: docker
    disk:
      name: data
      mountPath: /var/data
""")
    artifact = parser.parse_blueprint(source, source.parent, migration)
    disk, edge = disk_and_edge(artifact)
    assert disk["config"]["sizeGB"] == 10
    assert disk["config"]["sizeGB_provenance"] == "schema_default"
    assert edge["attributes"] == {"mountPath": "/var/data", "sizeGB": 10, "sizeGB_provenance": "schema_default"}


def test_explicit_disk_size_is_preserved(tmp_path: Path) -> None:
    source, migration = copy_fixture(tmp_path, "valid-full.yaml")
    artifact = parser.parse_blueprint(source, source.parent, migration)
    disk, edge = disk_and_edge(artifact)
    assert disk["config"]["sizeGB"] == 5
    assert disk["config"]["sizeGB_provenance"] == "declared"
    assert edge["attributes"]["sizeGB"] == 5
    assert edge["attributes"]["sizeGB_provenance"] == "declared"


def test_published_plan_spellings_are_preserved_and_normalized(tmp_path: Path) -> None:
    source, migration = write_blueprint(tmp_path, """services:
  - type: web
    name: api
    runtime: docker
    plan: 1c-2g
  - type: cron
    name: nightly
    runtime: python
    schedule: "0 0 * * *"
    startCommand: python job.py
    plan: pro plus
  - type: worker
    name: huge
    runtime: python
    startCommand: python worker.py
    plan: 2c-16g
  - type: keyvalue
    name: cache
    plan: pro ultra
    ipAllowList: []
""")
    artifact = parser.parse_blueprint(source, source.parent, migration)
    by_name = {item["name"]: item["config"] for item in artifact["resources"]}
    assert by_name["api"]["plan"] == "1c-2g"
    assert by_name["api"]["plan_normalized"] == "1c-2gb"
    assert by_name["nightly"]["plan"] == "pro plus"
    assert by_name["nightly"]["plan_normalized"] == "4c-8gb"
    # Unpriced plans keep the raw spelling and resolve to null rather than a neighbouring plan.
    assert by_name["huge"]["plan"] == "2c-16g"
    assert by_name["huge"]["plan_normalized"] is None
    assert by_name["cache"]["plan"] == "pro ultra"
    assert by_name["cache"]["plan_normalized"] == "40g"


def test_zero_disk_size_still_fails_schema_validation(tmp_path: Path) -> None:
    source, migration = write_blueprint(tmp_path, """services:
  - type: web
    name: api
    runtime: docker
    disk:
      name: data
      mountPath: /var/data
      sizeGB: 0
""")
    with pytest.raises(parser.BlueprintError, match="schema_invalid"):
        parser.parse_blueprint(source, source.parent, migration)


def test_output_is_byte_deterministic(tmp_path: Path) -> None:
    source, migration = copy_fixture(tmp_path, "valid-full.yaml")
    first = migration / "first.json"
    second = migration / "second.json"
    assert run_parser(source.parent, migration, source, first).returncode == 0
    assert run_parser(source.parent, migration, source, second).returncode == 0
    assert first.read_bytes() == second.read_bytes()
    artifact = json.loads(first.read_text())
    assert artifact["resources"] == sorted(artifact["resources"], key=lambda item: item["id"].encode())
    assert all(item["id"].startswith("rbp-") and len(item["id"]) == 28 for item in artifact["resources"])


def test_exact_safe_broken_reference_identities_are_retained(tmp_path: Path) -> None:
    source, migration = copy_fixture(tmp_path, "broken-reference.yaml")
    output = migration / "blueprint.json"
    result = run_parser(source.parent, migration, source, output)
    assert result.returncode == 0, result.stderr
    errors = json.loads(output.read_text())["local_reference_validation"]["errors"]
    assert errors == [{
        "code": "broken_reference",
        "column": 0,
        "line": 0,
        "message": "render.web_service 'safe-api' references missing render.postgres 'missing-db'.",
        "path": "/services/0/envVars/0",
        "source_kind": "render.web_service",
        "source_name": "safe-api",
        "target_kind": "render.postgres",
        "target_name": "missing-db",
    }]


def semantic_evidence(path: Path, digest: str) -> None:
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "source_path": "render.yaml",
        "source_digest": digest,
        "manifest_digest": "sha256:" + "c" * 64,
        "attempt_id": "12345678-1234-4234-9234-123456789abc",
        "workspace_id": "tea-safe",
        "consent_digest": "sha256:" + "b" * 64,
        "validated_at": "2026-10-21T12:00:00Z",
        "outcome": "valid",
        "errors": [],
    }))


def test_semantic_validation_is_digest_bound_and_source_change_requires_consent(tmp_path: Path) -> None:
    source, migration = copy_fixture(tmp_path, "broken-reference.yaml")
    digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    evidence = migration / "semantic.json"
    semantic_evidence(evidence, digest)
    current = migration / "current.json"
    assert run_parser(source.parent, migration, source, current, evidence).returncode == 0
    assert json.loads(current.read_text())["semantic_validation"]["status"] == "current"

    source.write_text(source.read_text() + "\n# source changed\n")
    stale = migration / "stale.json"
    assert run_parser(source.parent, migration, source, stale, evidence).returncode == 0
    state = json.loads(stale.read_text())["semantic_validation"]
    assert state["status"] == "stale"
    assert state["requires_renewed_consent"] is True


def test_structural_validation_precedes_normalization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, migration = copy_fixture(tmp_path, "schema-invalid.yaml")
    called = False

    def forbidden(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("normalization ran")

    monkeypatch.setattr(parser, "normalize_blueprint", forbidden)
    with pytest.raises(parser.BlueprintError, match="schema_invalid"):
        parser.parse_blueprint(source, source.parent, migration)
    assert called is False


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ("version: '1'\nservices: &items []\n", "yaml_anchor_forbidden"),
        ("version: '1'\nservices: &items []\nungrouped:\n  services: *items\n", "yaml_anchor_forbidden"),
        ("version: '1'\nvalue: !unsafe thing\n", "yaml_custom_tag_forbidden"),
        ("version: '1'\nversion: '1'\n", "duplicate_key"),
        ("version: '1'\nunsafe: .nan\n", "non_finite_number"),
    ],
)
def test_unsafe_yaml_features_fail_closed(content: str, code: str, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    migration = tmp_path / "migration"
    workspace.mkdir()
    migration.mkdir()
    source = workspace / "render.yaml"
    source.write_text(content)
    output = migration / "output.json"
    result = run_parser(workspace, migration, source, output)
    assert result.returncode == 1
    assert f"code={code}" in result.stderr
    assert not output.exists()


def test_depth_node_scalar_and_size_bounds_fail_closed(tmp_path: Path) -> None:
    nested = current = {}
    for _ in range(42):
        current["x"] = {}
        current = current["x"]
    with pytest.raises(Exception, match="depth_limit_exceeded"):
        parser.load_bounded_yaml(yaml.safe_dump(nested).encode())

    with pytest.raises(Exception, match="container_limit_exceeded"):
        parser.load_bounded_yaml(("version: '1'\nvalues:\n" + "".join(f"  k{i}: v\n" for i in range(10_001))).encode())
    node_heavy = {"version": "1", "values": [["v"] * 10 for _ in range(5_000)]}
    with pytest.raises(Exception, match="node_limit_exceeded"):
        parser.load_bounded_yaml(json.dumps(node_heavy).encode())
    with pytest.raises(Exception, match="scalar_limit_exceeded"):
        parser.load_bounded_yaml(("version: '1'\nvalue: '" + "x" * (128 * 1024 + 1) + "'\n").encode())

    workspace = tmp_path / "workspace"
    migration = tmp_path / "migration"
    workspace.mkdir()
    migration.mkdir()
    source = workspace / "render.yaml"
    source.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    result = run_parser(workspace, migration, source, migration / "out.json")
    assert result.returncode == 1
    assert "code=source_too_large" in result.stderr


def test_symlink_and_workspace_escape_are_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    migration = tmp_path / "migration"
    workspace.mkdir()
    migration.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("version: '1'\n")
    output = migration / "out.json"
    escaped = run_parser(workspace, migration, outside, output)
    assert escaped.returncode == 1
    assert "code=source_outside_workspace" in escaped.stderr

    link = workspace / "render.yaml"
    link.symlink_to(outside)
    linked = run_parser(workspace, migration, link, output)
    assert linked.returncode == 1
    assert "code=source_outside_workspace" in linked.stderr or "code=source_symlink_forbidden" in linked.stderr
    assert not output.exists()


def test_build_source_conflict_and_unknown_fields_fail_before_output(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    migration = tmp_path / "migration"
    workspace.mkdir()
    migration.mkdir()
    source = workspace / "render.yaml"
    source.write_text("""version: "1"
buildSources:
  - name: build
    image: {url: docker.io/library/alpine:3.21}
services:
  - type: web
    name: conflict
    buildSource: build
    runtime: docker
""")
    output = migration / "out.json"
    result = run_parser(workspace, migration, source, output)
    assert result.returncode == 1
    assert "code=schema_invalid" in result.stderr
    assert not output.exists()

    source.write_bytes((FIXTURES / "schema-invalid.yaml").read_bytes())
    result = run_parser(workspace, migration, source, output)
    assert result.returncode == 1
    assert "code=schema_invalid" in result.stderr
    assert not output.exists()


def test_failure_never_replaces_existing_output(tmp_path: Path) -> None:
    source, migration = copy_fixture(tmp_path, "schema-invalid.yaml")
    output = migration / "out.json"
    output.write_text("existing\n")
    result = run_parser(source.parent, migration, source, output)
    assert result.returncode == 1
    assert output.read_text() == "existing\n"


def test_parser_has_no_network_or_provisioning_surface() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("urllib", "requests", "boto", "socket", "Popen", "render services create", "subprocess"):
        assert forbidden not in source
