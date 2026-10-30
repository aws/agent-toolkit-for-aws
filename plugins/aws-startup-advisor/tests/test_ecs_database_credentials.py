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


@pytest.mark.parametrize("assignment", ["=", ":"])
@pytest.mark.parametrize(
    "environment,name,value",
    [
        (r'"environm\u0065nt"', "name", "value"),
        ("environment", r'"n\u0061me"', "value"),
        ("environment", "name", r'"v\u0061lue"'),
        (r'"environm\U00000065nt"', "name", "value"),
        ("environment", r'"n\U00000061me"', "value"),
        ("environment", "name", r'"v\U00000061lue"'),
    ],
)
def test_escaped_quoted_keys_are_decoded_before_matching(tmp_path, environment, name, value, assignment):
    expression = (
        f"jsonencode([{{{environment} {assignment} [{{{name} {assignment} \"DATABASE_URL\", "
        f'{value} {assignment} "postgres://app:PLACEHOLDER@db/orders"}}]}}])'
    )
    report = check(tmp_path, expression)
    assert [item["rule"] for item in report["findings"]] == ["ecs_database_password_placeholder"]


def test_escaped_key_text_inside_strings_comments_and_nested_objects_is_ignored(tmp_path):
    fake_entry = r'{"n\u0061me"="DATABASE_URL","v\u0061lue"="postgres://app:PLACEHOLDER@db/orders"}'
    fake_environment = r'"environm\u0065nt"=[' + fake_entry + "]"
    expression = (
        "jsonencode([{"
        + 'environment = [{name = "OTHER", value = "safe"}]\n'
        + "command = [" + json.dumps(fake_environment) + "]\n"
        + "# " + fake_environment + "\n"
        + "dockerLabels = {" + fake_environment + "}\n"
        + "}])"
    )
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_OK"


@pytest.mark.parametrize(
    "heredoc,expected",
    [
        ("<<URL\npostgres://app:PLACEHOLDER@db/orders\nURL", "postgres://app:PLACEHOLDER@db/orders\n"),
        ("<<-URL\n    postgres://app:PLACEHOLDER@db/orders\n  URL", "postgres://app:PLACEHOLDER@db/orders\n"),
        ("<<-URL\n\tpostgres://app:PLACEHOLDER@db/orders\n\tURL", "postgres://app:PLACEHOLDER@db/orders\n"),
        (
            "<<-URL\n    postgres://app:PLACEHOLDER@db/orders\n  \n      more\n  URL",
            "postgres://app:PLACEHOLDER@db/orders\n  \n  more\n",
        ),
        (
            "<<-URL\n    postgres://app:PLACEHOLDER@db/$${schema}\n    URL",
            "postgres://app:PLACEHOLDER@db/${schema}\n",
        ),
    ],
)
def test_literal_heredoc_values_preserve_terraform_string_semantics(tmp_path, heredoc, expected):
    expression = 'jsonencode([{environment=[{name="DATABASE_URL",value=' + heredoc + "\n}]}])"
    policy, _ = validator._dependencies()
    assert validator._inline_database_urls(expression, policy) == [expected]
    report = check(tmp_path, expression)
    assert [item["rule"] for item in report["findings"]] == ["ecs_database_password_placeholder"]
    assert expected not in json.dumps(report)


def test_heredoc_name_keeps_terminal_newline_and_does_not_match_database_url(tmp_path):
    expression = '''jsonencode([{environment=[{
      name=<<NAME
DATABASE_URL
NAME
      value="postgres://app:PLACEHOLDER@db/orders"
    }]}])'''
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_OK"


@pytest.mark.parametrize(
    "value",
    [
        "${var.database_url}",
        '${var.use_placeholder ? "postgres://app:PLACEHOLDER@db/orders" : var.database_url}',
        '%{if var.use_placeholder}postgres://app:PLACEHOLDER@db/orders%{endif}',
    ],
)
def test_dynamic_heredoc_values_are_not_evaluated(tmp_path, value):
    expression = 'jsonencode([{environment=[{name="DATABASE_URL",value=<<URL\n' + value + "\nURL\n}]}])"
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_OK"


def test_heredoc_literal_password_is_checked_with_interpolated_user_and_host(tmp_path):
    expression = '''jsonencode([{environment=[{name="DATABASE_URL",value=<<URL
postgres://${var.user}:PLACEHOLDER@${aws_db_instance.db.endpoint}/orders
URL
}]}])'''
    report = check(tmp_path, expression)
    assert [item["rule"] for item in report["findings"]] == ["ecs_database_password_placeholder"]


