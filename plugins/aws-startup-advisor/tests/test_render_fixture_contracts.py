from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
from html import escape
import subprocess  # nosec B404 - fixed local validation tools, no shell
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "plugins/aws-startup-advisor/skills/render-to-aws"
EXPECTED = SKILL_ROOT / "fixtures/expected"


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def assert_contiguous_ordinals(rows: list[dict]) -> None:
    assert [row["ordinal"] for row in rows] == list(range(1, len(rows) + 1))


def test_clarify_preferences_are_complete_schema_valid_and_deterministic() -> None:
    preferences = load(EXPECTED / "preferences.json")
    schema = load(SKILL_ROOT / "references/shared/schema-render-preferences.json")
    jsonschema.Draft202012Validator(schema).validate(preferences)
    questions = preferences["questions"]
    assert questions == sorted(
        questions,
        key=lambda row: ((row["resource_id"] or "").encode(), row["question_id"].encode()),
    )
    assert len({(row["resource_id"], row["question_id"]) for row in questions}) == len(questions)
    assert {row["disposition"] for row in questions} <= {"answered", "defaulted", "not_applicable"}
    for row in questions:
        assert row["decision_changed"] and row["consequence"]
        if row["disposition"] == "defaulted":
            assert row["provenance"] == "default" and row["default_rule"]
    clarify = (SKILL_ROOT / "references/phases/clarify/clarify-assemble.md").read_text()
    assert "zero `unresolved` rows" in clarify
    assert "Do not create a preference row merely to ask the user to select an AWS product" in clarify


def test_design_selectors_emit_one_target_all_rejections_and_exact_accounting() -> None:
    design = load(EXPECTED / "aws-design.json")
    schema = load(SKILL_ROOT / "references/shared/schema-render-aws-design.json")
    jsonschema.Draft202012Validator(schema).validate(design)
    mappings = design["mappings"]
    source_ids = [row["source_resource_id"] for row in mappings]
    assert source_ids == sorted(source_ids, key=str.encode)
    assert len(source_ids) == len(set(source_ids))
    accounting = design["accounting"]
    assert accounting["inventory_resource_count"] == accounting["mapped_resource_count"] == len(mappings)
    assert accounting["accounted_resource_ids"] == source_ids

    for mapping in mappings:
        assert mapping["aws_service"] and " or " not in mapping["aws_service"].lower()
        decision = mapping["decision"]
        assert mapping["aws_service"] in decision["candidate_set"]
        rejected = [row["aws_service"] for row in decision["rejected_candidates"]]
        assert len(rejected) == len(set(rejected))
        assert set(rejected) == set(decision["candidate_set"]) - {mapping["aws_service"]}
        for key in ("evidence", "rules_evaluated", "rules_fired", "questions_asked", "defaults_used", "rejected_candidates"):
            assert_contiguous_ordinals(decision[key])
        assert all(row["reason"].strip() for row in decision["rejected_candidates"])

    by_kind = {row["render_kind"]: row for row in mappings}
    assert by_kind["render.postgres"]["aws_service"] == "Amazon RDS for PostgreSQL"
    assert by_kind["render.persistent_disk"]["aws_service"] == "Amazon EFS"
    assert by_kind["render.workflow"]["aws_service"] == "AWS Step Functions Standard"
    assert by_kind["render.workflow_task"]["aws_service"] == "AWS Lambda"
    assert by_kind["render.background_worker"]["aws_service"] == "ECS on Fargate service"
    assert by_kind["render.cron_job"]["aws_service"] == "Amazon EventBridge Scheduler + ECS on Fargate RunTask"
    assert by_kind["render.static_site"]["aws_service"] == "Amazon S3 + Amazon CloudFront"
    assert by_kind["render.build_source"]["aws_config"]["build_once"] is True
    private = by_kind["render.private_service"]
    assert private["aws_config"] == {
        "ingress": "AWS Cloud Map or ECS Service Connect",
        "public_load_balancer": False,
    }
    assert "Amazon CloudWatch Logs, Metrics, and Alarms" == by_kind["render.web_service"]["aws_config"]["observability"]
    assert "App Runner" not in json.dumps(design)


def test_selector_missing_decisive_inputs_return_to_clarify() -> None:
    cases = load(EXPECTED / "selector-negative-cases.json")["cases"]
    assert {case["selector"] for case in cases} >= {
        "data.postgresql", "storage.persistent_disk", "workflow.orchestrator",
        "workflow.task", "compute.worker", "compute.cron", "ai.execution",
    }
    for case in cases:
        if case["selector"] == "ai.execution":
            assert case["expected"] == "deferred_shared_ai_engine"
            assert set(case["forbidden_fields"]) == {"aws_service", "model", "price", "adapter", "terraform"}
        else:
            assert case["expected"] == "clarify_required"
            assert case["missing"] and " or " in case["forbidden_output"].lower()


def test_ai_track_is_exact_deferral_without_fabricated_output() -> None:
    design = load(EXPECTED / "aws-design.json")
    track = design["ai_track"]
    assert track == {
        "status": "deferred_shared_ai_engine",
        "profile_path": "ai-workload-profile.json",
        "profile_digest": "sha256:" + "b" * 64,
        "reason": "provider-neutral AI Design, Estimate, and Generate execution is not available",
        "resume_from": "ai-workload-profile.json",
        "infrastructure_status": "completed",
    }
    forbidden = {"aws_service", "model", "pricing", "price", "adapter", "terraform"}
    assert not (set(track) & forbidden)
    estimate = load(EXPECTED / "estimation-infra.json")
    assert estimate["ai_track"] == {"status": "deferred_shared_ai_engine", "estimated_cost": None}


def test_pricing_cache_has_dated_freshness_dimensions_and_current_plans() -> None:
    cache = load(SKILL_ROOT / "knowledge/estimate/render-pricing-cache.json")
    assert cache["as_of"] == "2026-10-21"
    assert cache["max_age_days"] == 90
    assert cache["source_url"].startswith("https://render.com/")
    assert cache["source_digest"].startswith("sha256:") and len(cache["source_digest"]) == 71
    expiry = date.fromisoformat(cache["as_of"]) + timedelta(days=cache["max_age_days"])
    assert date(2027, 1, 20) > expiry  # A stale cache must become unavailable.

    key_value = cache["key_value"]
    assert key_value["plans"]["3g"] == {"ram_gb": 3, "monthly_usd": 60}
    assert key_value["plans"]["50g"] == {"ram_gb": 50, "monthly_usd": 750}
    assert key_value["legacy_aliases"]["pro_ultra"] == "40g"
    assert cache["service_compute"]["plans"]["4c-16gb"]["cpu"] == 4
    assert cache["service_compute"]["plans"]["4c-16gb"]["ram_gb"] == 16

    workflow = cache["workflow"]
    assert workflow["flex"]["cpu_hour_usd"] == 0.2
    assert workflow["flex"]["ram_gb_hour_usd"] == 0.05
    assert workflow["state_retention"] == {
        "retention_days": 30,
        "per_gb_month_usd": 0.25,
        "bill_once_per_task_run": True,
    }
    assert workflow["fixed_plans"]["2c-8g"]["hourly_usd"] == 0.7
    assert Decimal("1") * Decimal("0.20") + Decimal("1") * Decimal("0.05") + Decimal("1") * Decimal("0.25") == Decimal("0.50")


