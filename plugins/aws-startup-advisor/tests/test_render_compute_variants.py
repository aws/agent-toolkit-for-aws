from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "plugins/aws-startup-advisor/skills/render-to-aws"
VARIANTS = SKILL_ROOT / "fixtures/expected/generated-variants"
GENERATE = SKILL_ROOT / "references/phases/generate"
EB = VARIANTS / "compute-elastic-beanstalk/terraform"
LAMBDA = VARIANTS / "compute-lambda-cron/terraform"
EXPECTED_FILES = {
    "compute-elastic-beanstalk": {".gitignore", "main.tf", "variables.tf", "outputs.tf", "network.tf", "compute.tf"},
    "compute-lambda-cron": {".gitignore", "main.tf", "variables.tf", "outputs.tf", "compute.tf"},
}
EB_RETENTION_VALUES = {1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653}


def _load_script_module(path: Path, name: str):
    script_parent = str(path.parent)
    if script_parent not in sys.path:
        sys.path.insert(0, script_parent)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    parsed = yaml.safe_load(text[4 : text.index("\n---\n", 4)])
    assert isinstance(parsed, dict), path
    return parsed


def test_compute_variant_set_is_exactly_the_reviewed_set() -> None:
    # Other domains keep their own variants beside these; this test owns only the compute-* set.
    assert {path.name for path in VARIANTS.iterdir() if path.name.startswith("compute-")} == set(EXPECTED_FILES)
    for name, files in EXPECTED_FILES.items():
        terraform = VARIANTS / name / "terraform"
        assert {path.name for path in terraform.iterdir()} == files
        assert not [path for path in (VARIANTS / name).rglob("*") if path.suffix in {".md", ".json"}]


@pytest.mark.parametrize("variant", sorted(EXPECTED_FILES))
def test_compute_variant_passes_fmt_init_validate_and_policy(variant: str, tmp_path: Path) -> None:
    harness = _load_script_module(
        Path(__file__).with_name("render_pipeline_harness.py"), f"render_pipeline_harness_{variant.replace('-', '_')}"
    )
    result = harness.validate_terraform_directory(VARIANTS / variant / "terraform", tmp_path / variant)
    assert result["fmt"] == "passed"
    assert result["policy"] == "POLICY_OK"
    assert result["init"] in {"passed", "provider_registry_unavailable"}


def test_elastic_beanstalk_variant_follows_the_compute_guidance() -> None:
    compute = (EB / "compute.tf").read_text(encoding="utf-8")
    assert 'data "aws_elastic_beanstalk_solution_stack"' in compute
    assert "most_recent = true" in compute
    assert not re.search(r"solution_stack_name\s*=\s*\"", compute)
    for term in (
        "IamInstanceProfile",
        "HealthCheckPath",
        "StreamLogs",
        "environmentsecrets",
        "AssociatePublicIpAddress",
        "SSLCertificateArns",
        "DeploymentPolicy",
    ):
        assert term in compute, term
    assert re.search(r'"aws:elbv2:listener:443"\s*\n\s*name\s*=\s*"Protocol"\s*\n\s*value\s*=\s*"HTTPS"', compute)
    assert re.search(r'"aws:elbv2:listener:default"\s*\n\s*name\s*=\s*"ListenerEnabled"\s*\n\s*value\s*=\s*"false"', compute)
    fragment = (GENERATE / "generate-infra-compute.md").read_text(encoding="utf-8")
    assert 'Protocol = "HTTPS"' in fragment
    assert "aws:elbv2:listener:default" in fragment and 'ListenerEnabled = "false"' in fragment
    retention = re.search(r'"RetentionInDays"\s*\n\s*value\s*=\s*"(\d+)"', compute)
    assert retention and int(retention.group(1)) in EB_RETENTION_VALUES
    min_size = re.search(r'"MinSize"\s*\n\s*value\s*=\s*"(\d+)"', compute)
    assert min_size and int(min_size.group(1)) >= 1
    assert "data.aws_partition.current.partition" in compute
    assert "arn:aws:iam::aws:policy" not in compute
    assert 'Resource = "*"' not in compute


