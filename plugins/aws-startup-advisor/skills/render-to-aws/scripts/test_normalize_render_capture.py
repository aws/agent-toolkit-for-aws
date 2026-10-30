from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPT_DIR / "normalize-render-capture.py"
spec = importlib.util.spec_from_file_location("normalize_render_capture", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ATTEMPT = "12345678-1234-4234-9234-123456789abc"
DIGEST = "sha256:" + "a" * 64
INDEX_DIGEST = "sha256:" + "c" * 64
CAPTURED_AT = "2026-10-21T12:00:00Z"


def load_script(name: str, module_name: str) -> Any:
    script_spec = importlib.util.spec_from_file_location(module_name, SCRIPT_DIR / name)
    assert script_spec and script_spec.loader
    loaded = importlib.util.module_from_spec(script_spec)
    script_spec.loader.exec_module(loaded)
    return loaded


def write_capture(root: Path, name: str, transport: str, category: str, value: dict[str, Any]) -> dict[str, Any]:
    path = root / name
    payload = module.canonical_bytes(value)
    path.write_bytes(payload)
    live_capture = transport in {"cli", "rest"}
    return {
        "transport": transport,
        "category": category,
        "captured_at": value.get("captured_at", CAPTURED_AT),
        "workspace_id": value.get("workspace_id", "tea-safe"),
        "status": value.get("status", "ok"),
        "page_count": value.get("page_count") if live_capture else None,
        "ownership_index_digest": value.get("ownership_index_digest") if live_capture else None,
        "path": name,
        "digest": module.sha256_digest(payload),
    }


def live(transport: str, category: str, data: Any, resource_id: str | None = None, status: str = "ok") -> dict[str, Any]:
    return {
        "schema_version": "1.0", "transport": "render_cli_2.30.0" if transport == "cli" else "render_rest_v1",
        "category": category, "captured_at": CAPTURED_AT, "attempt_id": ATTEMPT,
        "workspace_id": "tea-safe", "consent_digest": DIGEST,
        "raw_shape": "array", "command_digest": "sha256:" + "b" * 64,
        "ownership_index_digest": INDEX_DIGEST, "status": status, "page_count": 1 if transport == "rest" else None, "raw_shapes": ["array"],
        "request": {"resource_id": resource_id, "start": None, "end": None, "resolution_seconds": None, "limit": 100}, "data": data,
    }


def build_estate(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    captures: list[dict[str, Any]] = []
    blueprint_parser = load_script("parse-render-blueprint.py", "blueprint_for_normalize")
    blueprint_root = SCRIPT_DIR.parent / "fixtures/render-blueprint"
    identity = {"schema_version": "1.0", "status": "active", "identity_scope": "live", "attempt_id": ATTEMPT, "workspace_id": "tea-safe", "local_identity": None, "consent_digest": DIGEST, "ownership_index_digest": INDEX_DIGEST}
    source = blueprint_root / "valid-full.yaml"
    evidence_path = tmp_path / "semantic-evidence.json"
    evidence_path.write_text(json.dumps({
        "schema_version": "1.0", "source_path": "valid-full.yaml",
        "source_digest": module.sha256_digest(source.read_bytes()),
        "manifest_digest": module.sha256_digest(module.canonical_bytes(identity)),
        "attempt_id": ATTEMPT, "workspace_id": "tea-safe", "consent_digest": DIGEST,
        "validated_at": "2026-10-21T12:00:00Z", "outcome": "valid", "errors": [],
    }))
    blueprint = blueprint_parser.parse_blueprint(source, blueprint_root, tmp_path, evidence_path)
    captures.append(write_capture(tmp_path, "blueprint.json", "blueprint", "blueprint", blueprint))
    captures.append(write_capture(tmp_path, "projects.json", "rest", "projects_list", live("rest", "projects_list", [{"id": "prj-safe", "name": "project", "ownerId": "tea-safe"}])))
    captures.append(write_capture(tmp_path, "environments.json", "rest", "environments_list", live("rest", "environments_list", [{"id": "evm-safe-prod", "name": "production", "projectId": "prj-safe", "serviceIds": ["srv-safe-api"], "databasesIds": [], "redisIds": [], "envGroupIds": []}], "prj-safe")))
    services = [{"id": "srv-safe-api", "name": "root-api", "ownerId": "tea-safe", "type": "web_service", "projectId": None, "region": "ohio", "repo": "https://github.com/example/live-drift", "serviceDetails": {"plan": "0.5c-512mb", "buildPlan": "starter", "runtime": "python", "numInstances": 1}}]
    captures.append(write_capture(tmp_path, "services.json", "rest", "services_list", live("rest", "services_list", services)))
    build_source = [{"id": "bld-safe", "name": "shared-build", "ownerId": "tea-safe", "repo": "https://github.com/example/safe-app", "branch": "main", "commit": "0123456789abcdef", "artifact": {"id": "artifact-safe", "digest": "sha256:" + "d" * 64}, "buildCommand": "docker build .", "serviceIds": ["srv-safe-api"], "environmentIds": ["evm-safe-prod"], "buildEnvVarNames": ["BUILD_MODE"], "runtimeEnvVarNames": ["PORT"]}]
    captures.append(write_capture(tmp_path, "build-sources.json", "rest", "build_sources_list", live("rest", "build_sources_list", build_source)))
    deploys = [{"id": "dep-old", "status": "live", "createdAt": "2026-10-20T12:00:00Z", "commit": {"id": "abc"}}, {"id": "dep-new", "status": "update_failed", "createdAt": "2026-10-21T12:00:00Z", "finishedAt": "2026-10-21T12:02:00Z", "commit": {"id": "abc"}}]
    captures.append(write_capture(tmp_path, "deploys.json", "rest", "deploys_list", live("rest", "deploys_list", deploys, "srv-safe-api")))
    events = [{"id": "evt-safe", "resourceId": "srv-safe-api", "type": "deploy_live", "timestamp": "2026-10-20T12:00:00Z", "statusCode": 200}]
    captures.append(write_capture(tmp_path, "events.json", "rest", "service_events", live("rest", "service_events", events, "srv-safe-api")))
    captures.append(write_capture(tmp_path, "workflows.json", "rest", "workflows_list", live("rest", "workflows_list", [{"id": "wfl-safe", "name": "workflow", "ownerId": "tea-safe", "type": "workflow", "environmentId": "evm-safe-prod"}])))
    captures.append(write_capture(tmp_path, "workflow-versions.json", "rest", "workflow_versions_list", live("rest", "workflow_versions_list", [{"id": "wfv-safe", "name": "v1", "workflowId": "wfl-safe", "ownerId": "tea-safe"}], "wfl-safe")))
    captures.append(write_capture(tmp_path, "workflow-tasks.json", "rest", "workflow_tasks_list", live("rest", "workflow_tasks_list", [{"id": "tsk-safe", "name": "task", "workflowVersionId": "wfv-safe", "ownerId": "tea-safe"}], "wfl-safe")))
    captures.append(write_capture(tmp_path, "workflow-runs.json", "rest", "workflow_task_runs_list", live("rest", "workflow_task_runs_list", [{"id": "run-safe", "name": "run", "taskId": "tsk-safe", "ownerId": "tea-safe", "attempts": [{"id": "att-safe", "name": "attempt-1", "status": "succeeded"}]}], "wfl-safe")))
    scanner = load_script("scan-render-application.py", "scanner_for_normalize")
    application = scanner.scan(SCRIPT_DIR.parent / "fixtures/render-application")
    captures.append(write_capture(tmp_path, "application.json", "application", "application", application))
    billing_parser = load_script("parse-render-billing.py", "billing_for_normalize")
    billing_data = (SCRIPT_DIR.parent / "fixtures/render-billing/user-stated.json").read_bytes()
    billing = billing_parser.parse(billing_data, ".json")
    captures.append(write_capture(tmp_path, "billing.json", "billing", "billing", billing))
    manifest = {"schema_version": "1.0", "status": "active", "identity_scope": "live", "attempt_id": ATTEMPT, "workspace_id": "tea-safe", "local_identity": None, "consent_digest": DIGEST, "ownership_index_digest": INDEX_DIGEST, "captures": captures}
    (tmp_path / "manifest.json").write_bytes(module.canonical_bytes(manifest))
    return tmp_path / "manifest.json"


def test_mixed_estate_normalizes_drift_lifecycle_build_sources_workflows_and_ai(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_manifest = build_estate(first_root)
    second_manifest = build_estate(second_root)
    first_inventory, first_clusters, first_ai, first_discovery = module.normalize(first_root, first_manifest, ATTEMPT)
    second_inventory, second_clusters, second_ai, second_discovery = module.normalize(second_root, second_manifest, ATTEMPT)
    assert module.canonical_bytes(first_inventory) == module.canonical_bytes(second_inventory)
    assert module.canonical_bytes(first_clusters) == module.canonical_bytes(second_clusters)
    assert module.canonical_bytes(first_ai) == module.canonical_bytes(second_ai)
    assert module.canonical_bytes(first_discovery) == module.canonical_bytes(second_discovery)
    kinds = {resource["kind"] for resource in first_inventory["resources"]}
    assert {
        "render.web_service", "render.static_site", "render.private_service",
        "render.background_worker", "render.cron_job", "render.postgres",
        "render.key_value", "render.persistent_disk", "render.project",
        "render.environment", "render.environment_group", "render.custom_domain",
        "render.preview_environment", "render.build_source", "render.build_artifact",
        "render.workflow", "render.workflow_version", "render.workflow_task",
        "render.task_run", "render.task_attempt",
    } <= kinds
    edge_types = {edge["type"] for edge in first_inventory["edges"]}
    assert {"service_to_key_value", "private_network_peer", "shares_repository", "service_uses_build_source", "build_source_produces_artifact", "environment_promotes_artifact", "workflow_has_version", "workflow_version_has_task", "workflow_task_has_run", "task_run_has_attempt"} <= edge_types
    api = next(
        resource for resource in first_inventory["resources"]
        if resource["kind"] == "render.web_service" and resource["name"] == "root-api"
    )
    assert api["region"] == "ohio"
    assert api["environment_id"] == "evm-safe-prod"
    assert api["project_id"] == "prj-safe"
    assert api["provenance"]["environment_id"] == "rest:environments_list"
    assert api["config"]["repo"] == "https://github.com/example/shared-app"
    repo_drift = next(item for item in first_inventory["drift"] if item["resource_id"] == api["id"] and item["field"] == "config.repo")
    assert repo_drift["selection_reason"] == "declared_repository_intent_prefers_blueprint"
    membership_edges = [edge for edge in first_inventory["edges"] if edge["from_id"] == api["id"] and edge["type"] in {"member_of_environment", "member_of_project"}]
    assert {edge["type"] for edge in membership_edges} == {"member_of_environment", "member_of_project"}
    disk = next(resource for resource in first_inventory["resources"] if resource["kind"] == "render.persistent_disk")
    disk_edge = next(edge for edge in first_inventory["edges"] if edge["type"] == "service_to_disk" and edge["to_id"] == disk["id"])
    disk_owner = next(resource for resource in first_inventory["resources"] if resource["id"] == disk_edge["from_id"])
    assert disk["region"] == disk_owner["region"] == "virginia"
    assert disk_edge["attributes"] == {
        "mountPath": "/var/data",
        "sizeGB": 5,
        "sizeGB_provenance": "declared",
        "capacity_unit": "GB",
        "region": "virginia",
        "region_provenance": disk["provenance"]["region"],
        "source": "declared",
    }
    assert len([edge for edge in first_inventory["edges"] if edge["type"] == "service_to_disk" and edge["to_id"] == disk["id"]]) == 1
    production_environment = next(
        resource for resource in first_inventory["resources"]
        if resource["kind"] == "render.environment" and resource["name"] == "production"
    )
    assert production_environment["render_id"] == "evm-safe-prod"
    assert production_environment["environment_id"] == "evm-safe-prod"
    production_cluster = next(
        cluster for cluster in first_clusters["clusters"]
        if api["id"] in cluster["member_ids"]
    )
    assert production_environment["id"] in production_cluster["member_ids"]
    assert production_cluster["seed"] == "evm-safe-prod"
    assert not any(cluster["seed"] == "production" for cluster in first_clusters["clusters"])
    assert api["config"]["lifecycle_evidence"]["live_deploy_id"] == "dep-old"
    assert api["config"]["lifecycle_evidence"]["newest_deploy_id"] == "dep-new"
    assert any(item["field"] in {"region", "config.plan"} for item in first_inventory["drift"])
    accounted = first_inventory["accounting"]["accounted_resource_ids"]
    clustered = [item for cluster in first_clusters["clusters"] for item in cluster["member_ids"]] + first_clusters["unclustered_resource_ids"]
    assert sorted(accounted) == sorted(clustered) and len(clustered) == len(set(clustered))
    assert "execution" not in first_ai and first_ai["schema_version"] == "1.0"
    assert first_inventory["resources"] == sorted(first_inventory["resources"], key=lambda item: item["id"].encode())


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing", "environment_membership_unresolved"),
        ("duplicate", "environment_membership_duplicate"),
        ("wrong_kind", "environment_membership_wrong_kind"),
        ("conflict", "environment_membership_conflict"),
    ],
)
def test_environment_membership_arrays_fail_closed(tmp_path: Path, mutation: str, error: str) -> None:
    manifest = build_estate(tmp_path)
    document = json.loads(manifest.read_text())
    entry = next(item for item in document["captures"] if item["category"] == "environments_list")
    capture_path = tmp_path / entry["path"]
    capture = json.loads(capture_path.read_text())
    environment = capture["data"][0]
    if mutation == "missing":
        environment["serviceIds"] = ["srv-missing"]
    elif mutation == "duplicate":
        environment["serviceIds"] = ["srv-safe-api", "srv-safe-api"]
    elif mutation == "wrong_kind":
        environment["databasesIds"] = ["srv-safe-api"]
    else:
        capture["data"].append({
            "id": "evm-safe-other", "name": "other", "projectId": "prj-safe",
            "serviceIds": ["srv-safe-api"], "databasesIds": [], "redisIds": [], "envGroupIds": [],
        })
    capture_path.write_bytes(module.canonical_bytes(capture))
    entry["digest"] = module.sha256_digest(capture_path.read_bytes())
    manifest.write_bytes(module.canonical_bytes(document))
    with pytest.raises(module.NormalizeError, match=error):
        module.normalize(tmp_path, manifest, ATTEMPT)


def test_manifest_digest_attempt_and_secret_fail_without_outputs(tmp_path: Path) -> None:
    manifest = build_estate(tmp_path)
    document = json.loads(manifest.read_text())
    document["captures"][0]["digest"] = "sha256:" + "0" * 64
    manifest.write_bytes(module.canonical_bytes(document))
    with pytest.raises(module.NormalizeError, match="capture_digest_mismatch"):
        module.normalize(tmp_path, manifest, ATTEMPT)
    assert not (tmp_path / "inventory.json").exists()

    manifest = build_estate(tmp_path)
    document = json.loads(manifest.read_text())
    del document["captures"][0]["captured_at"]
    manifest.write_bytes(module.canonical_bytes(document))
    with pytest.raises(module.NormalizeError, match="manifest_invalid"):
        module.normalize(tmp_path, manifest, ATTEMPT)

    manifest = build_estate(tmp_path)
    with pytest.raises(module.NormalizeError, match="manifest_invalid"):
        module.normalize(tmp_path, manifest, "87654321-4321-4321-8321-cba987654321")


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("captured_at", "2026-10-21T12:00:01Z"),
        ("workspace_id", "tea-other"),
        ("status", "successful_empty"),
        ("page_count", 2),
    ],
)
def test_manifest_capture_evidence_must_match_child(tmp_path: Path, field: str, replacement: object) -> None:
    manifest = build_estate(tmp_path)
    document = json.loads(manifest.read_text())
    live_entry = next(entry for entry in document["captures"] if entry["transport"] == "rest")
    live_entry[field] = replacement
    manifest.write_bytes(module.canonical_bytes(document))
    with pytest.raises(module.NormalizeError, match="capture_evidence_mismatch"):
        module.normalize(tmp_path, manifest, ATTEMPT)


