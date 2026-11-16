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


def test_generate_pins_a_provider_that_has_the_express_resource() -> None:
    """aws_ecs_express_gateway_service exists from hashicorp/aws 6.23.0 (cpu_architecture from 6.71.0);
    a ~> 5.80 pin can never select it, so every generator that emits it must name the 6.71 pin."""
    for skill, path in GENERATE_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert "~> 6.71" in text, f"{skill}: Express Mode emission without the 6.71 provider pin"
        assert "6.23.0" in text, f"{skill}: must record the version that introduced the resource"


HEROKU_GENERATE_DOCS = SKILLS / "heroku-to-aws" / "references" / "phases" / "generate" / "generate-docs.md"
GCP_FAST_PATH = SKILLS / "gcp-to-aws" / "references" / "design-refs" / "fast-path.md"
GCP_DESIGN_INFRA = SKILLS / "gcp-to-aws" / "references" / "phases" / "design" / "design-infra.md"
EXPRESS_INFRA_POLICY_ARN = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"


def _express_block(text: str) -> str:
    start = text.index('### Express Mode web services (`aws_config.ecs_mode == "express"`)')
    end = text.index("### Application Load Balancer (standard-mode web process types only)")
    return text[start:end]


def test_heroku_express_block_honors_the_writer_freeze() -> None:
    """Phase 6 failback sets writers_quiesced=true; the Express scaling target must go to 0 like aws_ecs_service.desired_count."""
    block = _express_block(GENERATE_FILES["heroku"].read_text(encoding="utf-8"))
    assert re.search(r"min_task_count\s*=\s*var\.writers_quiesced \? 0 :", block), "Express min_task_count must follow var.writers_quiesced"
    assert not re.search(r"max_task_count\s*=\s*var\.writers_quiesced", block), "max_task_count keeps its normal value; 0 is not a documented maxTaskCount"
    docs = HEROKU_GENERATE_DOCS.read_text(encoding="utf-8")
    assert "aws_ecs(_express_gateway)?_service" in docs, "the mixed EB/Fargate failback must target Express services too"


def test_heroku_express_block_references_only_declared_resources() -> None:
    text = GENERATE_FILES["heroku"].read_text(encoding="utf-8")
    hcl = "\n".join(re.findall(r"```hcl\n(.*?)```", text, flags=re.S))
    assert "data.aws_iam_policy_document.ecs_assume" not in hcl, "heroku declares no ecs_assume policy document; ECS trust policies are inline jsonencode"
    assert "aws_security_group.ecs_tasks" not in hcl, "the heroku task security group is aws_security_group.app"
    block = _express_block(text)
    assert "aws_security_group.app.id" in block
    assert 'Service = "ecs.amazonaws.com"' in block, "infrastructure role trust policy must be inline jsonencode like the other roles"
    assert "<public_subnet_references>" in block, "a public Heroku web dyno needs public subnets for an internet-facing Express ALB"
    for skill, path in GENERATE_FILES.items():
        assert EXPRESS_INFRA_POLICY_ARN in path.read_text(encoding="utf-8"), f"{skill}: infrastructure role policy ARN must be the documented service-role/ ARN"
    assert "arn:aws:iam::aws:policy/AmazonECSInfrastructureRoleforExpressGatewayServices" not in text


def test_heroku_guide_recognizes_the_express_web_target() -> None:
    docs = HEROKU_GENERATE_DOCS.read_text(encoding="utf-8")
    assert '`aws_config.ecs_mode == "express"` → `"express"`' in docs, "Step 0 target_kind must resolve an Express web app"
    assert '`output_name: "<app_sanitized>_web_endpoint"`' in docs
    assert "`alb` / `express` / `eb` / `eks` / `none`" in docs
    assert "{{IF has_express}}" in docs and "{{IF has_alb}}" in docs
    assert "terraform -chdir=terraform output -raw <app_sanitized>_web_endpoint" in docs, "Phase 4 must read the Express endpoint output, not ALB_DNS_NAME"
    assert 'target_kind == "express"' in docs
    assert "express-service-add-custom-domain" in docs, "the manual DNS branch must carry the Express listener host-header + certificate step"


def test_heroku_express_alb_pricing_runs_on_the_fargate_path_not_only_eks() -> None:
    text = ESTIMATE_FILES["heroku"].read_text(encoding="utf-8")
    fargate = text.index("### Fargate Cost Calculation — ECS Express Mode ALB")
    eks = text.index("### EKS Cost Calculation")
    assert fargate < eks, "Express ALB pricing must be a common Fargate step, before (and independent of) the EKS section"
    eks_section = text[eks:text.index("### Elastic Beanstalk Cost Calculation")]
    assert "ecs_mode == \"express\"" not in eks_section, "the EKS section must not own Express pricing"


