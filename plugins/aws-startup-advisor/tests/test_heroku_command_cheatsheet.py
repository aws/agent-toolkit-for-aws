"""Text contract: the heroku-to-aws MIGRATION_GUIDE "Day-to-day commands" section.

Pins the review corrections on the command cheat sheet so a later edit cannot quietly
reintroduce them:
- the section renders regardless of `deferred_addons` (it sits before that guard);
- Elastic Beanstalk log tailing names a streamed group with the full
  `.../eb-current-app/stdouterr.log` suffix and `beanstalk.tf` enables `StreamLogs`;
- interactive shells use `/bin/sh` (the Alpine Dockerfile patterns ship no bash);
- config rows follow the backing store (Secrets Manager / SSM / plain property) instead of
  an invented `/<app>/KEY` parameter path or `<app>/DATABASE_URL` secret;
- per-process rows are rendered from the design and web/ALB-only rows are guarded;
- the backup row branches RDS vs Aurora and both database rows need `has_postgres`;
- `open` uses the configured HTTPS hostname or the protocol the endpoint serves.
"""

from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
GENERATE = PLUGIN_ROOT / "skills" / "heroku-to-aws" / "references" / "phases" / "generate"
DOCS = (GENERATE / "generate-docs.md").read_text(encoding="utf-8")
TERRAFORM = (GENERATE / "generate-terraform.md").read_text(encoding="utf-8")

HEADING = "## Day-to-day commands: Heroku → AWS"
DEFERRED_GUARD = "{{IF deferred_addons.length > 0}}"


def _section() -> str:
    start = DOCS.index(HEADING)
    end = DOCS.index("## Manual Migration Items", start)
    return DOCS[start:end]


def test_section_is_outside_the_deferred_addons_guard() -> None:
    section = _section()
    # The guard that wraps Manual Migration Items opens after the cheat sheet body,
    # and no deferred guard opens between the Decommission section and the heading.
    decommission = DOCS.index("## Decommission Heroku Resources")
    heading = DOCS.index(HEADING)
    assert DEFERRED_GUARD not in DOCS[decommission:heading]
    assert section.rstrip().endswith("---")
    assert DEFERRED_GUARD in section
    assert section.index(DEFERRED_GUARD) > section.index("{{IF has_fargate}}")


def test_eb_log_tail_targets_streamed_stdouterr_group() -> None:
    section = _section()
    assert (
        "/aws/elasticbeanstalk/{{proc.environment_name}}/var/log/eb-docker/containers/"
        "eb-current-app/stdouterr.log --follow"
    ) in section
    eb_env = TERRAFORM[TERRAFORM.index('resource "aws_elastic_beanstalk_environment"'):]
    eb_env = eb_env[: eb_env.index("resource \"aws_iam_instance_profile\"")]
    assert 'namespace = "aws:elasticbeanstalk:cloudwatch:logs"' in eb_env
    assert re.search(r'name\s+= "StreamLogs"\s+value\s+= "true"', eb_env)
    assert 'name      = "RetentionInDays"' in eb_env


def test_interactive_shell_uses_sh_not_bash() -> None:
    section = _section()
    assert "--command /bin/sh" in section
    assert "docker exec -it $(sudo docker ps -q) /bin/sh" in section
    assert "--command bash" not in section
    assert "docker ps -q) bash" not in section


def test_eb_shell_uses_ssm_session_not_eb_ssh() -> None:
    # The generated environment has no EC2 key pair and no :22 ingress, so `eb ssh`
    # cannot work; the shell goes through Session Manager and beanstalk.tf grants it.
    section = _section()
    eb = section[section.index("{{IF has_beanstalk}}"):section.index("{{IF has_fargate}}")]
    assert "`eb ssh {{EB_RUN_ENVIRONMENT}}`" not in eb
    assert "`eb ssh` as above" not in eb
    assert (
        "aws ssm start-session --target $(aws elasticbeanstalk describe-environment-resources"
        " --environment-name {{EB_RUN_ENVIRONMENT}} --query 'EnvironmentResources.Instances[0].Id'"
    ) in eb
    assert "`eb ssh` does not work here" in eb
    beanstalk = TERRAFORM[TERRAFORM.index('resource "aws_iam_role" "eb_instance_<app_name>"'):]
    beanstalk = beanstalk[: beanstalk.index("**Per-environment rules:**")]
    assert re.search(
        r'resource "aws_iam_role_policy_attachment" "eb_ssm_<app_name>" \{\s+'
        r"role\s+= aws_iam_role\.eb_instance_<app_name>\.name\s+"
        r'policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"',
        beanstalk,
    )


