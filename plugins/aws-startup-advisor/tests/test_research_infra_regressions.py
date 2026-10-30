"""Research regressions for provider arguments and local DB secret wiring."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest


PLUGIN = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN / "skills/tf-best-practices/scripts/validate-migration-artifacts.py"
SPEC = importlib.util.spec_from_file_location("research_infra_validator", SCRIPT)
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def validate(tmp_path, source):
    terraform = tmp_path / "terraform"
    terraform.mkdir(exist_ok=True)
    (terraform / "main.tf").write_text(source)
    return validator.validate(tmp_path)


def fixture(*, selector=":password::", secret="db", host="main", resource_kind="aws_db_instance"):
    password_attribute = "password" if resource_kind == "aws_db_instance" else "master_password"
    return f'''
resource "{resource_kind}" "main" {{
  {password_attribute} = jsondecode(data.aws_secretsmanager_secret_version.db.secret_string)["password"]
}}
resource "{resource_kind}" "other" {{
  {password_attribute} = jsondecode(data.aws_secretsmanager_secret_version.other.secret_string)["password"]
}}
resource "aws_secretsmanager_secret" "db" {{ name = "app/db" }}
resource "aws_secretsmanager_secret" "other" {{ name = "app/other" }}
resource "aws_secretsmanager_secret_version" "db" {{
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({{ password = random_password.db.result }})
}}
resource "aws_secretsmanager_secret_version" "other" {{
  secret_id = aws_secretsmanager_secret.other.id
  secret_string = jsonencode({{ password = random_password.other.result }})
}}
data "aws_secretsmanager_secret_version" "db" {{
  secret_id = aws_secretsmanager_secret.db.id
}}
data "aws_secretsmanager_secret_version" "other" {{
  secret_id = aws_secretsmanager_secret.other.arn
}}
resource "aws_ecs_task_definition" "api" {{
  container_definitions = jsonencode([{{
    environment = [{{ name = "DB_HOST", value = {resource_kind}.{host}.address }}]
    secrets = [{{ name = "DB_PASSWORD", valueFrom = "${{aws_secretsmanager_secret.{secret}.arn}}{selector}" }}]
  }}])
}}
'''


def rules(report):
    return {finding["rule"] for finding in report["findings"]}


def test_instance_master_password_is_rejected(tmp_path):
    report = validate(tmp_path, 'resource "aws_db_instance" "db" {\n master_password = var.credential\n}\n')
    assert rules(report) == {"rds_instance_password_argument"}
    assert "var.credential" not in json.dumps(report)


@pytest.mark.parametrize(
    "kind,attribute",
    [("aws_db_instance", "password"), ("aws_rds_cluster", "master_password")],
)
def test_correct_provider_password_attributes_pass(tmp_path, kind, attribute):
    report = validate(tmp_path, f'resource "{kind}" "db" {{\n {attribute} = var.credential\n}}\n')
    assert report["artifact_status"] == "ARTIFACTS_OK", report


@pytest.mark.parametrize("kind", ["aws_db_instance", "aws_rds_cluster"])
def test_json_secret_without_password_selector_is_rejected(tmp_path, kind):
    report = validate(tmp_path, fixture(selector="", resource_kind=kind))
    assert "ecs_database_secret_json_key" in rules(report)


def test_matching_password_key_and_database_pass(tmp_path):
    report = validate(tmp_path, fixture())
    assert report["artifact_status"] == "ARTIFACTS_OK", report


def test_other_database_secret_with_valid_key_is_rejected(tmp_path):
    report = validate(tmp_path, fixture(secret="other"))
    assert rules(report) == {"ecs_database_credential_mismatch"}


@pytest.mark.parametrize("expression", [
    'jsondecode (data.aws_secretsmanager_secret_version.db.secret_string)["password"]',
    'jsondecode((data.aws_secretsmanager_secret_version.db.secret_string))["password"]',
    r'jsondecode(data.aws_secretsmanager_secret_version.db.secret_string)["\u0070assword"]',
])
def test_equivalent_password_access_preserves_mismatch_detection(tmp_path, expression):
    source = fixture(secret="other").replace(
        'jsondecode(data.aws_secretsmanager_secret_version.db.secret_string)["password"]',
        expression,
    )
    assert "ecs_database_credential_mismatch" in rules(validate(tmp_path, source))


@pytest.mark.parametrize("key", [
    '"${var.password_key}"', '"pass${var.middle}word"', 'var.password_key',
])
def test_dynamic_password_key_is_not_claimed_as_resolved_mismatch(tmp_path, key):
    source = fixture().replace(
        'jsondecode(data.aws_secretsmanager_secret_version.db.secret_string)["password"]',
        f'jsondecode(data.aws_secretsmanager_secret_version.db.secret_string)[{key}]',
    )
    assert validate(tmp_path, source)["artifact_status"] == "ARTIFACTS_OK"


def test_missing_json_key_is_rejected(tmp_path):
    report = validate(tmp_path, fixture(selector=":missing::"))
    assert "ecs_database_secret_json_key" in rules(report)


def test_comments_do_not_supply_json_secret_or_bad_argument(tmp_path):
    source = fixture().replace(
        "secret_string = jsonencode({ password = random_password.db.result })",
        'secret_string = "a-plain-string"\n # secret_string = jsonencode({ password = random_password.db.result })',
    )
    source += '\n# resource "aws_db_instance" "comment" { master_password = var.credential }\n'
    assert validate(tmp_path, source)["artifact_status"] == "ARTIFACTS_OK"


@pytest.mark.parametrize("definition", ["quoted", "heredoc"])
def test_literal_json_secret_selection_is_checked(tmp_path, definition):
    source = fixture()
    start = source.index("  container_definitions = ")
    end = source.index("\n}\n", start)
    document = json.dumps([{
        "environment": [{"name": "DB_HOST", "value": "${aws_db_instance.main.address}"}],
        "secrets": [{"name": "DB_PASSWORD", "valueFrom": "${aws_secretsmanager_secret.db.arn}"}],
    }])
    expression = json.dumps(document) if definition == "quoted" else f"<<JSON\n{document}\nJSON"
    source = source[:start] + "  container_definitions = " + expression + source[end:]
    assert "ecs_database_secret_json_key" in rules(validate(tmp_path, source))


@pytest.mark.parametrize("selector,expected", [(":password::", "ARTIFACTS_OK"), ("", "ARTIFACTS_FAIL")])
def test_rds_managed_secret_requires_password_selector(tmp_path, selector, expected):
    source = f'''
resource "aws_db_instance" "main" {{
  manage_master_user_password = true
}}
resource "aws_ecs_task_definition" "api" {{
  container_definitions = jsonencode([{{
    environment = [{{ name = "DB_HOST", value = aws_db_instance.main.address }}]
    secrets = [{{ name = "DB_PASSWORD", valueFrom = "${{aws_db_instance.main.master_user_secret[0].secret_arn}}{selector}" }}]
  }}])
}}
'''
    report = validate(tmp_path, source)
    assert report["artifact_status"] == expected, report


def test_unrelated_secret_variable_is_not_claimed_as_resolved(tmp_path):
    source = fixture().replace(
        '"${aws_secretsmanager_secret.db.arn}:password::"',
        "var.external_password_secret_arn",
    )
    report = validate(tmp_path, source)
    assert "ecs_database_credential_mismatch" not in rules(report)
    assert "Dynamic container definitions and secret retrieval code are not evaluated." in report["limitations"]


@pytest.mark.parametrize(
    "literal",
    ['"aws_secretsmanager_secret.db.arn"', '"$${aws_secretsmanager_secret.db.arn}"',
     r'"\u0024{aws_secretsmanager_secret.db.arn}"'],
)
def test_literal_address_text_is_not_a_terraform_reference(literal):
    policy, _ = validator._dependencies()
    assert validator._reference_text(literal, policy) is None


def test_authoring_source_names_provider_specific_attributes_and_capacity_gate():
    posture = (PLUGIN / "skills/tf-best-practices/references/security-posture-rules.md").read_text()
    infra = (PLUGIN / "skills/gcp-to-aws/references/phases/generate/generate-artifacts-infra.md").read_text()
    assert "On aws_db_instance" in posture
    assert "On aws_rds_cluster" in posture
    assert ':password::"' in posture
    assert "still put the secret value in Terraform state" in posture
    assert "return to Estimate to reprice" in infra
    assert "autoscaling minimum" in infra
    assert "contains `host:port`" in infra
