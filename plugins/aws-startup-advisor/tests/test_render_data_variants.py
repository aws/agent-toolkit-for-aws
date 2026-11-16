from __future__ import annotations

import json
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


def _generate_fragment(fragment_id: str) -> dict:
    # The same loader the phase-contract tests use, so the trigger is read as the interpreter reads it.
    from test_render_phase_contracts import phase
    entries = [item for item in phase("generate")["_fragments"] if item["_id"] == fragment_id]
    assert len(entries) == 1, fragment_id
    return entries[0]


def test_data_fragment_loads_only_when_a_data_row_exists() -> None:
    # 16 KB of guidance for data.tf must not load for a static site or a worker-only design. The trigger names
    # every row type the fragment handles, so a design with a database or cache still gets the guidance.
    fragment = _generate_fragment("infra-data")
    assert "_always" not in fragment["_trigger"]
    condition = fragment["_trigger"]["_when"]
    assert "render.postgres" in condition and "render.key_value" in condition
    # The trigger may only name what aws-design.json records. A mapping has render_kind and disposition and no
    # file field (additionalProperties is false), so a trigger on "maps to terraform/data.tf" is never true.
    schema = json.loads((SKILL_ROOT / "references/shared/schema-render-aws-design.json").read_text(encoding="utf-8"))
    mapping = schema["$defs"]["mapping"]
    assert mapping["additionalProperties"] is False
    assert {"render_kind", "disposition"} <= set(mapping["properties"])
    assert "mapped" in mapping["properties"]["disposition"]["enum"]
    assert "terraform/" not in condition and ".tf" not in condition
    assert "disposition mapped" in condition
    guidance = FRAGMENT.read_text(encoding="utf-8")
    assert "`render.postgres` and `render.key_value` rows" in guidance
    # the assembler lists the same condition, so its read list does not claim an always-present contribution
    assemble = (SKILL_ROOT / "references/phases/generate/generate-assemble.md").read_text(encoding="utf-8")
    assert "infra-data (fragment contribution, when aws-design.json has a render.postgres or render.key_value mapping with disposition mapped)" in assemble
    # always-loaded fragments still carry the data.tf routing, so a data design is never left without a pointer
    infra = (SKILL_ROOT / "references/phases/generate/generate-artifacts-infra.md").read_text(encoding="utf-8")
    assert "generate-infra-data.md" in infra


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