@pytest.mark.parametrize(
    "representation",
    ["quoted-field", "heredoc-field", "jsonencode-json", "quoted-json", "heredoc-json"],
)
@pytest.mark.parametrize(
    "value,rejected",
    [
        ("postgres://app:PLACEHOLDER@db/orders", True),
        ("postgres://app:real-test-password@db/orders", False),
        (
            "%{if false}postgres://app:PLACEHOLDER@db/orders"
            "%{else}postgres://app:real-test-password@db/orders%{endif}",
            False,
        ),
        (
            "%%{if false}postgres://app:PLACEHOLDER@db/orders"
            "%%{else}postgres://app:real-test-password@db/orders%%{endif}",
            True,
        ),
        ("postgres://app:PLACEHOLDER@${local.host}/orders", True),
        ("postgres://app:PLACEHOLDER@db/$${schema}", True),
    ],
)
def test_template_boundaries_match_across_literal_representations(tmp_path, representation, value, rejected):
    containers = [{"environment": [{"name": "DATABASE_URL", "value": value}]}]
    document = json.dumps(containers)
    expressions = {
        "quoted-field": 'jsonencode([{environment=[{name="DATABASE_URL",value=' + json.dumps(value) + "}]}])",
        "heredoc-field": 'jsonencode([{environment=[{name="DATABASE_URL",value=<<URL\n' + value + "\nURL\n}]}])",
        "jsonencode-json": "jsonencode(" + document + ")",
        "quoted-json": json.dumps(document),
        "heredoc-json": "<<JSON\n" + document + "\nJSON",
    }
    report = check(tmp_path, expressions[representation])
    expected = "ARTIFACTS_FAIL" if rejected else "ARTIFACTS_OK"
    assert report["artifact_status"] == expected, report
    if rejected:
        assert [item["rule"] for item in report["findings"]] == ["ecs_database_password_placeholder"]


@pytest.mark.parametrize("representation", ["jsonencode-json", "quoted-json", "heredoc-json"])
def test_dynamic_json_value_does_not_hide_a_separate_literal_placeholder(tmp_path, representation):
    document = json.dumps([{"environment": [
        {
            "name": "DATABASE_URL",
            "value": "%{if false}postgres://app:PLACEHOLDER@unused/orders%{else}safe%{endif}",
        },
        {"name": "DATABASE_URL", "value": "postgres://app:PLACEHOLDER@db/orders"},
    ]}])
    expressions = {
        "jsonencode-json": "jsonencode(" + document + ")",
        "quoted-json": json.dumps(document),
        "heredoc-json": "<<JSON\n" + document + "\nJSON",
    }
    report = check(tmp_path, expressions[representation])
    assert [item["rule"] for item in report["findings"]] == ["ecs_database_password_placeholder"]


@pytest.mark.parametrize(
    "representation",
    ["quoted-field", "heredoc-field", "jsonencode-json", "quoted-json", "heredoc-json"],
)
@pytest.mark.parametrize("escaped", [False, True])
def test_interpolation_source_is_ignored_but_escaped_source_is_literal(tmp_path, representation, escaped):
    interpolation = (
        '${false ? "postgres://app:PLACEHOLDER@db/orders"'
        ' : "postgres://app:real-test-password@db/orders"}'
    )
    value = "$" + interpolation if escaped else interpolation
    document = json.dumps([{"environment": [{"name": "DATABASE_URL", "value": "VALUE"}]}])
    if escaped:
        quoted = json.dumps(value)
        json_document = document.replace('"VALUE"', quoted)
        outer_json = json.dumps(json_document)
    else:
        # Quotes in an active HCL interpolation belong to its expression.
        quoted = '"' + value + '"'
        json_document = document.replace("VALUE", value)
        outer_json = json.dumps(document).replace("VALUE", value)
    expressions = {
        "quoted-field": 'jsonencode([{environment=[{name="DATABASE_URL",value=' + quoted + "}]}])",
        "heredoc-field": 'jsonencode([{environment=[{name="DATABASE_URL",value=<<URL\n' + value + "\nURL\n}]}])",
        "jsonencode-json": "jsonencode(" + json_document + ")",
        "quoted-json": outer_json,
        "heredoc-json": "<<JSON\n" + json_document + "\nJSON",
    }
    report = check(tmp_path, expressions[representation])
    expected = "ARTIFACTS_FAIL" if escaped else "ARTIFACTS_OK"
    assert report["artifact_status"] == expected, report


