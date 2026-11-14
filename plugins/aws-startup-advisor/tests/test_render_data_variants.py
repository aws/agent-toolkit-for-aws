from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from render_pipeline_harness import (  # noqa: E402
    REPO_ROOT,
    SKILL_ROOT,
    _run,
    classify_terraform_init_failure,
)

VARIANTS = SKILL_ROOT / "fixtures/expected/generated-variants"
POLICY = REPO_ROOT / "plugins/aws-startup-advisor/skills/tf-best-practices/scripts/validate-terraform-policy.py"
FRAGMENT = SKILL_ROOT / "references/phases/generate/generate-infra-data.md"
VARIANT_NAMES = ["data-aurora-postgres", "data-valkey-serverless"]
FORBIDDEN_CREDENTIAL = re.compile(r'^\s*(?:variable\s+"(?:\w*password\w*|auth_token)"|(?:master_)?password\s*=|auth_token\s*=)', re.MULTILINE)


def _terraform(name: str) -> Path:
    return VARIANTS / name / "terraform"


def _text(name: str) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(_terraform(name).glob("*.tf")))


def test_data_fragment_is_registered_and_routed() -> None:
    phase = (SKILL_ROOT / "references/phases/generate/generate.md").read_text(encoding="utf-8")
    assert "phases/generate/generate-infra-data.md" in phase
    infra = (SKILL_ROOT / "references/phases/generate/generate-artifacts-infra.md").read_text(encoding="utf-8")
    assert "generate-infra-data.md" in infra
    guidance = FRAGMENT.read_text(encoding="utf-8")
    for required in (
        "rds.logical_replication", "manage_master_user_password", "aws_rds_cluster",
        "aws_elasticache_serverless_cache", "aws_memorydb_cluster", "deletion_protection",
        "max_allocated_storage", "performance_insights_enabled", "snapshot_retention_limit",
        "## Anti-patterns", "## Ordering",
    ):
        assert required in guidance


@pytest.mark.parametrize("name", VARIANT_NAMES)
def test_variant_has_no_credential_input(name: str) -> None:
    assert not FORBIDDEN_CREDENTIAL.search(_text(name))


def test_aurora_variant_follows_guidance() -> None:
    tf = _text("data-aurora-postgres")
    assert 'resource "aws_rds_cluster" "postgres"' in tf
    assert 'resource "aws_rds_cluster_instance" "postgres"' in tf
    assert "aws_db_instance" not in tf
    for expected in (
        'engine                              = "aurora-postgresql"',
        "manage_master_user_password         = true",
        "storage_encrypted                   = true",
        "deletion_protection                 = true",
        "skip_final_snapshot                 = false",
        "performance_insights_enabled    = true",
        "publicly_accessible             = false",
    ):
        assert expected in tf
    logical = re.search(r'name\s*=\s*"rds\.logical_replication"\s*value\s*=\s*"1"\s*apply_method\s*=\s*"pending-reboot"', tf)
    assert logical
    assert "allocated_storage" not in tf
    assert "master_user_secret[0].secret_arn" in tf


def test_valkey_serverless_variant_follows_guidance() -> None:
    tf = _text("data-valkey-serverless")
    assert 'resource "aws_elasticache_serverless_cache" "valkey"' in tf
    assert "aws_elasticache_replication_group" not in tf
    assert 'engine                   = "valkey"' in tf
    assert "cache_usage_limits" in tf and "ecpu_per_second" in tf
    assert 'type = "iam"' in tf
    assert "kms_key_id" in tf and "snapshot_retention_limit" in tf
    assert 'engine = "redis"' not in tf
    assert "cidr_blocks" not in tf


@pytest.fixture(scope="module", autouse=True)
def _shared_provider_cache(tmp_path_factory: pytest.TempPathFactory):
    """Download the AWS provider once for both variants unless the caller already set a cache."""
    if os.environ.get("TF_PLUGIN_CACHE_DIR"):
        yield
        return
    cache = tmp_path_factory.mktemp("tf-plugin-cache")
    os.environ["TF_PLUGIN_CACHE_DIR"] = str(cache)
    try:
        yield
    finally:
        os.environ.pop("TF_PLUGIN_CACHE_DIR", None)


@pytest.mark.parametrize("name", VARIANT_NAMES)
def test_variant_passes_terraform_and_policy(name: str, tmp_path: Path) -> None:
    terraform_binary = shutil.which("terraform")
    if terraform_binary is None:
        pytest.fail("terraform is required to validate golden variants")
    work = tmp_path / name
    shutil.copytree(_terraform(name), work)
    fmt = _run([terraform_binary, "fmt", "-check", "-recursive", str(work)], tmp_path)
    assert fmt.returncode == 0, fmt.stdout + fmt.stderr
    init = _run([terraform_binary, "init", "-backend=false", "-input=false"], work)
    if init.returncode != 0:
        if classify_terraform_init_failure(init.stdout + init.stderr) == "provider_registry_unavailable":
            pytest.skip("provider registry unavailable")
        raise AssertionError(init.stdout + init.stderr)
    validate = _run([terraform_binary, "validate"], work)
    assert validate.returncode == 0, validate.stdout + validate.stderr
    policy = _run([sys.executable, str(POLICY), str(work)], tmp_path)
    assert policy.returncode == 0 and policy.stdout.startswith("POLICY_OK"), policy.stdout + policy.stderr
