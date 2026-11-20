"""Tests for config-first payment resource resolution."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents_pay_admin as module


MANAGER_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:"
    "111111111111:payment-manager/manager-1"
)


def _write_config(root: Path, name: str, resources: dict) -> Path:
    path = root / name
    path.write_text(json.dumps({"resources": resources, "policy": {}}))
    return path


def _write_v1_project(root: Path) -> Path:
    project = root / "v1-project"
    (project / "agentcore").mkdir(parents=True)
    (project / "agentcore" / "agentcore.json").write_text(
        '{"name":"PayTest","version":2}'
    )
    return project


def _v1_status(children=None, resources=None):
    payment_manager = {
        "resourceType": "payment-manager",
        "name": "Payments",
        "deploymentState": "deployed",
        "arn": MANAGER_ARN,
        "children": children or [{
            "resourceType": "payment-connector",
            "name": "Coinbase",
            "deploymentState": "deployed",
            "id": "connector-1",
        }],
    }
    return {
        "projectName": "PayTest",
        "target": "default",
        "region": "us-east-1",
        "resources": resources or [payment_manager],
    }


def test_resolve_region_precedence(tmp_path, monkeypatch):
    config = _write_config(tmp_path, "region.json", {"region": "us-east-1"})
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

    assert module.resolve_region("eu-west-1", config) == "eu-west-1"

    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")
    assert module.resolve_region(None, config) == "ap-southeast-2"

    monkeypatch.delenv("AWS_REGION")
    assert module.resolve_region(None, config) == "us-east-1"
    empty_config = _write_config(tmp_path, "empty-region.json", {})
    assert module.resolve_region(None, empty_config) is None


def test_resolve_manager_arn_precedence(tmp_path, monkeypatch):
    configured_arn = (
        "arn:aws:bedrock-agentcore:us-east-1:"
        "111111111111:payment-manager/config-saved"
    )
    config = _write_config(
        tmp_path,
        "manager.json",
        {"payment_manager_arn": configured_arn},
    )
    monkeypatch.delenv("PAYMENT_MANAGER_ARN", raising=False)

    assert module.resolve_manager_arn("arn:flag", config) == "arn:flag"

    monkeypatch.setenv("PAYMENT_MANAGER_ARN", "arn:env")
    assert module.resolve_manager_arn(None, config) == "arn:env"

    monkeypatch.delenv("PAYMENT_MANAGER_ARN")
    assert module.resolve_manager_arn(None, config) == configured_arn

    empty_config = _write_config(tmp_path, "empty-manager.json", {})
    monkeypatch.chdir(tmp_path)
    assert module.resolve_manager_arn(None, empty_config) is None


def test_config_rejects_manager_from_another_target(tmp_path, monkeypatch, capsys):
    config = _write_config(
        tmp_path, "manager.json",
        {"target": "default", "payment_manager_arn": MANAGER_ARN},
    )
    monkeypatch.setenv("AGENTCORE_TARGET", "prod")

    assert not module.config_matches_target(config)
    assert "belongs to target 'default'" in capsys.readouterr().err


def test_v1_discovery_uses_project_status_instead_of_stale_state(tmp_path):
    project = _write_v1_project(tmp_path)
    state_dir = project / "agentcore" / ".cli"
    state_dir.mkdir()
    (state_dir / "deployed-state.json").write_text(json.dumps({
        "targets": {
            "default": {
                "resources": {
                    "payments": {
                        "OldPayments": {
                            "managerArn": (
                                "arn:aws:bedrock-agentcore:us-east-1:"
                                "111111111111:payment-manager/old"
                            ),
                            "connectors": {
                                "OldConnector": {"connectorId": "old-connector"}
                            },
                        }
                    }
                }
            }
        }
    }))

    with patch.object(module.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(_v1_status())
        found = module.discover_deployed(project)

    assert found["manager_arn"] == MANAGER_ARN
    assert found["connector_id"] == "connector-1"
    assert run.call_args.kwargs["cwd"] == project.resolve()


def test_v1_discovery_honors_project_directory_environment(tmp_path, monkeypatch):
    project = _write_v1_project(tmp_path)
    monkeypatch.setenv("AGENTCORE_PROJECT_DIR", str(project))
    monkeypatch.setenv("AGENTCORE_TARGET", "default")

    with patch.object(module.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(_v1_status())
        found = module.discover_deployed()

    assert found["manager_arn"] == MANAGER_ARN
    assert found["connector_id"] == "connector-1"
    run.assert_called_once()


def test_v1_discovery_returns_empty_when_status_fails(tmp_path):
    project = _write_v1_project(tmp_path)

    with patch.object(module.subprocess, "run") as run:
        run.return_value.returncode = 1
        found = module.discover_deployed(project)

    assert found["manager_arn"] is None
    assert found["connector_id"] is None
    run.assert_called_once()


def test_v0_discovery_uses_legacy_deployed_state(tmp_path):
    project = _write_v1_project(tmp_path)
    (project / "agentcore" / "agentcore.json").write_text(
        '{"name":"PayTest","version":1}'
    )
    state_dir = project / "agentcore" / ".cli"
    state_dir.mkdir()
    (state_dir / "deployed-state.json").write_text(json.dumps({
        "targets": {
            "default": {
                "resources": {
                    "payments": {
                        "OldPayments": {
                            "managerArn": (
                                "arn:aws:bedrock-agentcore:us-east-1:"
                                "111111111111:payment-manager/old"
                            ),
                            "connectors": {
                                "OldConnector": {"connectorId": "old-connector"}
                            },
                        }
                    }
                }
            }
        }
    }))

    with patch.object(module.subprocess, "run") as run:
        found = module.discover_deployed(project)

    assert found["manager_arn"].endswith("payment-manager/old")
    assert found["connector_id"] == "old-connector"
    run.assert_not_called()


@pytest.mark.parametrize(
    ("children", "extra_resources", "expected_manager", "expected_connector"),
    [
        (
            [
                {"resourceType": "payment-connector", "id": "connector-1"},
                {"resourceType": "payment-connector", "id": "connector-2"},
            ],
            [],
            MANAGER_ARN,
            None,
        ),
        (
            None,
            [{
                "resourceType": "payment-manager",
                "name": "OtherPayments",
                "arn": (
                    "arn:aws:bedrock-agentcore:us-east-1:"
                    "111111111111:payment-manager/manager-2"
                ),
                "children": [{
                    "resourceType": "payment-connector",
                    "id": "connector-2",
                }],
            }],
            None,
            None,
        ),
    ],
)
def test_v1_discovery_rejects_ambiguous_resources(
    tmp_path,
    children,
    extra_resources,
    expected_manager,
    expected_connector,
):
    project = _write_v1_project(tmp_path)
    status = _v1_status(children=children)
    status["resources"].extend(extra_resources)

    with patch.object(module.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(status)
        found = module.discover_deployed(project)

    assert found["manager_arn"] == expected_manager
    assert found["connector_id"] == expected_connector