def test_plan_alias_table_covers_schema_enums_and_matches_knowledge_rows() -> None:
    scripts_dir = SKILL_ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from render_common.plans import normalize_plan  # noqa: PLC0415

    table = load(SKILL_ROOT / "references/shared/render-plan-aliases.json")
    schema = load(SKILL_ROOT / "references/render/render-yaml.schema.json")
    definitions = schema["definitions"]
    cache = load(SKILL_ROOT / "knowledge/estimate/render-pricing-cache.json")
    fargate = load(SKILL_ROOT / "knowledge/design/service-plan-fargate-sizing.json")
    beanstalk = load(SKILL_ROOT / "knowledge/design/service-plan-eb-sizing.json")
    elasticache = load(SKILL_ROOT / "knowledge/design/keyvalue-elasticache-sizing.json")

    # Every published Blueprint spelling either resolves to a canonical id or is explicitly unpriced.
    for surface, enum_names in (("service_compute", ("serverPlan", "cronPlan")), ("key_value", ("keyValuePlan",))):
        entry = table["surfaces"][surface]
        for enum_name in enum_names:
            for spelling in definitions[enum_name]["enum"]:
                resolved = normalize_plan(surface, spelling)
                if resolved is None:
                    assert spelling in entry["unpriced"], (surface, spelling)
                else:
                    assert resolved in entry["canonical"], (surface, spelling, resolved)
                    assert spelling not in entry["unpriced"]

    # Design/Estimate rows key by the canonical ids; the legacy alias maps are the shared table's.
    compute_aliases = table["surfaces"]["service_compute"]["aliases"]
    for knowledge in (cache["service_compute"], fargate, beanstalk):
        assert all(compute_aliases[alias] == target for alias, target in knowledge["legacy_aliases"].items())
    for knowledge in (fargate, beanstalk):
        assert set(table["surfaces"]["service_compute"]["canonical"]) == set(knowledge["source_plans"])
    assert set(cache["service_compute"]["plans"]) <= set(table["surfaces"]["service_compute"]["canonical"])
    key_value_aliases = table["surfaces"]["key_value"]["aliases"]
    for knowledge in (cache["key_value"], elasticache):
        assert knowledge["legacy_aliases"] == key_value_aliases
    assert set(table["surfaces"]["key_value"]["canonical"]) == set(cache["key_value"]["plans"]) == set(elasticache["source_memory_gb"])
    assert cache["workflow"]["legacy_aliases"] == table["surfaces"]["workflow"]["aliases"]
    assert set(table["surfaces"]["workflow"]["canonical"]) == {"flex", *cache["workflow"]["fixed_plans"]}
    for knowledge in (cache, fargate, beanstalk, elasticache):
        assert knowledge["alias_table"] == "references/shared/render-plan-aliases.json"
        assert (SKILL_ROOT / knowledge["alias_table"]).is_file()

    # Never borrow a nearby plan: an unpriced spelling resolves to nothing and has no price row.
    assert normalize_plan("service_compute", "2c-16g") is None
    assert "2c-16g" not in cache["service_compute"]["plans"]
    assert "2c-16gb" not in cache["service_compute"]["plans"]
    assert normalize_plan("service_compute", "1c-2g") == "1c-2gb"
    assert "1c-2gb" in cache["service_compute"]["plans"]
    assert normalize_plan("service_compute", "pro plus") == "4c-8gb"
    assert "4c-8gb" in cache["service_compute"]["plans"]


def test_rightsizing_thresholds_are_numeric_and_fail_closed() -> None:
    thresholds = load(SKILL_ROOT / "knowledge/estimate/rightsizing-thresholds.json")
    assert thresholds["minimum_lookback_days"] == 7
    assert thresholds["minimum_expected_sample_coverage"] == 0.8
    assert thresholds["allowed_resolutions_seconds"] == [30, 60, 300, 3600]
    assert thresholds["require_instance_lifecycle_alignment"] is True
    assert thresholds["replacement_instances_are_concurrent"] is False
    assert thresholds["interpolate_idle_gaps_as_zero"] is False
    assert thresholds["insufficient_evidence"] == {
        "confidence": "inferred",
        "right_sized_equals_capacity_preserving": True,
        "downsize_allowed": False,
    }
    assert thresholds["downsize_limits"]["maximum_cpu_p95_fraction"] == 0.4
    assert thresholds["downsize_limits"]["maximum_memory_p95_fraction"] == 0.6
    assert thresholds["memory_headroom_multipliers"]["agent_browser_or_tool_process"] == 1.5


def test_estimate_dual_totals_floors_and_metric_gates_reconcile() -> None:
    estimate = load(EXPECTED / "estimation-infra.json")
    vendored_schema = load(SKILL_ROOT / "references/vendored/estimate/estimation-infra.schema.json")
    jsonschema.Draft7Validator(vendored_schema).validate(estimate)
    design_ids = {row["source_resource_id"] for row in load(EXPECTED / "aws-design.json")["mappings"]}
    scenarios = estimate["scenarios"]
    for scenario in scenarios.values():
        lines = scenario["lines"]
        assert [row["source_resource_id"] for row in lines] == sorted(
            (row["source_resource_id"] for row in lines), key=str.encode
        )
        assert {row["source_resource_id"] for row in lines} == design_ids
        known = sum(Decimal(str(row["monthly_amount"])) for row in lines if row["monthly_amount"] is not None)
        assert known == Decimal(str(scenario["known_cost_monthly_usd"]))
        missing = [row["line_id"] for row in lines if row["monthly_amount"] is None]
        assert missing == scenario["unpriced_line_ids"]
        assert scenario["is_floor"] is bool(missing)

    capacity_by_id = {row["source_resource_id"]: row for row in scenarios["capacity_preserving"]["lines"]}
    for row in scenarios["right_sized"]["lines"]:
        capacity = capacity_by_id[row["source_resource_id"]]
        if row["monthly_amount"] is not None and capacity["monthly_amount"] is not None and row["monthly_amount"] < capacity["monthly_amount"]:
            assert row["evidence_sufficient"] is True
            assert row["confidence"] == "measured"
    expected_delta = Decimal(str(scenarios["right_sized"]["known_cost_monthly_usd"])) - Decimal(str(scenarios["capacity_preserving"]["known_cost_monthly_usd"]))
    assert expected_delta == Decimal(str(estimate["delta_monthly_usd"])) == Decimal("-62.0")
    assert estimate["migration_cost_considerations"]["human_labor_monthly_usd"] is None


def test_workshop_fingerprint_scenario_cap_and_return_state_are_deterministic() -> None:
    workshop = load(EXPECTED / "workshop-scenarios.json")
    scenarios = workshop["scenarios"]
    assert len(scenarios) <= 5
    ids = [row["scenario_id"] for row in scenarios]
    assert ids == sorted(ids, key=str.encode) and len(ids) == len(set(ids))
    assert workshop["baseline_scenario_id"] in ids
    assert workshop["active_scenario_id"] in ids
    assert all(row["inventory_fingerprint"] == workshop["inventory_fingerprint"] for row in scenarios)
    assert scenarios[0]["preferences_subset"] == {}
    for row in scenarios:
        summary = row["estimation_summary"]
        assert summary["calculator_url"] is None
        assert summary["capacity_preserving_is_floor"] is (summary["capacity_preserving_unpriced_count"] > 0)
        assert summary["right_sized_is_floor"] is (summary["right_sized_unpriced_count"] > 0)
    assert workshop["state_after_exit"] == {
        "current_phase": "estimate",
        "workshop": "completed",
        "run_mode_present": False,
        "return_to": "decision_gate",
        "generated_files_deleted": False,
    }
    refresh = (SKILL_ROOT / "references/phases/workshop/workshop-refresh.md").read_text()
    assert "exact raw inventory bytes" in refresh
    assert "emits no `HANDOFF_OK`" in refresh
    assert "never evict baseline" in refresh