def test_cli_child_from_previous_ownership_index_generation_is_rejected(tmp_path: Path) -> None:
    old_child = live("cli", "projects_list", [{"id": "prj-safe", "name": "project", "ownerId": "tea-safe"}])
    entry = write_capture(tmp_path, "projects-cli.json", "cli", "projects_list", old_child)
    new_index_digest = "sha256:" + "d" * 64
    entry["ownership_index_digest"] = new_index_digest
    manifest = {
        "schema_version": "1.0",
        "status": "active",
        "identity_scope": "live",
        "attempt_id": ATTEMPT,
        "workspace_id": "tea-safe",
        "local_identity": None,
        "consent_digest": DIGEST,
        "ownership_index_digest": new_index_digest,
        "captures": [entry],
    }
    path = tmp_path / "manifest.json"
    path.write_bytes(module.canonical_bytes(manifest))
    with pytest.raises(module.NormalizeError, match="capture_evidence_mismatch"):
        module.normalize(tmp_path, path, ATTEMPT)


def test_blueprint_only_discover_accepts_absent_or_stale_semantic_evidence(tmp_path: Path) -> None:
    for semantic in (
        {"status": "not_provided", "requires_renewed_consent": True},
        {"status": "stale", "evidence_source_digest": "sha256:" + "f" * 64, "requires_renewed_consent": True},
    ):
        root = tmp_path / semantic["status"]
        manifest = build_estate(root)
        document = json.loads(manifest.read_text())
        document["captures"] = [document["captures"][0]]
        local_identity = "sha256:" + "e" * 64
        document.update({
            "identity_scope": "local",
            "workspace_id": None,
            "local_identity": local_identity,
            "consent_digest": None,
            "ownership_index_digest": None,
        })
        document["captures"][0]["workspace_id"] = None
        document["captures"][0]["ownership_index_digest"] = None
        blueprint_path = root / "blueprint.json"
        blueprint = json.loads(blueprint_path.read_text())
        blueprint["semantic_validation"] = semantic
        blueprint_path.write_bytes(module.canonical_bytes(blueprint))
        document["captures"][0]["digest"] = module.sha256_digest(blueprint_path.read_bytes())
        manifest.write_bytes(module.canonical_bytes(document))

        inventory, clusters, ai_profile, ai_discovery = module.normalize(root, manifest, ATTEMPT)
        assert inventory["discovery_sources"] == ["render_blueprint"]
        assert inventory["workspace_id"] == "local:" + local_identity.removeprefix("sha256:")
        assert all(resource["workspace_id"] == inventory["workspace_id"] for resource in inventory["resources"])
        assert inventory["resources"]
        assert clusters["clusters"] or clusters["unclustered_resource_ids"]
        assert ai_profile is None
        assert ai_discovery is None


