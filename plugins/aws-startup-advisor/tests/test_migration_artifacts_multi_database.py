"""Network checks for the generated, secret-backed multi-app EB template."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
VALIDATOR = PLUGIN / "skills/tf-best-practices/scripts/validate-migration-artifacts.py"
SPEC = importlib.util.spec_from_file_location("multi_database_artifact_validator", VALIDATOR)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


class MultiDatabaseArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policy, _ = validator._dependencies()
        cls.design = json.loads((
            PLUGIN / "fixtures/heroku-live-capture/seed-estimate/aws-design.json"
        ).read_text(encoding="utf-8"))
        source = (
            PLUGIN / "skills/heroku-to-aws/references/phases/generate/generate-terraform.md"
        ).read_text(encoding="utf-8")
        header = 'resource "aws_elastic_beanstalk_environment" "<app_name>_<process_type>" '
        start = source.index(header)
        opening = source.index("{", start)
        body, _ = cls.policy._extract_braced_block(source, opening)
        cls.environment_template = header + body

    @staticmethod
    def secret_arn(app: str) -> str:
        return f"arn:aws:secretsmanager:us-east-1:123456789012:secret:{app}/database-ABC123"

    def fixture(self) -> str:
        """Render the repository's three EB processes and two RDS targets."""
        parts = ['resource "aws_security_group" "app" {\n  name = "application"\n}\n']
        for service in self.design["services"]:
            app = service["heroku_app"]
            safe_app = app.replace("-", "_")
            if service["aws_service"] == "Elastic Beanstalk":
                rendered = self.environment_template
                for old, new in {
                    "<app_name>": safe_app,
                    "<app_sanitized>": safe_app,
                    "<heroku_app>": app,
                    "<process_type>": service["aws_config"]["process_type"],
                    "<secret-or-parameter-arn>": self.secret_arn(app),
                }.items():
                    rendered = rendered.replace(old, new)
                parts.append(rendered)
            elif service["aws_service"] == "RDS PostgreSQL":
                parts.append(f"""
resource "aws_security_group" "database_{safe_app}" {{
  ingress {{
    from_port = 5432
    to_port = 5432
    protocol = "tcp"
    security_groups = [aws_security_group.app.id]
  }}
}}
resource "aws_db_instance" "{safe_app}_postgres" {{
  engine = "postgres"
  vpc_security_group_ids = [aws_security_group.database_{safe_app}.id]
}}
""")
        return "\n".join(parts)

    def findings(self, text: str) -> list:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "terraform").mkdir()
            (root / "terraform/main.tf").write_text(text, encoding="utf-8")
            findings = []
            resources = validator._resources(root, self.policy, findings)
            validator._eb_database_access(resources, self.policy, findings)
            return findings

    def test_actual_template_and_multi_app_fixture_pass_with_shared_access(self) -> None:
        text = self.fixture()
        self.assertEqual(text.count('resource "aws_elastic_beanstalk_environment"'), 3)
        self.assertEqual(text.count('resource "aws_db_instance"'), 2)
        self.assertIn(
            'namespace = "aws:elasticbeanstalk:application:environmentsecrets"', text,
        )
        self.assertEqual(self.findings(text), [])

    def test_public_validator_and_cli_report_real_multi_database_outcome(self) -> None:
        valid = self.fixture()
        invalid = valid.replace("    security_groups = [aws_security_group.app.id]", "", 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "terraform").mkdir()
            for text, expected_status, expected_code in (
                (valid, "ARTIFACTS_OK", 0),
                (invalid, "ARTIFACTS_FAIL", 1),
            ):
                with self.subTest(expected_status=expected_status):
                    (root / "terraform/main.tf").write_text(text, encoding="utf-8")
                    report = validator.validate(root)
                    self.assertEqual(report["artifact_status"], expected_status, report)
                    result = subprocess.run(
                        [sys.executable, str(VALIDATOR), str(root), "--json", "-"],
                        text=True, capture_output=True, check=False,
                    )
                    self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout)["artifact_status"], expected_status)

    def test_parameter_arn_also_uses_all_target_proof(self) -> None:
        text = self.fixture().replace(
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:",
            "arn:aws:ssm:us-east-1:123456789012:parameter/",
        )
        self.assertEqual(self.findings(text), [])

    def test_local_secret_or_parameter_arn_requires_existing_resource(self) -> None:
        for kind in ("aws_secretsmanager_secret", "aws_ssm_parameter"):
            with self.subTest(kind=kind):
                text = self.fixture()
                for app in ("acme-web", "acme-staging"):
                    safe_app = app.replace("-", "_")
                    text = text.replace(f'"{self.secret_arn(app)}"', f"{kind}.{safe_app}.arn")
                    text += f'\nresource "{kind}" "{safe_app}" {{\n name = "{app}/db"\n}}\n'
                self.assertEqual(self.findings(text), [])

    def test_missing_database_ingress_fails_for_every_environment(self) -> None:
        text = self.fixture().replace(
            "    security_groups = [aws_security_group.app.id]", "", 1,
        )
        findings = self.findings(text)
        failures = [item for item in findings if item.rule == "eb_database_access_unverified"]
        self.assertEqual(len(failures), 3, findings)
        self.assertTrue(all("aws_db_instance.acme_web_postgres" in item.summary for item in failures))

    def test_direct_setting_does_not_hide_an_opaque_secret_target(self) -> None:
        text = self.fixture()
        secret = f"""  setting {{
    namespace = "aws:elasticbeanstalk:application:environmentsecrets"
    name      = "DATABASE_URL"
    value     = "{self.secret_arn("acme-web")}"
  }}"""
        explicit = """
  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name = "DB_READONLY_URL"
    value = "postgres://${aws_db_instance.acme_web_postgres.endpoint}/app"
  }"""
        text = text.replace(secret, secret + explicit, 1)
        text = "".join(text.rsplit("    security_groups = [aws_security_group.app.id]", 1))
        failures = self.findings(text)
        self.assertTrue(any(
            item.rule == "eb_database_access_unverified"
            and "acme_web_web:" in item.summary and "acme_staging_postgres" in item.summary
            for item in failures
        ), failures)

    def test_wrong_ingress_group_or_port_is_not_accepted(self) -> None:
        for old, new in (
            ("security_groups = [aws_security_group.app.id]",
             "security_groups = [aws_security_group.unrelated.id]"),
            ("from_port = 5432", "from_port = 5433"),
        ):
            with self.subTest(new=new):
                findings = self.findings(self.fixture().replace(old, new, 1))
                self.assertTrue(
                    any(item.rule == "eb_database_access_unverified" for item in findings),
                    findings,
                )

    def test_each_environment_must_have_access_to_all_unknown_targets(self) -> None:
        text = self.fixture().replace(
            "value     = aws_security_group.app.id",
            'value     = "sg-unrelated"',
            1,
        )
        failures = [
            item for item in self.findings(text) if item.rule == "eb_database_access_unverified"
        ]
        self.assertEqual(len(failures), 2, failures)
        self.assertTrue(all("acme_web_web:" in item.summary for item in failures))

    def test_isolated_app_groups_require_explicit_mapping(self) -> None:
        text = self.fixture().replace(
            "security_groups = [aws_security_group.app.id]",
            "security_groups = [aws_security_group.production.id]",
            1,
        )
        text += '\nresource "aws_security_group" "production" {\n name = "production"\n}\n'
        text = text.replace(
            "value     = aws_security_group.app.id",
            "value     = aws_security_group.production.id",
            1,
        )
        # Knowing a secret's app-like name is not proof of its database target.
        failures = [
            item for item in self.findings(text) if item.rule == "eb_database_access_unverified"
        ]
        self.assertTrue(any(
            "acme_web_web:" in item.summary and "acme_staging_postgres" in item.summary
            for item in failures
        ), failures)

    def test_no_database_setting_keeps_ambiguous_mapping_failure(self) -> None:
        findings = self.findings(self.fixture().replace('name      = "DATABASE_URL"', 'name = "REDIS_URL"'))
        self.assertEqual(sum(item.rule == "eb_database_mapping_unverified" for item in findings), 3)

    def test_unresolved_secret_expression_or_missing_resource_requires_review(self) -> None:
        for value in ('var.database_secret_arn', 'aws_secretsmanager_secret.missing.arn',
                      '"not-a-secret-arn"', '"arn:aws:s3:::not-a-database-secret"'):
            with self.subTest(value=value):
                text = self.fixture().replace(f'"{self.secret_arn("acme-web")}"', value)
                findings = self.findings(text)
                self.assertEqual(
                    sum(item.rule == "eb_database_mapping_unverified" for item in findings),
                    2, findings,
                )

    def test_disabled_or_dynamic_secret_resource_cannot_establish_mapping(self) -> None:
        for count in ("0", "var.secret_count"):
            with self.subTest(count=count):
                text = self.fixture()
                for app in ("acme-web", "acme-staging"):
                    safe_app = app.replace("-", "_")
                    text = text.replace(
                        f'"{self.secret_arn(app)}"', f"aws_secretsmanager_secret.{safe_app}.arn",
                    )
                    text += (
                        f'\nresource "aws_secretsmanager_secret" "{safe_app}" {{\n'
                        f'  count = {count}\n  name = "{app}/db"\n}}\n'
                    )
                findings = self.findings(text)
                self.assertEqual(
                    sum(item.rule == "eb_database_mapping_unverified" for item in findings),
                    3, findings,
                )

    def test_direct_missing_database_reference_still_fails(self) -> None:
        text = self.fixture().replace(
            "aws:elasticbeanstalk:application:environmentsecrets",
            "aws:elasticbeanstalk:application:environment",
        ).replace(
            f'"{self.secret_arn("acme-web")}"',
            '"postgres://${aws_db_instance.missing.endpoint}/app"',
        )
        findings = self.findings(text)
        self.assertTrue(any(
            item.rule == "eb_database_mapping_unverified"
            and "referenced database resource is missing" in item.summary
            for item in findings
        ), findings)


if __name__ == "__main__":
    unittest.main()