def test_config_rows_follow_the_backing_store() -> None:
    section = _section()
    assert "/{{app_name}}/KEY" not in section
    assert "{{app_name}}/DATABASE_URL" not in section
    for store in (
        "aws:elasticbeanstalk:application:environmentsecrets",
        "aws secretsmanager get-secret-value --secret-id <secret-arn>",
        "aws secretsmanager put-secret-value --secret-id <secret-arn>",
        "aws ssm get-parameter --name <parameter-name> --with-decryption",
        "aws ssm put-parameter --name <parameter-name>",
        "Namespace=aws:elasticbeanstalk:application:environment,OptionName=KEY",
        "containerDefinitions[0].[environment,secrets]",
    ):
        assert store in section, store


def test_config_set_splits_existing_key_from_new_key() -> None:
    # A new key is a silent no-op on both targets unless Terraform binds it: EB injects
    # only `environmentsecrets` names and its role reads only the project prefix; the
    # Fargate task definition has no secrets block and the execution role no SSM/Secrets
    # Manager read. Both tables say so and route the new key through the IAM-scoped prefix.
    section = _section()
    eb = section[section.index("{{IF has_beanstalk}}"):section.index("{{IF has_fargate}}")]
    fargate = section[section.index("{{IF has_fargate}}"):section.index(DEFERRED_GUARD)]
    for table in (eb, fargate):
        assert "`heroku config:set KEY=value -a {{app_name}}` (existing key)" in table
        assert "`heroku config:set NEW_KEY=value -a {{app_name}}` (new key)" in table
        assert "silent no-op" in table
        assert "aws ssm put-parameter --name /{{PROJECT_NAME}}/NEW_KEY" in table
        assert "aws secretsmanager create-secret --name {{PROJECT_NAME}}/NEW_KEY" in table
        assert "then `terraform apply`" in table
    assert "reads only `parameter/{{PROJECT_NAME}}/*` and `secret:{{PROJECT_NAME}}/*`" in eb
    assert "the generated task definition has no `secrets` block" in fargate
    assert "`AmazonECSTaskExecutionRolePolicy`, which grants no `ssm:GetParameters`" in fargate
    assert "grant `aws_iam_role.ecs_execution`" in fargate
    # The intro no longer implies ecs.tf emits a secrets[] list.
    assert "the generated task\ndefinition emits none" in section
    # The eb_read_secrets policy really is prefix-scoped (the reason for the split).
    assert (
        "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}"
        ":parameter/${var.project_name}/*"
    ) in TERRAFORM
    # And the Fargate task definition template really has no secrets block.
    task_def = TERRAFORM[TERRAFORM.index('resource "aws_ecs_task_definition"'):]
    task_def = task_def[: task_def.index("**Task definition rules:**")]
    assert "secrets" not in task_def


def test_eb_rows_use_the_application_name_and_basic_health() -> None:
    # aws_elastic_beanstalk_application.name is var.project_name, not the Heroku app
    # name; describe-environment-health needs enhanced health, which is not enabled.
    section = _section()
    eb = section[section.index("{{IF has_beanstalk}}"):section.index("{{IF has_fargate}}")]
    assert "--application-name {{app_name}}" not in eb
    assert eb.count("--application-name {{EB_APPLICATION}}") == 4
    assert "aws elasticbeanstalk describe-environment-health " not in eb
    assert (
        "aws elasticbeanstalk describe-environments --application-name {{EB_APPLICATION}}"
        " --query 'Environments[].[EnvironmentName,Status,Health]' --output table"
    ) in eb
    assert "| `{{EB_APPLICATION}}` | `name` of the generated `aws_elastic_beanstalk_application`" in DOCS


def test_scale_rows_warn_about_terraform_drift_and_writers_quiesced() -> None:
    section = _section()
    eb = section[section.index("{{IF has_beanstalk}}"):section.index("{{IF has_fargate}}")]
    fargate = section[section.index("{{IF has_fargate}}"):section.index(DEFERRED_GUARD)]
    assert "`terraform apply` reverts this" in eb and "`terraform apply` reverts this" in fargate
    assert "edit `eb_min_instances_*` / `eb_max_instances_*` in `terraform/terraform.tfvars`" in eb
    assert "edit `desired_count_*` in `terraform/terraform.tfvars`" in fargate
    for table in (eb, fargate):
        assert table.count("Never scale or restart while `writers_quiesced = true`") == 1
        assert table.count("(not while `writers_quiesced = true`)") == 1


def test_pg_psql_reads_the_generated_db_credentials_secret() -> None:
    section = _section()
    assert "TARGET_DB_PASSWORD" not in section
    assert "stored for `DATABASE_URL`" not in section
    assert section.count(
        "aws secretsmanager get-secret-value --secret-id {{DB_CREDENTIALS_SECRET}}"
        " --query SecretString --output text"
    ) == 2
    assert section.count(
        'PGPASSWORD=$(jq -r .password <<<"$creds") psql "postgres://$(jq -r .username <<<"$creds")@'
        "{{TARGET_DB_HOST}}:{{TARGET_DB_PORT}}/{{TARGET_DB_NAME}}?sslmode=verify-full"
    ) == 2
    assert (
        "| `{{DB_CREDENTIALS_SECRET}}` | `name` of the generated"
        " `aws_secretsmanager_secret.db_credentials` (`${var.project_name}-${var.environment}/db-credentials`"
    ) in DOCS
    assert 'name = "${var.project_name}-${var.environment}/db-credentials"' in TERRAFORM