def blueprint_only_manifest(root: Path, blueprint_yaml: str) -> Path:
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    source = workspace / "render.yaml"
    source.write_text(blueprint_yaml)
    blueprint_parser = load_script("parse-render-blueprint.py", "blueprint_for_normalize_local")
    blueprint = blueprint_parser.parse_blueprint(source, workspace, root)
    capture = write_capture(root, "blueprint.json", "blueprint", "blueprint", blueprint)
    capture["workspace_id"] = None
    capture["ownership_index_digest"] = None
    manifest = {"schema_version": "1.0", "status": "active", "identity_scope": "local", "attempt_id": ATTEMPT, "workspace_id": None, "local_identity": "sha256:" + "e" * 64, "consent_digest": None, "ownership_index_digest": None, "captures": [capture]}
    path = root / "manifest.json"
    path.write_bytes(module.canonical_bytes(manifest))
    return path


def test_blueprint_only_disk_without_size_normalizes_with_schema_default(tmp_path: Path) -> None:
    manifest = blueprint_only_manifest(tmp_path, """services:
  - type: web
    name: api
    runtime: docker
    disk:
      name: data
      mountPath: /var/data
""")
    inventory, _clusters, _ai_profile, _ai_discovery = module.normalize(tmp_path, manifest, ATTEMPT)
    disk = next(item for item in inventory["resources"] if item["kind"] == "render.persistent_disk")
    assert disk["config"]["sizeGB"] == 10
    assert disk["config"]["sizeGB_provenance"] == "schema_default"
    edge = next(edge for edge in inventory["edges"] if edge["type"] == "service_to_disk")
    assert edge["to_id"] == disk["id"]
    assert edge["attributes"]["sizeGB"] == 10
    assert edge["attributes"]["sizeGB_provenance"] == "schema_default"
    assert edge["attributes"]["source"] == "declared"