def _resource_block(text: str, header: str) -> str:
    start = text.index(header)
    depth = 0
    for index in range(text.index("{", start), len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            return text[start:index + 1]
    raise AssertionError(header)


def test_aurora_engine_version_ignores_minor_upgrade_drift() -> None:
    # The cluster pins a version and allows automatic minor upgrades. Without ignore_changes the next plan after an
    # upgrade proposes a downgrade, which RDS rejects. The cluster and EVERY instance must carry the rule: a bare
    # substring count would still pass with one of them removed, so each resource's own block is checked.
    tf = _text("data-aurora-postgres")
    for header in ('resource "aws_rds_cluster" "postgres"', 'resource "aws_rds_cluster_instance" "postgres"'):
        block = _resource_block(tf, header)
        assert re.search(r"lifecycle\s*\{[^{}]*ignore_changes\s*=\s*\[[^\]]*engine_version[^\]]*\]", block), header
    # the same rule is stated in the fragment, both as guidance and as an anti-pattern
    guidance = FRAGMENT.read_text(encoding="utf-8")
    assert guidance.count("ignore_changes = [engine_version]") >= 2
    # removing either block must be detected by this module
    for header in ('resource "aws_rds_cluster" "postgres"', 'resource "aws_rds_cluster_instance" "postgres"'):
        block = _resource_block(tf, header)
        stripped = tf.replace(block, re.sub(r"lifecycle\s*\{[^{}]*\}", "", block))
        assert stripped != tf
        assert not re.search(
            r"lifecycle\s*\{[^{}]*ignore_changes\s*=\s*\[[^\]]*engine_version[^\]]*\]",
            _resource_block(stripped, header),
        ), header


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


DATA_SELECTORS = SKILL_ROOT / "references/design-refs/data.md"
# nearest heading in the fragment -> (selector section in data.md, words the cited rule must contain)
CITED_RULES = {
    "Amazon RDS for PostgreSQL (`aws_db_instance`)": ("PostgreSQL target", "Select RDS for a conventional"),
    "Amazon Aurora PostgreSQL (`aws_rds_cluster` and `aws_rds_cluster_instance`)": ("PostgreSQL target", "Aurora-specific"),
    "ElastiCache for Valkey Serverless (`aws_elasticache_serverless_cache`)": ("Key Value target", "ElastiCache Serverless"),
}


def _selector_rules(section: str) -> dict[int, str]:
    text = DATA_SELECTORS.read_text(encoding="utf-8")
    body = text.split(f"## {section}", 1)[1].split("\n## ", 1)[0]
    return {int(m.group(1)): m.group(2) for m in re.finditer(r"^(\d+)\. (.+)$", body, re.MULTILINE)}


def test_selector_rule_numbers_cited_by_the_data_fragment_have_the_cited_meaning() -> None:
    heading = ""
    cited = 0
    for line in FRAGMENT.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        for number in (int(n) for n in re.findall(r"\brule (\d+)\b", line)):
            cited += 1
            assert heading in CITED_RULES, f"rule {number} cited under unmapped heading {heading!r}"
            section, words = CITED_RULES[heading]
            assert words in _selector_rules(section).get(number, ""), f"rule {number} under {heading!r}"
    assert cited >= 3
    # the RDS startup default is cited by name, because its number moves when the selector gains rules
    startup = [rule for rule in _selector_rules("PostgreSQL target").values() if "lower-change startup default" in rule]
    assert startup and "select RDS" in startup[0]
    assert "RDS startup default" in FRAGMENT.read_text(encoding="utf-8")
    assert not re.search(r"rule 3 or 6", FRAGMENT.read_text(encoding="utf-8"))


def test_data_tier_uses_the_single_stack_key_from_kms_tf() -> None:
    guidance = FRAGMENT.read_text(encoding="utf-8")
    baseline = (SKILL_ROOT / "references/phases/generate/generate-artifacts-baseline.md").read_text(encoding="utf-8")
    kms_section = baseline.split("## kms.tf (gated)", 1)[1].split("\n## ", 1)[0]
    assert "`aws_kms_key.stack`" in kms_section and "`kms_key_arn`" in kms_section
    assert "aws_kms_key.stack" in guidance and "`kms_key_arn`" in guidance
    assert "aws_kms_key.data" in guidance and "never an `aws_kms_key.data`" in guidance
    for name in VARIANT_NAMES:
        files = {path.name: path.read_text(encoding="utf-8") for path in _terraform(name).glob("*.tf")}
        assert files["kms.tf"].count('resource "aws_kms_key" "stack"') == 1
        assert 'output "kms_key_arn"' in files["kms.tf"]
        assert "aws_kms_key.data" not in "".join(files.values())
        assert "aws_kms_key" not in files["data.tf"].replace("aws_kms_key.stack", "")
    golden = (SKILL_ROOT / "fixtures/expected/generated/terraform").glob("*.tf")
    golden_text = {path.name: path.read_text(encoding="utf-8") for path in golden}
    assert "kms.tf" not in golden_text
    assert "kms_key" not in golden_text["data.tf"] and "aws_kms" not in golden_text["data.tf"]


def test_data_security_group_is_declared_once_in_network_and_referenced_by_data() -> None:
    fragment = (SKILL_ROOT / "references/phases/generate/generate-artifacts-infra-network-storage-delivery.md").read_text(encoding="utf-8")
    line = next(item for item in fragment.splitlines() if item.startswith("- Security groups, one per tier"))
    assert "`network.tf` also declares `aws_security_group.data`" in line and "`data.tf` references it" in line
    assert "The data tier is owned by the data fragment" not in fragment
    terraform = SKILL_ROOT / "fixtures/expected/generated/terraform"
    assert (terraform / "network.tf").read_text(encoding="utf-8").count('resource "aws_security_group" "data"') == 1
    assert 'resource "aws_security_group" "data"' not in (terraform / "data.tf").read_text(encoding="utf-8")


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