def test_lambda_cron_variant_follows_the_compute_guidance() -> None:
    compute = (LAMBDA / "compute.tf").read_text(encoding="utf-8")
    log_group = compute.split('resource "aws_cloudwatch_log_group" "cron"', 1)[1].split("\n}\n", 1)[0]
    assert re.search(r"retention_in_days\s*=\s*\d+", log_group)
    for term in (
        "schedule_expression_timezone",
        "retry_policy",
        "reserved_concurrent_executions",
        "dead_letter_config",
        "scheduler.amazonaws.com",
        "lambda.amazonaws.com",
    ):
        assert term in compute, term
    assert re.search(
        r'Action\s*=\s*\["lambda:InvokeFunction"\]\s*\n\s*Resource\s*=\s*\[aws_lambda_function\.cron\.arn\]', compute
    )
    assert not re.search(r'Resource\s*=\s*"\*"', compute)


def test_compute_fragment_is_registered_and_covers_every_compute_target() -> None:
    generate = _frontmatter(GENERATE / "generate.md")
    entries = [entry for entry in generate["_fragments"] if entry["_id"] == "infra-compute"]
    assert len(entries) == 1
    assert entries[0]["_file"] == "phases/generate/generate-infra-compute.md"
    fragment_path = GENERATE / "generate-infra-compute.md"
    fragment = _frontmatter(fragment_path)
    assert fragment["_fragment"] == "infra-compute"
    assert fragment["_of_phase"] == "generate"
    assert (GENERATE / "generate-artifacts-infra.md").read_text(encoding="utf-8").count("generate-infra-compute.md") == 1
    text = fragment_path.read_text(encoding="utf-8")
    for term in (
        "Elastic Beanstalk",
        "Elastic Beanstalk Cluster Mode",
        "Amazon EKS",
        "AWS Lambda",
        "AWS Batch",
        "EventBridge Scheduler",
        "iam:PassRole",
        "iam:PassedToService",
        "execution role",
        "task role",
        "retention_in_days",
        "stopTimeout",
        "mount target",
    ):
        assert term in text, term
    assert "`aws_config.ecs_mode`" in text and "aws_ecs_express_gateway_service" in text


def test_assembler_reads_the_compute_fragment_and_one_fragment_writes_compute_tf() -> None:
    assemble = _frontmatter(GENERATE / "generate-assemble.md")
    reads = [str(entry) for entry in assemble["_reads"]]
    compute_reads = [entry for entry in reads if entry.startswith("infra-compute")]
    assert len(compute_reads) == 1
    assert "terraform/compute.tf" in compute_reads[0]
    writers = [
        path.name
        for path in sorted(GENERATE.glob("generate-*.md"))
        if "terraform/compute.tf" in (_frontmatter(path).get("_contributes") or [])
    ]
    assert writers == ["generate-infra-compute.md"]
    assert "only writer of `terraform/compute.tf`" in (GENERATE / "generate-infra-compute.md").read_text(encoding="utf-8")


def test_representative_design_is_covered_by_the_documented_sizing_fallbacks() -> None:
    design = json.loads((SKILL_ROOT / "fixtures/expected/aws-design.json").read_text(encoding="utf-8"))
    fragment = (GENERATE / "generate-infra-compute.md").read_text(encoding="utf-8")
    golden = (SKILL_ROOT / "fixtures/expected/generated/terraform/compute.tf").read_text(encoding="utf-8")
    assert "Fallbacks when `aws_config` omits a field" in fragment
    assert "`cpu = 512`, `memory = 1024`" in fragment
    for row in design["mappings"]:
        if not row["aws_service"].startswith(("ECS on Fargate", "Amazon EventBridge Scheduler + ECS")):
            continue
        name = row["source_resource_id"].removeprefix("rr-")
        task = golden.split(f'resource "aws_ecs_task_definition" "{name}"', 1)[1].split("\n}\n", 1)[0]
        config = row["aws_config"]
        cpu, memory = (int(config["vcpu"] * 1024), int(config["memory_gb"] * 1024)) if "vcpu" in config else (512, 1024)
        assert f"cpu                      = {cpu}" in task, name
        assert f"memory                   = {memory}" in task, name
        service = golden.split(f'resource "aws_ecs_service" "{name}"', 1)
        if len(service) == 2:
            assert f"desired_count   = {config.get('desired_count', 1)}" in service[1].split("\n}\n", 1)[0], name