def test_blueprint_only_disk_with_explicit_size_keeps_declared_provenance(tmp_path: Path) -> None:
    manifest = blueprint_only_manifest(tmp_path, """services:
  - type: web
    name: api
    runtime: docker
    disk:
      name: data
      mountPath: /var/data
      sizeGB: 5
""")
    inventory, *_ = module.normalize(tmp_path, manifest, ATTEMPT)
    edge = next(edge for edge in inventory["edges"] if edge["type"] == "service_to_disk")
    assert edge["attributes"]["sizeGB"] == 5
    assert edge["attributes"]["sizeGB_provenance"] == "declared"


def test_live_plans_resolve_through_the_shared_alias_table(tmp_path: Path) -> None:
    services = live("rest", "services_list", [
        {"id": "srv-plan-web", "name": "web", "ownerId": "tea-safe", "type": "web_service", "serviceDetails": {"runtime": "python", "plan": "pro plus"}},
        {"id": "srv-plan-cron", "name": "cron", "ownerId": "tea-safe", "type": "cron_job", "serviceDetails": {"runtime": "python", "plan": "1c-2g"}},
        {"id": "srv-plan-huge", "name": "huge", "ownerId": "tea-safe", "type": "background_worker", "serviceDetails": {"runtime": "python", "plan": "8c-64g"}},
        {"id": "srv-plan-static", "name": "site", "ownerId": "tea-safe", "type": "static_site", "serviceDetails": {"runtime": "static"}},
    ])
    key_values = live("cli", "keyvalues_list", {"data": [{"id": "red-plan", "name": "cache", "ownerId": "tea-safe", "plan": "pro ultra"}]})
    manifest = live_manifest(tmp_path, [
        write_capture(tmp_path, "services.json", "rest", "services_list", services),
        write_capture(tmp_path, "keyvalues.json", "cli", "keyvalues_list", key_values),
    ])
    inventory, *_ = module.normalize(tmp_path, manifest, ATTEMPT)
    configs = {resource["name"]: resource["config"] for resource in inventory["resources"]}
    assert configs["web"]["serviceDetails"]["plan"] == "pro plus"
    assert configs["web"]["plan_normalized"] == "4c-8gb"
    assert configs["cron"]["plan_normalized"] == "1c-2gb"
    # Unpriced spelling: raw plan retained, normalized form null, no neighbouring plan borrowed.
    assert configs["huge"]["serviceDetails"]["plan"] == "8c-64g"
    assert configs["huge"]["plan_normalized"] is None
    assert "plan_normalized" not in configs["site"]
    assert configs["cache"]["plan"] == "pro ultra"
    assert configs["cache"]["plan_normalized"] == "40g"


def test_live_only_discover_has_no_blueprint_provenance(tmp_path: Path) -> None:
    capture = live("rest", "services_list", [{
        "id": "srv-live-only", "name": "live-only", "ownerId": "tea-safe",
        "type": "web_service", "serviceDetails": {"runtime": "python"},
    }])
    entry = write_capture(tmp_path, "services.json", "rest", "services_list", capture)
    manifest = {
        "schema_version": "1.0", "status": "active", "identity_scope": "live", "attempt_id": ATTEMPT,
        "workspace_id": "tea-safe", "local_identity": None, "consent_digest": DIGEST,
        "ownership_index_digest": INDEX_DIGEST, "captures": [entry],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(module.canonical_bytes(manifest))

    inventory, _, _, _ = module.normalize(tmp_path, manifest_path, ATTEMPT)
    assert inventory["discovery_sources"] == ["render_rest"]
    assert "render_blueprint" not in inventory["discovery_sources"]


def test_blueprint_semantic_tuple_and_local_references_fail_closed(tmp_path: Path) -> None:
    manifest = build_estate(tmp_path)
    document = json.loads(manifest.read_text())
    blueprint_path = tmp_path / "blueprint.json"
    blueprint = json.loads(blueprint_path.read_text())
    blueprint["semantic_validation"]["outcome"] = "semantic_invalid"
    blueprint["semantic_validation"]["status"] = "invalid"
    blueprint_path.write_bytes(module.canonical_bytes(blueprint))
    document["captures"][0]["digest"] = module.sha256_digest(blueprint_path.read_bytes())
    manifest.write_bytes(module.canonical_bytes(document))
    with pytest.raises(module.NormalizeError, match="blueprint_semantic_validation_invalid"):
        module.normalize(tmp_path, manifest, ATTEMPT)

    manifest = build_estate(tmp_path)
    blueprint = json.loads(blueprint_path.read_text())
    blueprint["local_reference_validation"] = {"status": "semantic_invalid", "errors": [{"code": "broken_reference"}]}
    blueprint_path.write_bytes(module.canonical_bytes(blueprint))
    document = json.loads(manifest.read_text())
    document["captures"][0]["digest"] = module.sha256_digest(blueprint_path.read_bytes())
    manifest.write_bytes(module.canonical_bytes(document))
    with pytest.raises(module.NormalizeError, match="blueprint_local_references_invalid"):
        module.normalize(tmp_path, manifest, ATTEMPT)


def test_multi_output_commit_rolls_back_every_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = [tmp_path / "inventory.json", tmp_path / "clusters.json", tmp_path / "ai.json"]
    for index, path in enumerate(paths):
        path.write_text(f"old-{index}\n")
    real_replace = module.os.replace
    replacements = 0

    def fail_second(source: object, destination: object) -> None:
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("injected commit failure")
        real_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_second)
    with pytest.raises(OSError, match="injected commit failure"):
        module._write_generation([(paths[0], {"new": 1}), (paths[1], {"new": 2}), (paths[2], None)])
    assert [path.read_text() for path in paths] == ["old-0\n", "old-1\n", "old-2\n"]


def test_duplicate_live_identity_rejects_instead_of_suffixing(tmp_path: Path) -> None:
    captures = []
    duplicate = [{"id": "srv-duplicate", "name": "one", "ownerId": "tea-safe", "type": "web_service"}, {"id": "srv-duplicate", "name": "two", "ownerId": "tea-safe", "type": "web_service"}]
    captures.append(write_capture(tmp_path, "services.json", "rest", "services_list", live("rest", "services_list", duplicate)))
    manifest = {"schema_version": "1.0", "status": "active", "identity_scope": "live", "attempt_id": ATTEMPT, "workspace_id": "tea-safe", "local_identity": None, "consent_digest": DIGEST, "ownership_index_digest": INDEX_DIGEST, "captures": captures}
    path = tmp_path / "manifest.json"
    path.write_bytes(module.canonical_bytes(manifest))
    with pytest.raises(module.NormalizeError, match="duplicate_resource_identity"):
        module.normalize(tmp_path, path, ATTEMPT)


INVENTORY_SCHEMA = SCRIPT_DIR.parent / "references/shared/schema-render-resource-inventory.json"


