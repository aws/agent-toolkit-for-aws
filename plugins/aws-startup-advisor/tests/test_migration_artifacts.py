"""Regression checks for the read-only generated migration artifact gate."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
VALIDATOR = PLUGIN / "skills/tf-best-practices/scripts/validate-migration-artifacts.py"
SPEC = importlib.util.spec_from_file_location("migration_artifact_validator", VALIDATOR)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


SAFE_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "--verify" ]; then
  psql -X -d "$SOURCE_DATABASE_URL" -c "SELECT count(*) FROM public.orders;"
  psql -X -d "$TARGET_DATABASE_URL" -c "SELECT count(*) FROM public.orders;"
  exit $?
fi
pg_restore "$TARGET_DATABASE_URL"
"""

TERRAFORM = """resource "aws_security_group" "app" {
  name = "application"
}
resource "aws_security_group" "database" {
  name = "database"
  ingress {
    from_port = 5432
    to_port = 5432
    protocol = "tcp"
    security_groups = [aws_security_group.app.id]
  }
}
resource "aws_db_instance" "main" {
  engine = "postgres"
  vpc_security_group_ids = [aws_security_group.database.id]
  backup_window = "03:00-03:30"
  maintenance_window = "sun:04:00-sun:04:30"
}
resource "aws_elastic_beanstalk_environment" "main" {
  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name = "SecurityGroups"
    value = aws_security_group.app.id
  }
  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name = "DATABASE_URL"
    value = "postgres://${aws_db_instance.main.endpoint}/app"
  }
}
"""

WORKFLOW = """name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2
      - name: Build image
        run: |
          docker build -t ${{ steps.login-ecr.outputs.registry }}/app .
      - name: Deploy
        run: |
          aws elasticbeanstalk update-environment \\
            --environment-name app-production \\
            --version-label "${GITHUB_SHA}"
"""


def canonical_script() -> str:
    text = (
        PLUGIN / "skills/heroku-to-aws/references/phases/generate/generate-docs.md"
    ).read_text(encoding="utf-8")
    return (
        text.split("### 3A: PostgreSQL Migration Script", 1)[1]
        .split("```bash\n", 1)[1].split("\n```", 1)[0] + "\n"
    )


class MigrationArtifactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.write("terraform/main.tf", TERRAFORM)
        self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT)
        self.write(".github/workflows/deploy-eb.yml", WORKFLOW)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, path: str, text: str) -> Path:
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        return destination

    def report(self) -> dict:
        return validator.validate(self.root)

    def rules(self) -> set[str]:
        return {item["rule"] for item in self.report()["findings"]}

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(self.root), *args],
            text=True, capture_output=True, check=False,
        )

    def test_complete_valid_fixture_passes(self) -> None:
        report = self.report()
        self.assertEqual(report["artifact_status"], "ARTIFACTS_OK", report)
        self.assertIn("ecs_database_credentials", report["checks_run"])

    def test_canonical_template_verification_is_accepted(self) -> None:
        self.write("scripts/migrate-postgres.sh", canonical_script())
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_reviewed_template_allows_connection_values_and_migration_only_changes(self) -> None:
        script = canonical_script().replace("{{SOURCE_DB_PASSWORD}}", "literal-secret")
        script = script.replace("  log \"Exporting source database to $BACKUP_FILE...\"",
                                "  log \"Different migration implementation\"")
        script = script.replace('  log "=== PostgreSQL Migration Started ==="',
                                '  log "A different full migration path"')
        self.write("scripts/migrate-postgres.sh", script)
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_canonical_reachable_function_change_requires_review(self) -> None:
        script = canonical_script().replace(
            'log "Testing source database connection..."',
            'pg_restore "$TARGET_DB_NAME"',
        )
        self.write("scripts/migrate-postgres.sh", script)
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_canonical_control_flow_mutation_requires_review(self) -> None:
        script = canonical_script().replace(
            '  if [ "$MODE" = "verify" ]; then',
            '  import_target\n  if [ "$MODE" = "verify" ]; then',
        )
        self.write("scripts/migrate-postgres.sh", script)
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_canonical_quote_semantics_cannot_be_normalized_away(self) -> None:
        for old, new in [
            ('if [ "$MODE" = "verify" ]; then', """if [ '$MODE' = "verify" ]; then"""),
            ('case "${1:-}" in', """case '${1:-}' in"""),
            ('  MODE="migrate"', """  MODE='migrate'"""),
            ('main "$@"', """main '$@'"""),
            ('if [ "$MODE" = "verify" ]; then', r'if [ "\$MODE" = "verify" ]; then'),
        ]:
            with self.subTest(new=new):
                self.write("scripts/migrate-postgres.sh", canonical_script().replace(old, new))
                self.assertIn("postgres_verify_unverified", self.rules())

    def test_canonical_top_level_effect_after_attached_hash_not_hidden(self) -> None:
        script = canonical_script().replace('main "$@"', 'main "$@"# ; pg_restore "$TARGET_DB_NAME"')
        self.write("scripts/migrate-postgres.sh", script)
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_continued_comment_line_cannot_hide_a_top_level_command(self) -> None:
        marker = self.root / "MUST_NOT_EXIST"
        assignment = 'LOG_FILE="postgres_migration_$(date +%Y%m%d_%H%M%S).log"'
        for continuation in ["\\\n", "\\\n  ", "\\\r\n"]:
            with self.subTest(continuation=repr(continuation)):
                script = canonical_script().replace(
                    assignment, assignment + continuation + f"#; touch {marker}",
                )
                self.write("scripts/migrate-postgres.sh", script)
                self.assertIn("postgres_verify_unverified", self.rules())
                self.assertFalse(marker.exists())

    def test_canonical_comments_and_whitespace_are_accepted(self) -> None:
        script = canonical_script().replace(
            '\n  MODE="migrate"\n', '\n  # ordinary harmless comment\n\n    MODE="migrate"\n',
        )
        self.write("scripts/migrate-postgres.sh", script)
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_connection_substitution_cannot_introduce_execution(self) -> None:
        script = canonical_script().replace("{{SOURCE_DB_PASSWORD}}", "$(pg_restore evil)")
        self.write("scripts/migrate-postgres.sh", script)
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_comment_and_quoted_verify_text_do_not_prove_guard(self) -> None:
        self.write("scripts/migrate-postgres.sh", """#!/usr/bin/env bash
# --verify is safe!
echo 'if [ "${1:-}" = "--verify" ]; then exit 0; fi'
pg_restore "$TARGET_DATABASE_URL"
""")
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_unconditional_effect_before_guard_fails(self) -> None:
        self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT.replace(
            "set -euo pipefail", 'set -euo pipefail\nheroku maintenance:on --app example',
        ))
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_redirection_or_execution_environment_before_guard_requires_review(self) -> None:
        for prefix in ["X=1>/tmp/not-created", "PATH=/tmp/unknown", "PSQLRC=/tmp/unknown"]:
            with self.subTest(prefix=prefix):
                self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT.replace(
                    "set -euo pipefail", "set -euo pipefail\n" + prefix,
                ))
                self.assertIn("postgres_verify_unverified", self.rules())

    def test_verify_branch_requires_exit(self) -> None:
        self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT.replace("  exit $?\n", ""))
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_quoted_parameter_cannot_make_guard_permanently_false(self) -> None:
        self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT.replace('"${1:-}"', "'${1:-}'"))
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_verify_branch_cannot_restore_or_write_sql(self) -> None:
        for mutation in [
            SAFE_SCRIPT.replace('  exit $?', '  pg_restore "$TARGET_DATABASE_URL"\n  exit $?'),
            SAFE_SCRIPT.replace("SELECT count(*) FROM public.orders;", "DROP TABLE orders;"),
            SAFE_SCRIPT.replace("SELECT count(*) FROM public.orders;", "SELECT pg_terminate_backend(1);"),
            SAFE_SCRIPT.replace("SELECT count(*) FROM public.orders;", "SELECT 1; DROP TABLE orders;"),
            SAFE_SCRIPT.replace('-c "SELECT count(*) FROM public.orders;"', "-f destructive.sql"),
            SAFE_SCRIPT.replace('psql -X -d "$SOURCE_DATABASE_URL"', 'psql -X -d $SOURCE_DATABASE_URL'),
            SAFE_SCRIPT.replace('psql -X -d "$SOURCE_DATABASE_URL"', 'psql -X -d "$SOURCE_DATABASE_URL" --command="DROP TABLE orders"'),
            SAFE_SCRIPT.replace('psql -X -d "$SOURCE_DATABASE_URL"', 'psql -X -d "$SOURCE_DATABASE_URL" -fdestructive.sql'),
        ]:
            with self.subTest(script=mutation):
                self.write("scripts/migrate-postgres.sh", mutation)
                self.assertIn("postgres_verify_unverified", self.rules())

    def test_verify_environment_prefix_and_redirects_cannot_hide_effects(self) -> None:
        for prefix in [
            "X=1>/tmp/unexpected-write ",
            "X=1 2>/tmp/unexpected-write ",
            "PGPASSWORD=ok>/tmp/unexpected-write ",
            "PGPASSWORD=$(touch /tmp/unexpected-write) ",
            'PGPASSWORD="$(touch /tmp/unexpected-write)" ',
            'PGPASSWORD="`touch /tmp/unexpected-write`" ',
            "PSQLRC=/tmp/startup ",
            "PATH=/tmp/bin ",
            "BASH_ENV=/tmp/startup ",
        ]:
            with self.subTest(prefix=prefix):
                self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT.replace(
                    "  psql -X", "  " + prefix + "psql -X", 1,
                ))
                self.assertIn("postgres_verify_unverified", self.rules())

    def test_verify_psql_must_disable_startup_files(self) -> None:
        self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT.replace("psql -X", "psql"))
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_positional_connection_cannot_inject_psql_command_option(self) -> None:
        script = SAFE_SCRIPT.replace(
            "set -euo pipefail",
            "set -euo pipefail\nSOURCE_DATABASE_URL='--command=DROP TABLE orders'",
        ).replace('-d "$SOURCE_DATABASE_URL"', '"$SOURCE_DATABASE_URL"')
        self.write("scripts/migrate-postgres.sh", script)
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_parameter_transformations_cannot_synthesize_verification_commands(self) -> None:
        for connection in [
            "${EXPANDED:=${PAYLOAD@E}}${EXPANDED@P}",
            "${PAYLOAD@P}",
            "${VALUE:=unsafe}",
            "${array[PATH=0]}",
        ]:
            with self.subTest(connection=connection):
                script = SAFE_SCRIPT.replace(
                    "set -euo pipefail",
                    "set -euo pipefail\nPAYLOAD='\\044\\050pg_restore foo\\051'",
                ).replace("$SOURCE_DATABASE_URL", connection)
                self.write("scripts/migrate-postgres.sh", script)
                self.assertIn("postgres_verify_unverified", self.rules())
        self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT.replace("psql -X", "psql --no-psqlrc"))
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")
        self.write("scripts/migrate-postgres.sh", canonical_script().replace("psql -X", "psql", 1))
        self.assertIn("postgres_verify_unverified", self.rules())

    def test_shell_syntax_error_is_distinct(self) -> None:
        self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT.replace("\nfi\n", "\n"))
        self.assertIn("postgres_script_syntax", self.rules())

    def test_postgres_interpreter_cannot_disable_verification(self) -> None:
        for script in [SAFE_SCRIPT, canonical_script()]:
            for header in ["#!/bin/bash -n", "#!/usr/bin/env bash -n", "#!/bin/sh", ""]:
                with self.subTest(header=header, canonical=script != SAFE_SCRIPT):
                    self.write("scripts/migrate-postgres.sh", script.replace(
                        "#!/usr/bin/env bash", header, 1,
                    ))
                    self.assertIn("postgres_interpreter_unverified", self.rules())
        self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT.replace(
            "#!/usr/bin/env bash", "#!/bin/bash",
        ))
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_simple_double_bracket_safe_variant(self) -> None:
        self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT.replace(
            '[ "${1:-}" = "--verify" ]', '[[ "$1" == --verify ]]',
        ))
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_postgres_script_is_required_when_applicable(self) -> None:
        (self.root / "scripts/migrate-postgres.sh").unlink()
        report = validator.validate(self.root, require_postgres_script=True)
        self.assertIn("postgres_script_missing", {item["rule"] for item in report["findings"]})
        self.assertNotIn("postgres_script_missing", self.rules())

    def test_require_postgres_flag_is_authoritative_with_unknown_engine(self) -> None:
        (self.root / "scripts/migrate-postgres.sh").unlink()
        self.write("terraform/main.tf", TERRAFORM.replace('engine = "postgres"', 'engine = var.engine\n  port = 5432'))
        report = validator.validate(self.root, require_postgres_script=True)
        self.assertIn("postgres_script_missing", {item["rule"] for item in report["findings"]})

    def test_gcp_does_not_require_heroku_script_name(self) -> None:
        (self.root / "scripts/migrate-postgres.sh").unlink()
        self.write("scripts/migrate-database.sh", "#!/bin/bash\nexit 0\n")
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_eb_manual_deploy_or_codepipeline_does_not_require_github(self) -> None:
        (self.root / ".github/workflows/deploy-eb.yml").unlink()
        self.assertNotIn("eb_deploy_missing", self.rules())
        report = validator.validate(self.root, require_eb_workflow=True)
        self.assertIn("eb_deploy_missing", {item["rule"] for item in report["findings"]})
        self.write("terraform/pipeline.tf", 'resource "aws_codepipeline" "deploy" {\n name = "deploy"\n}\n')
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")
        report = validator.validate(self.root, require_eb_workflow=True)
        self.assertIn("eb_deploy_missing", {item["rule"] for item in report["findings"]})

    def test_selected_github_workflow_cannot_be_satisfied_by_retained_pipeline(self) -> None:
        text = (PLUGIN / "skills/heroku-to-aws/references/phases/generate/generate-terraform.md").read_text()
        section = text.split("### `pipeline.tf`", 1)[1]
        pipeline = section.split("```hcl\n", 1)[1].split("\n```", 1)[0]
        self.write("terraform/pipeline.tf", pipeline.replace("<app_name>", "main").replace("<process_type>", "web"))
        for workflow in (
            None,
            "jobs:\n  deploy:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo deploy\n",
            WORKFLOW.replace("      - name: Deploy\n", "      - name: Deploy\n        if: false\n"),
            WORKFLOW,
        ):
            with self.subTest(workflow=workflow):
                path = self.root / ".github/workflows/deploy-eb.yml"
                if workflow is None:
                    path.unlink(missing_ok=True)
                else:
                    self.write(".github/workflows/deploy-eb.yml", workflow)
                # The caller may explicitly choose CodePipeline, but a retained
                # pipeline must never substitute for selected GitHub Actions.
                self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")
                report = validator.validate(self.root, require_eb_workflow=True)
                if workflow == WORKFLOW:
                    self.assertEqual(report["artifact_status"], "ARTIFACTS_OK", report)
                else:
                    self.assertIn("eb_deploy_missing", {item["rule"] for item in report["findings"]})
                    result = self.cli("--require-eb-workflow", "--json", "-")
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout)["artifact_status"], "ARTIFACTS_FAIL")

    def test_no_postgres_no_eb_skips_inapplicable_checks(self) -> None:
        self.write("terraform/main.tf", 'resource "aws_s3_bucket" "test" {\n bucket = "example"\n}\n')
        (self.root / "scripts/migrate-postgres.sh").unlink()
        (self.root / ".github/workflows/deploy-eb.yml").unlink()
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_require_eb_flag_is_authoritative_when_environment_is_missing(self) -> None:
        self.write("terraform/main.tf", 'resource "aws_codepipeline" "deploy" {\n name = "deploy"\n}\n')
        (self.root / ".github/workflows/deploy-eb.yml").unlink()
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")
        report = validator.validate(self.root, require_eb_workflow=True)
        self.assertIn("eb_deploy_missing", {item["rule"] for item in report["findings"]})
        self.write(".github/workflows/deploy-eb.yml", WORKFLOW)
        report = validator.validate(self.root, require_eb_workflow=True)
        self.assertEqual(report["artifact_status"], "ARTIFACTS_OK", report)

    def test_security_group_must_be_attached(self) -> None:
        self.write("terraform/main.tf", TERRAFORM.replace(
            "    value = aws_security_group.app.id", '    value = "sg-other"',
        ))
        self.assertIn("eb_database_access_unverified", self.rules())

    def test_commented_attachment_is_not_accepted(self) -> None:
        self.write("terraform/main.tf", TERRAFORM.replace(
            "    value = aws_security_group.app.id", "    # value = aws_security_group.app.id",
        ))
        self.assertIn("eb_database_security_group", self.rules())

    def test_nested_setting_is_not_the_environment_setting(self) -> None:
        section = """  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name = "SecurityGroups"
    value = aws_security_group.app.id
  }"""
        self.write("terraform/main.tf", TERRAFORM.replace(section, "  lifecycle {\n" + section + "\n  }"))
        self.assertIn("eb_database_security_group", self.rules())

    def test_direct_list_join_and_interpolation_groups(self) -> None:
        for expression in [
            "[aws_security_group.app.id]",
            'join(",", [aws_security_group.app.id])',
            '"${aws_security_group.app.id}"',
        ]:
            with self.subTest(expression=expression):
                self.write("terraform/main.tf", TERRAFORM.replace(
                    "    value = aws_security_group.app.id", f"    value = {expression}",
                ))
                self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_unknown_group_expression_is_explicitly_unverified(self) -> None:
        self.write("terraform/main.tf", TERRAFORM.replace(
            "    value = aws_security_group.app.id",
            "    value = var.use_app ? aws_security_group.app.id : aws_security_group.other.id",
        ))
        self.assertIn("eb_database_security_group", self.rules())

    def test_database_port_must_be_allowed(self) -> None:
        self.write("terraform/main.tf", TERRAFORM.replace("from_port = 5432", "from_port = 3306")
                   .replace("to_port = 5432", "to_port = 3306"))
        self.assertIn("eb_database_access_unverified", self.rules())

    def test_separate_ingress_resources(self) -> None:
        inline = """  ingress {
    from_port = 5432
    to_port = 5432
    protocol = "tcp"
    security_groups = [aws_security_group.app.id]
  }
"""
        for kind, source, protocol, extra in [
            ("aws_security_group_rule", "source_security_group_id", "protocol", '  type = "ingress"\n'),
            ("aws_vpc_security_group_ingress_rule", "referenced_security_group_id", "ip_protocol", ""),
        ]:
            with self.subTest(kind=kind):
                rule = f"""
resource "{kind}" "db_access" {{
{extra}  security_group_id = aws_security_group.database.id
  {source} = aws_security_group.app.id
  {protocol} = "tcp"
  from_port = 5432
  to_port = 5432
}}
"""
                self.write("terraform/main.tf", TERRAFORM.replace(inline, "") + rule)
                self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_disabled_or_dynamic_ingress_cannot_prove_connectivity(self) -> None:
        inline = """  ingress {
    from_port = 5432
    to_port = 5432
    protocol = "tcp"
    security_groups = [aws_security_group.app.id]
  }
"""
        for instancing in ["count = 0", "for_each = {}", "for_each = toset([])", "count = var.enabled ? 1 : 0", "for_each = var.rules"]:
            with self.subTest(instancing=instancing):
                rule = f"""
resource "aws_security_group_rule" "db_access" {{
  {instancing}
  type = "ingress"
  security_group_id = aws_security_group.database.id
  source_security_group_id = aws_security_group.app.id
  protocol = "tcp"
  from_port = 5432
  to_port = 5432
}}
"""
                self.write("terraform/main.tf", TERRAFORM.replace(inline, "") + rule)
                self.assertIn("eb_database_access_unverified", self.rules())

    def test_unrelated_conditional_resource_does_not_block_connectivity(self) -> None:
        self.write("terraform/main.tf", TERRAFORM + """
resource "aws_s3_bucket" "conditional" {
  count = var.enabled ? 1 : 0
  bucket = "unrelated"
}
""")
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_terraform_subdirectory_cannot_supply_root_security_group(self) -> None:
        inline = """  ingress {
    from_port = 5432
    to_port = 5432
    protocol = "tcp"
    security_groups = [aws_security_group.app.id]
  }
"""
        self.write("terraform/main.tf", TERRAFORM.replace(inline, ""))
        self.write("terraform/examples/security.tf", TERRAFORM)
        self.assertIn("eb_database_access_unverified", self.rules())

    def test_referenced_module_requires_review_without_flattening(self) -> None:
        self.write("terraform/main.tf", TERRAFORM + """
module "network" {
  source = "./modules/network"
}
""")
        self.write("terraform/modules/network/main.tf", TERRAFORM)
        self.assertIn("terraform_module_unverified", self.rules())

    def test_comment_cannot_supply_ingress(self) -> None:
        self.write("terraform/main.tf", TERRAFORM.replace(
            "    security_groups = [aws_security_group.app.id]",
            "    # security_groups = [aws_security_group.app.id]",
        ))
        self.assertIn("eb_database_access_unverified", self.rules())

    def test_windows_overlap_and_boundary(self) -> None:
        self.write("terraform/main.tf", TERRAFORM.replace(
            "sun:04:00-sun:04:30", "sun:03:15-sun:03:45",
        ))
        self.assertIn("rds_windows_overlap", self.rules())
        self.write("terraform/main.tf", TERRAFORM.replace(
            "sun:04:00-sun:04:30", "sun:03:30-sun:04:00",
        ))
        self.assertNotIn("rds_windows_overlap", self.rules())

    def test_invalid_and_unknown_windows_are_not_passed(self) -> None:
        self.write("terraform/main.tf", TERRAFORM.replace('"03:00-03:30"', '"26:00-26:30"'))
        self.assertIn("rds_windows_invalid", self.rules())
        self.write("terraform/main.tf", TERRAFORM.replace('"03:00-03:30"', "var.backup_window"))
        self.assertIn("rds_windows_unverified", self.rules())

    def test_each_explicit_rds_window_is_validated_independently(self) -> None:
        for removed, old, new in [
            ('  maintenance_window = "sun:04:00-sun:04:30"\n', "03:00-03:30", "29:00-29:30"),
            ('  backup_window = "03:00-03:30"\n', "sun:04:00-sun:04:30", "sun:29:00-sun:29:30"),
        ]:
            with self.subTest(new=new):
                self.write("terraform/main.tf", TERRAFORM.replace(removed, "").replace(old, new))
                self.assertIn("rds_windows_invalid", self.rules())

    def test_comment_window_does_not_override_actual_window(self) -> None:
        self.write("terraform/main.tf", TERRAFORM.replace(
            '  backup_window = "03:00-03:30"',
            '  # backup_window = "10:00-10:30"\n  backup_window = "04:00-04:30"',
        ))
        self.assertIn("rds_windows_overlap", self.rules())

    def test_missing_action_id_and_per_job_resolution(self) -> None:
        self.write(".github/workflows/deploy-eb.yml", WORKFLOW.replace("      - id: login-ecr\n", "      - name: Login\n"))
        self.assertIn("workflow_step_reference", self.rules())
        self.write(".github/workflows/deploy-eb.yml", WORKFLOW.replace(
            "      - id: login-ecr", "      - id: something-else",
        ) + """
  another:
    runs-on: ubuntu-latest
    steps:
      - id: login-ecr
        run: echo hello
""")
        self.assertIn("workflow_step_reference", self.rules())

    def test_with_input_id_does_not_define_a_step_id(self) -> None:
        self.write(".github/workflows/deploy-eb.yml", WORKFLOW.replace(
            "      - id: login-ecr\n        uses: aws-actions/amazon-ecr-login@v2",
            "      - uses: aws-actions/amazon-ecr-login@v2\n        with:\n          id: login-ecr",
        ))
        self.assertIn("workflow_step_reference", self.rules())

    def test_duplicate_step_ids_fail(self) -> None:
        self.write(".github/workflows/deploy-eb.yml", WORKFLOW.replace(
            "      - name: Build image", "      - id: login-ecr\n        name: Build image",
        ))
        self.assertIn("workflow_duplicate_step_id", self.rules())

    def test_echo_and_comment_deploy_are_not_deployment(self) -> None:
        for body in [
            'echo "aws elasticbeanstalk update-environment --version-label abc"',
            "# aws elasticbeanstalk update-environment --version-label abc\necho hello",
            "echo eb deploy",
            'deploy() { aws elasticbeanstalk update-environment --version-label abc; }\necho hello',
            'if false; then\n aws elasticbeanstalk update-environment --version-label abc\nfi',
            'false && aws elasticbeanstalk update-environment --version-label abc',
            'exit 0; aws elasticbeanstalk update-environment --version-label abc',
            'echo hello; exit 0; aws elasticbeanstalk update-environment --version-label abc',
            "aws echo elasticbeanstalk update-environment --version-label abc",
            "eb deploy --help",
        ]:
            with self.subTest(body=body):
                workflow = """jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: |
""" + "\n".join("          " + line for line in body.splitlines()) + "\n"
                self.write(".github/workflows/deploy-eb.yml", workflow)
                self.assertIn("eb_deploy_missing", self.rules())

    def test_whole_run_structure_cannot_hide_nonexecuted_deployment(self) -> None:
        command = "aws elasticbeanstalk update-environment --version-label abc"
        for body in [
            "cat <<'TEXT'\n" + command + "\nTEXT",
            'echo "documentation only\n' + command + '\n"',
            "false && {\n" + command + "\n}",
            "set -n\n" + command,
            "PATH=/tmp/unverified-tools\n" + command,
            "for unused in; do\n" + command + "\ndone",
            'for unused in ${EMPTY}; do\n' + command + "\ndone",
        ]:
            with self.subTest(body=body):
                workflow = """jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: |
""" + "\n".join("          " + line for line in body.splitlines()) + "\n"
                self.write(".github/workflows/deploy-eb.yml", workflow)
                self.assertIn("workflow_run_unverified", self.rules())
                self.assertIn("eb_deploy_missing", self.rules())

    def test_nested_workflow_example_cannot_satisfy_deployment(self) -> None:
        (self.root / ".github/workflows/deploy-eb.yml").unlink()
        self.write(".github/workflows/examples/deploy-eb.yml", WORKFLOW)
        report = validator.validate(self.root, require_eb_workflow=True)
        self.assertIn("eb_deploy_missing", {item["rule"] for item in report["findings"]})

    def test_source_eb_workflow_with_literal_environment_list_passes(self) -> None:
        text = (PLUGIN / "skills/heroku-to-aws/references/phases/generate/generate-terraform.md").read_text()
        section = text.split("### `.github/workflows/deploy-eb.yml`", 1)[1]
        workflow = section.split("```yaml\n", 1)[1].split("\n```", 1)[0]
        workflow = workflow.replace("<space-separated EB environment names from aws-design.json>", "app-web app-worker")
        self.write(".github/workflows/deploy-eb.yml", workflow)
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK", self.report())

    def test_loop_environment_reassignment_must_remain_provably_nonempty(self) -> None:
        for assignment in ['EB_ENVIRONMENTS=""', "EB_ENVIRONMENTS=$MISSING", 'export EB_ENVIRONMENTS=""', "read EB_ENVIRONMENTS", 'EB_ENVIRONMENTS+=""']:
            with self.subTest(assignment=assignment):
                body = assignment + """
for ENVIRONMENT in ${EB_ENVIRONMENTS}; do
  aws elasticbeanstalk update-environment --environment-name "$ENVIRONMENT" --version-label abc
done
"""
                workflow = """env:
  EB_ENVIRONMENTS: app-web
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: |
""" + "\n".join("          " + line for line in body.splitlines()) + "\n"
                self.write(".github/workflows/deploy-eb.yml", workflow)
                self.assertIn("workflow_run_unverified", self.rules())

    def test_execution_context_wrappers_and_dynamic_command_words_require_review(self) -> None:
        command = "aws elasticbeanstalk update-environment --version-label abc"
        for prefix in [
            'STOP=exit\n"$STOP" 0',
            "command -p exit 0",
            "time exit 0",
            "! exit 0",
            "hash -p /usr/bin/true aws",
            "kill -TERM $$",
            'echo "$(kill -TERM $$)"',
            'printf -vEB_ENVIRONMENTS ""',
            'printf "%n" PATH',
            'echo "$((PATH=0))"',
            'echo "${PATH:=/tmp/unknown}"',
            'echo "${array[PATH=0]}"',
            'echo "`kill -TERM $$`"',
        ]:
            with self.subTest(prefix=prefix):
                body = prefix + "\n" + command
                workflow = """jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: |
""" + "\n".join("          " + line for line in body.splitlines()) + "\n"
                self.write(".github/workflows/deploy-eb.yml", workflow)
                self.assertIn("workflow_run_unverified", self.rules())

    def test_reserved_environment_overrides_are_rejected_in_every_scope(self) -> None:
        examples = [
            WORKFLOW.replace("          aws elasticbeanstalk", "          PATH=/no-such-path aws elasticbeanstalk"),
            "env:\n  PATH: /no-such-path\n" + WORKFLOW,
            WORKFLOW.replace("    runs-on: ubuntu-latest", "    runs-on: ubuntu-latest\n    env:\n      PATH: /no-such-path"),
            WORKFLOW.replace("      - name: Deploy", "      - name: Deploy\n        env:\n          PATH: /no-such-path"),
        ]
        for workflow in examples:
            with self.subTest(workflow=workflow):
                self.write(".github/workflows/deploy-eb.yml", workflow)
                self.assertNotEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_loops_cannot_mutate_execution_environment_or_hide_state_changes(self) -> None:
        command = "aws elasticbeanstalk update-environment --version-label abc"
        examples = [
            "for PATH in app-web; do\n" + command + "\ndone",
            'EB_ENVIRONMENTS=app-web\nfor ENVIRONMENT in ${EB_ENVIRONMENTS}; do\n EB_ENVIRONMENTS=""\ndone\n'
            "for ENVIRONMENT in ${EB_ENVIRONMENTS}; do\n" + command + "\ndone",
        ]
        for body in examples:
            with self.subTest(body=body):
                workflow = """jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - run: |
""" + "\n".join("          " + line for line in body.splitlines()) + "\n"
                self.write(".github/workflows/deploy-eb.yml", workflow)
                self.assertIn("workflow_run_unverified", self.rules())

    def test_non_shell_deployment_run_requires_review(self) -> None:
        self.write(".github/workflows/deploy-eb.yml", WORKFLOW.replace(
            "      - name: Deploy", "      - name: Deploy\n        shell: python",
        ))
        self.assertIn("workflow_shell_unverified", self.rules())

    def test_workflow_and_job_defaults_cannot_hide_non_shell_execution(self) -> None:
        for workflow in [
            "defaults:\n  run:\n    shell: python\n" + WORKFLOW,
            WORKFLOW.replace("    runs-on: ubuntu-latest", "    runs-on: ubuntu-latest\n    defaults:\n      run:\n        shell: python"),
            WORKFLOW.replace("runs-on: ubuntu-latest", "runs-on: windows-latest"),
        ]:
            with self.subTest(workflow=workflow):
                self.write(".github/workflows/deploy-eb.yml", workflow)
                self.assertIn("workflow_shell_unverified", self.rules())

    def test_unknown_deployment_conditions_require_review(self) -> None:
        for condition in ["${{ github.event_name == 'push' }}", "always()"]:
            with self.subTest(condition=condition):
                self.write(".github/workflows/deploy-eb.yml", WORKFLOW.replace(
                    "      - name: Deploy", f"      - name: Deploy\n        if: {condition}",
                ))
                self.assertIn("workflow_condition_unverified", self.rules())

    def test_eb_cli_and_known_deploy_action(self) -> None:
        for step in ["run: eb deploy app", "uses: einaregilsson/beanstalk-deploy@v22"]:
            with self.subTest(step=step):
                self.write(".github/workflows/deploy-eb.yml", f"""jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - {step}
""")
                self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_disabled_deploy_does_not_count(self) -> None:
        self.write(".github/workflows/deploy-eb.yml", WORKFLOW.replace(
            "      - name: Deploy", "      - name: Deploy\n        if: false",
        ))
        self.assertIn("eb_deploy_missing", self.rules())
        for workflow in [
            WORKFLOW.replace("      - name: Deploy", "      - name: Deploy\n        if: ${{ false }}"),
            WORKFLOW.replace("    runs-on: ubuntu-latest", "    runs-on: ubuntu-latest\n    if: ${{ false }}"),
        ]:
            with self.subTest(workflow=workflow):
                self.write(".github/workflows/deploy-eb.yml", workflow)
                self.assertIn("eb_deploy_missing", self.rules())

    def test_flow_yaml_is_explicitly_unverified(self) -> None:
        self.write(".github/workflows/deploy-eb.yml", "jobs: {deploy: {steps: []}}\n")
        self.assertIn("workflow_unverified", self.rules())

    def test_placeholder_docker_comment_is_not_a_failure(self) -> None:
        self.write(".github/workflows/deploy-eb.yml", WORKFLOW.replace(
            "          docker build", "          # TODO: customer source Dockerfile path\n          docker build",
        ))
        self.assertEqual(self.report()["artifact_status"], "ARTIFACTS_OK")

    def test_invalid_hcl_and_duplicate_attr_fail(self) -> None:
        self.write("terraform/main.tf", TERRAFORM + 'resource "aws_s3_bucket" "bad" {\n')
        self.assertIn("hcl_unverified", self.rules())
        self.write("terraform/main.tf", TERRAFORM.replace(
            '  backup_window = "03:00-03:30"',
            '  backup_window = "03:00-03:30"\n  backup_window = "04:00-04:30"',
        ))
        self.assertIn("artifact_shape_unverified", self.rules())

    def test_cli_deterministic_and_no_execution_or_artifact_writes(self) -> None:
        sentinel = self.root / "MUST_NOT_EXIST"
        self.write("scripts/migrate-postgres.sh", SAFE_SCRIPT + f'\ntouch "{sentinel}"\n')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        first = self.cli("--json", "-")
        second = self.cli("--json", "-")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertFalse(sentinel.exists())
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_cli_report_file_is_only_requested_write(self) -> None:
        output = self.root / "artifact-validation.json"
        result = self.cli("--json", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ARTIFACTS_OK")
        self.assertEqual(json.loads(output.read_text())["artifact_status"], "ARTIFACTS_OK")
        self.assertEqual(self.cli("--json", str(output)).returncode, 0)

    def test_report_cannot_overwrite_existing_input_or_state(self) -> None:
        for name in ["preferences.json", ".phase-status.json", "terraform/main.tf"]:
            with self.subTest(name=name):
                destination = self.root / name
                if not destination.exists():
                    destination.write_text('{"original":true}')
                before = destination.read_bytes()
                result = self.cli("--json", str(destination))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(destination.read_bytes(), before)

    def test_symlink_outside_root_and_missing_dependency_fail_as_input_errors(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "outside.tf"
            outside.write_text(TERRAFORM)
            target = self.root / "terraform/main.tf"
            target.unlink()
            target.symlink_to(outside)
            result = self.cli("--json", "-")
            self.assertEqual(result.returncode, 2)
            self.assertIn("escapes migration directory", result.stdout)
        with patch.object(validator, "_dependencies", side_effect=validator.InputError("missing parser")):
            self.assertRaises(validator.InputError, validator.validate, self.root)

    def test_missing_directory_and_non_utf8_are_input_errors(self) -> None:
        missing = subprocess.run(
            [sys.executable, str(VALIDATOR), str(self.root / "absent"), "--json", "-"],
            text=True, capture_output=True,
        )
        self.assertEqual(missing.returncode, 2)
        (self.root / "terraform/main.tf").write_bytes(b"\xff")
        self.assertEqual(self.cli("--json", "-").returncode, 2)


if __name__ == "__main__":
    unittest.main()