def test_generate_ledger_schemas_and_complete_target_accounting() -> None:
    generated = EXPECTED / "generated"
    ledger = load(generated / "generation-warnings.json")
    ledger_schema = load(SKILL_ROOT / "references/shared/schema-generation-warnings.json")
    jsonschema.Draft202012Validator(ledger_schema).validate(ledger)
    validation = load(generated / "validation-report.json")
    validation_schema = load(SKILL_ROOT / "references/shared/schema-validation-report.json")
    jsonschema.Draft202012Validator(validation_schema, format_checker=jsonschema.FormatChecker()).validate(validation)

    design = load(EXPECTED / "aws-design.json")
    design_ids = [row["source_resource_id"] for row in design["mappings"]]
    classified = [
        row["source_resource_id"]
        for bucket in ("generated", "consumed_topology", "deferred", "unsupported")
        for row in ledger[bucket]
    ]
    assert sorted(classified, key=str.encode) == design_ids
    assert len(classified) == len(set(classified)) == ledger["accounting"]["accounted_count"]
    assert ledger["accounting"] == {
        "design_count": 15,
        "generated_count": 11,
        "consumed_topology_count": 2,
        "deferred_count": 0,
        "unsupported_count": 2,
        "accounted_count": 15,
        "source_resource_ids": design_ids,
    }
    codes = {row["code"] for row in ledger["warnings"]}
    assert codes == {
        "conditional_workflow_generation_unsupported",
        "deferred_shared_ai_engine",
        "unpriced_cost_floor",
    }
    assert all(row["target_files"] == [] for row in ledger["unsupported"])
    assert not any("ai" in path.lower() for row in ledger["generated"] for path in row["target_files"])


def test_generated_terraform_docs_and_scripts_cover_cutover_and_rollback() -> None:
    generated = EXPECTED / "generated"
    terraform = generated / "terraform"
    required = {
        "main.tf", "variables.tf", "outputs.tf", "network.tf", "compute.tf",
        "data.tf", "storage.tf", "delivery.tf", "README.md",
        "terraform.tfvars.example", ".gitignore",
    }
    assert required <= {path.name for path in terraform.iterdir()}
    tf = "\n".join(path.read_text(encoding="utf-8") for path in sorted(terraform.glob("*.tf")))
    for expected in (
        "aws_ecs_service", "aws_scheduler_schedule", "aws_db_instance",
        "aws_elasticache_replication_group", "aws_efs_access_point",
        "aws_cloudfront_distribution", "aws_ecr_repository", "issued_certificate_arn",
    ):
        assert expected in tf
    assert "aws_service_discovery_private_dns_namespace" in tf
    assert "aws_service_discovery_service" in tf
    assert "registry_arn = aws_service_discovery_service.private.arn" in tf
    network = (terraform / "network.tf").read_text(encoding="utf-8")
    compute = (terraform / "compute.tf").read_text(encoding="utf-8")
    assert "security_groups" in network and "[aws_security_group.edge.id]" in network
    assert 'security_group_id        = aws_security_group.web.id' in network
    assert 'source_security_group_id = aws_security_group.edge.id' in network
    assert 'security_groups  = [aws_security_group.web.id]' in compute
    assert 'from_port       = 10000' in network and 'security_groups = [aws_security_group.worker.id]' in network
    assert 'security_groups  = [aws_security_group.private.id]' in compute
    assert 'gateway_id = aws_internet_gateway.main.id' in network
    assert 'nat_gateway_id = aws_nat_gateway.main.id' in network
    assert 'route_table_id = aws_route_table.public.id' in network
    assert 'route_table_id = aws_route_table.private.id' in network
    storage = (terraform / "storage.tf").read_text(encoding="utf-8")
    assert 'security_groups = [aws_security_group.private.id]' in storage
    assert 'sourceVolume  = "private-data"' in compute
    assert 'containerPath = "/var/data"' in compute
    assert 'file_system_id     = aws_efs_file_system.application.id' in compute
    assert 'access_point_id = aws_efs_access_point.application.id' in compute
    assert 'transit_encryption = "ENABLED"' in compute
    assert "aws_sfn_state_machine" not in tf
    assert "bedrock" not in tf.lower()
    assert re.search(r"publicly_accessible\s*=\s*false", tf)
    assert re.search(r"storage_encrypted\s*=\s*true", tf)
    assert re.search(r"manage_master_user_password\s*=\s*true", tf)
    assert "db_password" not in tf
    assert not re.search(r"(?:master_)?password\\s*=\\s*var\\.", tf)
    assert "at_rest_encryption_enabled = true" in tf
    delivery = (terraform / "delivery.tf").read_text(encoding="utf-8")
    assert "aws_cloudfront_origin_access_control.static.id" in delivery
    assert 'resource "aws_s3_bucket_policy" "static_cloudfront"' in delivery
    assert 'Principal = { Service = "cloudfront.amazonaws.com" }' in delivery
    assert 'Action    = "s3:GetObject"' in delivery
    assert '"AWS:SourceArn" = aws_cloudfront_distribution.static.arn' in delivery
    assert 'resource "aws_s3_bucket_versioning" "static"' in delivery
    assert re.search(r'status\s*=\s*"Enabled"', delivery)
    assert 'resource "aws_s3_bucket_server_side_encryption_configuration" "static"' in delivery
    assert re.search(r'sse_algorithm\s*=\s*"AES256"', delivery)
    assert 'resource "aws_iam_role" "scheduler"' in compute
    assert 'resource "aws_iam_role_policy" "scheduler"' in compute
    assert 'role_arn = aws_iam_role.scheduler.arn' in compute
    assert re.search(r'Action\s*=\s*\["ecs:RunTask"\]', compute)
    assert re.search(r'Action\s*=\s*\["iam:PassRole"\]', compute)
    assert '"iam:PassedToService" = "ecs-tasks.amazonaws.com"' in compute
    assert 'network_configuration {' in compute
    assert 'security_groups  = [aws_security_group.worker.id]' in compute
    assert 'subnets          = aws_subnet.private[*].id' in compute
    assert 'from_port   = 5432' in network and 'from_port   = 6379' in network
    assert 'vpc_security_group_ids      = [aws_security_group.data.id]' in tf
    assert 'security_group_ids         = [aws_security_group.data.id]' in tf
    assert "certificate_arn   = var.issued_certificate_arn" in network
    assert "aws_acm_certificate.web.arn" not in network
    variables = (terraform / "variables.tf").read_text(encoding="utf-8")
    for name, source_id in (("web", "rr-web"), ("private", "rr-private"), ("worker", "rr-worker"), ("cron", "rr-cron")):
        assert f'variable "{name}_image"' in variables
        assert f"Render source resource {source_id}" in variables
        assert f"image" in compute and f"var.{name}_image" in compute

    guide = (generated / "MIGRATION_GUIDE.md").read_text(encoding="utf-8")
    for phrase in (
        "## Prerequisites", "## PostgreSQL migration", "## Persistent-disk migration",
        "## DNS and traffic cutover", "## Verification", "## Rollback and source retention",
        "writer quiescence", "integrity", "deferred_shared_ai_engine",
        "conditional_workflow_generation_unsupported",
    ):
        assert phrase in guide
    scripts = generated / "scripts"
    assert {path.name for path in scripts.iterdir()} == {
        "migrate-disk.sh", "migrate-postgres.sh", "promote-image.sh"
    }
    assert all("set -euo pipefail" in path.read_text(encoding="utf-8") for path in scripts.iterdir())
    assert all(path.stat().st_mode & 0o777 == 0o755 for path in scripts.iterdir())
    assert "DRY_RUN" in (scripts / "migrate-postgres.sh").read_text(encoding="utf-8")
    assert "DRY_RUN" in (scripts / "migrate-disk.sh").read_text(encoding="utf-8")