def test_estimators_price_the_shared_express_alb_per_25_services() -> None:
    for skill, path in ESTIMATE_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert "ceil(count / 25)" in text, f"{skill}: fixed ALB charge must be ceil(count / 25) per group"
        assert re.search(r"(?i)VPC and (ALB )?scheme", text), f"{skill}: Express ALB groups are per VPC and scheme"
        assert re.search(r"(?i)never combine the two", text), f"{skill}: internal and internet-facing ALBs must not share a group"
        assert "express-service-resource-sharing" in text, f"{skill}: cite the Express resource-sharing docs"


def test_gcp_cloud_run_v2_and_design_infra_finalize_ecs_mode() -> None:
    fast_path = GCP_FAST_PATH.read_text(encoding="utf-8")
    v2_row = next(line for line in fast_path.splitlines() if line.startswith("| `google_cloud_run_v2_service`"))
    assert "aws_config.ecs_mode" in v2_row, "the Cloud Run v2 direct mapping must invoke the mode selector like v1"
    design = GCP_DESIGN_INFRA.read_text(encoding="utf-8")
    assert "### Finalize `ecs_mode`" in design, "design-infra needs a common finalize step for fast-path and rubric Fargate mappings"
    assert "google_cloud_run_v2_service" in design and "No Fargate mapping leaves Design without `ecs_mode`" in design


def test_selectors_and_generators_reconcile_public_ingress_with_subnet_placement() -> None:
    for skill, path in DESIGN_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert "express-service-network-defaults" in text, f"{skill}: cite the Express network defaults for the subnet → ALB scheme rule"
        assert re.search(r"(?i)public\*{0,2} subnets", text), f"{skill}: public Express services must be placed in public subnets"
    for skill, path in GENERATE_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert "express-service-network-defaults" in text, skill
        assert re.search(r"(?i)deviation from the `tf-best-practices`", text), f"{skill}: the public-subnet placement must be named as the accepted deviation"


def test_generators_normalize_an_absent_ecs_mode_to_standard() -> None:
    for skill, path in GENERATE_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert re.search(r"no `ecs_mode` key[^.\n]*(is|treated as) `\"standard\"`", text), f"{skill}: absent ecs_mode must normalize to standard"
        assert re.search(r"(?i)never (an error|error)[^.\n]*never (default it to |)`\"express\"`", text), f"{skill}: absent ecs_mode must not error or become express"


def test_standard_branch_emits_code_deploy_for_blue_green_and_never_silently_rolls() -> None:
    heroku = GENERATE_FILES["heroku"].read_text(encoding="utf-8")
    assert 'deployment_controller {\n    type = "CODE_DEPLOY"\n  }' in heroku
    assert 'resource "aws_codedeploy_deployment_group"' in heroku and 'deployment_type   = "BLUE_GREEN"' in heroku
    for skill, path in GENERATE_FILES.items():
        text = path.read_text(encoding="utf-8")
        assert 'deployment_controller { type = "CODE_DEPLOY" }' in text or 'type = "CODE_DEPLOY"' in text, f"{skill}: blue_green must emit the CodeDeploy controller"
        assert "aws_codedeploy_deployment_group" in text, skill
        assert re.search(r"(?i)never (a )?silent(ly)?", text), f"{skill}: a non-rolling choice must never silently become rolling"
        assert re.search(r"requested canary releases; Express Mode was not selected", text), f"{skill}: canary on a standard service must be warned, not downgraded quietly"


def test_no_file_still_calls_express_mode_a_forward_look() -> None:
    offenders = []
    for path in sorted(SKILLS.rglob("*.md")):
        if "vendored" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"(?i)express mode[^.\n]{0,80}forward-?look|forward-?look[^.\n]{0,80}express mode", line):
                offenders.append(f"{path.relative_to(PLUGIN_ROOT)}:{lineno}")
    assert not offenders, offenders


