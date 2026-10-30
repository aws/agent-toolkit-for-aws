"""Regression tests for config.json-first resource resolution in agents_pay_admin.py.

Covers resolve_region() and resolve_manager_arn(): both must prefer an explicit
--flag, then the environment, then whatever init-config / create-instrument
already persisted into config.json's resources section, before falling back
further (boto3's own resolution for region; deployed-state.json for the
manager ARN). Neither should silently ignore a value the tool itself wrote to
config.json, and region must never fall back to a hardcoded default that
overrides a value the operator (or boto3) actually has.
"""
import sys
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents_pay_admin as m

d = tempfile.mkdtemp()


def _write_config(name: str, resources: dict) -> Path:
    p = Path(d) / name
    p.write_text(json.dumps({"resources": resources, "policy": {}}))
    return p


# --- resolve_region() ---------------------------------------------------

cfg = _write_config("region-config.json", {"region": "us-east-1"})

_saved_region = os.environ.pop("AWS_REGION", None)
_saved_default_region = os.environ.pop("AWS_DEFAULT_REGION", None)
try:
    assert m.resolve_region("eu-west-1", cfg) == "eu-west-1", "flag should win"

    os.environ["AWS_REGION"] = "ap-southeast-2"
    assert m.resolve_region(None, cfg) == "ap-southeast-2", "env should win over config"
    del os.environ["AWS_REGION"]

    assert m.resolve_region(None, cfg) == "us-east-1", (
        "config region should be used, not hardcoded us-west-2"
    )

    empty_cfg = _write_config("region-empty.json", {})
    assert m.resolve_region(None, empty_cfg) is None, (
        "should fall through to None, not us-west-2"
    )
finally:
    if _saved_region is not None:
        os.environ["AWS_REGION"] = _saved_region
    if _saved_default_region is not None:
        os.environ["AWS_DEFAULT_REGION"] = _saved_default_region

print("resolve_region: PASSED")

# --- resolve_manager_arn() ------------------------------------------------

arn_cfg = _write_config(
    "arn-config.json",
    {"payment_manager_arn": "arn:aws:bedrock-agentcore:us-east-1:111111111111:payment-manager/config-saved"},
)

_saved_env_arn = os.environ.pop("PAYMENT_MANAGER_ARN", None)
try:
    # 1. explicit flag wins over everything
    assert m.resolve_manager_arn("arn:flag", arn_cfg) == "arn:flag", "flag should win"

    # 2. env wins over config
    os.environ["PAYMENT_MANAGER_ARN"] = "arn:env"
    assert m.resolve_manager_arn(None, arn_cfg) == "arn:env", "env should win over config"
    del os.environ["PAYMENT_MANAGER_ARN"]

    # 3. config.json wins when no flag/env — this is the regression case: a
    # manager ARN persisted by a previous create-instrument/init-config run
    # must be found even when re-running from a directory with no
    # deployed-state.json in reach.
    assert m.resolve_manager_arn(None, arn_cfg) == (
        "arn:aws:bedrock-agentcore:us-east-1:111111111111:payment-manager/config-saved"
    ), "config.json's payment_manager_arn must not be ignored"

    # 4. nothing set anywhere -> None (discover_deployed() finds nothing in
    # this tempdir, since there's no deployed-state.json here)
    empty_arn_cfg = _write_config("arn-empty.json", {})
    cwd = os.getcwd()
    os.chdir(d)
    try:
        assert m.resolve_manager_arn(None, empty_arn_cfg) is None, (
            "should fall through to None when nothing is configured or discoverable"
        )
    finally:
        os.chdir(cwd)
finally:
    if _saved_env_arn is not None:
        os.environ["PAYMENT_MANAGER_ARN"] = _saved_env_arn

print("resolve_manager_arn: PASSED")

# --- CLI v1 project status ------------------------------------------------

v1_root = Path(d) / "v1-project"
(v1_root / "agentcore").mkdir(parents=True)
(v1_root / "agentcore" / "agentcore.json").write_text('{"name":"PayTest","version":2}')
v1_status = {
    "projectName": "PayTest",
    "target": "default",
    "region": "us-east-1",
    "resources": [
        {
            "resourceType": "payment-manager",
            "name": "Payments",
            "deploymentState": "deployed",
            "arn": "arn:aws:bedrock-agentcore:us-east-1:111111111111:payment-manager/manager-1",
            "children": [
                {
                    "resourceType": "payment-connector",
                    "name": "Coinbase",
                    "deploymentState": "deployed",
                    "id": "connector-1",
                }
            ],
        }
    ],
}
with patch.object(m.subprocess, "run") as run:
    run.return_value.returncode = 0
    run.return_value.stdout = json.dumps(v1_status)
    found = m.discover_deployed(v1_root)
    assert found["manager_arn"] == v1_status["resources"][0]["arn"]
    assert found["connector_id"] == "connector-1"
    run.assert_called_once()
    assert run.call_args.kwargs["cwd"] == v1_root.resolve()