def live_manifest(root: Path, captures: list[dict[str, Any]]) -> Path:
    manifest = {"schema_version": "1.0", "status": "active", "identity_scope": "live", "attempt_id": ATTEMPT, "workspace_id": "tea-safe", "local_identity": None, "consent_digest": DIGEST, "ownership_index_digest": INDEX_DIGEST, "captures": captures}
    path = root / "manifest.json"
    path.write_bytes(module.canonical_bytes(manifest))
    return path


def metric_capture(resource_id: str, day: int, series: list[dict[str, Any]], captured_at: str = CAPTURED_AT) -> dict[str, Any]:
    capture = live("rest", "metric_cpu", series, resource_id)
    capture["captured_at"] = captured_at
    capture["raw_shapes"] = ["metric_series"]
    capture["request"] = {"resource_id": resource_id, "start": f"2026-10-{14 + day:02d}T00:00:00Z", "end": f"2026-10-{15 + day:02d}T00:00:00Z", "resolution_seconds": 3600, "event_type": None, "limit": None}
    return capture


def web_service(resource_id: str, name: str, project_id: str | None = None, environment_id: str | None = None) -> dict[str, Any]:
    return {"id": resource_id, "name": name, "ownerId": "tea-safe", "type": "web_service", "projectId": project_id, "environmentId": environment_id, "serviceDetails": {"runtime": "python"}}


def environment(render_id: str, name: str, project_id: str, service_ids: list[str] | None = None) -> dict[str, Any]:
    return {"id": render_id, "name": name, "projectId": project_id, "serviceIds": service_ids or [], "databasesIds": [], "redisIds": [], "envGroupIds": []}


def test_populated_metric_series_and_log_labels_normalize(tmp_path: Path) -> None:
    from jsonschema import Draft202012Validator, FormatChecker

    series = [{"labels": [{"field": "instance", "value": "srv-a-1"}], "unit": "percent", "values": [{"timestamp": "2026-10-14T00:00:00Z", "value": 1.5}]}]
    logs = [{"id": "log-1", "timestamp": "2026-10-14T00:00:01Z", "labels": [{"name": "level", "value": "info"}, {"name": "instance", "value": "srv-a-1"}]}]
    log_capture = live("cli", "log_metadata", logs, "srv-a")
    log_capture["raw_shape"] = "json_stream"
    log_capture["request"] = {"resource_id": "srv-a", "start": "2026-10-14T00:00:00Z", "end": "2026-10-14T01:00:00Z", "limit": 100}
    captures = [
        write_capture(tmp_path, "services.json", "rest", "services_list", live("rest", "services_list", [web_service("srv-a", "api")])),
        write_capture(tmp_path, "metric-cpu.json", "rest", "metric_cpu", metric_capture("srv-a", 0, series)),
        write_capture(tmp_path, "logs.json", "cli", "log_metadata", log_capture),
    ]
    inventory, _, _, _ = module.normalize(tmp_path, live_manifest(tmp_path, captures), ATTEMPT)
    api = next(resource for resource in inventory["resources"] if resource["kind"] == "render.web_service")
    evidence = api["config"]["lifecycle_evidence"]
    assert evidence["metrics"]["metric_cpu"][0]["series"][0]["values"][0]["value"] == 1.5
    assert evidence["metrics"]["metric_cpu"][0]["series"][0]["labels"] == [{"field": "instance", "value": "srv-a-1"}]
    assert evidence["metrics"]["metric_cpu"][0]["outcome"] == "ok"
    assert evidence["metrics"]["metric_cpu"][0]["source_ref"] == "rest:metric_cpu"
    assert evidence["log_metadata"] == logs
    assert inventory["discovery_sources"] == ["render_cli", "render_rest"]
    assert not list(Draft202012Validator(json.loads(INVENTORY_SCHEMA.read_text()), format_checker=FormatChecker()).iter_errors(inventory))


def test_seven_daily_metric_windows_are_all_retained_in_order(tmp_path: Path) -> None:
    captures = [write_capture(tmp_path, "services.json", "rest", "services_list", live("rest", "services_list", [web_service("srv-a", "api")]))]
    # Written newest-first so retention order cannot come from manifest order.
    for day in reversed(range(7)):
        series = [{"labels": [], "unit": "percent", "values": [{"timestamp": f"2026-10-{14 + day:02d}T00:00:00Z", "value": float(day)}]}]
        status = "ok" if day != 3 else "successful_empty"
        capture = metric_capture("srv-a", day, series if day != 3 else [], captured_at=f"2026-10-{15 + day:02d}T00:05:00Z")
        capture["status"] = status
        captures.append(write_capture(tmp_path, f"metric-{day}.json", "rest", "metric_cpu", capture))
    inventory, _, _, _ = module.normalize(tmp_path, live_manifest(tmp_path, captures), ATTEMPT)
    api = next(resource for resource in inventory["resources"] if resource["kind"] == "render.web_service")
    windows = api["config"]["lifecycle_evidence"]["metrics"]["metric_cpu"]
    assert len(windows) == 7
    starts = [item["window"]["start"] for item in windows]
    assert starts == sorted(starts)
    assert [item["outcome"] for item in windows] == ["ok", "ok", "ok", "successful_empty", "ok", "ok", "ok"]
    assert all(item["source_ref"] == "rest:metric_cpu" and item["captured_at"].endswith("T00:05:00Z") for item in windows)
    assert windows[6]["series"][0]["values"][0]["value"] == 6.0

    duplicate = metric_capture("srv-a", 2, [], captured_at="2026-10-21T00:00:00Z")
    captures.append(write_capture(tmp_path, "metric-duplicate.json", "rest", "metric_cpu", duplicate))
    with pytest.raises(module.NormalizeError, match="duplicate_metric_window"):
        module.normalize(tmp_path, live_manifest(tmp_path, captures), ATTEMPT)


@pytest.mark.parametrize(
    ("category", "payload", "error"),
    [
        ("metric_cpu", [{"labels": [{"field": "instance", "value": "-----BEGIN RSA PRIVATE KEY-----"}], "unit": "percent", "values": []}], "secret_bearing_input"),
        ("metric_cpu", [{"labels": [{"field": "instance", "value": "rnd_abcdefghijklmnop1234"}], "unit": "percent", "values": []}], "secret_bearing_input"),
        ("metric_cpu", [{"labels": [], "unit": "percent", "values": [], "token": "x"}], "metric_series_invalid"),
        ("metric_cpu", [{"labels": [], "unit": "percent", "values": [{"timestamp": "2026-10-14T00:00:00Z", "value": "1.5"}]}], "metric_series_invalid"),
        ("log_metadata", [{"id": "log-1", "timestamp": "2026-10-14T00:00:00Z", "labels": [{"name": "message", "value": "x"}]}], "log_metadata_invalid"),
        ("log_metadata", [{"id": "log-1", "timestamp": "2026-10-14T00:00:00Z", "labels": [{"name": "level", "value": "AKIAIOSFODNN7EXAMPLE"}]}], "secret_bearing_input"),
    ],
)
def test_metric_projection_keeps_secret_rejection_elsewhere(tmp_path: Path, category: str, payload: Any, error: str) -> None:
    captures = [write_capture(tmp_path, "services.json", "rest", "services_list", live("rest", "services_list", [web_service("srv-a", "api")]))]
    if category == "metric_cpu":
        captures.append(write_capture(tmp_path, "metric.json", "rest", "metric_cpu", metric_capture("srv-a", 0, payload)))
    else:
        capture = live("cli", "log_metadata", payload, "srv-a")
        capture["raw_shape"] = "json_stream"
        captures.append(write_capture(tmp_path, "logs.json", "cli", "log_metadata", capture))
    with pytest.raises(module.NormalizeError, match=error):
        module.normalize(tmp_path, live_manifest(tmp_path, captures), ATTEMPT)


