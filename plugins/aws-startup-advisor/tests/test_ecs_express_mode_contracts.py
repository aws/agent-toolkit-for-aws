"""Text contract: HTTP web services on Fargate default to ECS Express Mode in the three infra skills.

AWS names ECS Express Mode as the replacement for App Runner-style "run this container as an
HTTPS web service" workloads: it provisions the Fargate cluster, ALB with HTTPS and ACM
certificate, security groups, auto scaling, logs, and canary deployments at no extra charge,
and up to 25 Express services share one ALB. It restricts two things — canary-only
deployments and an ALB-only edge — so workers, TCP/gRPC passthrough, rolling/blue-green
releases, oversized tasks, and Terraform-owned custom-domain ALBs stay on a standard ECS
service. This test pins that the Clarify, Design, Generate, and Estimate phases of gcp-to-aws,
azure-to-aws, and heroku-to-aws all carry the same `aws_config.ecs_mode` contract.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"

DESIGN_FILES = {
    "gcp": SKILLS / "gcp-to-aws" / "references" / "design-refs" / "compute.md",
    "azure": SKILLS / "azure-to-aws" / "references" / "design-refs" / "compute.md",
    "heroku": SKILLS / "heroku-to-aws" / "references" / "phases" / "design" / "design-mapping.md",
}
GENERATE_FILES = {
    "gcp": SKILLS / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-infra.md",
    "azure": SKILLS / "azure-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-infra.md",
    "heroku": SKILLS / "heroku-to-aws" / "references" / "phases" / "generate" / "generate-terraform.md",
}
ESTIMATE_FILES = {
    "gcp": SKILLS / "gcp-to-aws" / "references" / "phases" / "estimate" / "estimate-infra.md",
    "azure": SKILLS / "azure-to-aws" / "references" / "phases" / "estimate" / "estimate-infra.md",
    "heroku": SKILLS / "heroku-to-aws" / "references" / "phases" / "estimate" / "estimate-cost-engine.md",
}
CLARIFY_FILES = {
    "gcp": SKILLS / "gcp-to-aws" / "references" / "phases" / "clarify" / "clarify-compute.md",
    "azure": SKILLS / "azure-to-aws" / "references" / "phases" / "clarify" / "clarify-compute.md",
    "heroku": SKILLS / "heroku-to-aws" / "references" / "phases" / "clarify" / "clarify-interview.md",
}
PREFERENCE_SCHEMAS = {
    "gcp": SKILLS / "gcp-to-aws" / "references" / "shared" / "schema-preferences.md",
    "azure": SKILLS / "azure-to-aws" / "references" / "shared" / "schema-preferences.md",
}
ELIMINATOR_TERMS = ("worker", "tcp_or_grpc_passthrough", "release_strategy", "4096", "8192")


def test_design_rubrics_define_ecs_mode_with_the_same_eliminators() -> None:
    for skill, path in DESIGN_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert '"ecs_mode"' in text or "`ecs_mode`" in text or "aws_config.ecs_mode" in text, skill
        assert '"express"' in text and '"standard"' in text, skill
        terms = ELIMINATOR_TERMS if skill != "heroku" else ("worker", "release_strategy", "4096", "8192", "route53")
        for term in terms:  # heroku has only web/non-web shapes; its extra eliminator is the Route 53 cutover
            assert term in text, f"{skill}: eliminator {term!r} missing"
        assert "express-service-work.html" in text, f"{skill}: Express Mode docs link missing"


def test_design_keeps_fargate_as_the_service_label() -> None:
    """Express Mode is a shape of Fargate; the aws_service label must not fork into a new value."""
    for skill, path in DESIGN_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert '"aws_service": "ECS Express' not in text, skill
        assert "ECS Express Mode" in text, skill
        assert ('"aws_service": "Fargate"' in text) or ('aws_service` stays `"Fargate"`' in text), skill


def test_generate_emits_the_express_gateway_resource_and_no_duplicate_alb() -> None:
    for skill, path in GENERATE_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert "aws_ecs_express_gateway_service" in text, skill
        assert "infrastructure_role_arn" in text, skill
        assert "ingress_paths" in text, skill
        assert re.search(r"(?i)no (separate )?`?aws_lb`?|do \*\*not\*\* also emit an ALB|No separate ALB", text), f"{skill}: must say Express Mode owns the ALB"


def test_heroku_express_web_formation_skips_the_alb_entry() -> None:
    text = DESIGN_FILES["heroku"].read_text(encoding="utf-8")
    assert 'If `process_type == "web"` AND `aws_config.ecs_mode == "standard"`, produce an additional ALB entry' in text
    assert 'dns_strategy != "route53"' in text, "Route 53 cutover must force standard mode"


def test_estimate_prices_express_as_fargate_plus_a_shared_alb() -> None:
    for skill, path in ESTIMATE_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert "express" in text.lower() and "25" in text, skill
        assert "alb.monthly_fixed" in text, skill


def test_clarify_asks_release_strategy_only_for_fargate_bound_workloads() -> None:
    for skill, path in CLARIFY_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert "release_strategy" in text, skill
        for value in ("canary", "rolling", "blue_green"):
            assert re.search(rf"\b{value}\b", text), f"{skill}: {value} missing"
        assert re.search(r"(?i)fargate", text), skill
    gcp = CLARIFY_FILES["gcp"].read_text(encoding="utf-8")
    assert "compute_shape" in gcp and "cannot be derived" in gcp, "gcp Q10c must be asked only when the inventory cannot derive the shape"
    heroku = CLARIFY_FILES["heroku"].read_text(encoding="utf-8")
    assert "| Q12e — Release strategy" in heroku, "Q12e must be in the question catalog"


def test_preference_schemas_record_the_new_keys() -> None:
    for skill, path in PREFERENCE_SCHEMAS.items():
        text = path.read_text(encoding="utf-8")
        assert "release_strategy" in text, skill
        assert "compute_shape" in text, skill