@pytest.mark.parametrize("escape", [r"\u0025", r"\U00000025"])
@pytest.mark.parametrize("representation", ["quoted-field", "quoted-json"])
def test_unicode_introduced_marker_is_literal_data(tmp_path, escape, representation):
    value = escape + "{if false}postgres://app:PLACEHOLDER@db/orders"
    if representation == "quoted-field":
        expression = 'jsonencode([{environment=[{name="DATABASE_URL",value="' + value + '"}]}])'
    else:
        document = json.dumps([{"environment": [{"name": "DATABASE_URL", "value": "MARKER{if false}postgres://app:PLACEHOLDER@db/orders"}]}])
        expression = json.dumps(document).replace("MARKER", escape)
    report = check(tmp_path, expression)
    assert [item["rule"] for item in report["findings"]] == ["ecs_database_password_placeholder"]


@pytest.mark.parametrize(
    "expression",
    [
        '''<<JSON
[${jsonencode({name="api",environment=[{name="DATABASE_URL",value="postgres://app:real-test-password@db/orders"}]})}]
JSON''',
        '''"[${jsonencode({name="api",environment=[]})}]"''',
        '''<<JSON
[%{ for name in ["api"] }{"name":"${name}","environment":[]}%{ endfor }]
JSON''',
        '''<<JSON
[%{ for index, name in ["api", "worker"] ~}
${index > 0 ? "," : ""}{"name":"${name}","environment":[]}
%{ endfor ~}]
JSON''',
        '''<<JSON
[{"name":"api","environment":${jsonencode([{name="DATABASE_URL",value="postgres://app:real-test-password@db/orders"}])}}]
JSON''',
        '''<<JSON
${jsonencode([{name="api",environment=[]}])}
JSON''',
    ],
)
def test_dynamic_json_structure_remains_outside_literal_check(tmp_path, expression):
    assert check(tmp_path, expression)["artifact_status"] == "ARTIFACTS_OK"


@pytest.mark.parametrize(
    "document",
    [
        '[{"environment": []} __ecs_template_0__]',
        '[{"environment": [{"name":"DATABASE_URL","value":"postgres://app:${local.password}@db/orders"}]} BROKEN]',
    ],
)
def test_malformed_literal_json_is_not_mistaken_for_dynamic_structure(tmp_path, document):
    report = check(tmp_path, "<<JSON\n" + document + "\nJSON")
    assert report["artifact_status"] == "ARTIFACTS_FAIL"
    assert report["findings"][0]["rule"] == "artifact_shape_unverified"


@pytest.mark.parametrize("assignment", ["=", ":"])
@pytest.mark.parametrize(
    "body,rejected",
    [
        ('environment = [{name = "OTHER", name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders"}]', True),
        ('environment = [{name = "DATABASE_URL", name = "OTHER", value = "postgres://app:PLACEHOLDER@db/orders"}]', False),
        ('environment = [{name = "DATABASE_URL", value = "safe", value = "postgres://app:PLACEHOLDER@db/orders"}]', True),
        ('environment = [{name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders", value = "safe"}]', False),
        ('environment = [], environment = [{name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders"}]', True),
        ('environment = [{name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders"}], environment = []', False),
        ('environment = [{name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders", value = local.safe_url}]', False),
        ('environment = [{name = "DATABASE_URL", name = local.field_name, value = "postgres://app:PLACEHOLDER@db/orders"}]', False),
        ('environment = [{name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders"}], environment = local.environment', False),
        ('environment = [{name = "DATABASE_URL", value = local.safe_url, value = "postgres://app:PLACEHOLDER@db/orders"}]', True),
        (r'environment = [{name = "DATABASE_URL", value = "safe", "v\u0061lue" = "postgres://app:PLACEHOLDER@db/orders"}]', True),
        (r'environment = [{name = "DATABASE_URL", value = "postgres://app:PLACEHOLDER@db/orders", "v\u0061lue" = "safe"}]', False),
    ],
)
def test_last_direct_object_key_matches_terraform_semantics(tmp_path, assignment, body, rejected):
    expression = "jsonencode([{" + body.replace(" = ", f" {assignment} ") + "}])"
    if assignment == ":":
        for key in ("environment", "name", "value"):
            expression = expression.replace(f"{key} :", f'"{key}" :')
    report = check(tmp_path, expression)
    expected = "ARTIFACTS_FAIL" if rejected else "ARTIFACTS_OK"
    assert report["artifact_status"] == expected, report
    if rejected:
        assert [item["rule"] for item in report["findings"]] == ["ecs_database_password_placeholder"]


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