def test_heroku_blue_green_block_is_safe_for_two_web_apps_and_opens_the_test_listener() -> None:
    text = GENERATE_FILES["heroku"].read_text(encoding="utf-8")
    start = text.index("# Blue/green — <heroku_app>:web")
    block = text[start : text.index("### Express Mode web services", start)]
    assert 'resource "aws_lb_listener" "<app_sanitized>_web_test"' in block, "the test listener is per-app and must carry the app suffix"
    assert 'resource "aws_lb_listener" "test"' not in block
    assert "aws_lb_listener.<app_sanitized>_web_test.arn" in block
    assert "Emitted ONCE per design" in block, "the shared CodeDeploy role must be declared once, not once per blue/green app"
    assert 'variable "codedeploy_test_cidrs"' in block
    # Single owner for ALB ingress: aws_security_group.alb uses inline rules, so 8443 must be inline too.
    assert 'resource "aws_security_group_rule" "alb_codedeploy_test"' not in text, "no standalone rule on a group that owns inline rules"
    alb_sg = text[text.index('resource "aws_security_group" "alb"') :]
    alb_sg = alb_sg[: alb_sg.index("\n}\n")]
    assert "{{IF has_blue_green}}" in alb_sg and re.search(r"from_port\s*=\s*8443", alb_sg), "8443 ingress must be an inline block in aws_security_group.alb"
    assert "cidr_blocks = var.codedeploy_test_cidrs" in alb_sg
    # AWS names, not only Terraform labels, must carry the app identity.
    assert '-${var.environment}-<app_sanitized>-tg-green"' in block
    assert 'name             = "${var.project_name}-${var.environment}-<app_sanitized>-web"' in block
    assert 'deployment_group_name  = "${var.project_name}-${var.environment}-<app_sanitized>-web"' in block


def test_heroku_design_template_and_alb_rate_row_match_the_express_prose() -> None:
    design = DESIGN_FILES["heroku"].read_text(encoding="utf-8")
    assert '"placement": "<public_subnets when ecs_mode == \\"express\\", otherwise omit>"' in design, "the JSON template must carry the placement key the prose asks for"
    estimate = ESTIMATE_FILES["heroku"].read_text(encoding="utf-8")
    alb_row = next(line for line in estimate.splitlines() if line.startswith("| **ALB**"))
    assert 'ecs_mode != "express"' in alb_row, "the ALB rate row must exclude Express web entries so they are not priced twice"


def test_heroku_express_block_has_unique_names_a_shared_role_and_a_verified_stop() -> None:
    text = GENERATE_FILES["heroku"].read_text(encoding="utf-8")
    block = _express_block(text)
    assert 'service_name            = "${var.project_name}-${var.environment}-<app_sanitized>-web"' in block
    assert "wait_for_steady_state   = true" in block
    assert "shared infrastructure role. Emitted ONCE per design" in block
    assert 'output "<app_sanitized>_web_service_arn"' in block
    assert "register-scalable-target" in block and "describe-services" in block, "the writer-freeze rule must name the explicit stop check and scaling suspension"
    docs = HEROKU_GENERATE_DOCS.read_text(encoding="utf-8")
    # Health check: the endpoint output is already an https:// URL
    assert "https://$(terraform -chdir=terraform output -raw <app_sanitized>_web_endpoint)" not in docs, "never prefix the Express endpoint URL with another https://"
    assert "https://<endpoint>/" not in docs, "the health-check line must not add a scheme to the endpoint URL"
    assert "already a full `https://…` URL" in docs
    assert "state <> 'idle'" not in docs, "an idle application session can still write; the failback query must count it"
    assert "usename IS DISTINCT FROM 'rdsadmin'" in docs
    # Phase 6: explicit stop + suspended scaling for Express services
    assert "--suspended-state DynamicScalingInSuspended=true,DynamicScalingOutSuspended=true,ScheduledScalingSuspended=true" in docs
    assert "services[0].[runningCount,pendingCount]" in docs
    # Phase 3: deployment branches on the release strategy
    assert "aws deploy create-deployment" in docs and "appspec.yaml" in docs, "blue/green apps need the CodeDeploy/AppSpec handoff"
    assert "`has_blue_green = true`" in docs


def test_gcp_and_azure_guard_code_deploy_to_load_balanced_shapes() -> None:
    for skill in ("gcp", "azure"):
        text = GENERATE_FILES[skill].read_text(encoding="utf-8")
        assert "`blue_green` on a load-balanced shape" in text, skill
        assert "`blue_green` on a `worker`" in text and "no** CodeDeploy resources" in text, f"{skill}: a worker cannot carry a CodeDeploy target-group pair"
        assert "one IAM role per design, emitted once and shared by every Express service" in text, skill
        assert "`wait_for_steady_state = true`" in text, skill
