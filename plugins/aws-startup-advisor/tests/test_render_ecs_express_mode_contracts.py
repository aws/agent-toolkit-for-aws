"""Text contract: public HTTP web services on Fargate default to ECS Express Mode in render-to-aws.

Mirrors tests/test_ecs_express_mode_contracts.py for the other infra skills. Render's Clarify,
Design, Estimate, and Generate references must carry one `aws_config.ecs_mode` contract, the
generation-warnings schema must accept the two warning codes Generate emits for Express, and the
golden design fixture must record `ecs_mode` on every ECS on Fargate mapping.
"""
from __future__ import annotations

import json
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "render-to-aws"
REFS = SKILL / "references"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_design_reference_defines_express_default_and_all_eliminators() -> None:
    text = read(REFS / "design-refs" / "compute.md")
    assert "## ECS Fargate mode (Express vs standard)" in text
    assert "ECS Express Mode is the default shape" in text
    for field in ("aws_config.ecs_mode", "aws_config.ecs_mode_reason", "aws_config.placement"):
        assert field in text
    for reason in (
        "no_http_listener",
        "private_discovery",
        "passthrough",
        "release_strategy",
        "task_size",
        "efs_mount",
        "custom_domain_alb",
        "private_tasks",
    ):
        assert f'"{reason}"' in text, reason
    assert "CPU above 4096" in text and "memory above 8192" in text
    assert "`aws_service` stays `ECS on Fargate`" in text
    assert "read as `\"standard\"`" in text


def test_design_step_finalizes_ecs_mode_without_changing_service_selection() -> None:
    text = read(REFS / "phases" / "design" / "design-infra.md")
    assert "Finalize `ecs_mode`" in text
    assert "never changes `aws_service`" in text


def test_clarify_asks_release_strategy_only_for_fargate_bound_web_services() -> None:
    text = read(REFS / "phases" / "clarify" / "clarify-compute.md")
    assert "compute.release_strategy" in text
    assert "release.canary_default" in text
    assert "Never ask it for Beanstalk, EKS, workers, cron, or static sites" in text


def test_estimate_shares_one_alb_per_twenty_five_express_services() -> None:
    text = read(REFS / "phases" / "estimate" / "estimate-infra.md")
    assert "ceil(count / 25)" in text
    assert "VPC and ALB scheme" in text
    assert "no `ecs_mode`" in text


def test_generate_emits_express_resource_and_pins_provider() -> None:
    text = read(REFS / "phases" / "generate" / "generate-artifacts-infra.md")
    assert "aws_ecs_express_gateway_service" in text
    assert "AmazonECSInfrastructureRoleforExpressGatewayServices" in text
    assert "`~> 6.71`" in text and "6.23.0" in text and "6.71.0" in text
    assert "A mapping with no `ecs_mode` key is `\"standard\"`" in text
    for code in ("ecs_express_public_subnet_placement", "ecs_express_not_selected_rolling_release"):
        assert code in text, code


def test_warnings_schema_accepts_the_express_warning_codes() -> None:
    schema = json.loads(read(REFS / "shared" / "schema-generation-warnings.json"))
    codes = schema["$defs"]["warning"]["properties"]["code"]["enum"]
    assert {"ecs_express_public_subnet_placement", "ecs_express_not_selected_rolling_release"} <= set(codes)


def test_golden_design_records_ecs_mode_on_every_fargate_mapping() -> None:
    design = json.loads(read(SKILL / "fixtures" / "expected" / "aws-design.json"))
    fargate = [m for m in design["mappings"] if "Fargate" in m["aws_service"]]
    assert fargate
    for mapping in fargate:
        config = mapping["aws_config"]
        assert config["ecs_mode"] in {"express", "standard"}, mapping["source_resource_id"]
        assert config["ecs_mode_reason"], mapping["source_resource_id"]
        if config["ecs_mode"] == "express":
            assert config["placement"] in {"public_subnets", "private_subnets"}
    web = next(m for m in fargate if m["render_kind"] == "render.web_service")
    assert web["aws_config"]["ecs_mode_reason"] == "custom_domain_alb"