def test_golden_compute_follows_the_mandatory_fragment_rules() -> None:
    golden = (SKILL_ROOT / "fixtures/expected/generated/terraform/compute.tf").read_text(encoding="utf-8")
    assert "arn:aws:iam::aws:policy" not in golden
    assert "data.aws_partition.current.partition" in golden
    assert 'data "aws_partition" "current"' not in golden
    main = (SKILL_ROOT / "fixtures/expected/generated/terraform/main.tf").read_text(encoding="utf-8")
    assert main.count('data "aws_partition" "current"') == 1
    fragment = (GENERATE / "generate-infra-compute.md").read_text(encoding="utf-8")
    assert "shared application log group" in fragment
    assert "When an ALB target group checks the path, omit the container `healthCheck`." in fragment
    assert golden.count("task_role_arn") == golden.count('resource "aws_ecs_task_definition"') == 4
    for name in ("web", "private", "worker"):
        service = golden.split(f'resource "aws_ecs_service" "{name}"', 1)[1].split("\n}\n", 1)[0]
        assert "deployment_circuit_breaker" in service and "rollback = true" in service, name
    web = golden.split('resource "aws_ecs_service" "web"', 1)[1].split("\n}\n", 1)[0]
    assert "health_check_grace_period_seconds" in web
    assert re.search(r'ArnLike\s*=\s*\{\s*"ecs:cluster"', golden)
    assert golden.count("awslogs-group") == 4

GENERATE_REFS = SKILL_ROOT / "references/phases/generate"
def test_compute_fragment_pins_shared_addresses_and_cloud_map_ownership() -> None:
    fragment = (GENERATE_REFS / "generate-infra-compute.md").read_text(encoding="utf-8")
    for address in ("aws_ecs_cluster.main", "aws_iam_role.ecs_execution", "aws_iam_role.ecs_task"):
        assert f"`{address}`" in fragment, address
    assert "Do not declare the Cloud Map namespace or `aws_service_discovery_service` here" in fragment
    assert "`service_discovery_service_arn`" in fragment
    assert "Register a Cloud Map service" not in fragment
    assert "`observability.log_retention`" in fragment
    assert "`aws_kms_key.stack`" in fragment and "kms:Decrypt" in fragment
    assert "lifecycle { ignore_changes = [desired_count] }" in fragment
    golden = SKILL_ROOT / "fixtures/expected/generated/terraform"
    compute = (golden / "compute.tf").read_text(encoding="utf-8")
    network = (golden / "network.tf").read_text(encoding="utf-8")
    assert "aws_service_discovery_service" not in compute.replace("aws_service_discovery_service.private.arn", "")
    assert network.count('resource "aws_service_discovery_service"') == 1
    assert 'output "service_discovery_service_arn"' in (golden / "outputs.tf").read_text(encoding="utf-8")
def test_compute_trigger_includes_workflow_ecs_rows_in_both_fragment_lists() -> None:
    generate = (GENERATE_REFS / "generate.md").read_text(encoding="utf-8")
    assemble = (GENERATE_REFS / "generate-assemble.md").read_text(encoding="utf-8")
    assert "maps a Workflow task row to ECS" in generate
    assert "maps a Workflow task row to ECS" in assemble
def test_baseline_leaves_autoscaling_lifecycle_to_compute_and_covers_per_target_alarms() -> None:
    baseline = (GENERATE_REFS / "generate-artifacts-baseline.md").read_text(encoding="utf-8")
    assert "this file never edits `compute.tf`" in baseline
    for resource in ("aws_ecs_express_gateway_service", "aws_rds_cluster", "aws_elasticache_serverless_cache"):
        assert resource in baseline, resource
