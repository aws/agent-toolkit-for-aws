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


@pytest.mark.parametrize(
    "representation",
    [
        "quoted-json",
        "heredoc",
        "indented-heredoc",
        "parenthesized-heredoc",
        "jsonencode",
        "parenthesized-jsonencode",
        "nested-jsonencode",
        "nested-argument",
        "commented-groups",
    ],
)
@pytest.mark.parametrize("password", ["PLACEHOLDER", "real-test-credential"])
def test_literal_representations_have_the_same_verdict(tmp_path, representation, password):
    url = f"postgres://app:{password}@db/orders"
    containers = [{"environment": [{"name": "DATABASE_URL", "value": url}]}]
    document = json.dumps(containers)
    hcl = '[{environment = [{name = "DATABASE_URL", value = ' + json.dumps(url) + "}]}]"
    expressions = {
        "quoted-json": json.dumps(document),
        "heredoc": f"<<JSON\n{document}\nJSON",
        "indented-heredoc": f"<<-JSON\n    {document}\n    JSON",
        "parenthesized-heredoc": f"((<<JSON\n{document}\nJSON\n))",
        "jsonencode": f"jsonencode({hcl})",
        "parenthesized-jsonencode": f"(jsonencode({hcl}))",
        "nested-jsonencode": f"((( jsonencode({hcl}) )))",
        "nested-argument": f"jsonencode( (( {hcl} )) )",
        "commented-groups": f"( /* before */ (jsonencode( /* argument */ ({hcl}) )) /* after */ ) ",
    }
    report = check(tmp_path, expressions[representation])
    expected = "ARTIFACTS_FAIL" if password == "PLACEHOLDER" else "ARTIFACTS_OK"
    assert report["artifact_status"] == expected, report
    if password == "PLACEHOLDER":
        assert [item["rule"] for item in report["findings"]] == ["ecs_database_password_placeholder"]
    assert url not in json.dumps(report)


@pytest.mark.parametrize("opener,terminator", [("<<JSON", "JSON"), ("<<-JSON", "    JSON")])
def test_heredoc_secret_reference_and_other_fields_do_not_false_positive(tmp_path, opener, terminator):
    document = json.dumps([{
        "secrets": [{"name": "DATABASE_URL", "valueFrom": "${aws_secretsmanager_secret.db.arn}"}],
        "environment": [{"name": "DATABASE_URL", "value": "postgres://app:${var.password}@PLACEHOLDER/orders"}],
        "dockerLabels": {"name": "DATABASE_URL", "value": "postgres://app:REDACTED@db/orders"},
        "command": ['echo environment = [{name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders"}]'],
    }])
    report = check(tmp_path, f"{opener}\n{document}\n{terminator}")
    assert report["artifact_status"] == "ARTIFACTS_OK", report


@pytest.mark.parametrize("name_groups", [0, 1, 3])
@pytest.mark.parametrize("value_groups", [0, 1, 3])
def test_grouped_literal_fields_are_checked(tmp_path, name_groups, value_groups):
    name = "(" * name_groups + '"DATABASE_URL"' + ")" * name_groups
    value = (
        "(" * value_groups + '"postgres://app:PLACEHOLDER@db/orders"' + ")" * value_groups
    )
    expression = (
        'jsonencode([{environment = [{'
        f'name = {name}, value = /* before */ {value} /* after */'
        '}]}])'
    )
    report = check(tmp_path, expression)
    assert [item["rule"] for item in report["findings"]] == ["ecs_database_password_placeholder"]


@pytest.mark.parametrize("groups", [1, 3])
@pytest.mark.parametrize("password", ["PLACEHOLDER", "real-test-credential"])
def test_grouped_environment_lists_and_objects_are_checked(tmp_path, groups, password):
    entry = '({name = ("DATABASE_URL"), value = ("postgres://app:' + password + '@db/orders")})'
    environment = "(" * groups + f"[{entry}]" + ")" * groups
    expression = f"jsonencode([({{environment = {environment}}})])"
    report = check(tmp_path, expression)
    expected = "ARTIFACTS_FAIL" if password == "PLACEHOLDER" else "ARTIFACTS_OK"
    assert report["artifact_status"] == expected, report
    if password == "PLACEHOLDER":
        assert [item["rule"] for item in report["findings"]] == ["ecs_database_password_placeholder"]


