"""Compare workflow checks with local shell behavior and job dependencies."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


CHECKER = (
    Path(__file__).resolve().parents[1]
    / "skills/tf-best-practices/scripts/validate-migration-artifacts.py"
)
SPEC = importlib.util.spec_from_file_location("workflow_execution_validator", CHECKER)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)

DEPLOY = (
    "aws elasticbeanstalk update-environment "
    "--environment-name example --version-label abc"
)


@pytest.fixture
def migration(tmp_path):
    (tmp_path / "terraform").mkdir()
    (tmp_path / "terraform/main.tf").write_text(
        'resource "aws_elastic_beanstalk_environment" "app" {\n name = "example"\n}\n'
    )
    (tmp_path / ".github/workflows").mkdir(parents=True)
    return tmp_path


def check_workflow(root, workflow, expected, rule=None):
    (root / ".github/workflows/deploy-eb.yml").write_text(workflow)
    report = validator.validate(root, require_eb_workflow=True)
    assert report["artifact_status"] == expected, report
    if rule:
        assert rule in {item["rule"] for item in report["findings"]}, report
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(root), "--require-eb-workflow", "--json", "-"],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == (0 if expected == "ARTIFACTS_OK" else 1), result.stderr
    assert json.loads(result.stdout)["artifact_status"] == expected


@pytest.mark.parametrize(
    ("prefix", "executes"),
    [
        ('echo ";" ', False),
        ("echo ';' ", False),
        (r"echo \; ", False),
        ('echo ""\\; ', False),
        ('echo ";" ";" ', False),
        ("echo ready; ", True),
        ("echo ready ;", True),
        ('echo ";"; ', True),
    ],
)
def test_semicolon_arguments_match_real_shell_behavior(migration, prefix, executes):
    body = prefix + DEPLOY
    calls = migration / "aws-calls"
    # Only this test-owned function runs; there is no AWS executable or API call.
    shell = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-c",
         'aws() { printf "called\\n" >> "$CALL_LOG"; }\n' + body],
        env={
            "PATH": "/usr/bin:/bin",
            "BASH_ENV": "/dev/null",
            "CALL_LOG": os.fspath(calls),
        },
        text=True, capture_output=True, check=False,
    )
    assert shell.returncode == 0, shell.stderr
    assert calls.exists() is executes
    workflow = (
        "jobs:\n  deploy:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: |\n          " + body + "\n"
    )
    check_workflow(
        migration, workflow,
        "ARTIFACTS_OK" if executes else "ARTIFACTS_FAIL",
        None if executes else "eb_deploy_missing",
    )


@pytest.mark.parametrize(
    "dependencies",
    [
        "    needs: build\n",
        "    needs: [build]\n",
        "    needs:\n      - build\n",
        "    needs: missing\n",
        "    needs: intermediate\n",
    ],
)
@pytest.mark.parametrize(
    "deploy_step",
    [
        "      - run: " + DEPLOY + "\n",
        "      - uses: einaregilsson/beanstalk-deploy@v22\n",
    ],
)
def test_dependent_deployment_requires_review(migration, dependencies, deploy_step):
    workflow = (
        "jobs:\n"
        "  build:\n    if: false\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo skipped\n"
        "  intermediate:\n    needs: build\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo waiting\n"
        "  deploy:\n" + dependencies
        + "    runs-on: ubuntu-latest\n    steps:\n" + deploy_step
    )
    check_workflow(
        migration, workflow, "ARTIFACTS_FAIL", "workflow_dependency_unverified",
    )


def test_unrelated_dependencies_do_not_block_direct_deployment(migration):
    workflow = (
        "jobs:\n"
        "  build:\n    if: false\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo skipped\n"
        "  unrelated:\n    needs: build\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo waiting\n"
        "  deploy:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: " + DEPLOY + "\n"
    )
    check_workflow(migration, workflow, "ARTIFACTS_OK")


@pytest.mark.parametrize(
    "key",
    ['"needs"', "'needs'", "needs ", '"ne\\u0065ds"', '"if"', "'if'", "if "],
)
@pytest.mark.parametrize(
    "deploy_step",
    [
        "      - run: " + DEPLOY + "\n",
        "      - uses: einaregilsson/beanstalk-deploy@v22\n",
    ],
)
def test_noncanonical_control_keys_cannot_hide_skipped_jobs(migration, key, deploy_step):
    value = "false" if "if" in key else "build"
    workflow = (
        "jobs:\n"
        "  build:\n    if: false\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo skipped\n"
        f"  deploy:\n    {key}: {value}\n"
        "    runs-on: ubuntu-latest\n    steps:\n" + deploy_step
    )
    check_workflow(migration, workflow, "ARTIFACTS_FAIL", "workflow_unverified")


@pytest.mark.parametrize(
    "prefix",
    [
        '"env":\n  PATH: /unavailable\n',
        "env :\n  PATH: /unavailable\n",
        '"defaults":\n  run:\n    shell: python\n',
        "defaults :\n  run:\n    shell: python\n",
    ],
)
def test_noncanonical_root_keys_cannot_hide_execution_overrides(migration, prefix):
    workflow = prefix + (
        "jobs:\n  deploy:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: " + DEPLOY + "\n"
    )
    check_workflow(migration, workflow, "ARTIFACTS_FAIL", "workflow_unverified")
