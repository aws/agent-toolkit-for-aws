from __future__ import annotations

import importlib.util
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
    assert {path.name for path in VARIANTS.iterdir()} == set(EXPECTED_FILES)
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
    assert "ecs_mode" not in text
    assert "Express" not in text