print("discover_deployed v1: PASSED")

# v1 deployed state exists, but has no payments branch. Discovery must still
# read status from the project root.
(v1_root / "agentcore" / ".cli").mkdir()
(v1_root / "agentcore" / ".cli" / "deployed-state.json").write_text('{"version":2}')
with patch.object(m.subprocess, "run") as run:
    run.return_value.returncode = 0
    run.return_value.stdout = json.dumps(v1_status)
    found = m.discover_deployed(v1_root)
    assert found["manager_arn"] == v1_status["resources"][0]["arn"]
    assert found["connector_id"] == "connector-1"
    assert run.call_args.kwargs["cwd"] == v1_root.resolve()

print("discover_deployed v1 with state: PASSED")

# Migrated v0 state can retain an outdated payments branch after the v1 project
# replaces its resources. The v1 status result must take precedence over it.
(v1_root / "agentcore" / ".cli" / "deployed-state.json").write_text(json.dumps({
    "targets": {
        "default": {
            "resources": {
                "payments": {
                    "OldPayments": {
                        "managerArn": "arn:aws:bedrock-agentcore:us-east-1:111111111111:payment-manager/old",
                        "connectors": {"OldConnector": {"connectorId": "old-connector"}},
                    }
                }
            }
        }
    }
}))
with patch.object(m.subprocess, "run") as run:
    run.return_value.returncode = 0
    run.return_value.stdout = json.dumps(v1_status)
    found = m.discover_deployed(v1_root)
    assert found["manager_arn"] == v1_status["resources"][0]["arn"]
    assert found["connector_id"] == "connector-1"
    run.assert_called_once()
    assert run.call_args.kwargs["cwd"] == v1_root.resolve()

with patch.object(m.subprocess, "run") as run:
    run.return_value.returncode = 1
    found = m.discover_deployed(v1_root)
    assert found["manager_arn"] is None
    assert found["connector_id"] is None
    run.assert_called_once()

with patch.dict(os.environ, {"AGENTCORE_PROJECT_DIR": str(v1_root), "AGENTCORE_TARGET": "default"}):
    with patch.object(m.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(v1_status)
        found = m.discover_deployed()
        assert found["manager_arn"] == v1_status["resources"][0]["arn"]
        assert found["connector_id"] == "connector-1"
        run.assert_called_once()

print("discover_deployed migrated v1 with stale state: PASSED")

# Legacy v0 projects still use their payment entries without calling v1 status.
(v1_root / "agentcore" / "agentcore.json").write_text('{"name":"PayTest","version":1}')
with patch.object(m.subprocess, "run") as run:
    found = m.discover_deployed(v1_root)
    assert found["manager_arn"].endswith("payment-manager/old")
    assert found["connector_id"] == "old-connector"
    run.assert_not_called()
(v1_root / "agentcore" / "agentcore.json").write_text('{"name":"PayTest","version":2}')

print("discover_deployed v0 fallback: PASSED")

# Ambiguous project resources must require explicit selection by the operator.
with patch.object(m.subprocess, "run") as run:
    run.return_value.returncode = 0
    run.return_value.stdout = json.dumps({
        **v1_status,
        "resources": [
            *v1_status["resources"],
            {
                "resourceType": "payment-manager",
                "name": "OtherPayments",
                "arn": "arn:aws:bedrock-agentcore:us-east-1:111111111111:payment-manager/manager-2",
                "children": [{"resourceType": "payment-connector", "id": "connector-2"}],
            },
        ],
    })
    found = m.discover_deployed(v1_root)
    assert found["manager_arn"] is None
    assert found["connector_id"] is None

with patch.object(m.subprocess, "run") as run:
    run.return_value.returncode = 0
    run.return_value.stdout = json.dumps({
        **v1_status,
        "resources": [{
            **v1_status["resources"][0],
            "children": [
                *v1_status["resources"][0]["children"],
                {"resourceType": "payment-connector", "id": "connector-2"},
            ],
        }],
    })
    found = m.discover_deployed(v1_root)
    assert found["manager_arn"] == v1_status["resources"][0]["arn"]
    assert found["connector_id"] is None

print("discover_deployed ambiguity: PASSED")

print("ALL RESOURCE RESOLUTION TESTS PASSED")
