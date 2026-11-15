"""Deterministic mixed-estate Design, Estimate, and Generate test harness."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess  # nosec B404 - fixed local validation tools, no shell
import sys
from html import escape
from pathlib import Path
from typing import Any

import jsonschema


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "plugins/aws-startup-advisor/skills/render-to-aws"
TOPOLOGY_KINDS = {
    "render.project",
    "render.environment",
    "render.environment_group",
    "render.preview_environment",
}
WORKFLOW_KINDS = {
    "render.workflow",
    "render.workflow_version",
    "render.workflow_task",
    "render.task_run",
    "render.task_attempt",
}
TARGETS = {
    "render.web_service": "ECS on Fargate",
    "render.static_site": "Amazon S3 + Amazon CloudFront",
    "render.private_service": "ECS on Fargate",
    "render.background_worker": "ECS on Fargate service",
    "render.cron_job": "Amazon EventBridge Scheduler + ECS on Fargate RunTask",
    "render.workflow": "AWS Step Functions Standard",
    "render.workflow_version": "AWS workflow definition version metadata",
    "render.workflow_task": "AWS Lambda",
    "render.task_run": "AWS workflow execution-history metadata",
    "render.task_attempt": "AWS workflow retry-attempt metadata",
    "render.postgres": "Amazon RDS for PostgreSQL",
    "render.key_value": "Amazon ElastiCache for Valkey node-based",
    "render.persistent_disk": "Amazon EFS",
    "render.environment_group": "AWS Secrets Manager + AWS Systems Manager Parameter Store",
    "render.project": "AWS account and VPC environment strategy",
    "render.environment": "AWS deployment environment stack",
    "render.custom_domain": "AWS Certificate Manager + external DNS",
    "render.preview_environment": "AWS CI/CD ephemeral stack pattern",
    "render.build_source": "Amazon ECR + CI/CD immutable digest promotion",
    "render.build_artifact": "Amazon ECR immutable image digest",
}
TARGET_FILES = {
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
CAPACITY_COSTS = {
    "render.web_service": 50.0,
    "render.static_site": 15.0,
    "render.private_service": 40.0,
    "render.background_worker": 30.0,
    "render.cron_job": 20.0,
    "render.workflow": 25.0,
    "render.workflow_task": 10.0,
    "render.postgres": 100.0,
    "render.key_value": 50.0,
    "render.environment_group": 2.0,
    "render.build_source": 10.0,
    "render.build_artifact": 0.0,
    "render.custom_domain": 0.0,
    "render.project": 0.0,
    "render.environment": 0.0,
    "render.preview_environment": 0.0,
    "render.workflow_version": 0.0,
    "render.task_run": 0.0,
    "render.task_attempt": 0.0,
}
RIGHT_SIZED_FACTORS = {
    "render.web_service": 0.8,
    "render.private_service": 0.875,
    "render.background_worker": 5 / 6,
    "render.cron_job": 0.75,
    "render.workflow": 0.8,
    "render.workflow_task": 0.8,
    "render.postgres": 0.8,
    "render.key_value": 0.8,
}
# Smallest node target in knowledge/design/keyvalue-elasticache-sizing.json; the
# Design mapping carries it so Generate emits exactly the selected node type.
VALKEY_NODE_TYPE = "cache.t4g.micro"
VALKEY_ENGINE_VERSION = "8.0"


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _ordered(value: str) -> list[dict[str, Any]]:
    return [{"ordinal": 1, "value": value}]


def design_from_inventory(
    inventory: dict[str, Any],
    preferences: dict[str, Any],
    inventory_fingerprint: str,
    preferences_fingerprint: str,
) -> dict[str, Any]:
    mappings = []
    for resource in inventory["resources"]:
        kind = resource["kind"]
        if kind not in TARGETS:
            raise AssertionError(f"no selector for {kind}")
        selected = TARGETS[kind]
        alternative = "Alternative requiring evidence absent from the completed preferences"
        aws_config: dict[str, Any] = {
            "selection_source": "canonical_inventory_and_completed_preferences",
            "source_kind": kind,
        }
        if kind == "render.key_value":
            aws_config["node_type"] = VALKEY_NODE_TYPE
        mappings.append(
            {
                "source_resource_id": resource["id"],
                "render_kind": kind,
                "aws_service": selected,
                "aws_config": aws_config,
                "confidence": "deterministic" if kind in {"render.static_site", "render.build_source", "render.build_artifact"} else "inferred",
                "disposition": "consumed_topology" if kind in TOPOLOGY_KINDS else "mapped",
                "rationale": f"The ordered {kind} selector resolves to {selected} from the completed migration preferences.",
                "decision": {
                    "selector": f"render.{kind.removeprefix('render.')}",
                    "candidate_set": [selected, alternative],
                    "evidence": _ordered(f"Canonical inventory contains {kind} and all decision-driving preferences are complete."),
                    "rules_evaluated": _ordered("Apply eliminators, deterministic mappings, and the ordered service rubric."),
                    "rules_fired": _ordered(f"The first decisive rule selects {selected}."),
                    "questions_asked": [],
                    "defaults_used": [],
                    "rejected_candidates": [{"ordinal": 1, "aws_service": alternative, "reason": "No captured requirement fires that alternative."}],
                },
            }
        )
    mappings.sort(key=lambda row: row["source_resource_id"].encode())
    source_ids = [row["source_resource_id"] for row in mappings]
    return {
        "schema_version": "1.0",
        "phase": "design",
        "inventory_fingerprint": inventory_fingerprint,
        "preferences_fingerprint": preferences_fingerprint,
        "mappings": mappings,
        "accounting": {
            "inventory_resource_count": len(source_ids),
            "mapped_resource_count": len(source_ids),
            "accounted_resource_ids": source_ids,
        },
        "ai_track": {**preferences["ai_track"], "infrastructure_status": "completed"},
    }


def estimate_from_design(design: dict[str, Any]) -> dict[str, Any]:
    scenarios: dict[str, dict[str, Any]] = {}
    for scenario_name in ("capacity_preserving", "right_sized"):
        lines = []
        for index, mapping in enumerate(design["mappings"], 1):
            kind = mapping["render_kind"]
            amount = CAPACITY_COSTS.get(kind)
            if kind == "render.persistent_disk":
                amount = None
            evidence_sufficient = scenario_name == "right_sized" and kind in RIGHT_SIZED_FACTORS
            if amount is not None and evidence_sufficient:
                amount = round(amount * RIGHT_SIZED_FACTORS[kind], 2)
            lines.append(
                {
                    "line_id": f"line-{index:03d}",
                    "source_resource_id": mapping["source_resource_id"],
                    "aws_service": mapping["aws_service"],
                    "monthly_amount": amount,
                    "pricing_source": "unavailable" if amount is None else ("no_direct_charge" if amount == 0 else "cached"),
                    "confidence": "measured" if evidence_sufficient else mapping["confidence"],
                    "exclusion_reason": "No reviewed EFS rate row" if amount is None else None,
                    "evidence_sufficient": evidence_sufficient,
                }
            )
        known = round(sum(row["monthly_amount"] for row in lines if row["monthly_amount"] is not None), 2)
        missing = [row["line_id"] for row in lines if row["monthly_amount"] is None]
        scenarios[scenario_name] = {
            "known_cost_monthly_usd": known,
            "is_floor": bool(missing),
            "unpriced_line_ids": missing,
            "lines": lines,
        }
    capacity = scenarios["capacity_preserving"]["known_cost_monthly_usd"]
    right_sized = scenarios["right_sized"]["known_cost_monthly_usd"]
    delta = round(right_sized - capacity, 2)
    return {
        "phase": "estimate",
        "design_source": "aws-design.json",
        "timestamp": "2026-10-21T12:00:00Z",
        "pricing_source": {
            "status": "cached",
            "message": "Deterministic mixed-estate rates use the reviewed cache; EFS remains unavailable.",
            "services_by_source": {"cached": sorted({row["aws_service"] for row in design["mappings"]}), "fallback": [], "estimated": []},
            "services_with_missing_fallback": ["efs"],
        },
        "accuracy_confidence": "known-cost floors; EFS is unpriced",
        "current_costs": {"source": "user_stated", "render_monthly": 123.45, "baseline_note": "Fixture user-stated monthly amount", "breakdown": {}},
        "projected_costs": {
            "aws_monthly_premium": capacity,
            "aws_monthly_balanced": capacity,
            "aws_monthly_optimized": right_sized,
            "aws_annual_optimized": round(right_sized * 12, 2),
            "breakdown": {},
        },
        "scenarios": scenarios,
        "delta_monthly_usd": delta,
        "delta_explanation": f"Evidence-based right-sizing changes the known-cost floor by ${delta:.2f}; EFS remains unpriced.",
        "cost_comparison": {},
        "migration_cost_considerations": {"human_labor_monthly_usd": None},
        "roi_analysis": {},
        "optimization_opportunities": [],
        "complexity_tier": "large",
        "complexity_inputs": {"service_count": len(design["mappings"])},
        "financial_summary": {},
        "recommendation": {"path": "migrate_phased", "migrate_if": ["Validate EFS pricing"], "stay_if": []},
        "ai_track": {"status": "deferred_shared_ai_engine", "estimated_cost": None},
    }


def ledger_from_design(design: dict[str, Any]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {name: [] for name in ("generated", "consumed_topology", "deferred", "unsupported")}
    for mapping in design["mappings"]:
        kind = mapping["render_kind"]
        target_files = TARGET_FILES.get(kind, ["MIGRATION_GUIDE.md"])
        bucket = "generated"
        if kind in WORKFLOW_KINDS:
            bucket, target_files = "unsupported", []
        elif mapping["disposition"] == "consumed_topology":
            bucket = "consumed_topology"
        buckets[bucket].append(
            {
                "source_resource_id": mapping["source_resource_id"],
                "render_kind": kind,
                "aws_service": mapping["aws_service"],
                "reason": "Classification is derived from the same canonical Design mapping.",
                "target_files": target_files,
            }
        )
    source_ids = [row["source_resource_id"] for row in design["mappings"]]
    warnings = [
        {"code": "deferred_shared_ai_engine", "subject": "AI execution", "detail": "AI execution remains deferred to the provider-neutral shared engine.", "blocking": False},
        {"code": "conditional_workflow_generation_unsupported", "subject": "Workflow artifacts", "detail": "Workflow execution semantics require manual validation before artifact generation.", "blocking": False},
        {"code": "unpriced_cost_floor", "subject": "Estimate floor", "detail": "EFS has no reviewed rate and both totals are known-cost floors.", "blocking": False},
    ]
    return {
        "schema_version": "1.0",
        "phase": "generate",
        **buckets,
        "warnings": warnings,
        "accounting": {
            "design_count": len(source_ids),
            "generated_count": len(buckets["generated"]),
            "consumed_topology_count": len(buckets["consumed_topology"]),
            "deferred_count": len(buckets["deferred"]),
            "unsupported_count": len(buckets["unsupported"]),
            "accounted_count": len(source_ids),
            "source_resource_ids": source_ids,
        },
    }


def _bindings(rows: list[dict[str, Any]], relative_file: str) -> str:
    selected = [row for row in rows if relative_file in TARGET_FILES.get(row["render_kind"], [])]
    prefix = Path(relative_file).stem.replace("-", "_")
    blocks = []
    for index, row in enumerate(selected, 1):
        blocks.append(
            f'''resource "terraform_data" "source_{prefix}_{index:03d}" {{
  input = {{
    source_resource_id = "{row['source_resource_id']}"
    aws_service        = "{row['aws_service']}"
  }}
}}
'''
        )
    return "\n".join(blocks)


def _mappings_for_kind(mappings: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    matches = [row for row in mappings if row["render_kind"] == kind]
    if not matches:
        raise AssertionError(f"expected at least one {kind} mapping")
    return matches


def _mapping_name(kind: str, index: int) -> str:
    prefix = {
        "render.web_service": "web",
        "render.private_service": "private",
        "render.background_worker": "worker",
        "render.cron_job": "cron",
    }[kind]
    return prefix if index == 1 else f"{prefix}_{index:03d}"


def _image_variable_block(name: str, source_id: str, digest_digit: str) -> str:
    return f'''variable "{name}_image" {{
  description = "Immutable ECR image for Render source resource {source_id}."
  type        = string
  default     = "000000000000.dkr.ecr.us-east-1.amazonaws.com/render-migration@sha256:{digest_digit * 64}"
  validation {{
    condition     = can(regex("^[0-9]{{12}}\\\\.dkr\\\\.ecr\\\\.[a-z0-9-]+\\\\.amazonaws\\\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{{64}}$", var.{name}_image))
    error_message = "{name}_image must be an immutable ECR digest reference."
  }}
}}
'''


def _web_blocks(name: str, source_id: str) -> tuple[str, str]:
    network = '''resource "aws_lb" "__NAME__" {
  name               = "render-__NAME_HYPHEN__"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.edge.id]
  subnets            = [aws_subnet.public.id]
}
resource "aws_lb_target_group" "__NAME__" {
  name        = "render-__NAME_HYPHEN__"
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check { path = "/health" }
}
resource "aws_lb_listener" "__NAME___https" {
  load_balancer_arn = aws_lb.__NAME__.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.issued_certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.__NAME__.arn
  }
}
'''
    compute = '''resource "aws_ecs_task_definition" "__NAME__" {
  family                   = "render-__NAME_HYPHEN__"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name         = "__NAME_HYPHEN__"
    image        = var.__NAME___image
    essential    = true
    portMappings = [{ containerPort = 8080, hostPort = 8080, protocol = "tcp" }]
  }])
  tags = { SourceResourceId = "__SOURCE_ID__" }
}
resource "aws_ecs_service" "__NAME__" {
  name            = "render-__NAME_HYPHEN__"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.__NAME__.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.web.id]
    subnets          = [aws_subnet.private.id]
  }
  load_balancer {
    container_name   = "__NAME_HYPHEN__"
    container_port   = 8080
    target_group_arn = aws_lb_target_group.__NAME__.arn
  }
  depends_on = [aws_lb_listener.__NAME___https]
  tags       = { SourceResourceId = "__SOURCE_ID__" }
}
'''
    substitutions = {"__NAME__": name, "__NAME_HYPHEN__": name.replace("_", "-"), "__SOURCE_ID__": source_id}
    for old, new in substitutions.items():
        network = network.replace(old, new)
        compute = compute.replace(old, new)
    return network, compute


def _service_blocks(name: str, source_id: str, kind: str) -> str:
    port = 10000 if kind == "private" else None
    security_group = "private" if kind == "private" else "worker"
    port_mapping = '    portMappings = [{ containerPort = 10000, hostPort = 10000, protocol = "tcp" }]\n' if port else ""
    registry = '''  service_registries {
    registry_arn = aws_service_discovery_service.__NAME__.arn
  }
''' if kind == "private" else ""
    discovery = '''resource "aws_service_discovery_service" "__NAME__" {
  name = "__NAME_HYPHEN__"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.application.id
    dns_records { ttl = 10, type = "A" }
    routing_policy = "MULTIVALUE"
  }
}
''' if kind == "private" else ""
    block = discovery + '''resource "aws_ecs_task_definition" "__NAME__" {
  family                   = "render-__NAME_HYPHEN__"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name      = "__NAME_HYPHEN__"
    image     = var.__NAME___image
    essential = true
__PORT_MAPPING__  }])
  tags = { SourceResourceId = "__SOURCE_ID__" }
}
resource "aws_ecs_service" "__NAME__" {
  name            = "render-__NAME_HYPHEN__"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.__NAME__.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.__SECURITY_GROUP__.id]
    subnets          = [aws_subnet.private.id]
  }
__REGISTRY__  tags = { SourceResourceId = "__SOURCE_ID__" }
}
'''
    substitutions = {
        "__NAME__": name,
        "__NAME_HYPHEN__": name.replace("_", "-"),
        "__SOURCE_ID__": source_id,
        "__PORT_MAPPING__": port_mapping,
        "__SECURITY_GROUP__": security_group,
        "__REGISTRY__": registry,
    }
    for old, new in substitutions.items():
        block = block.replace(old, new)
    return block


def _cron_blocks(name: str, source_id: str) -> str:
    return '''resource "aws_ecs_task_definition" "__NAME__" {
  family                   = "render-__NAME_HYPHEN__"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name      = "__NAME_HYPHEN__"
    image     = var.__NAME___image
    essential = true
  }])
  tags = { SourceResourceId = "__SOURCE_ID__" }
}
resource "aws_scheduler_schedule" "__NAME__" {
  name                = "render-__NAME_HYPHEN__"
  schedule_expression = "cron(0 * * * ? *)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn
    ecs_parameters {
      launch_type         = "FARGATE"
      task_definition_arn = aws_ecs_task_definition.__NAME__.arn
      network_configuration {
        assign_public_ip = false
        security_groups  = [aws_security_group.worker.id]
        subnets          = [aws_subnet.private.id]
      }
    }
  }
}
'''.replace("__NAME__", name).replace("__NAME_HYPHEN__", name.replace("_", "-")).replace("__SOURCE_ID__", source_id)


def _valkey_block(mapping: dict[str, Any], index: int) -> str:
    label = "valkey" if index == 1 else f"valkey_{index:03d}"
    if "Valkey" not in mapping["aws_service"]:
        raise AssertionError(f"render.key_value mapping {mapping['source_resource_id']} does not select Valkey")
    node_type = mapping["aws_config"].get("node_type")
    if not isinstance(node_type, str) or not node_type:
        raise AssertionError(f"node-based Valkey mapping {mapping['source_resource_id']} carries no aws_config.node_type")
    return f'''resource "aws_elasticache_replication_group" "{label}" {{
  replication_group_id       = "render-migration-{label.replace("_", "-")}"
  description                = "Render Key Value replacement"
  engine                     = "valkey"
  engine_version             = "{VALKEY_ENGINE_VERSION}"
  node_type                  = "{node_type}"
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.data.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}}
'''


def assert_cache_engine_parity(data_tf_text: str, design: dict[str, Any]) -> None:
    """Design's Valkey selection must reach the provider configuration unchanged."""
    engines = re.findall(r'^\s*engine\s*=\s*"([^"]*)"', data_tf_text, flags=re.MULTILINE)
    if "redis" in engines:
        raise AssertionError('data.tf sets engine = "redis" although Design selected Valkey')
    cache_blocks = re.findall(
        r'^resource "aws_elasticache_replication_group" "[^"]+" \{\n(.*?)^\}',
        data_tf_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    valkey_mappings = [
        row for row in design["mappings"]
        if row["render_kind"] == "render.key_value" and "Valkey" in row["aws_service"]
    ]
    if not valkey_mappings:
        raise AssertionError("expected at least one render.key_value mapping selecting Valkey")
    if len(cache_blocks) != len(valkey_mappings):
        raise AssertionError(
            f"data.tf declares {len(cache_blocks)} aws_elasticache_replication_group blocks for {len(valkey_mappings)} Valkey mappings"
        )
    for row, block in zip(valkey_mappings, cache_blocks):
        source_id = row["source_resource_id"]
        if not re.search(r'^\s*engine\s*=\s*"valkey"$', block, flags=re.MULTILINE):
            raise AssertionError(f'data.tf does not set engine = "valkey" for {source_id}')
        if not re.search(r'^\s*engine_version\s*=\s*"[0-9][0-9.]*"$', block, flags=re.MULTILINE):
            raise AssertionError(f"data.tf does not pin a Valkey engine_version for {source_id}")
        if "node-based" in row["aws_service"]:
            node_type = row["aws_config"].get("node_type")
            if not isinstance(node_type, str) or not node_type:
                raise AssertionError(f"node-based Valkey mapping {source_id} carries no aws_config.node_type")
            if not re.search(rf'^\s*node_type\s*=\s*"{re.escape(node_type)}"$', block, flags=re.MULTILINE):
                raise AssertionError(f'data.tf does not set node_type = "{node_type}" selected for {source_id}')


def _terraform_files(mappings: list[dict[str, Any]], accounted: int, generated: int, unsupported: int) -> dict[str, str]:
    compute_kinds = ("render.web_service", "render.private_service", "render.background_worker", "render.cron_job")
    mappings_by_kind = {kind: _mappings_for_kind(mappings, kind) for kind in compute_kinds}
    main = '''terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
}
provider "aws" {
  region = var.aws_region
  default_tags {
    tags = { ManagedBy = "terraform", Migration = "render-to-aws" }
  }
}
'''
    variables = '''variable "aws_region" {
  description = "AWS Region selected during Clarify."
  type        = string
  default     = "us-east-1"
}
variable "issued_certificate_arn" {
  description = "ARN of an ACM certificate already validated and issued for the public web service."
  type        = string
  validation {
    condition     = can(regex("^arn:aws(?:-[a-z]+)?:acm:[a-z0-9-]+:[0-9]{12}:certificate/[0-9a-fA-F-]{36}$", var.issued_certificate_arn))
    error_message = "issued_certificate_arn must be a non-empty ACM certificate ARN."
  }
}
'''
    digest_digits = iter("123456789abcdef")
    for kind in compute_kinds:
        for index, mapping in enumerate(mappings_by_kind[kind], 1):
            variables += _image_variable_block(
                _mapping_name(kind, index),
                mapping["source_resource_id"],
                next(digest_digits),
            )
    network = '''resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
}
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.42.101.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = true
}
resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.42.1.0/24"
  availability_zone = "us-east-1a"
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}
resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}
resource "aws_eip" "nat" {
  domain     = "vpc"
  depends_on = [aws_internet_gateway.main]
}
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public.id
  depends_on    = [aws_route_table_association.public]
}
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
}
resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}
resource "aws_security_group" "edge" {
  name        = "render-migration-edge"
  description = "Public edge"
  vpc_id      = aws_vpc.main.id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_security_group" "web" {
  name        = "render-migration-web"
  description = "ALB to web only"
  vpc_id      = aws_vpc.main.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_security_group_rule" "edge_to_web_egress" {
  type                     = "egress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  security_group_id        = aws_security_group.edge.id
  source_security_group_id = aws_security_group.web.id
}
resource "aws_security_group_rule" "edge_to_web_ingress" {
  type                     = "ingress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  security_group_id        = aws_security_group.web.id
  source_security_group_id = aws_security_group.edge.id
}
resource "aws_security_group" "worker" {
  name        = "render-migration-worker"
  description = "Established private-service caller"
  vpc_id      = aws_vpc.main.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_security_group" "private" {
  name        = "render-migration-private"
  description = "Worker to private service only"
  vpc_id      = aws_vpc.main.id
  ingress {
    from_port       = 10000
    to_port         = 10000
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_security_group" "data" {
  name        = "render-migration-data"
  description = "Private data access from application tasks"
  vpc_id      = aws_vpc.main.id
  ingress {
    description     = "PostgreSQL from application tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.web.id, aws_security_group.private.id, aws_security_group.worker.id]
  }
  ingress {
    description     = "Valkey from application tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.web.id, aws_security_group.private.id, aws_security_group.worker.id]
  }
}
resource "aws_lb" "web" {
  name               = "render-migration-web"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.edge.id]
  subnets            = [aws_subnet.public.id]
}
resource "aws_lb_target_group" "web" {
  name        = "render-migration-web"
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check { path = "/health" }
}
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.web.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.issued_certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
'''
    compute = '''resource "aws_ecs_cluster" "main" {
  name = "render-migration"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}
resource "aws_cloudwatch_log_group" "application" {
  name              = "/render-migration/application"
  retention_in_days = 30
}
resource "aws_iam_role" "ecs_execution" {
  name = "render-migration-ecs-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}
resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
resource "aws_ecs_task_definition" "web" {
  family                   = "render-migration-web"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name         = "web"
    image        = var.web_image
    essential    = true
    portMappings = [{ containerPort = 8080, hostPort = 8080, protocol = "tcp" }]
  }])
  tags = { SourceResourceId = "__WEB_SOURCE_ID__" }
}
resource "aws_ecs_service" "web" {
  name            = "render-migration-web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.web.id]
    subnets          = [aws_subnet.private.id]
  }
  load_balancer {
    container_name   = "web"
    container_port   = 8080
    target_group_arn = aws_lb_target_group.web.arn
  }
  depends_on = [aws_lb_listener.https]
  tags       = { SourceResourceId = "__WEB_SOURCE_ID__" }
}
resource "aws_service_discovery_private_dns_namespace" "application" {
  name = "production.render-migration.internal"
  vpc  = aws_vpc.main.id
}
resource "aws_service_discovery_service" "private" {
  name = "private"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.application.id
    dns_records {
      ttl  = 10
      type = "A"
    }
    routing_policy = "MULTIVALUE"
  }
}
resource "aws_ecs_task_definition" "private" {
  family                   = "render-migration-private"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name         = "private"
    image        = var.private_image
    essential    = true
    portMappings = [{ containerPort = 10000, hostPort = 10000, protocol = "tcp" }]
    mountPoints = [{
      sourceVolume  = "private-data"
      containerPath = "/var/data"
      readOnly      = false
    }]
  }])
  tags = { SourceResourceId = "__PRIVATE_SOURCE_ID__" }
  volume {
    name = "private-data"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.application.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.application.id
        iam             = "DISABLED"
      }
    }
  }
}
resource "aws_ecs_service" "private" {
  name            = "render-migration-private"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.private.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.private.id]
    subnets          = [aws_subnet.private.id]
  }
  service_registries {
    registry_arn = aws_service_discovery_service.private.arn
  }
  depends_on = [aws_efs_mount_target.application]
  tags       = { SourceResourceId = "__PRIVATE_SOURCE_ID__" }
}
resource "aws_ecs_task_definition" "worker" {
  family                   = "render-migration-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name        = "worker"
    image       = var.worker_image
    essential   = true
    stopTimeout = 30
  }])
  tags = { SourceResourceId = "__WORKER_SOURCE_ID__" }
}
resource "aws_ecs_service" "worker" {
  name            = "render-migration-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    assign_public_ip = false
    security_groups  = [aws_security_group.worker.id]
    subnets          = [aws_subnet.private.id]
  }
  tags = { SourceResourceId = "__WORKER_SOURCE_ID__" }
}
resource "aws_ecs_task_definition" "cron" {
  family                   = "render-migration-cron"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  container_definitions = jsonencode([{
    name      = "cron"
    image     = var.cron_image
    essential = true
  }])
  tags = { SourceResourceId = "__CRON_SOURCE_ID__" }
}
resource "aws_iam_role" "scheduler" {
  name = "render-migration-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}
resource "aws_iam_role_policy" "scheduler" {
  name = "run-selected-tasks"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecs:RunTask"], Resource = [__CRON_TASK_ARNS__] },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.ecs_execution.arn]
        Condition = {
          StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" }
        }
      }
    ]
  })
}
resource "aws_scheduler_schedule" "cron" {
  name                = "render-migration-cron"
  schedule_expression = "cron(0 * * * ? *)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn
    ecs_parameters {
      launch_type         = "FARGATE"
      task_definition_arn = aws_ecs_task_definition.cron.arn
      network_configuration {
        assign_public_ip = false
        security_groups  = [aws_security_group.worker.id]
        subnets          = [aws_subnet.private.id]
      }
    }
  }
}
'''
    data = '''resource "aws_db_subnet_group" "main" {
  name       = "render-migration"
  subnet_ids = [aws_subnet.private.id]
}
resource "aws_db_instance" "postgres" {
  allocated_storage           = 100
  engine                      = "postgres"
  instance_class              = "db.m6g.large"
  username                    = "migration_admin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.main.name
  vpc_security_group_ids      = [aws_security_group.data.id]
  publicly_accessible         = false
  storage_encrypted           = true
  skip_final_snapshot         = true
}
resource "aws_elasticache_subnet_group" "main" {
  name       = "render-migration"
  subnet_ids = [aws_subnet.private.id]
}
'''
    for index, mapping in enumerate(_mappings_for_kind(mappings, "render.key_value"), 1):
        data += _valkey_block(mapping, index)
    storage = '''resource "aws_security_group" "efs" {
  name        = "render-migration-efs"
  description = "NFS from the disk-owning private task only"
  vpc_id      = aws_vpc.main.id
  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.private.id]
  }
}
resource "aws_efs_file_system" "application" {
  encrypted = true
}
resource "aws_efs_mount_target" "application" {
  file_system_id  = aws_efs_file_system.application.id
  subnet_id       = aws_subnet.private.id
  security_groups = [aws_security_group.efs.id]
}
resource "aws_efs_access_point" "application" {
  file_system_id = aws_efs_file_system.application.id
  root_directory { path = "/var/data" }
}
'''
    delivery = '''resource "aws_ecr_repository" "application" {
  name                 = "render-migration"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}
resource "aws_s3_bucket" "static" {
  bucket_prefix = "render-migration-static-"
}
resource "aws_s3_bucket_versioning" "static" {
  bucket = aws_s3_bucket.static.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "static" {
  bucket = aws_s3_bucket.static.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_public_access_block" "static" {
  bucket                  = aws_s3_bucket.static.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_cloudfront_origin_access_control" "static" {
  name                              = "render-migration-static"
  description                       = "Private access to the static migration origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}
resource "aws_cloudfront_distribution" "static" {
  enabled = true
  origin {
    domain_name              = aws_s3_bucket.static.bucket_regional_domain_name
    origin_id                = "static-origin"
    origin_access_control_id = aws_cloudfront_origin_access_control.static.id
  }
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "static-origin"
    viewer_protocol_policy = "redirect-to-https"
    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }
  }
  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
resource "aws_s3_bucket_policy" "static_cloudfront" {
  bucket = aws_s3_bucket.static.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontRead"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.static.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.static.arn
        }
      }
    }]
  })
}
'''
    first_by_kind = {kind: rows[0] for kind, rows in mappings_by_kind.items()}
    compute = (
        compute.replace("__WEB_SOURCE_ID__", first_by_kind["render.web_service"]["source_resource_id"])
        .replace("__PRIVATE_SOURCE_ID__", first_by_kind["render.private_service"]["source_resource_id"])
        .replace("__WORKER_SOURCE_ID__", first_by_kind["render.background_worker"]["source_resource_id"])
        .replace("__CRON_SOURCE_ID__", first_by_kind["render.cron_job"]["source_resource_id"])
    )
    for index, mapping in enumerate(mappings_by_kind["render.web_service"][1:], 2):
        name = _mapping_name("render.web_service", index)
        extra_network, extra_compute = _web_blocks(name, mapping["source_resource_id"])
        network += extra_network
        compute += extra_compute
    for kind, service_kind in (("render.private_service", "private"), ("render.background_worker", "worker")):
        for index, mapping in enumerate(mappings_by_kind[kind][1:], 2):
            compute += _service_blocks(_mapping_name(kind, index), mapping["source_resource_id"], service_kind)
    for index, mapping in enumerate(mappings_by_kind["render.cron_job"][1:], 2):
        compute += _cron_blocks(_mapping_name("render.cron_job", index), mapping["source_resource_id"])
    cron_task_arns = ", ".join(
        f"aws_ecs_task_definition.{_mapping_name('render.cron_job', index)}.arn"
        for index, _mapping in enumerate(mappings_by_kind["render.cron_job"], 1)
    )
    compute = compute.replace("__CRON_TASK_ARNS__", cron_task_arns)
    return {
        "main.tf": main,
        "variables.tf": variables,
        "outputs.tf": f'''output "migration_summary" {{
  description = "Deterministic source accounting for this migration pack."
  value = {{
    accounted_count   = {accounted}
    generated_count   = {generated}
    unsupported_count = {unsupported}
  }}
}}
''',
        "network.tf": network,
        "compute.tf": compute + "\n" + _bindings(mappings, "terraform/compute.tf"),
        "data.tf": data + "\n" + _bindings(mappings, "terraform/data.tf"),
        "storage.tf": storage + "\n" + _bindings(mappings, "terraform/storage.tf"),
        "delivery.tf": delivery + "\n" + _bindings(mappings, "terraform/delivery.tf"),
    }


def _write_text(path: Path, value: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _artifact_digest(generated: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(generated.rglob("*"), key=lambda item: item.relative_to(generated).as_posix().encode()):
        if not path.is_file() or ".terraform" in path.parts or path.name == "validation-report.json":
            continue
        digest.update(path.relative_to(generated).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 - fixed local validators and generated fixture paths
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_listener_uses_issued_certificate(network: str) -> None:
    if re.search(r"certificate_arn\s*=\s*aws_acm_certificate\.", network):
        raise AssertionError("listener must not consume a newly requested, potentially pending certificate")
    if not re.search(r"certificate_arn\s*=\s*var\.issued_certificate_arn", network):
        raise AssertionError("listener must consume the required pre-issued ACM certificate ARN")


def assert_generated_infrastructure_graph(terraform: Path) -> None:
    network = (terraform / "network.tf").read_text(encoding="utf-8")
    compute = (terraform / "compute.tf").read_text(encoding="utf-8")
    delivery = (terraform / "delivery.tf").read_text(encoding="utf-8")
    variables = (terraform / "variables.tf").read_text(encoding="utf-8")
    _assert_listener_uses_issued_certificate(network)
    assert 'variable "issued_certificate_arn"' in variables
    assert "issued_certificate_arn must be a non-empty ACM certificate ARN" in variables
    certificate_block = variables.split('variable "issued_certificate_arn"', 1)[1].split("}\n", 1)[0]
    assert "default" not in certificate_block

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
    assert 'Principal = { Service = "scheduler.amazonaws.com" }' in compute
    assert 'resource "aws_iam_role_policy" "scheduler"' in compute
    assert re.search(r'Action\s*=\s*\["ecs:RunTask"\]', compute)
    assert re.search(r'Action\s*=\s*\["iam:PassRole"\]', compute)
    assert re.search(r'Resource\s*=\s*\[aws_iam_role\.ecs_execution\.arn\]', compute)
    assert '"iam:PassedToService" = "ecs-tasks.amazonaws.com"' in compute
    assert 'role_arn = aws_iam_role.scheduler.arn' in compute
    assert "arn:aws:iam::000000000000:role/render-migration-scheduler" not in compute
    schedule_count = compute.count('resource "aws_scheduler_schedule"')
    assert schedule_count > 0
    assert compute.count("network_configuration {") >= schedule_count + 3
    assert compute.count("security_groups  = [aws_security_group.worker.id]") >= schedule_count + 1
    private_subnet_bindings = re.findall(
        r"subnets\s*=\s*(?:\[aws_subnet\.private\.id\]|aws_subnet\.private\[\*\]\.id)",
        compute,
    )
    assert len(private_subnet_bindings) >= schedule_count + 3

    data = (terraform / "data.tf").read_text(encoding="utf-8")
    assert re.search(r'from_port\s*=\s*5432', network)
    assert re.search(r'from_port\s*=\s*6379', network)
    for security_group in ("web", "private", "worker"):
        assert f"aws_security_group.{security_group}.id" in network
    assert 'vpc_security_group_ids      = [aws_security_group.data.id]' in data
    assert 'security_group_ids         = [aws_security_group.data.id]' in data

    for name in ("web", "private", "worker", "cron"):
        assert f'resource "aws_ecs_task_definition" "{name}"' in compute
        assert f"image" in compute and f"var.{name}_image" in compute
    for name in ("web", "private", "worker"):
        assert f'resource "aws_ecs_service" "{name}"' in compute
    assert "aws_lb_target_group.web.arn" in compute
    assert "security_groups  = [aws_security_group.web.id]" in compute
    assert "security_groups  = [aws_security_group.private.id]" in compute
    assert "security_groups  = [aws_security_group.worker.id]" in compute
    assert "task_definition_arn = aws_ecs_task_definition.cron.arn" in compute
    image_references = {re.search(rf"image\s*=\s*(var\.{name}_image)", compute).group(1) for name in ("web", "private", "worker", "cron")}
    assert len(image_references) == 4


REGISTRY_TRANSPORT_SIGNATURES = (
    "lookup registry.terraform.io",
    "no such host",
    "i/o timeout",
    "connection refused",
    "network is unreachable",
)
REGISTRY_CONNECTIVITY_SIGNATURES = (
    "could not connect to registry.terraform.io",
    "tls handshake timeout",
)
REJECTED_INIT_SIGNATURES = (
    "checksum",
    "does not match",
    "doesn't match",
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "invalid provider",
    "unsupported",
    "invalid configuration",
    "lock file",
    "no available releases match",
)


def classify_terraform_init_failure(output: str) -> str | None:
    """Return provider_registry_unavailable only for registry DNS/connectivity failures.

    Checksum, authentication, configuration, and lock-file diagnostics return None
    so the caller keeps them as hard failures, even when they also name the
    registry host or appear alongside a transport error.
    """
    text = output.lower()
    if any(signature in text for signature in REJECTED_INIT_SIGNATURES):
        return None
    transport = any(signature in text for signature in REGISTRY_TRANSPORT_SIGNATURES)
    if "dial tcp" in text and transport:
        return "provider_registry_unavailable"
    if any(signature in text for signature in REGISTRY_CONNECTIVITY_SIGNATURES):
        return "provider_registry_unavailable"
    if "failed to query available provider packages" in text and transport:
        return "provider_registry_unavailable"
    return None


def _validate_generated_pack(root: Path, generated: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    terraform = generated / "terraform"
    assert_generated_infrastructure_graph(terraform)
    terraform_binary = shutil.which("terraform")
    gitleaks_binary = shutil.which("gitleaks")
    mise_binary = shutil.which("mise")
    if terraform_binary is None or (gitleaks_binary is None and mise_binary is None):
        raise AssertionError("terraform and project-managed gitleaks are required to validate a completed generated pack")

    artifact_digest = _artifact_digest(generated)
    fmt = _run([terraform_binary, "fmt", "-check", "-recursive", str(terraform)], root)
    if fmt.returncode != 0:
        raise AssertionError(fmt.stdout + fmt.stderr)

    init = _run([terraform_binary, "init", "-backend=false", "-input=false"], terraform)
    registry_failure = (
        init.returncode != 0
        and classify_terraform_init_failure(init.stdout + init.stderr) == "provider_registry_unavailable"
    )
    if init.returncode != 0 and not registry_failure:
        raise AssertionError(init.stdout + init.stderr)
    if registry_failure:
        validate_status = "provider_registry_unavailable"
    else:
        validate = _run([terraform_binary, "validate"], terraform)
        if validate.returncode != 0:
            raise AssertionError(validate.stdout + validate.stderr)
        validate_status = "passed"

    policy = REPO_ROOT / "plugins/aws-startup-advisor/skills/tf-best-practices/scripts/validate-terraform-policy.py"
    policy_result = _run([sys.executable, str(policy), str(terraform)], root)
    if policy_result.returncode != 0 or not policy_result.stdout.startswith("POLICY_OK"):
        raise AssertionError(policy_result.stdout + policy_result.stderr)

    jsonschema.Draft202012Validator(
        json.loads((SKILL_ROOT / "references/shared/schema-generation-warnings.json").read_text(encoding="utf-8"))
    ).validate(ledger)
    report_script = SKILL_ROOT / "scripts/validate-render-migration-report.py"
    report_result = _run(
        [sys.executable, str(report_script), str(generated / "migration-report.html"), "--migration-dir", str(root)],
        root,
    )
    if report_result.returncode != 0 or report_result.stdout.strip() != "REPORT_OK":
        raise AssertionError(report_result.stdout + report_result.stderr)

    secret_command = [gitleaks_binary] if gitleaks_binary is not None else [mise_binary, "exec", "gitleaks", "--", "gitleaks"]
    secret = _run(secret_command + ["detect", "--no-git", "--source", str(generated), "--no-banner"], root)
    if secret.returncode != 0:
        raise AssertionError(secret.stdout + secret.stderr)

    shutil.rmtree(terraform / ".terraform", ignore_errors=True)
    lock = terraform / ".terraform.lock.hcl"
    if lock.exists():
        lock.unlink()

    status = "passed_degraded_offline" if registry_failure else "passed"
    init_status = "provider_registry_unavailable" if registry_failure else "passed"
    evidence = f"Executed against final artifacts excluding this report; artifact_digest={artifact_digest}"
    return {
        "schema_version": "1.0",
        "status": status,
        "offline_fallback_used": registry_failure,
        "checks": {
            "terraform_fmt": {"status": "passed", "command": "terraform fmt -check -recursive terraform", "evidence": evidence},
            "terraform_init": {"status": init_status, "command": "terraform init -backend=false -input=false", "evidence": evidence},
            "terraform_validate": {"status": validate_status, "command": "terraform validate", "evidence": evidence},
            "policy": {"status": "passed", "command": "validate-terraform-policy.py terraform", "evidence": evidence, "policy_status": "POLICY_OK", "violations": []},
            "secret_scan": {"status": "passed", "command": "gitleaks detect --no-git --source generated", "evidence": evidence},
            "schemas": {"status": "passed", "command": "jsonschema generated artifacts", "evidence": evidence},
            "report": {"status": "passed", "command": "validate-render-migration-report.py", "evidence": evidence},
        },
        "timestamp": "2026-10-21T12:00:00Z",
    }


def _promotion_script() -> str:
    return r'''#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "usage: promote-image.sh ECR_REPOSITORY_URL SHA256_DIGEST TARGET_ENVIRONMENT [--execute]" >&2
  exit 2
fi
repository_url=$1
digest=$2
target_environment=$3
mode=${4:-}
if [[ ! $repository_url =~ ^([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/([a-z0-9][a-z0-9._/-]*)$ ]]; then
  echo "repository must be an ECR repository URL" >&2
  exit 2
fi
registry_id=${BASH_REMATCH[1]}
region=${BASH_REMATCH[2]}
repository_name=${BASH_REMATCH[3]}
if [[ ! $digest =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "digest must be an immutable lowercase sha256 value; tags such as latest are rejected" >&2
  exit 2
fi
if [[ ! $target_environment =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]]; then
  echo "target environment must use lowercase letters, digits, and hyphens" >&2
  exit 2
fi
if [[ -n $mode && $mode != "--execute" ]]; then
  echo "unknown argument: $mode" >&2
  exit 2
fi

image_reference="${repository_url}@${digest}"
digest_short=${digest#sha256:}
digest_short=${digest_short:0:12}
promotion_tag="deploy-${target_environment}-${digest_short}"
if [[ $mode != "--execute" ]]; then
  printf 'PROMOTION_DRY_RUN environment=%s image=%s immutable_tag=%s\n' \
    "$target_environment" "$image_reference" "$promotion_tag"
  printf 'Re-run with --execute to verify the source digest and create the immutable environment tag without rebuilding.\n'
  exit 0
fi

command -v aws >/dev/null 2>&1 || {
  echo "aws CLI is required for --execute" >&2
  exit 1
}
mutability=$(aws ecr describe-repositories \
  --registry-id "$registry_id" \
  --region "$region" \
  --repository-names "$repository_name" \
  --query 'repositories[0].imageTagMutability' \
  --output text)
if [[ $mutability != "IMMUTABLE" ]]; then
  echo "target ECR repository must enforce immutable tags" >&2
  exit 1
fi
IFS=$'\t' read -r resolved_digest image_manifest < <(
  aws ecr batch-get-image \
    --registry-id "$registry_id" \
    --region "$region" \
    --repository-name "$repository_name" \
    --image-ids "imageDigest=$digest" \
    --accepted-media-types application/vnd.oci.image.manifest.v1+json application/vnd.docker.distribution.manifest.v2+json \
    --query 'images[0].[imageId.imageDigest,imageManifest]' \
    --output text
)
if [[ $resolved_digest != "$digest" || -z $image_manifest || $image_manifest == "None" ]]; then
  echo "source digest was not found exactly in the target ECR repository" >&2
  exit 1
fi
aws ecr put-image \
  --registry-id "$registry_id" \
  --region "$region" \
  --repository-name "$repository_name" \
  --image-manifest "$image_manifest" \
  --image-tag "$promotion_tag" \
  --output json >/dev/null
printf 'PROMOTION_COMPLETE environment=%s image=%s immutable_tag=%s\n' \
  "$target_environment" "$image_reference" "$promotion_tag"
'''


def emit_pack(root: Path, design: dict[str, Any], estimate: dict[str, Any], ledger: dict[str, Any]) -> Path:
    generated = root / "generated"
    terraform = generated / "terraform"
    scripts = generated / "scripts"
    terraform.mkdir(parents=True)
    scripts.mkdir(parents=True)
    for name, content in _terraform_files(
        design["mappings"],
        ledger["accounting"]["accounted_count"],
        ledger["accounting"]["generated_count"],
        ledger["accounting"]["unsupported_count"],
    ).items():
        _write_text(terraform / name, content)
    _write_text(
        terraform / "README.md",
        "# Terraform\n\nBalanced infrastructure generated from the canonical Design mappings. For external DNS, request the public certificate in ACM, create its DNS validation records, wait for `Issued`, then supply `issued_certificate_arn`. Each service uses its own immutable image input bound to its Render source ID.",
    )
    _write_text(
        terraform / "terraform.tfvars.example",
        'aws_region = "us-east-1"\nissued_certificate_arn = "arn:aws:acm:us-east-1:000000000000:certificate/11111111-1111-4111-8111-111111111111"',
    )
    _write_text(terraform / ".gitignore", ".terraform/\n*.tfstate\n*.tfstate.*")

    source_rows = "\n".join(f"- `{row['source_resource_id']}` → {row['aws_service']}" for row in design["mappings"])
    guide = f'''# Render-to-AWS migration guide

## Overview and scope

This pack is generated from one normalized mixed estate. AI remains `deferred_shared_ai_engine`; Workflow artifacts are `conditional_workflow_generation_unsupported`.

## Prerequisites

Confirm AWS credentials, region, Terraform, source retention, external DNS, migration owners, and maintenance windows. Request the public certificate in ACM, create every DNS validation record at the external DNS provider, wait until ACM reports `Issued`, and provide its ARN as `issued_certificate_arn` before apply.

## Build and deployment migration

Build once into ECR, then run `scripts/promote-image.sh ECR_REPOSITORY_URL SHA256_DIGEST TARGET_ENVIRONMENT` in dry-run mode and repeat with `--execute`. The helper verifies the immutable repository and exact digest, creates the environment promotion tag from the same manifest without rebuilding, and emits the exact `repository@sha256:...` deployment reference. Preserve the serving deploy and auto-deploy state, and retain rollback lineage.

## PostgreSQL migration

Validate PostgreSQL privileges, use Database Migration Service, quiesce writers, verify integrity, and retain the source.

## Key Value migration

Verify cache persistence and eviction semantics before switching endpoints.

## Persistent-disk migration

Pre-copy `/var/data` to EFS, apply the final delta under writer quiescence, and verify ownership, permissions, and integrity.

## Deployment and service cutover

Validate private discovery, worker draining, cron overlap, health, and capacity.

## DNS and traffic cutover

Lower DNS TTL, validate the certificate, stage traffic, and preserve writer quiescence.

## Verification

Verify each endpoint, database, cache, disk, Build Source digest, worker, cron, and Workflow manually.

## Rollback and source retention

Fence target writers, restore Render writers and DNS, preserve copied data, and retain the source through sign-off.

## Known limitations

EFS remains an unpriced floor. AI is `deferred_shared_ai_engine`; Workflow automation is `conditional_workflow_generation_unsupported`.

## Complete source accounting

{source_rows}
'''
    _write_text(generated / "MIGRATION_GUIDE.md", guide)
    _write_text(generated / "README.md", "# Generated migration pack\n\nSee `MIGRATION_GUIDE.md`; `validation-report.json` is authoritative.")
    _write_text(scripts / "promote-image.sh", _promotion_script(), executable=True)
    _write_text(scripts / "migrate-postgres.sh", '#!/usr/bin/env bash\nset -euo pipefail\n[[ "${1:-}" == "--execute" ]] || { printf "DRY_RUN PostgreSQL full-load CDC quiescence\\n"; exit 0; }\nprintf "Execute only after confirmed writer quiescence\\n"', executable=True)
    _write_text(scripts / "migrate-disk.sh", '#!/usr/bin/env bash\nset -euo pipefail\n[[ "${1:-}" == "--execute" ]] || { printf "DRY_RUN disk pre-copy delta checksums\\n"; exit 0; }\nprintf "Execute final delta after confirmed writer quiescence\\n"', executable=True)
    (generated / "generation-warnings.json").write_bytes(canonical_bytes(ledger))

    sections = {
        "decision-summary": "Complete deterministic decision summary.",
        "architecture": "Build-once private managed architecture.",
        "exec-targets": "".join(f'<p data-source-resource-id="{escape(row["source_resource_id"])}" data-aws-service="{escape(row["aws_service"])}">{escape(row["aws_service"])}</p>' for row in design["mappings"]),
        "exec-costs": f'<span data-cost-key="current_render">{estimate["current_costs"]["render_monthly"]}</span><span data-cost-key="capacity_preserving">{estimate["scenarios"]["capacity_preserving"]["known_cost_monthly_usd"]}</span><span data-cost-key="right_sized">{estimate["scenarios"]["right_sized"]["known_cost_monthly_usd"]}</span><span data-cost-key="delta">{estimate["delta_monthly_usd"]}</span>',
        "migration-data": "Postgres Database Migration Service writer quiescence integrity source retention.",
        "migration-storage": "EFS /var/data pre-copy delta ownership permissions integrity.",
        "migration-deployment": "ECR digest serving deploy auto-deploy rollback.",
        "cutover": "DNS TTL certificate traffic writer quiescence.",
        "rollback": "Source retention Render restore DNS writer rollback.",
        "verification": "Endpoint database cache disk workflow verification.",
        "deferred-surfaces": "deferred_shared_ai_engine conditional_workflow_generation_unsupported.",
        "appendix-accounting": f'<span data-accounted-count="{ledger["accounting"]["accounted_count"]}">{ledger["accounting"]["accounted_count"]}</span>',
        "appendix-artifacts": "Terraform, documentation, scripts, and complete source ledger.",
        "appendix-assumptions": "Draft for review.",
    }
    toc = "".join(f'<a href="#{name}">{name}</a>' for name in sections)
    body = "".join(f'<section id="{name}">{content}</section>' for name, content in sections.items())
    _write_text(generated / "migration-report.html", f'<html lang="en"><body><h1>Render migration</h1><nav class="toc">{toc}</nav>{body}<footer>Draft for review</footer></body></html>')
    validation = _validate_generated_pack(root, generated, ledger)
    (generated / "validation-report.json").write_bytes(canonical_bytes(validation))
    return generated


def assert_pack_bound_to_design(generated: Path, design: dict[str, Any], ledger: dict[str, Any]) -> None:
    all_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(generated.rglob("*"), key=lambda item: item.relative_to(generated).as_posix().encode())
        if path.is_file()
    )
    for row in design["mappings"]:
        assert row["source_resource_id"] in all_text
    classified = [
        row["source_resource_id"]
        for bucket in ("generated", "consumed_topology", "deferred", "unsupported")
        for row in ledger[bucket]
    ]
    expected = [row["source_resource_id"] for row in design["mappings"]]
    assert sorted(classified, key=str.encode) == expected
    assert len(classified) == len(set(classified))
    assert not re.search(r"\{\{[^}]+\}\}|AKIA[A-Z0-9]{16}|-----BEGIN .*PRIVATE KEY-----", all_text)

    terraform = generated / "terraform"
    assert_generated_infrastructure_graph(terraform)
    network = (terraform / "network.tf").read_text(encoding="utf-8")
    compute = (terraform / "compute.tf").read_text(encoding="utf-8")
    storage = (terraform / "storage.tf").read_text(encoding="utf-8")
    data = (terraform / "data.tf").read_text(encoding="utf-8")
    compute_infrastructure = compute.split('resource "terraform_data"', 1)[0]
    variables = (terraform / "variables.tf").read_text(encoding="utf-8")
    for row in design["mappings"]:
        if row["render_kind"] in {"render.web_service", "render.private_service", "render.background_worker", "render.cron_job"}:
            assert row["source_resource_id"] in compute_infrastructure
            assert f'Render source resource {row["source_resource_id"]}' in variables
    assert compute_infrastructure.count('resource "aws_ecs_task_definition"') == sum(
        row["render_kind"] in {"render.web_service", "render.private_service", "render.background_worker", "render.cron_job"}
        for row in design["mappings"]
    )
    assert compute_infrastructure.count('resource "aws_ecs_service"') == sum(
        row["render_kind"] in {"render.web_service", "render.private_service", "render.background_worker"}
        for row in design["mappings"]
    )
    assert 'gateway_id = aws_internet_gateway.main.id' in network
    assert 'nat_gateway_id = aws_nat_gateway.main.id' in network
    assert 'route_table_id = aws_route_table.public.id' in network
    assert 'route_table_id = aws_route_table.private.id' in network
    assert 'security_groups = [aws_security_group.private.id]' in storage
    assert 'sourceVolume  = "private-data"' in compute
    assert 'containerPath = "/var/data"' in compute
    assert 'file_system_id     = aws_efs_file_system.application.id' in compute
    assert 'access_point_id = aws_efs_access_point.application.id' in compute
    assert 'transit_encryption = "ENABLED"' in compute
    assert 'depends_on = [aws_efs_mount_target.application]' in compute
    assert 'manage_master_user_password = true' in data
    assert not re.search(r"(?:master_)?password\s*=\s*var\.", data)
    assert_cache_engine_parity(data, design)
    promotion = (generated / "scripts/promote-image.sh").read_text(encoding="utf-8")
    assert all(
        path.stat().st_mode & 0o777 == 0o755
        for path in (generated / "scripts").glob("*.sh")
    )
    assert "ECR_REPOSITORY_URL SHA256_DIGEST TARGET_ENVIRONMENT [--execute]" in promotion
    assert "imageDigest=$digest" in promotion
    assert 'image_reference="${repository_url}@${digest}"' in promotion
    assert "digest_short=${digest#sha256:}" in promotion
    assert "digest_short=${digest_short:0:12}" in promotion
    assert 'promotion_tag="deploy-${target_environment}-${digest_short}"' in promotion
    assert "aws ecr put-image" in promotion
    assert "target ECR repository must enforce immutable tags" in promotion