def test_fargate_rollback_is_by_digest() -> None:
    section = _section()
    fargate = section[section.index("{{IF has_fargate}}"):section.index(DEFERRED_GUARD)]
    assert "previous image tag" not in fargate
    assert "[imageDigest,imageTags[0],imagePushedAt]" in fargate
    assert (
        "set each `container_image_<app>_<process_type>` in `terraform/terraform.tfvars` to"
        " `{{AWS_ACCOUNT_ID}}.dkr.ecr.{{target_region}}.amazonaws.com/{{app_name}}@<digest>`,"
        " then `terraform apply`"
    ) in fargate


def test_closing_paragraph_does_not_depend_on_another_report_section() -> None:
    section = _section()
    assert "Developer workflow" not in section
    assert "`heroku pipelines:promote` (not generated;" in section


def test_per_process_rows_and_web_only_guards() -> None:
    section = _section()
    eb = section[section.index("{{IF has_beanstalk}}"):section.index("{{IF has_fargate}}")]
    fargate = section[section.index("{{IF has_fargate}}"):section.index(DEFERRED_GUARD)]
    assert eb.count("{{FOR proc IN eb_processes}}") == 3
    assert fargate.count("{{FOR proc IN fargate_processes}}") == 3
    # No hardcoded web service/task family: the Fargate target may run only a worker.
    assert "{{ECS_CLUSTER}}-web" not in fargate
    assert "--container web" not in fargate
    for table, flag in ((eb, "app_has_eb_web"), (fargate, "app_has_fargate_web")):
        guarded = re.findall(r"\{\{IF " + flag + r"\}\}\n(.*?)\n\{\{ENDIF\}\}", table, re.DOTALL)
        assert len(guarded) == 2, (flag, guarded)
        assert any("maintenance:on" in g for g in guarded)
        assert any("heroku open" in g for g in guarded)
    assert "--services {{FARGATE_SERVICE_NAMES}}" in fargate
    assert "for env in {{EB_ENVIRONMENT_NAMES}}; do aws elasticbeanstalk restart-app-server" in eb


def test_backup_row_branches_rds_and_aurora_behind_has_postgres() -> None:
    section = _section()
    postgres_blocks = re.findall(
        r"\{\{IF has_postgres\}\}\n(.*?)\n\{\{ENDIF\}\}", section, re.DOTALL
    )
    assert len(postgres_blocks) == 2
    for block in postgres_blocks:
        assert "pg:psql" in block and "pg:backups:capture" in block
        assert '{{IF postgres_engine == "aurora"}}' in block
        assert (
            "aws rds create-db-cluster-snapshot --db-cluster-identifier {{DB_CLUSTER_IDENTIFIER}}"
            " --db-cluster-snapshot-identifier" in block
        )
        assert "aws rds create-db-snapshot --db-instance-identifier {{DB_INSTANCE_IDENTIFIER}}" in block
    # No database command leaks outside the guards.
    unguarded = re.sub(r"\{\{IF has_postgres\}\}.*?\{\{ENDIF\}\}", "", section, flags=re.DOTALL)
    assert "aws rds " not in unguarded
    assert "psql " not in unguarded


def test_open_row_uses_configured_protocol_and_hostname() -> None:
    section = _section()
    assert "open https://{{EB_ENVIRONMENT_URL}}" not in section
    assert "open https://{{ALB_DNS_NAME}}" not in section
    assert "{{IF has_route53_dns}}`open https://{{app_domain}}`" in section
    assert "{{ELSE}}`open http://{{EB_ENVIRONMENT_URL}}`" in section
    assert "`open https://{{app_domain}}` — the ALB certificate" in section


def test_step0_and_variable_table_define_the_new_inputs() -> None:
    for token in (
        "- `eb_processes[]`",
        "- `fargate_processes[]`",
        "- `postgres_engine`",
        "| `{{EB_RUN_ENVIRONMENT}}` |",
        "| `{{FARGATE_SERVICE_NAMES}}` |",
        "| `{{FARGATE_RUN_SERVICE}}` / `{{FARGATE_RUN_PROCESS}}` |",
        "| `{{DB_INSTANCE_IDENTIFIER}}` |",
        "| `{{DB_CLUSTER_IDENTIFIER}}` |",
        "| `{{PROJECT_NAME}}` |",
        "| `{{EB_APPLICATION}}` |",
        "| `{{DB_CREDENTIALS_SECRET}}` |",
        '- "Day-to-day commands: Heroku → AWS" is ALWAYS rendered',
    ):
        assert token in DOCS, token
    assert "EB_WEB_ENVIRONMENT" not in DOCS