def test_value_key_outside_metric_and_log_shapes_is_still_secret_bearing(tmp_path: Path) -> None:
    item = web_service("srv-a", "api")
    item["value"] = "plain"
    captures = [write_capture(tmp_path, "services.json", "rest", "services_list", live("rest", "services_list", [item]))]
    with pytest.raises(module.NormalizeError, match="secret_bearing_input"):
        module.normalize(tmp_path, live_manifest(tmp_path, captures), ATTEMPT)
    with pytest.raises(module.NormalizeError, match="secret_bearing_input"):
        module._safe_tree([{"labels": [{"field": "instance", "value": "srv-a"}]}])


def test_cli_nullable_data_envelope_yields_no_resource_row(tmp_path: Path) -> None:
    postgres = live("cli", "postgres_get", {"data": None}, "dpg-safe")
    postgres["raw_shape"] = "data_null"
    absent = live("rest", "service_get", [], "srv-gone", status="absent")
    absent["raw_shapes"] = ["http_404"]
    captures = [
        write_capture(tmp_path, "services.json", "cli", "services_list", live("cli", "services_list", [{"service": web_service("srv-a", "api")}])),
        write_capture(tmp_path, "postgres.json", "cli", "postgres_get", postgres),
        write_capture(tmp_path, "service-absent.json", "rest", "service_get", absent),
    ]
    inventory, _, _, _ = module.normalize(tmp_path, live_manifest(tmp_path, captures), ATTEMPT)
    assert [resource["kind"] for resource in inventory["resources"]] == ["render.web_service"]
    assert inventory["discovery_sources"] == ["render_cli", "render_rest"]
    assert module._iter_cli_data("keyvalue_get", {"data": None}) == []
    assert module._iter_cli_data("projects_list", None) == []

    # services_list is `nullable_wrapper_array` in render-cli-contracts.json, so the non-nullable controls are
    # environments_list (`array`) and postgres_list (`data_array`).
    assert module._iter_cli_data("services_list", None) == []
    for category, payload in (("postgres_get", {"data": "oops"}), ("postgres_get", {"data": 5}), ("environments_list", None), ("postgres_list", {"data": None}), ("postgres_list", None)):
        with pytest.raises(module.NormalizeError, match="capture_data_invalid"):
            module._iter_cli_data(category, payload)
    bad = live("cli", "postgres_get", {"data": "oops"}, "dpg-safe")
    bad["raw_shape"] = "data_null"
    captures[1] = write_capture(tmp_path, "postgres.json", "cli", "postgres_get", bad)
    with pytest.raises(module.NormalizeError, match="capture_data_invalid"):
        module.normalize(tmp_path, live_manifest(tmp_path, captures), ATTEMPT)


def test_populated_task_run_detail_normalizes_with_attempts_and_parent(tmp_path: Path) -> None:
    detail = {"id": "run-safe", "name": "run", "ownerId": "tea-safe", "taskId": "tsk-safe", "status": "succeeded", "attempts": [{"id": "att-safe", "name": "attempt-1", "status": "succeeded"}]}
    captures = [
        write_capture(tmp_path, "workflow-tasks.json", "rest", "workflow_tasks_list", live("rest", "workflow_tasks_list", [{"id": "tsk-safe", "name": "task", "workflowVersionId": "wfv-safe", "ownerId": "tea-safe"}], "wfl-safe")),
        write_capture(tmp_path, "workflow-task-run.json", "cli", "workflow_task_run_show", live("cli", "workflow_task_run_show", detail, "run-safe")),
    ]
    inventory, _, _, _ = module.normalize(tmp_path, live_manifest(tmp_path, captures), ATTEMPT)
    run = next(resource for resource in inventory["resources"] if resource["kind"] == "render.task_run")
    assert run["render_id"] == "run-safe"
    attempt = next(resource for resource in inventory["resources"] if resource["kind"] == "render.task_attempt")
    assert attempt["render_id"] == "att-safe"
    edge_types = {(edge["type"], edge["from_id"], edge["to_id"]) for edge in inventory["edges"]}
    assert ("task_run_has_attempt", run["id"], attempt["id"]) in edge_types
    assert any(edge["type"] == "workflow_task_has_run" and edge["to_id"] == run["id"] for edge in inventory["edges"])
def test_nullable_task_run_detail_yields_no_resource_row(tmp_path: Path) -> None:
    absent = live("cli", "workflow_task_run_show", None, "run-safe")
    absent["raw_shape"] = "null"
    captures = [write_capture(tmp_path, "workflow-task-run.json", "cli", "workflow_task_run_show", absent)]
    inventory, _, _, _ = module.normalize(tmp_path, live_manifest(tmp_path, captures), ATTEMPT)
    assert inventory["resources"] == []
    assert module._iter_cli_data("workflow_task_run_show", None) == []
def two_project_captures(root: Path) -> list[dict[str, Any]]:
    projects = [{"id": "prj-a", "name": "alpha", "ownerId": "tea-safe"}, {"id": "prj-b", "name": "beta", "ownerId": "tea-safe"}]
    environments = [environment("evm-a", "production", "prj-a", ["srv-a"]), environment("evm-b", "production", "prj-b", ["srv-b"])]
    services = [web_service("srv-a", "alpha-api"), web_service("srv-b", "beta-api")]
    return [
        write_capture(root, "projects.json", "rest", "projects_list", live("rest", "projects_list", projects)),
        write_capture(root, "environments.json", "rest", "environments_list", live("rest", "environments_list", environments)),
        write_capture(root, "services.json", "rest", "services_list", live("rest", "services_list", services)),
    ]


def assert_distinct_production_environments(inventory: dict[str, Any]) -> None:
    environments = {resource["render_id"]: resource for resource in inventory["resources"] if resource["kind"] == "render.environment" and resource["name"] == "production"}
    assert set(environments) == {"evm-a", "evm-b"}
    assert environments["evm-a"]["project_id"] == "prj-a" and environments["evm-b"]["project_id"] == "prj-b"
    by_render_id = {resource["render_id"]: resource for resource in inventory["resources"] if resource["render_id"]}
    for service_id, environment_id in (("srv-a", "evm-a"), ("srv-b", "evm-b")):
        service = by_render_id[service_id]
        assert service["environment_id"] == environment_id
        edge = next(edge for edge in inventory["edges"] if edge["type"] == "member_of_environment" and edge["from_id"] == service["id"])
        assert edge["to_id"] == environments[environment_id]["id"]