def test_image_promotion_requires_environment_and_preserves_exact_digest(tmp_path: Path) -> None:
    script = EXPECTED / "generated/scripts/promote-image.sh"
    repository = "000000000000.dkr.ecr.us-east-1.amazonaws.com/render-migration"
    digest = "sha256:" + "a" * 64

    missing_environment = subprocess.run(  # nosec B603 - checked-in fixture script and fixed arguments
        [str(script), repository, digest],
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing_environment.returncode == 2
    assert "TARGET_ENVIRONMENT" in missing_environment.stderr

    mutable = subprocess.run(  # nosec B603 - checked-in fixture script and fixed arguments
        [str(script), repository, "latest", "production"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert mutable.returncode == 2
    assert "immutable lowercase sha256" in mutable.stderr

    dry_run = subprocess.run(  # nosec B603 - checked-in fixture script and fixed arguments
        [str(script), repository, digest, "production"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert dry_run.returncode == 0, dry_run.stderr
    assert f"environment=production image={repository}@{digest}" in dry_run.stdout
    assert "immutable_tag=deploy-production-aaaaaaaaaaaa\n" in dry_run.stdout
    assert "without rebuilding" in dry_run.stdout

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_log = tmp_path / "aws-calls"
    fake_aws = fake_bin / "aws"
    fake_aws.write_text(
        '''#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$AWS_CALL_LOG"
case "${2:-}" in
  describe-repositories) printf 'IMMUTABLE\\n' ;;
  batch-get-image) printf '%s\\t%s\\n' "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" '{"schemaVersion":2}' ;;
  put-image) printf '{}\\n' ;;
  *) exit 9 ;;
esac
''',
        encoding="utf-8",
    )
    fake_aws.chmod(0o755)
    environment = dict(os.environ)
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    environment["AWS_CALL_LOG"] = str(call_log)
    executed = subprocess.run(  # nosec B603 - fake aws confines the explicit execution path
        [str(script), repository, digest, "production", "--execute"],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    assert executed.returncode == 0, executed.stderr
    assert f"PROMOTION_COMPLETE environment=production image={repository}@{digest}" in executed.stdout
    calls = call_log.read_text(encoding="utf-8")
    assert "describe-repositories" in calls and "batch-get-image" in calls and "put-image" in calls
    assert f"imageDigest={digest}" in calls
    assert "--image-tag deploy-production-aaaaaaaaaaaa " in calls
    assert all(line.startswith("ecr ") for line in calls.splitlines())
    assert " build " not in f" {calls} "


IMMUTABLE_FAKE_AWS = '''#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$AWS_CALL_LOG"
value_after() {
  local flag=$1
  shift
  while [[ $# -gt 0 ]]; do
    if [[ $1 == "$flag" ]]; then
      printf '%s' "$2"
      return 0
    fi
    shift
  done
  return 1
}
case "${2:-}" in
  describe-repositories) printf 'IMMUTABLE\\n' ;;
  batch-get-image)
    requested=$(value_after --image-ids "$@")
    requested=${requested#imageDigest=}
    printf '%s\\t%s\\n' "$requested" "{\\"schemaVersion\\":2,\\"digest\\":\\"$requested\\"}" ;;
  put-image)
    tag=$(value_after --image-tag "$@")
    manifest=$(value_after --image-manifest "$@")
    touch "$AWS_TAG_STORE"
    if grep -q "^$tag " "$AWS_TAG_STORE"; then
      echo "An error occurred (ImageTagAlreadyExistsException) when calling the PutImage operation: The image tag '$tag' already exists in the repository" >&2
      exit 254
    fi
    printf '%s %s\\n' "$tag" "$manifest" >> "$AWS_TAG_STORE"
    printf '{}\\n' ;;
  *) exit 9 ;;
esac
'''


def test_two_digests_promote_to_one_repository_and_environment(tmp_path: Path) -> None:
    script = EXPECTED / "generated/scripts/promote-image.sh"
    repository = "000000000000.dkr.ecr.us-east-1.amazonaws.com/render-migration"
    first_digest = "sha256:" + "a" * 64
    second_digest = "sha256:" + "b" * 64
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_aws = fake_bin / "aws"
    fake_aws.write_text(IMMUTABLE_FAKE_AWS, encoding="utf-8")
    fake_aws.chmod(0o755)
    call_log = tmp_path / "aws-calls"
    tag_store = tmp_path / "ecr-tags"
    environment = dict(os.environ)
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    environment["AWS_CALL_LOG"] = str(call_log)
    environment["AWS_TAG_STORE"] = str(tag_store)

    def promote(digest: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 - fake aws confines the explicit execution path
            [str(script), repository, digest, "production", "--execute"],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

    first = promote(first_digest)
    assert first.returncode == 0, first.stderr
    second = promote(second_digest)
    assert second.returncode == 0, second.stderr
    assert f"PROMOTION_COMPLETE environment=production image={repository}@{first_digest} immutable_tag=deploy-production-aaaaaaaaaaaa" in first.stdout
    assert f"PROMOTION_COMPLETE environment=production image={repository}@{second_digest} immutable_tag=deploy-production-bbbbbbbbbbbb" in second.stdout

    recorded = dict(line.split(" ", 1) for line in tag_store.read_text(encoding="utf-8").splitlines())
    assert set(recorded) == {"deploy-production-aaaaaaaaaaaa", "deploy-production-bbbbbbbbbbbb"}
    assert first_digest in recorded["deploy-production-aaaaaaaaaaaa"]
    assert second_digest in recorded["deploy-production-bbbbbbbbbbbb"]
    calls = call_log.read_text(encoding="utf-8")
    assert f"imageDigest={first_digest}" in calls and f"imageDigest={second_digest}" in calls
    assert all(line.startswith("ecr ") for line in calls.splitlines())

    repeated = promote(first_digest)
    assert repeated.returncode != 0
    assert "ImageTagAlreadyExistsException" in repeated.stderr
    assert "deploy-production-aaaaaaaaaaaa" in repeated.stderr


def test_fixture_promotion_script_matches_harness_emitter() -> None:
    harness = _load_script_module(
        Path(__file__).with_name("render_pipeline_harness.py"),
        "render_pipeline_harness_promotion_parity",
    )
    fixture = (EXPECTED / "generated/scripts/promote-image.sh").read_bytes()
    assert fixture == harness._promotion_script().encode("utf-8")
    assert b'promotion_tag="deploy-${target_environment}-${digest_short}"' in fixture
    assert b'image_reference="${repository_url}@${digest}"' in fixture


def test_generated_valkey_engine_matches_design_selection() -> None:
    harness = _load_script_module(
        Path(__file__).with_name("render_pipeline_harness.py"),
        "render_pipeline_harness_cache_parity",
    )
    design = load(EXPECTED / "aws-design.json")
    data_tf = (EXPECTED / "generated/terraform/data.tf").read_text(encoding="utf-8")
    key_value = [row for row in design["mappings"] if row["render_kind"] == "render.key_value"]
    assert key_value and all("Valkey" in row["aws_service"] for row in key_value)
    harness.assert_cache_engine_parity(data_tf, design)
    assert re.search(r'^\s*engine\s*=\s*"valkey"', data_tf, flags=re.MULTILINE)
    assert re.search(r'^\s*engine_version\s*=\s*"8\.0"', data_tf, flags=re.MULTILINE)
    assert re.search(r'^\s*node_type\s*=\s*"cache\.m6g\.large"', data_tf, flags=re.MULTILINE)
    assert key_value[0]["aws_config"]["node_type"] == "cache.m6g.large"
    assert not re.search(r'^\s*engine\s*=\s*"redis"', data_tf, flags=re.MULTILINE)

    substituted = data_tf.replace('engine                     = "valkey"', 'engine                     = "redis"')
    assert substituted != data_tf
    with pytest.raises(AssertionError, match='engine = "redis"'):
        harness.assert_cache_engine_parity(substituted, design)
    unversioned = re.sub(r'^\s*engine_version\s*=\s*"8\.0"\n', "", data_tf, flags=re.MULTILINE)
    with pytest.raises(AssertionError, match="engine_version"):
        harness.assert_cache_engine_parity(unversioned, design)
    wrong_node = data_tf.replace('"cache.m6g.large"', '"cache.t4g.micro"')
    with pytest.raises(AssertionError, match="node_type"):
        harness.assert_cache_engine_parity(wrong_node, design)


def test_generated_certificate_and_static_origin_graph_fail_closed() -> None:
    harness = _load_script_module(
        Path(__file__).with_name("render_pipeline_harness.py"),
        "render_pipeline_harness_graph_contract",
    )
    terraform = EXPECTED / "generated/terraform"
    harness.assert_generated_infrastructure_graph(terraform)
    with pytest.raises(AssertionError, match="newly requested"):
        harness._assert_listener_uses_issued_certificate(
            '''resource "aws_acm_certificate" "web" {
  domain_name       = "migration.example.invalid"
  validation_method = "DNS"
}
resource "aws_lb_listener" "https" {
  certificate_arn = aws_acm_certificate.web.arn
}
'''
        )


def test_generated_terraform_passes_local_policy_and_fmt_when_available() -> None:
    terraform = EXPECTED / "generated/terraform"
    policy = REPO_ROOT / "plugins/aws-startup-advisor/skills/tf-best-practices/scripts/validate-terraform-policy.py"
    result = subprocess.run(  # nosec B603
        [sys.executable, str(policy), str(terraform)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("POLICY_OK")
    terraform_binary = shutil.which("terraform")
    if terraform_binary:
        result = subprocess.run(  # nosec B603
            [terraform_binary, "fmt", "-check", "-recursive", str(terraform)],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


INIT_DNS_FAILURE = '''Error: Failed to query available provider packages

Could not retrieve the list of available versions for provider hashicorp/aws:
could not connect to registry.terraform.io: failed to request discovery
document: Get "https://registry.terraform.io/.well-known/terraform.json":
dial tcp: lookup registry.terraform.io: no such host
'''
INIT_CONNECTION_REFUSED = '''Error: Failed to query available provider packages

Could not retrieve the list of available versions for provider hashicorp/aws:
Get "https://registry.terraform.io/v1/providers/hashicorp/aws/versions":
dial tcp 203.0.113.10:443: connect: connection refused
'''
INIT_TLS_TIMEOUT = '''Error: Failed to install provider

Error while installing hashicorp/aws v5.80.0: Get
"https://releases.hashicorp.com/terraform-provider-aws/5.80.0/terraform-provider-aws_5.80.0_darwin_arm64.zip":
net/http: TLS handshake timeout
'''
INIT_CHECKSUM_MISMATCH = '''Error: Failed to install provider

Error while installing hashicorp/aws v5.80.0: checksum mismatch for
registry.terraform.io/hashicorp/aws: the downloaded archive does not match
the checksum recorded in the dependency lock file
'''
INIT_UNAUTHORIZED = '''Error: Failed to query available provider packages

Could not retrieve the list of available versions for provider
registry.terraform.io/hashicorp/aws: 401 Unauthorized
'''
INIT_FORBIDDEN = '''Error: Failed to install provider

Error while installing hashicorp/aws v5.80.0 from registry.terraform.io:
403 Forbidden
'''
INIT_INVALID_CONFIGURATION = '''Error: Invalid provider configuration

Provider "registry.terraform.io/hashicorp/aws" requires explicit
configuration. Add a provider block to the root module.
'''
INIT_LOCK_FILE_MISMATCH = '''Error: Failed to install provider

Error while installing hashicorp/aws v5.80.0: the current package for
registry.terraform.io/hashicorp/aws 5.80.0 doesn't match any of the
checksums recorded in the dependency lock file
'''
INIT_MIXED_DNS_AND_CHECKSUM = INIT_DNS_FAILURE + "\n" + INIT_CHECKSUM_MISMATCH
INIT_NO_RELEASES_MATCH = '''Error: Failed to query available provider packages

Could not retrieve the list of available versions for provider hashicorp/aws:
no available releases match the given constraints ~> 5.80
'''


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        pytest.param(INIT_DNS_FAILURE, "provider_registry_unavailable", id="dns-no-such-host"),
        pytest.param(INIT_CONNECTION_REFUSED, "provider_registry_unavailable", id="connection-refused"),
        pytest.param(INIT_TLS_TIMEOUT, "provider_registry_unavailable", id="tls-handshake-timeout"),
        pytest.param(INIT_CHECKSUM_MISMATCH, None, id="checksum-mismatch-naming-registry"),
        pytest.param(INIT_UNAUTHORIZED, None, id="401-unauthorized"),
        pytest.param(INIT_FORBIDDEN, None, id="403-forbidden"),
        pytest.param(INIT_INVALID_CONFIGURATION, None, id="invalid-provider-configuration"),
        pytest.param(INIT_LOCK_FILE_MISMATCH, None, id="lock-file-mismatch"),
        pytest.param(INIT_NO_RELEASES_MATCH, None, id="no-available-releases"),
        pytest.param(INIT_MIXED_DNS_AND_CHECKSUM, None, id="dns-plus-checksum-rejected-wins"),
        pytest.param("registry.terraform.io timeout connection", None, id="bare-substrings-are-not-enough"),
        pytest.param("", None, id="empty-output"),
    ],
)
def test_terraform_init_failure_classification_is_signature_specific(output: str, expected: str | None) -> None:
    harness = _load_script_module(
        Path(__file__).with_name("render_pipeline_harness.py"),
        "render_pipeline_harness_init_classifier",
    )
    assert harness.classify_terraform_init_failure(output) == expected


def _simulated_terraform_run(init_output: str, recorded: list[list[str]]):
    def fake_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        recorded.append([str(part) for part in command])
        name = Path(command[0]).name
        if name == "terraform" and command[1] == "init":
            return subprocess.CompletedProcess(command, 1, "", init_output)
        if name == "terraform":
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:2] and command[1].endswith("validate-terraform-policy.py"):
            return subprocess.CompletedProcess(command, 0, "POLICY_OK\n", "")
        if command[1:2] and command[1].endswith("validate-render-migration-report.py"):
            return subprocess.CompletedProcess(command, 0, "REPORT_OK\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    return fake_run


def _simulated_pack(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "run"
    generated = root / "generated"
    shutil.copytree(
        EXPECTED / "generated",
        generated,
        ignore=shutil.ignore_patterns(".terraform", ".terraform.lock.hcl"),
    )
    return root, generated, load(EXPECTED / "generated/generation-warnings.json")


def test_validate_generated_pack_degrades_only_on_registry_connectivity_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = _load_script_module(
        Path(__file__).with_name("render_pipeline_harness.py"),
        "render_pipeline_harness_offline_degrade",
    )
    root, generated, ledger = _simulated_pack(tmp_path)
    recorded: list[list[str]] = []
    monkeypatch.setattr(harness.shutil, "which", lambda name: f"/simulated/bin/{name}")
    monkeypatch.setattr(harness, "_run", _simulated_terraform_run(INIT_DNS_FAILURE, recorded))

    validation = harness._validate_generated_pack(root, generated, ledger)

    assert validation["status"] == "passed_degraded_offline"
    assert validation["offline_fallback_used"] is True
    assert validation["checks"]["terraform_init"]["status"] == "provider_registry_unavailable"
    assert validation["checks"]["terraform_validate"]["status"] == "provider_registry_unavailable"
    terraform_subcommands = [command[1] for command in recorded if Path(command[0]).name == "terraform"]
    assert terraform_subcommands == ["fmt", "init"]


@pytest.mark.parametrize(
    ("init_output", "match"),
    [
        pytest.param(INIT_CHECKSUM_MISMATCH, "checksum mismatch", id="checksum"),
        pytest.param(INIT_UNAUTHORIZED, "401 Unauthorized", id="auth"),
        pytest.param(INIT_INVALID_CONFIGURATION, "Invalid provider configuration", id="config"),
        pytest.param(INIT_MIXED_DNS_AND_CHECKSUM, "checksum mismatch", id="mixed"),
    ],
)
def test_validate_generated_pack_keeps_rejected_init_errors_as_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, init_output: str, match: str
) -> None:
    harness = _load_script_module(
        Path(__file__).with_name("render_pipeline_harness.py"),
        "render_pipeline_harness_rejected_init",
    )
    root, generated, ledger = _simulated_pack(tmp_path)
    recorded: list[list[str]] = []
    monkeypatch.setattr(harness.shutil, "which", lambda name: f"/simulated/bin/{name}")
    monkeypatch.setattr(harness, "_run", _simulated_terraform_run(init_output, recorded))

    with pytest.raises(AssertionError, match=match):
        harness._validate_generated_pack(root, generated, ledger)
    terraform_subcommands = [command[1] for command in recorded if Path(command[0]).name == "terraform"]
    assert terraform_subcommands == ["fmt", "init"]


def test_validation_report_has_independent_fail_closed_statuses() -> None:
    schema = load(SKILL_ROOT / "references/shared/schema-validation-report.json")
    report = load(EXPECTED / "generated/validation-report.json")
    assert set(report["checks"]) == {
        "terraform_fmt", "terraform_init", "terraform_validate", "policy",
        "secret_scan", "schemas", "report",
    }
    assert report["checks"]["policy"]["policy_status"] == "POLICY_OK"
    degraded = json.loads(json.dumps(report))
    degraded["status"] = "passed_degraded_offline"
    degraded["offline_fallback_used"] = True
    degraded["checks"]["terraform_init"]["status"] = "provider_registry_unavailable"
    degraded["checks"]["terraform_validate"]["status"] = "provider_registry_unavailable"
    jsonschema.Draft202012Validator(schema).validate(degraded)
    for local_check in ("terraform_fmt", "secret_scan", "schemas", "report"):
        invalid = json.loads(json.dumps(degraded))
        invalid["checks"][local_check]["status"] = "failed"
        errors = list(jsonschema.Draft202012Validator(schema).iter_errors(invalid))
        assert errors, local_check
    invalid_policy = json.loads(json.dumps(degraded))
    invalid_policy["checks"]["policy"]["status"] = "failed"
    invalid_policy["checks"]["policy"]["policy_status"] = "POLICY_FAIL"
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(invalid_policy))


def test_workshop_canonical_and_all_four_consumers_are_byte_identical() -> None:
    canonical = REPO_ROOT / "plugins/aws-startup-advisor/skills/shared/workshop/workshop-invariants.md"
    expected = canonical.read_bytes()
    assert b"render-resource-inventory.json" in expected
    assert b'"Azure" / "GCP" / "Heroku" / "Render"' in expected
    for skill in ("azure-to-aws", "gcp-to-aws", "heroku-to-aws", "render-to-aws"):
        copy = REPO_ROOT / f"plugins/aws-startup-advisor/skills/{skill}/references/vendored/workshop/workshop-invariants.md"
        assert copy.read_bytes() == expected, copy


def test_feedback_privacy_contract_is_allowlist_first_and_non_gating() -> None:
    collect = (SKILL_ROOT / "references/phases/feedback/feedback-collect.md").read_text(encoding="utf-8")
    assemble = (SKILL_ROOT / "references/phases/feedback/feedback-assemble.md").read_text(encoding="utf-8")
    assert "Ask exactly five optional questions" in collect
    assert collect.count("prefer_not_to_answer") == 5
    assert "Construct the allowlisted object from counts; never copy then redact" in collect
    for excluded in ("names and IDs", "paths", "domains/URLs", "repository data", "account/email data", "configuration or environment names/values", "source snippets"):
        assert excluded in collect
    assert "set only `phases.feedback: \"completed\"`" in assemble
    assert "never changes the Done-versus-Generate decision" in assemble
    feedback_phase = (SKILL_ROOT / "references/phases/feedback/feedback.md").read_text(encoding="utf-8")
    assert "no `_advances_to` and no `_gates`" in feedback_phase
    assert "There is no retry prompt and no second offer after Generate" in feedback_phase


def _load_script_module(path: Path, name: str):
    script_parent = str(path.parent)
    if script_parent not in sys.path:
        sys.path.insert(0, script_parent)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _materialize_complete_mocked_pipeline(root: Path) -> dict[str, bytes]:
    scripts = SKILL_ROOT / "scripts"
    normalize_test = _load_script_module(scripts / "test_normalize_render_capture.py", f"normalize_fixture_{root.name}")
    manifest = normalize_test.build_estate(root)
    inventory, clusters, ai_profile, ai_discovery = normalize_test.module.normalize(root, manifest, normalize_test.ATTEMPT)
    inventory_fingerprint = normalize_test.module.sha256_digest(normalize_test.module.canonical_bytes(inventory))

    preferences = load(EXPECTED / "preferences.json")
    preferences["inventory_fingerprint"] = inventory_fingerprint
    preferences["questions"] = []
    preferences["ai_track"]["profile_digest"] = normalize_test.module.ai_profile_digest(ai_profile)
    preferences_fingerprint = normalize_test.module.sha256_digest(normalize_test.module.canonical_bytes(preferences))
    jsonschema.Draft202012Validator(load(SKILL_ROOT / "references/shared/schema-render-preferences.json")).validate(preferences)

    templates = {row["render_kind"]: row for row in load(EXPECTED / "aws-design.json")["mappings"]}
    topology_kinds = {"render.project", "render.environment", "render.environment_group", "render.preview_environment", "render.workflow_version", "render.task_run", "render.task_attempt"}
    target_by_kind = {
        "render.build_artifact": "Amazon ECR immutable image digest",
        "render.workflow_version": "AWS workflow definition version metadata",
        "render.task_run": "AWS workflow execution-history metadata",
        "render.task_attempt": "AWS workflow retry-attempt metadata",
        "render.preview_environment": "AWS CI/CD ephemeral stack pattern",
    }
    mappings = []
    fallback = templates["render.project"]
    for resource in inventory["resources"]:
        row = json.loads(json.dumps(templates.get(resource["kind"], fallback)))
        row["source_resource_id"] = resource["id"]
        row["render_kind"] = resource["kind"]
        if resource["kind"] in target_by_kind:
            row["aws_service"] = target_by_kind[resource["kind"]]
            row["aws_config"] = {"source_metadata_only": True}
            row["rationale"] = "Preserves this discovered source record in the selected migration topology."
            row["decision"] = {
                "selector": "topology.complete_accounting",
                "candidate_set": [row["aws_service"], "Drop source record"],
                "evidence": [{"ordinal": 1, "value": "The source record is reachable from the canonical inventory."}],
                "rules_evaluated": [{"ordinal": 1, "value": "Every discovered source record must be accounted for exactly once."}],
                "rules_fired": [{"ordinal": 1, "value": "Preserve source topology and lifecycle evidence."}],
                "questions_asked": [], "defaults_used": [],
                "rejected_candidates": [{"ordinal": 1, "aws_service": "Drop source record", "reason": "Dropping it would make migration accounting incomplete."}],
            }
        row["disposition"] = "consumed_topology" if resource["kind"] in topology_kinds else "mapped"
        mappings.append(row)
    mappings.sort(key=lambda row: row["source_resource_id"].encode())
    source_ids = [row["source_resource_id"] for row in mappings]
    design = {
        "schema_version": "1.0", "phase": "design", "inventory_fingerprint": inventory_fingerprint,
        "preferences_fingerprint": preferences_fingerprint, "mappings": mappings,
        "accounting": {"inventory_resource_count": len(source_ids), "mapped_resource_count": len(source_ids), "accounted_resource_ids": source_ids},
        "ai_track": {**preferences["ai_track"], "infrastructure_status": "completed"},
    }
    jsonschema.Draft202012Validator(load(SKILL_ROOT / "references/shared/schema-render-aws-design.json")).validate(design)

    line_rows = [{"line_id": f"line-{index:03d}", "source_resource_id": row["source_resource_id"], "aws_service": row["aws_service"], "monthly_amount": 0.0, "pricing_source": "no_direct_charge", "confidence": "inferred", "exclusion_reason": None, "evidence_sufficient": False} for index, row in enumerate(mappings, 1)]
    estimate = load(EXPECTED / "estimation-infra.json")
    for scenario in estimate["scenarios"].values():
        scenario.update({"known_cost_monthly_usd": 0.0, "is_floor": False, "unpriced_line_ids": [], "lines": line_rows})
    estimate["projected_costs"].update({"aws_monthly_premium": 0.0, "aws_monthly_balanced": 0.0, "aws_monthly_optimized": 0.0, "aws_annual_optimized": 0.0})
    estimate["delta_monthly_usd"] = 0.0
    estimate["complexity_inputs"]["service_count"] = len(source_ids)
    jsonschema.Draft7Validator(load(SKILL_ROOT / "references/vendored/estimate/estimation-infra.schema.json")).validate(estimate)

    classified = []
    unsupported = []
    consumed = []
    workflow_unsupported = {"render.workflow", "render.workflow_version", "render.workflow_task", "render.task_run", "render.task_attempt"}
    target_by_render_kind = {
        "render.web_service": ["terraform/compute.tf"],
        "render.private_service": ["terraform/compute.tf"],
        "render.background_worker": ["terraform/compute.tf"],
        "render.cron_job": ["terraform/compute.tf"],
        "render.postgres": ["terraform/data.tf", "scripts/migrate-postgres.sh"],
        "render.key_value": ["terraform/data.tf"],
        "render.persistent_disk": ["terraform/storage.tf", "scripts/migrate-disk.sh"],
        "render.static_site": ["terraform/delivery.tf"],
        "render.custom_domain": ["terraform/delivery.tf"],
        "render.build_source": ["terraform/delivery.tf", "scripts/promote-image.sh"],
        "render.build_artifact": ["terraform/delivery.tf", "scripts/promote-image.sh"],
    }
    for row in mappings:
        target_files = target_by_render_kind.get(row["render_kind"], ["MIGRATION_GUIDE.md"])
        record = {"source_resource_id": row["source_resource_id"], "render_kind": row["render_kind"], "aws_service": row["aws_service"], "reason": "Classification is derived from the same canonical Design mapping.", "target_files": target_files}
        if row["render_kind"] in workflow_unsupported:
            record["target_files"] = []
            unsupported.append(record)
        elif row["disposition"] == "consumed_topology":
            consumed.append(record)
        else:
            classified.append(record)
    warnings = load(EXPECTED / "generated/generation-warnings.json")["warnings"]
    ledger = {"schema_version": "1.0", "phase": "generate", "generated": classified, "consumed_topology": consumed, "deferred": [], "unsupported": unsupported, "warnings": warnings, "accounting": {"design_count": len(source_ids), "generated_count": len(classified), "consumed_topology_count": len(consumed), "deferred_count": 0, "unsupported_count": len(unsupported), "accounted_count": len(source_ids), "source_resource_ids": source_ids}}
    jsonschema.Draft202012Validator(load(SKILL_ROOT / "references/shared/schema-generation-warnings.json")).validate(ledger)

    generated = root / "generated"
    shutil.copytree(EXPECTED / "generated", generated)
    (root / "aws-design.json").write_bytes(normalize_test.module.canonical_bytes(design))
    (root / "estimation-infra.json").write_bytes(normalize_test.module.canonical_bytes(estimate))
    (generated / "generation-warnings.json").write_bytes(normalize_test.module.canonical_bytes(ledger))
    validation = load(generated / "validation-report.json")
    jsonschema.Draft202012Validator(
        load(SKILL_ROOT / "references/shared/schema-validation-report.json"),
        format_checker=jsonschema.FormatChecker(),
    ).validate(validation)
    for row in classified + consumed:
        assert row["target_files"]
        assert all((generated / target).is_file() for target in row["target_files"])
    sections = {
        "decision-summary": "Complete deterministic decision summary.",
        "architecture": "Build-once private managed architecture.",
        "exec-targets": "".join(f'<p data-source-resource-id="{escape(row["source_resource_id"])}" data-aws-service="{escape(row["aws_service"])}">{escape(row["aws_service"])}</p>' for row in mappings),
        "exec-costs": '<span data-cost-key="current_render">123.45</span><span data-cost-key="capacity_preserving">0.0</span><span data-cost-key="right_sized">0.0</span><span data-cost-key="delta">0.0</span>',
        "migration-data": "Postgres Database Migration Service writer quiescence integrity source retention.",
        "migration-storage": "EFS /var/data pre-copy delta ownership permissions integrity.",
        "migration-deployment": "ECR digest serving deploy auto-deploy rollback.",
        "cutover": "DNS TTL certificate traffic writer quiescence.",
        "rollback": "Source retention Render restore DNS writer rollback.",
        "verification": "Endpoint database cache disk workflow verification.",
        "deferred-surfaces": "deferred_shared_ai_engine conditional_workflow_generation_unsupported.",
        "appendix-accounting": f'<span data-accounted-count="{len(source_ids)}">{len(source_ids)}</span>',
        "appendix-artifacts": "Terraform and migration artifact ledger.",
        "appendix-assumptions": "Draft for review.",
    }
    toc = "".join(f'<a href="#{name}">{name}</a>' for name in sections)
    body = "".join(f'<section id="{name}">{content}</section>' for name, content in sections.items())
    report = f'<html lang="en"><body><h1>Render migration</h1><nav class="toc">{toc}</nav>{body}<footer>Draft for review</footer></body></html>'
    report_path = generated / "migration-report.html"
    report_path.write_text(report, encoding="utf-8")
    validator = _load_script_module(scripts / "validate-render-migration-report.py", f"report_validator_{root.name}")
    assert validator.validate(report_path, root) == []

    outputs = {
        "inventory": normalize_test.module.canonical_bytes(inventory),
        "clusters": normalize_test.module.canonical_bytes(clusters),
        "preferences": normalize_test.module.canonical_bytes(preferences),
        "design": normalize_test.module.canonical_bytes(design),
        "estimate": normalize_test.module.canonical_bytes(estimate),
    }
    for path in sorted(generated.rglob("*"), key=lambda item: item.relative_to(generated).as_posix().encode()):
        if path.is_file():
            outputs[f"generated/{path.relative_to(generated).as_posix()}"] = path.read_bytes()
    required_generated = {
        "generated/MIGRATION_GUIDE.md",
        "generated/README.md",
        "generated/generation-warnings.json",
        "generated/migration-report.html",
        "generated/validation-report.json",
        "generated/scripts/migrate-disk.sh",
        "generated/scripts/migrate-postgres.sh",
        "generated/scripts/promote-image.sh",
        "generated/terraform/main.tf",
        "generated/terraform/compute.tf",
        "generated/terraform/data.tf",
        "generated/terraform/delivery.tf",
        "generated/terraform/network.tf",
        "generated/terraform/storage.tf",
    }
    assert required_generated <= set(outputs)
    return outputs


def _materialize_independent_mixed_pipeline(root: Path) -> dict[str, bytes]:
    scripts = SKILL_ROOT / "scripts"
    normalize_test = _load_script_module(
        scripts / "test_normalize_render_capture.py",
        f"independent_normalize_{root.name}",
    )
    harness = _load_script_module(
        Path(__file__).with_name("render_pipeline_harness.py"),
        f"render_pipeline_harness_{root.name}",
    )
    manifest = normalize_test.build_estate(root)
    inventory, clusters, ai_profile, ai_discovery = normalize_test.module.normalize(
        root,
        manifest,
        normalize_test.ATTEMPT,
    )
    inventory_fingerprint = normalize_test.module.sha256_digest(
        normalize_test.module.canonical_bytes(inventory)
    )

    preferences = load(EXPECTED / "preferences.json")
    preferences["inventory_fingerprint"] = inventory_fingerprint
    preferences["questions"] = []
    preferences["ai_track"]["profile_digest"] = normalize_test.module.ai_profile_digest(ai_profile)
    preferences_fingerprint = normalize_test.module.sha256_digest(
        normalize_test.module.canonical_bytes(preferences)
    )
    jsonschema.Draft202012Validator(
        load(SKILL_ROOT / "references/shared/schema-render-preferences.json")
    ).validate(preferences)

    design = harness.design_from_inventory(
        inventory,
        preferences,
        inventory_fingerprint,
        preferences_fingerprint,
    )
    jsonschema.Draft202012Validator(
        load(SKILL_ROOT / "references/shared/schema-render-aws-design.json")
    ).validate(design)
    assert design["accounting"]["accounted_resource_ids"] == inventory["accounting"]["accounted_resource_ids"]

    estimate = harness.estimate_from_design(design)
    jsonschema.Draft7Validator(
        load(SKILL_ROOT / "references/vendored/estimate/estimation-infra.schema.json")
    ).validate(estimate)
    for scenario in estimate["scenarios"].values():
        assert [row["source_resource_id"] for row in scenario["lines"]] == design["accounting"]["accounted_resource_ids"]

    ledger = harness.ledger_from_design(design)
    jsonschema.Draft202012Validator(
        load(SKILL_ROOT / "references/shared/schema-generation-warnings.json")
    ).validate(ledger)
    (root / "aws-design.json").write_bytes(harness.canonical_bytes(design))
    (root / "estimation-infra.json").write_bytes(harness.canonical_bytes(estimate))
    (root / "ai-workload-profile.json").write_bytes(harness.canonical_bytes(ai_profile))
    (root / "render-ai-discovery.json").write_bytes(harness.canonical_bytes(ai_discovery))
    assert normalize_test.module.sha256_digest((root / "ai-workload-profile.json").read_bytes()) == preferences["ai_track"]["profile_digest"]
    generated = harness.emit_pack(root, design, estimate, ledger)
    harness.assert_pack_bound_to_design(generated, design, ledger)

    validation = load(generated / "validation-report.json")
    jsonschema.Draft202012Validator(
        load(SKILL_ROOT / "references/shared/schema-validation-report.json"),
        format_checker=jsonschema.FormatChecker(),
    ).validate(validation)
    assert validation["status"] in {"passed", "passed_degraded_offline"}
    for check in validation["checks"].values():
        assert "artifact_digest=sha256:" in check["evidence"]
    assert validation["checks"]["secret_scan"]["command"] == "gitleaks detect --no-git --source generated"
    if validation["status"] == "passed":
        assert validation["checks"]["terraform_init"]["status"] == "passed"
        assert validation["checks"]["terraform_validate"]["status"] == "passed"
    else:
        assert validation["checks"]["terraform_init"]["status"] == "provider_registry_unavailable"
    report_validator = _load_script_module(
        scripts / "validate-render-migration-report.py",
        f"independent_report_validator_{root.name}",
    )
    assert report_validator.validate(generated / "migration-report.html", root) == []

    policy = REPO_ROOT / "plugins/aws-startup-advisor/skills/tf-best-practices/scripts/validate-terraform-policy.py"
    policy_result = subprocess.run(  # nosec B603
        [sys.executable, str(policy), str(generated / "terraform")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert policy_result.returncode == 0, policy_result.stdout + policy_result.stderr
    assert policy_result.stdout.startswith("POLICY_OK")
    terraform_binary = shutil.which("terraform")
    if terraform_binary:
        fmt_result = subprocess.run(  # nosec B603
            [terraform_binary, "fmt", "-check", "-recursive", str(generated / "terraform")],
            text=True,
            capture_output=True,
            check=False,
        )
        assert fmt_result.returncode == 0, fmt_result.stdout + fmt_result.stderr

    outputs = {
        "inventory": normalize_test.module.canonical_bytes(inventory),
        "clusters": normalize_test.module.canonical_bytes(clusters),
        "preferences": normalize_test.module.canonical_bytes(preferences),
        "design": harness.canonical_bytes(design),
        "estimate": harness.canonical_bytes(estimate),
        "ai-workload-profile.json": (root / "ai-workload-profile.json").read_bytes(),
        "render-ai-discovery.json": (root / "render-ai-discovery.json").read_bytes(),
    }
    for path in sorted(
        generated.rglob("*"),
        key=lambda item: item.relative_to(generated).as_posix().encode(),
    ):
        if path.is_file():
            outputs[f"generated/{path.relative_to(generated).as_posix()}"] = path.read_bytes()
    return outputs


def test_complete_mocked_pipeline_replays_all_phases_from_same_inventory(tmp_path: Path) -> None:
    first = _materialize_independent_mixed_pipeline(tmp_path / "first")
    second = _materialize_independent_mixed_pipeline(tmp_path / "second")
    assert first == second

