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
        '- "Day-to-day commands: Heroku → AWS" is ALWAYS rendered',
    ):
        assert token in DOCS, token
    assert "EB_WEB_ENVIRONMENT" not in DOCS