def test_same_named_environments_in_two_projects_are_distinct_live_only(tmp_path: Path) -> None:
    inventory, clusters, _, _ = module.normalize(tmp_path, live_manifest(tmp_path, two_project_captures(tmp_path)), ATTEMPT)
    assert_distinct_production_environments(inventory)
    by_render_id = {resource["render_id"]: resource["id"] for resource in inventory["resources"] if resource["render_id"]}
    cluster_of = {member: cluster["seed"] for cluster in clusters["clusters"] for member in cluster["member_ids"]}
    assert cluster_of[by_render_id["srv-a"]] == "evm-a" and cluster_of[by_render_id["srv-b"]] == "evm-b"
    assert not any(cluster["seed"] == "production" for cluster in clusters["clusters"])


def test_same_named_environments_in_two_projects_are_distinct_mixed_input(tmp_path: Path) -> None:
    manifest = build_estate(tmp_path)
    document = json.loads(manifest.read_text())
    # The Blueprint declares project `storefront` / environment `production`; live side maps it to prj-safe and adds an unrelated project with its own `production`.
    for entry in document["captures"]:
        if entry["category"] == "projects_list":
            projects = [{"id": "prj-safe", "name": "storefront", "ownerId": "tea-safe"}, {"id": "prj-other", "name": "other", "ownerId": "tea-safe"}]
            document["captures"][document["captures"].index(entry)] = write_capture(tmp_path, "projects.json", "rest", "projects_list", live("rest", "projects_list", projects))
        elif entry["category"] == "environments_list":
            environments = [environment("evm-safe-prod", "production", "prj-safe", ["srv-safe-api"]), environment("evm-other-prod", "production", "prj-other")]
            document["captures"][document["captures"].index(entry)] = write_capture(tmp_path, "environments.json", "rest", "environments_list", live("rest", "environments_list", environments))
    manifest.write_bytes(module.canonical_bytes(document))
    inventory, clusters, _, _ = module.normalize(tmp_path, manifest, ATTEMPT)
    productions = [resource for resource in inventory["resources"] if resource["kind"] == "render.environment" and resource["name"] == "production"]
    assert sorted(resource["render_id"] for resource in productions) == ["evm-other-prod", "evm-safe-prod"]
    blueprint_bound = next(resource for resource in productions if resource["render_id"] == "evm-safe-prod")
    assert any(ref.startswith("blueprint:") for ref in blueprint_bound["provenance"].values())
    other = next(resource for resource in productions if resource["render_id"] == "evm-other-prod")
    assert other["project_id"] == "prj-other" and not any(ref.startswith("blueprint:") for ref in other["provenance"].values())
    assert not any(resource["render_id"] is None for resource in productions)
    api = next(resource for resource in inventory["resources"] if resource["kind"] == "render.web_service" and resource["name"] == "root-api")
    assert api["environment_id"] == "evm-safe-prod" and api["project_id"] == "prj-safe"
    assert not any(cluster["seed"] == "production" for cluster in clusters["clusters"])


def test_duplicate_environment_name_within_one_project_still_rejected(tmp_path: Path) -> None:
    captures = two_project_captures(tmp_path)
    environments = [environment("evm-a", "production", "prj-a", ["srv-a"]), environment("evm-a2", "production", "prj-a", ["srv-b"])]
    captures[1] = write_capture(tmp_path, "environments.json", "rest", "environments_list", live("rest", "environments_list", environments))
    with pytest.raises(module.NormalizeError, match="ambiguous_membership_identity"):
        module.normalize(tmp_path, live_manifest(tmp_path, captures), ATTEMPT)


BLUEPRINT_TWO_PROJECTS = """version: "1"
projects:
  - name: alpha
    environments:
      - name: production
        services:
          - type: web
            name: alpha-api
            runtime: python
            repo: https://github.com/example/alpha
            region: virginia
            plan: starter
            buildCommand: pip install -r requirements.txt
            startCommand: gunicorn app:app
  - name: beta
    environments:
      - name: production
        services:
          - type: web
            name: beta-api
            runtime: python
            repo: https://github.com/example/beta
            region: virginia
            plan: starter
            buildCommand: pip install -r requirements.txt
            startCommand: gunicorn app:app
"""


def test_blueprint_only_same_named_environments_in_two_projects_cluster_apart(tmp_path: Path) -> None:
    manifest = blueprint_only_manifest(tmp_path, BLUEPRINT_TWO_PROJECTS)
    inventory, clusters, _, _ = module.normalize(tmp_path, manifest, ATTEMPT)
    by_name = {resource["name"]: resource["id"] for resource in inventory["resources"] if resource["kind"] == "render.web_service"}
    cluster_of = {member: cluster["id"] for cluster in clusters["clusters"] for member in cluster["member_ids"]}
    assert cluster_of[by_name["alpha-api"]] != cluster_of[by_name["beta-api"]]
    seeds = {cluster["seed"] for cluster in clusters["clusters"]}
    assert "alpha/production" in seeds and "beta/production" in seeds
    assert "production" not in seeds