@pytest.mark.parametrize(
    "expression",
    [
        "jsonencode([{environment = (var.environment)}])",
        'jsonencode([{environment = ([{name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders"}] == [] ? local.primary : local.backup)}])',
        'jsonencode([{dockerLabels = {environment = [{name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders"}]}}])',
        'jsonencode([{other-environment = [{name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders"}]}])',
    ],
)
def test_only_direct_literal_environment_lists_are_checked(tmp_path, expression):
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_OK"


@pytest.mark.parametrize(
    "name,value",
    [
        (
            '("DATABASE_URL" == var.field ? "OTHER" : "ELSE")',
            '"postgres://app:PLACEHOLDER@db/orders"',
        ),
        (
            '"DATABASE_URL"',
            '("postgres://app:PLACEHOLDER@db/orders" == var.url ? var.secret_url : var.fallback_url)',
        ),
        ('("DATABASE_URL")', 'format("postgres://app:%s@db/orders", var.password)'),
    ],
)
def test_dynamic_fields_do_not_match_a_literal_prefix(tmp_path, name, value):
    expression = f"jsonencode([{{environment = [{{name = {name}, value = {value}}}]}}])"
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_OK"


@pytest.mark.parametrize(
    "expression",
    [
        "local.container_definitions",
        "((local.container_definitions))",
        "(jsonencode(var.containers))",
        "jsonencode([for container in var.containers : container])",
        '"${local.container_definitions}"',
        "<<JSON\n${jsonencode(var.containers)}\nJSON",
    ],
)
def test_dynamic_container_definitions_remain_outside_literal_check(tmp_path, expression):
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_OK"


@pytest.mark.parametrize(
    "expression",
    [
        '<<JSON\n[{"environment":[{"name":"DATABASE_URL","value":"postgres://app:PLACEHOLDER@db/orders"}]}\nJSON',
        json.dumps('[{"environment":'),
    ],
)
def test_unparseable_literal_json_is_unverified_without_leaking_values(tmp_path, expression):
    report = check(tmp_path, expression)
    assert report["artifact_status"] == "ARTIFACTS_FAIL"
    assert report["findings"][0]["rule"] == "artifact_shape_unverified"
    assert "PLACEHOLDER" not in json.dumps(report)


@pytest.mark.parametrize("opener", ["jsonencode (", "jsonencode /* renderer note */ ("])
def test_function_spacing_and_comments_do_not_hide_placeholder(tmp_path, opener):
    expression = (
        opener + '[{environment = [{name="DATABASE_URL", '
        'value="postgres://app:PLACEHOLDER@db/orders"}]}])'
    )
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_FAIL"


@pytest.mark.parametrize(
    "environment,name,value",
    [
        ('"environment"', "name", "value"),
        ("environment", '"name"', '"value"'),
        ('"environment"', '"name"', '"value"'),
    ],
)
@pytest.mark.parametrize("assignment", ["=", ":"])
def test_quoted_hcl_keys_have_the_same_credential_check(tmp_path, environment, name, value, assignment):
    expression = (
        f"jsonencode([{{{environment} {assignment} [{{{name} {assignment} \"DATABASE_URL\", "
        f'{value} {assignment} "postgres://app:PLACEHOLDER@db/orders"}}]}}])'
    )
    report = check(tmp_path, expression)
    assert report["artifact_status"] == "ARTIFACTS_FAIL"
    assert any(item["rule"] == "ecs_database_password_placeholder" for item in report["findings"])


def test_secret_reference_and_non_password_placeholder_do_not_false_positive(tmp_path):
    expression = '''jsonencode([{
      secrets = [{ name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.db.arn }]
      environment = [{ name = "DATABASE_URL", value = "postgres://app:${var.password}@PLACEHOLDER/orders" }]
      dockerLabels = { name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders" }
      # environment = [{ name = "DATABASE_URL", value = "postgres://app:REDACTED@db/orders" }]
    }])'''
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_OK"


def test_quoted_keys_in_strings_and_comments_are_not_environment_entries(tmp_path):
    expression = '''jsonencode([{
      "environment" = [{"name" = "DATABASE_URL", "value" = "postgres://app:${var.password}@db/orders"}]
      dockerLabels = { "name" = "DATABASE_URL", "value" = "postgres://app:PLACEHOLDER@db/orders" }
      # "environment" = [{"name" = "DATABASE_URL", "value" = "postgres://app:REDACTED@db/orders"}]
      command = ["echo", "\\"environment\\" = [{\\"name\\" = \\"DATABASE_URL\\", \\"value\\" = \\"postgres://app:REDACTED@db/orders\\"}]"]
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
