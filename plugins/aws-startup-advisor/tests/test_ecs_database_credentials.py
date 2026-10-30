"""Regression coverage for placeholder passwords in generated ECS definitions."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills/tf-best-practices/scripts/validate-migration-artifacts.py"
)
SPEC = importlib.util.spec_from_file_location("ecs_credentials_validator", SCRIPT)
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def check(tmp_path, expression, extra=""):
    path = tmp_path / "terraform"
    path.mkdir(exist_ok=True)
    (path / "main.tf").write_text(
        'resource "aws_ecs_task_definition" "api" {\n'
        f"{extra}\ncontainer_definitions = {expression}\n}}\n"
    )
    return validator.validate(tmp_path)


@pytest.mark.parametrize("password", ["PLACEHOLDER", "REDACTED", "change_me", "REPLACE_ME"])
def test_inline_hcl_placeholder_password_is_rejected_without_leaking_url(tmp_path, password):
    url = f"postgresql://${{var.user}}:{password}@${{aws_db_instance.db.endpoint}}/orders"
    expression = (
        'jsonencode([{ environment = ['
        f'{{ name = "DATABASE_URL", value = {json.dumps(url)} }}'
        "] }])"
    )
    report = check(tmp_path, expression)
    assert report["artifact_status"] == "ARTIFACTS_FAIL"
    assert report["findings"][0]["rule"] == "ecs_database_password_placeholder"
    assert url not in json.dumps(report)


def test_literal_json_container_definitions_are_checked(tmp_path):
    containers = [{
        "environment": [{"name": "DATABASE_URL", "value": "postgres://app:PLACEHOLDER@db/orders"}],
    }]
    expression = json.dumps(json.dumps(containers))
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_FAIL"


def test_jsonencode_json_object_is_checked(tmp_path):
    containers = [{
        "environment": [{"name": "DATABASE_URL", "value": "postgres://app:REDACTED@db/orders"}],
    }]
    expression = "jsonencode(" + json.dumps(containers) + ")"
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_FAIL"


@pytest.mark.parametrize("opener", ["jsonencode (", "jsonencode /* renderer note */ ("])
def test_function_spacing_and_comments_do_not_hide_placeholder(tmp_path, opener):
    expression = (
        opener + '[{environment = [{name="DATABASE_URL", '
        'value="postgres://app:PLACEHOLDER@db/orders"}]}])'
    )
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_FAIL"


def test_secret_reference_and_non_password_placeholder_do_not_false_positive(tmp_path):
    expression = '''jsonencode([{
      secrets = [{ name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.db.arn }]
      environment = [{ name = "DATABASE_URL", value = "postgres://app:${var.password}@PLACEHOLDER/orders" }]
      dockerLabels = { name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders" }
      # environment = [{ name = "DATABASE_URL", value = "postgres://app:REDACTED@db/orders" }]
    }])'''
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_OK"


def test_uninstantiated_task_does_not_block_other_routes(tmp_path):
    expression = 'jsonencode([{ environment = [{name="DATABASE_URL", value="postgres://a:PLACEHOLDER@db/x"}] }])'
    assert check(tmp_path, expression, "count = 0")["artifact_status"] == "ARTIFACTS_OK"


def test_malformed_environment_is_reported_not_an_uncaught_exception(tmp_path):
    expression = 'jsonencode([{"environment": null}])'
    report = check(tmp_path, expression)
    assert report["artifact_status"] == "ARTIFACTS_FAIL"
    assert report["findings"][0]["rule"] == "artifact_shape_unverified"