def test_blueprint_only_duplicate_environment_name_within_one_project_rejected(tmp_path: Path) -> None:
    blueprint = """version: "1"
projects:
  - name: alpha
    environments:
      - name: production
        services:
          - type: web
            name: alpha-api
            runtime: python
            repo: https://github.com/example/alpha
            region: virginia
            plan: starter
            buildCommand: pip install -r requirements.txt
            startCommand: gunicorn app:app
      - name: production
        services:
          - type: web
            name: alpha-worker-api
            runtime: python
            repo: https://github.com/example/alpha
            region: virginia
            plan: starter
            buildCommand: pip install -r requirements.txt
            startCommand: gunicorn app:app
"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "render.yaml"
    source.write_text(blueprint)
    blueprint_parser = load_script("parse-render-blueprint.py", "blueprint_for_duplicate_environment")
    with pytest.raises(blueprint_parser.BlueprintError, match="duplicate_normalized_identity"):
        blueprint_parser.parse_blueprint(source, workspace, tmp_path)


def normalizer_argv(root: Path, manifest: Path, *, ai_flags: bool = True) -> list[str]:
    argv = [
        "normalize-render-capture.py", "--migration-dir", str(root), "--attempt-id", ATTEMPT, "--manifest", str(manifest),
        "--output-inventory", str(root / "render-resource-inventory.json"), "--output-clusters", str(root / "render-resource-clusters.json"),
    ]
    if ai_flags:
        argv += ["--output-ai-profile", str(root / "ai-workload-profile.json"), "--output-ai-discovery", str(root / "render-ai-discovery.json")]
    return argv


OUTPUT_NAMES = ("render-resource-inventory.json", "render-resource-clusters.json", "ai-workload-profile.json", "render-ai-discovery.json")


def replace_application_with_non_ai_scan(root: Path, manifest: Path) -> None:
    scanner = load_script("scan-render-application.py", "scanner_non_ai")
    source = root / "plain-app"
    source.mkdir()
    (source / "main.py").write_text("print('x')\n")
    application = scanner.scan(source)
    assert application["ai_profile"] is None and application["ai_discovery"] is None
    document = json.loads(manifest.read_text())
    document["captures"] = [entry for entry in document["captures"] if entry["transport"] != "application"]
    document["captures"].append(write_capture(root, "application.json", "application", "application", application))
    manifest.write_bytes(module.canonical_bytes(document))


def test_non_ai_rerun_removes_stale_ai_artifacts_atomically(tmp_path: Path) -> None:
    import subprocess
    import sys

    manifest = build_estate(tmp_path)
    first = subprocess.run([sys.executable, str(SCRIPT), *normalizer_argv(tmp_path, manifest)[1:]], capture_output=True, text=True, cwd=SCRIPT_DIR)
    assert first.returncode == 0 and first.stdout.startswith("NORMALIZE_OK"), first.stderr
    assert all((tmp_path / name).exists() for name in OUTPUT_NAMES)
    first_inventory = (tmp_path / OUTPUT_NAMES[0]).read_bytes()

    replace_application_with_non_ai_scan(tmp_path, manifest)
    second = subprocess.run([sys.executable, str(SCRIPT), *normalizer_argv(tmp_path, manifest)[1:]], capture_output=True, text=True, cwd=SCRIPT_DIR)
    assert second.returncode == 0 and second.stdout.startswith("NORMALIZE_OK"), second.stderr
    assert not (tmp_path / "ai-workload-profile.json").exists()
    assert not (tmp_path / "render-ai-discovery.json").exists()
    # The inventory carries no application-derived fields, so a non-AI rerun rewrites it byte-identically.
    assert (tmp_path / OUTPUT_NAMES[0]).read_bytes() == first_inventory
    assert (tmp_path / OUTPUT_NAMES[1]).exists()
    assert not [path for path in tmp_path.iterdir() if ".generation." in path.name or ".rollback." in path.name]

    missing_flag = subprocess.run([sys.executable, str(SCRIPT), *normalizer_argv(tmp_path, manifest, ai_flags=False)[1:]], capture_output=True, text=True, cwd=SCRIPT_DIR)
    assert missing_flag.returncode == 2 and "--output-ai-profile" in missing_flag.stderr
    one_flag = subprocess.run([sys.executable, str(SCRIPT), *normalizer_argv(tmp_path, manifest, ai_flags=False)[1:], "--output-ai-profile", str(tmp_path / "ai-workload-profile.json")], capture_output=True, text=True, cwd=SCRIPT_DIR)
    assert one_flag.returncode == 2 and "--output-ai-discovery" in one_flag.stderr


def test_failed_rerun_rolls_back_ai_removal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = build_estate(tmp_path)
    monkeypatch.setattr(module.sys, "argv", normalizer_argv(tmp_path, manifest))
    assert module.main() == 0
    before = {name: (tmp_path / name).read_bytes() for name in OUTPUT_NAMES}
    assert before["ai-workload-profile.json"]

    replace_application_with_non_ai_scan(tmp_path, manifest)
    real_replace = module.os.replace
    replacements = 0

    def fail_second(source: object, destination: object) -> None:
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("injected commit failure")
        real_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_second)
    assert module.main() == 1
    assert "NORMALIZE_FAIL | code=injected commit failure".split(" | ")[0] in capsys.readouterr().err
    assert {name: (tmp_path / name).read_bytes() for name in OUTPUT_NAMES} == before


def test_live_manifest_with_local_producers_carries_null_ownership_digest(tmp_path: Path) -> None:
    # discover.md Step 2: Blueprint, application, and billing entries carry null even inside a live manifest.
    captures = [write_capture(tmp_path, "projects.json", "rest", "projects_list", live("rest", "projects_list", [{"id": "prj-safe", "name": "project", "ownerId": "tea-safe"}]))]
    billing_parser = load_script("parse-render-billing.py", "billing_for_mixed_handoff")
    captures.append(write_capture(tmp_path, "billing.json", "billing", "billing", billing_parser.parse((SCRIPT_DIR.parent / "fixtures/render-billing/user-stated.json").read_bytes(), ".json")))
    scanner = load_script("scan-render-application.py", "scanner_for_mixed_handoff")
    captures.append(write_capture(tmp_path, "application.json", "application", "application", scanner.scan(SCRIPT_DIR.parent / "fixtures/render-application")))
    assert [capture["ownership_index_digest"] for capture in captures[1:]] == [None, None]
    manifest = {"schema_version": "1.0", "status": "active", "identity_scope": "live", "attempt_id": ATTEMPT, "workspace_id": "tea-safe", "local_identity": None, "consent_digest": DIGEST, "ownership_index_digest": INDEX_DIGEST, "captures": captures}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(module.canonical_bytes(manifest))
    inventory, _, _, _ = module.normalize(tmp_path, manifest_path, ATTEMPT)
    assert any(resource["kind"] == "render.project" for resource in inventory["resources"])


def test_live_manifest_rejects_copied_digest_on_local_producer(tmp_path: Path) -> None:
    # discover.md Step 2: local producer entries carry null in a live manifest.
    # A copied active digest is rejected by the manifest JSON schema (allOf if/then from 1ccaf359)
    # before the per-entry capture_evidence_mismatch check runs, so the code asserted here is manifest_invalid.
    captures = [write_capture(tmp_path, "projects.json", "rest", "projects_list", live("rest", "projects_list", [{"id": "prj-safe", "name": "project", "ownerId": "tea-safe"}]))]
    billing_parser = load_script("parse-render-billing.py", "billing_for_copied_digest")
    captures.append(write_capture(tmp_path, "billing.json", "billing", "billing", billing_parser.parse((SCRIPT_DIR.parent / "fixtures/render-billing/user-stated.json").read_bytes(), ".json")))
    scanner = load_script("scan-render-application.py", "scanner_for_copied_digest")
    captures.append(write_capture(tmp_path, "application.json", "application", "application", scanner.scan(SCRIPT_DIR.parent / "fixtures/render-application")))
    manifest_path = tmp_path / "manifest.json"

    def normalize_with_local_digest(local_digest: str | None) -> Any:
        for capture in captures[1:]:
            capture["ownership_index_digest"] = local_digest
        manifest = {"schema_version": "1.0", "status": "active", "identity_scope": "live", "attempt_id": ATTEMPT, "workspace_id": "tea-safe", "local_identity": None, "consent_digest": DIGEST, "ownership_index_digest": INDEX_DIGEST, "captures": captures}
        manifest_path.write_bytes(module.canonical_bytes(manifest))
        return module.normalize(tmp_path, manifest_path, ATTEMPT)

    with pytest.raises(module.NormalizeError) as rejected:
        normalize_with_local_digest(INDEX_DIGEST)
    assert rejected.value.code == "manifest_invalid"

    inventory, _, _, _ = normalize_with_local_digest(None)
    assert any(resource["kind"] == "render.project" for resource in inventory["resources"])
