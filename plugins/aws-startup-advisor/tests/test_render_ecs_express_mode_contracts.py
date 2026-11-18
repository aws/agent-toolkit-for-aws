"""Text contract: public HTTP web services on Fargate default to ECS Express Mode in render-to-aws.

Mirrors tests/test_ecs_express_mode_contracts.py for the other infra skills. Render's Clarify,
Design, Estimate, and Generate references must carry one `aws_config.ecs_mode` contract, the
generation-warnings schema must accept the two warning codes Generate emits for Express, and the
golden design fixture must record `ecs_mode` on every ECS on Fargate mapping.
"""
from __future__ import annotations

import importlib.util
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
    generate = REFS / "phases" / "generate"
    pointer = read(generate / "generate-artifacts-infra.md")
    assert "compute fragment" in pointer and "skip the target group and listener" in pointer
    assert "AmazonECSInfrastructureRoleforExpressGatewayServices" not in pointer
    text = read(generate / "generate-infra-compute.md")
    assert "## ECS on Fargate: Express vs standard mode" in text
    assert "Express rows skip the target group and listener" in text
    assert "aws_ecs_express_gateway_service" in text
    assert "AmazonECSInfrastructureRoleforExpressGatewayServices" in text
    assert "6.23.0" in text and "6.71.0" in text
    assert "`~> 6.71`" in pointer
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
def test_design_finalize_walk_covers_every_fargate_aws_service_name() -> None:
    text = read(REFS / "phases" / "design" / "design-infra.md")
    assert "`ECS on Fargate`, `ECS on Fargate service`, or `ECS on Fargate task`" in text
    assert "`ECS on Fargate task` mappings" in text and "`no_http_listener`" in text
def test_estimate_allocates_the_shared_alb_across_mapping_lines() -> None:
    text = read(REFS / "phases" / "estimate" / "estimate-infra.md")
    assert "exactly one estimate line per design mapping" in text
    assert "floor(fee_cents / count)" in text and "fee_cents mod count" in text and "byte order" in text
    assert "accounting.accounted_resource_ids" in text
    assert "own line" in text and "never becomes its own line" in text
def test_report_reference_lists_both_express_warning_codes_and_mode_statement() -> None:
    text = read(REFS / "phases" / "generate" / "generate-artifacts-report.md")
    for code in ("ecs_express_public_subnet_placement", "ecs_express_not_selected_rolling_release"):
        assert code in text, code
    assert "Express or standard" in text
def test_canary_warning_follows_the_answered_release_not_only_the_reason() -> None:
    spec = importlib.util.spec_from_file_location(
        "render_pipeline_harness_express_release",
        Path(__file__).with_name("render_pipeline_harness.py"),
    )
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    design = {
        "mappings": [
            {
                "source_resource_id": "rr-web",
                "aws_service": "ECS on Fargate",
                "aws_config": {"ecs_mode": "standard", "ecs_mode_reason": "passthrough"},
            }
        ]
    }
    rolling = {"questions": [{"question_id": "compute.release_strategy", "resource_id": "rr-web", "value": "rolling"}]}
    blue_green = {"questions": [{"question_id": "compute.release_strategy", "resource_id": "rr-web", "value": "blue_green"}]}
    canary = {"questions": [{"question_id": "compute.release_strategy", "resource_id": "rr-web", "value": "canary"}]}
    assert harness.express_not_selected_warnings(design, rolling) == []
    assert harness.express_not_selected_warnings(design, blue_green) == []
    warned = harness.express_not_selected_warnings(design, canary)
    assert [row["subject"] for row in warned] == ["rr-web"]
    assert harness.express_not_selected_warnings(design), "an absent answer defaults to canary"


def test_golden_pack_warns_for_rr_web_and_states_the_mode_of_every_fargate_service() -> None:
    design = json.loads(read(SKILL / "fixtures" / "expected" / "aws-design.json"))
    generated = SKILL / "fixtures" / "expected" / "generated"
    warnings = json.loads(read(generated / "generation-warnings.json"))["warnings"]
    rolling = [row for row in warnings if row["code"] == "ecs_express_not_selected_rolling_release"]
    assert [row["subject"] for row in rolling] == ["rr-web"]
    assert "custom_domain_alb" in rolling[0]["detail"] and rolling[0]["blocking"] is False
    assert not [row for row in warnings if row["code"] == "ecs_express_public_subnet_placement"]
    assert "ecs_express_not_selected_rolling_release" in read(generated / "terraform" / "README.md")
    for name in ("MIGRATION_GUIDE.md", "migration-report.html"):
        text = read(generated / name)
        for mapping in design["mappings"]:
            if "Fargate" in mapping["aws_service"]:
                config = mapping["aws_config"]
                assert mapping["source_resource_id"] in text and config["ecs_mode_reason"] in text, (name, mapping["source_resource_id"])
