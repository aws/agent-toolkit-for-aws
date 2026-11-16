from __future__ import annotations
import importlib.util
import re
import shutil
import subprocess  # nosec B404 - fixed local validation tools, no shell
import sys
from pathlib import Path
import pytest
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "plugins/aws-startup-advisor/skills/render-to-aws"
EXPECTED = SKILL_ROOT / "fixtures/expected"
VARIANTS_ROOT = EXPECTED / "generated-variants"
POLICY = REPO_ROOT / "plugins/aws-startup-advisor/skills/tf-best-practices/scripts/validate-terraform-policy.py"
GENERATE = SKILL_ROOT / "references/phases/generate"
FRAGMENT = GENERATE / "generate-artifacts-infra-network-storage-delivery.md"
EXPECTED_VARIANTS = {"network-vpc-endpoints", "delivery-static-spa"}
PLUGIN_START_TIMEOUT = "timeout while waiting for plugin to start"
def _load_harness():
    path = Path(__file__).with_name("render_pipeline_harness.py")
    script_parent = str(path.parent)
    if script_parent not in sys.path:
        sys.path.insert(0, script_parent)
    spec = importlib.util.spec_from_file_location("render_pipeline_harness_variants", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
def _read(terraform: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(terraform.glob("*.tf")))
def _block(text: str, header: str) -> str:
    """Return the body of the first top-level block whose header line starts with `header`."""
    start = text.index(header)
    depth = 0
    for index in range(text.index("{", start), len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"unterminated block {header}")
def _blocks(text: str, prefix: str) -> list[str]:
    return [_block(text, match.group(0)) for match in re.finditer(rf'^{re.escape(prefix)}[^\n]*\{{', text, re.M)]
def assert_endpoint_variant(terraform: Path) -> None:
    text = _read(terraform)
    assert "aws_nat_gateway" not in text, "endpoint mode must not create a NAT gateway"
    assert 'resource "aws_eip"' not in text, "endpoint mode must not allocate an EIP"
    assert "aws_acm_certificate" not in text, "never create or validate a certificate for the listener"
    assert "aws_secretsmanager_secret_version" not in text, "secret values must not enter state"
    private_table = _block(text, 'resource "aws_route_table" "private"')
    assert "0.0.0.0/0" not in private_table and "route {" not in private_table, "private table has a default route"
    s3 = _block(text, 'resource "aws_vpc_endpoint" "s3"')
    assert 'vpc_endpoint_type = "Gateway"' in s3 and "aws_route_table.private.id" in s3, "S3 gateway endpoint missing"
    interface = _block(text, 'resource "aws_vpc_endpoint" "interface"')
    assert "private_dns_enabled = true" in interface, "interface endpoints need private DNS"
    services = re.search(r"interface_endpoint_services\s*=\s*toset\(\[([^\]]*)\]\)", text)
    assert services, "interface endpoint service set missing"
    names = set(re.findall(r'"([^"]+)"', services.group(1)))
    assert names == {"ecr.api", "ecr.dkr", "logs", "secretsmanager", "sts"}, names
    endpoint_ingress = _block(text, 'resource "aws_vpc_security_group_ingress_rule" "endpoints_from_task"')
    assert "from_port                    = 443" in endpoint_ingress
    assert "referenced_security_group_id = aws_security_group.task.id" in endpoint_ingress
    assert "cidr_ipv4" not in endpoint_ingress and "cidr_ipv6" not in endpoint_ingress, "endpoint SG ingress must not use a CIDR"
    for rule in _blocks(text, 'resource "aws_vpc_security_group_ingress_rule"'):
        if "cidr_ipv4" in rule:
            assert "aws_security_group.edge.id" in rule and re.search(r"to_port\s*=\s*(80|443)\b", rule), rule
    for rule in _blocks(text, 'resource "aws_vpc_security_group_egress_rule"'):
        assert "-1" not in rule and "cidr_ipv4" not in rule, "task and edge egress must stay scoped"
    lb = _block(text, 'resource "aws_lb" "web"')
    assert "drop_invalid_header_fields = true" in lb
    assert re.search(r"access_logs\s*\{[^}]*enabled\s*=\s*true", lb), "ALB access logs must be enabled"
    https = _block(text, 'resource "aws_lb_listener" "https"')
    assert "certificate_arn   = var.issued_certificate_arn" in https
    assert 'type             = "forward"' in https
    http = _block(text, 'resource "aws_lb_listener" "http"')
    assert 'type = "redirect"' in http and "forward" not in http, "HTTP listener must only redirect"
    assert "health_check {" in _block(text, 'resource "aws_lb_target_group" "web"')
    assert "encrypted        = true" in _block(text, 'resource "aws_efs_file_system" "application"')
    assert 'status = "ENABLED"' in _block(text, 'resource "aws_efs_backup_policy" "application"')
    mount = _block(text, 'resource "aws_efs_mount_target" "application"')
    assert "count           = length(aws_subnet.private)" in mount
    posix = re.search(r"posix_user\s*\{([^}]*)\}", text)
    assert posix
    ids = [int(value) for value in re.findall(r"(?:uid|gid)\s*=\s*(\d+)", posix.group(1))]
    assert ids and all(value != 0 for value in ids), "access point must not run as root"
    efs_ingress = _block(text, 'resource "aws_vpc_security_group_ingress_rule" "efs_from_task"')
    assert "from_port                    = 2049" in efs_ingress
    assert "referenced_security_group_id = aws_security_group.task.id" in efs_ingress
    assert "cidr_ipv4" not in efs_ingress
    private_egress = _block(text, 'resource "aws_vpc_security_group_egress_rule" "task_to_private_service"')
    assert "from_port                    = 10000" in private_egress
    assert "referenced_security_group_id = aws_security_group.private_service.id" in private_egress
    private_ingress = _block(text, 'resource "aws_vpc_security_group_ingress_rule" "private_service_from_task"')
    assert "from_port                    = 10000" in private_ingress
    assert "referenced_security_group_id = aws_security_group.task.id" in private_ingress
    assert "cidr_ipv4" not in private_ingress
    # The private service is a task tier too: with no egress of its own it cannot reach ECR, Logs or Secrets Manager.
    to_endpoints = _block(text, 'resource "aws_vpc_security_group_egress_rule" "private_service_to_endpoints"')
    assert "security_group_id            = aws_security_group.private_service.id" in to_endpoints
    assert "from_port                    = 443" in to_endpoints
    assert "referenced_security_group_id = aws_security_group.endpoints.id" in to_endpoints
    assert "cidr_ipv4" not in to_endpoints
    to_s3 = _block(text, 'resource "aws_vpc_security_group_egress_rule" "private_service_to_s3"')
    assert "security_group_id = aws_security_group.private_service.id" in to_s3
    assert "from_port         = 443" in to_s3
    assert "prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id" in to_s3
    assert "cidr_ipv4" not in to_s3
    from_private = _block(text, 'resource "aws_vpc_security_group_ingress_rule" "endpoints_from_private_service"')
    assert "security_group_id            = aws_security_group.endpoints.id" in from_private
    assert "from_port                    = 443" in from_private
    assert "referenced_security_group_id = aws_security_group.private_service.id" in from_private
    assert "cidr_ipv4" not in from_private
    ecr = _block(text, 'resource "aws_ecr_repository" "application"')
    assert 'image_tag_mutability = "IMMUTABLE"' in ecr and "scan_on_push = true" in ecr
    assert 'resource "aws_ecr_lifecycle_policy"' in text
def assert_static_spa_variant(terraform: Path) -> None:
    text = _read(terraform)
    for forbidden in ('resource "aws_lb"', 'resource "aws_vpc"', "aws_ecs_", "forwarded_values", 'resource "aws_acm_certificate"'):
        assert forbidden not in text, forbidden
    oac = _block(text, 'resource "aws_cloudfront_origin_access_control" "static"')
    assert 'signing_behavior                  = "always"' in oac and 'signing_protocol                  = "sigv4"' in oac
    policy = _block(text, 'resource "aws_s3_bucket_policy" "static"')
    assert '"AWS:SourceArn" = aws_cloudfront_distribution.static.arn' in policy
    assert re.findall(r'Action\s*=\s*"([^"]+)"', policy) == ["s3:GetObject", "s3:*"]
    for statement in policy.split("Sid ")[1:]:
        if 'Effect    = "Allow"' in statement:
            assert 'Principal = "*"' not in statement and 'AWS = "*"' not in statement, "wildcard Allow principal"
            assert 'Principal = { Service = "cloudfront.amazonaws.com" }' in statement
    public_block = _block(text, 'resource "aws_s3_bucket_public_access_block" "static"')
    for flag in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
        assert re.search(rf"{flag}\s*=\s*true", public_block), flag
    assert "response_headers_policy_id" in text and "cache_policy_id" in text
    errors = re.findall(r"custom_error_response\s*\{([^}]*)\}", text)
    codes = {int(re.search(r"error_code\s*=\s*(\d+)", body).group(1)) for body in errors}
    assert codes == {403, 404}, codes
    for body in errors:
        assert 'response_page_path    = "/index.html"' in body and re.search(r"response_code\s*=\s*200", body)
    distribution = _block(text, 'resource "aws_cloudfront_distribution" "static"')
    assert 'default_root_object = "index.html"' in distribution
    assert "precondition" in distribution
    for line in distribution.splitlines():
        if "acm_certificate_arn" in line:
            assert "length(var.custom_domain_names) == 0 ? null" in line, "certificate must be guarded"
def _mutations() -> list[tuple[str, str, callable]]:
    endpoints = VARIANTS_ROOT / "network-vpc-endpoints/terraform"
    static = VARIANTS_ROOT / "delivery-static-spa/terraform"
    return [
        ("nat", endpoints, lambda t: t + '\nresource "aws_nat_gateway" "x" {}\n'),
        ("no_ecr_dkr", endpoints, lambda t: t.replace('"ecr.dkr", ', "")),
        ("no_s3_gateway", endpoints, lambda t: t.replace('vpc_endpoint_type = "Gateway"', 'vpc_endpoint_type = "Interface"')),
        (
            "endpoint_sg_open",
            endpoints,
            lambda t: t.replace(
                'resource "aws_vpc_security_group_ingress_rule" "endpoints_from_task" {',
                'resource "aws_vpc_security_group_ingress_rule" "endpoints_from_task" {\n  cidr_ipv4 = "0.0.0.0/0"',
            ),
        ),
        ("pending_cert", endpoints, lambda t: t.replace("certificate_arn   = var.issued_certificate_arn", "certificate_arn   = aws_acm_certificate.x.arn")),
        ("efs_unencrypted", endpoints, lambda t: t.replace("encrypted        = true", "encrypted        = false")),
        ("no_spa_403", static, lambda t: t.replace("error_code            = 403", "error_code            = 400")),
        (
            "wildcard_principal",
            static,
            lambda t: t.replace('Principal = { Service = "cloudfront.amazonaws.com" }', 'Principal = "*"'),
        ),
    ]
@pytest.mark.parametrize("name,terraform,mutate", _mutations(), ids=[row[0] for row in _mutations()])
def test_variant_negative_controls_fail_closed(name: str, terraform: Path, mutate, tmp_path: Path) -> None:
    check = assert_endpoint_variant if "network" in terraform.parent.name else assert_static_spa_variant
    check(terraform)
    copy = tmp_path / "terraform"
    copy.mkdir()
    changed = False
    for path in terraform.glob("*.tf"):
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        changed = changed or mutated != original
        (copy / path.name).write_text(mutated, encoding="utf-8")
    assert changed, f"mutation {name} did not change any file"
    with pytest.raises(AssertionError):
        check(copy)
def test_variant_set_is_deliberate_and_clean() -> None:
    # Other domains keep their own variants beside these (compute-*, data-*); each has its own test.
    found = {
        path.name
        for path in VARIANTS_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith(("compute-", "data-"))
    }
    assert found == EXPECTED_VARIANTS
    for name in found:
        terraform = VARIANTS_ROOT / name / "terraform"
        for required in ("main.tf", "variables.tf", "outputs.tf", "terraform.tfvars.example", ".gitignore"):
            assert (terraform / required).is_file(), f"{name}/{required}"
        assert not (terraform / ".terraform").exists()
        assert not (terraform / ".terraform.lock.hcl").exists()
def test_variant_resources_satisfy_least_privilege_assertions() -> None:
    assert_endpoint_variant(VARIANTS_ROOT / "network-vpc-endpoints/terraform")
    assert_static_spa_variant(VARIANTS_ROOT / "delivery-static-spa/terraform")
@pytest.mark.parametrize("variant", sorted(EXPECTED_VARIANTS))
def test_variant_passes_policy_fmt_init_and_validate(variant: str, tmp_path: Path) -> None:
    terraform = VARIANTS_ROOT / variant / "terraform"
    result = subprocess.run(  # nosec B603
        [sys.executable, str(POLICY), str(terraform)], text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("POLICY_OK")
    terraform_binary = shutil.which("terraform")
    if not terraform_binary:
        pytest.skip("terraform binary not available")
    result = subprocess.run(  # nosec B603
        [terraform_binary, "fmt", "-check", "-recursive", str(terraform)], text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    work = tmp_path / "terraform"
    shutil.copytree(terraform, work)
    init = subprocess.run(  # nosec B603
        [terraform_binary, "init", "-backend=false", "-input=false", "-no-color"],
        cwd=work,
        text=True,
        capture_output=True,
        check=False,
    )
    output = init.stdout + init.stderr
    if init.returncode != 0:
        if _load_harness().classify_terraform_init_failure(output) == "provider_registry_unavailable":
            pytest.skip("provider registry unavailable")
        pytest.fail(output)
    for _attempt in range(2):
        validate = subprocess.run(  # nosec B603
            [terraform_binary, "validate", "-no-color"], cwd=work, text=True, capture_output=True, check=False
        )
        output = validate.stdout + validate.stderr
        if validate.returncode == 0 or PLUGIN_START_TIMEOUT not in output:
            break
    assert validate.returncode == 0, output
    assert "Success! The configuration is valid." in output
def test_network_storage_delivery_guidance_is_registered_and_complete() -> None:
    fragment = FRAGMENT.read_text(encoding="utf-8")
    assert re.search(r"^_fragment: artifacts-infra-network-storage-delivery$", fragment, re.M)
    assert re.search(r"^_of_phase: generate$", fragment, re.M)
    generate = (GENERATE / "generate.md").read_text(encoding="utf-8")
    assert generate.count("_id: artifacts-infra-network-storage-delivery\n") == 1
    assert generate.count("phases/generate/generate-artifacts-infra-network-storage-delivery.md") == 1
    pointer = "references/phases/generate/generate-artifacts-infra-network-storage-delivery.md"
    assert (GENERATE / "generate-artifacts-infra.md").read_text(encoding="utf-8").count(pointer) == 1
    for anchor in (
        "ecr.dkr",
        "sts",
        "secretsmanager",
        "logs",
        "private_dns_enabled",
        "issued_certificate_arn",
        "Issued",
        "aws_efs_access_point",
        "aws_efs_backup_policy",
        "origin_access_control",
        "AWS:SourceArn",
        "custom_error_response",
        "IMMUTABLE",
        "scan_on_push",
        "aws_ecr_lifecycle_policy",
        "aws_service_discovery_private_dns_namespace",
        "logdelivery.elasticloadbalancing.amazonaws.com",
    ):
        assert anchor in fragment, anchor
    for out_of_scope in ("aws_ecs_service", "aws_db_instance", "aws_elasticache"):
        assert out_of_scope not in fragment, out_of_scope

def _max_len(variables: str, name: str) -> int:
    body = _block(variables, f'variable "{name}"')
    return int(re.search(r"\{0,(\d+)\}", body).group(1)) + 1
@pytest.mark.parametrize(
    "variant,suffixes",
    [
        ("network-vpc-endpoints", {"-alb-logs-": 37, "-web": 32}),
        ("delivery-static-spa", {"-static-": 37}),
    ],
)
def test_derived_names_fit_provider_limits_at_validation_maximum(variant: str, suffixes: dict[str, int]) -> None:
    terraform = VARIANTS_ROOT / variant / "terraform"
    variables = (terraform / "variables.tf").read_text(encoding="utf-8")
    longest = _max_len(variables, "project_name") + 1 + _max_len(variables, "environment")
    for suffix, limit in suffixes.items():
        assert f'"${{local.name_prefix}}{suffix}"' in _read(terraform), suffix
        assert longest + len(suffix) <= limit, f"{variant}: {suffix} exceeds {limit}"
    for default_name in ("project_name", "environment"):
        default = re.search(r'default\s*=\s*"([^"]+)"', _block(variables, f'variable "{default_name}"')).group(1)
        assert len(default) <= _max_len(variables, default_name), default_name
@pytest.mark.parametrize("variant", sorted(EXPECTED_VARIANTS))
def test_over_long_names_fail_validation_at_plan_time(variant: str, tmp_path: Path) -> None:
    terraform_binary = shutil.which("terraform")
    if not terraform_binary:
        pytest.skip("terraform binary not available")
    # Variable validation runs before any provider is needed, so only variables.tf is evaluated.
    work = tmp_path / "terraform"
    work.mkdir()
    shutil.copy(VARIANTS_ROOT / variant / "terraform/variables.tf", work / "variables.tf")
    (work / "locals.tf").write_text('locals {\n  name_prefix = "${var.project_name}-${var.environment}"\n}\n', encoding="utf-8")
    for name, value in (("project_name", "acme-marketing-website-long"), ("environment", "production-eu-west")):
        result = subprocess.run(  # nosec B603
            [terraform_binary, "console", "-no-color", f"-var={name}={value}"],
            cwd=work,
            input="local.name_prefix\n",
            text=True,
            capture_output=True,
            check=False,
        )
        output = result.stdout + result.stderr
        assert result.returncode != 0 and f"{name} must be 1 to" in output, output
def test_guidance_states_endpoint_egress_name_limits_and_tls_deny_wording() -> None:
    fragment = FRAGMENT.read_text(encoding="utf-8")
    assert "every selected internal flow" in fragment
    assert "5432" in fragment and "6379" in fragment and "private-service security group" in fragment
    assert "No `-1` protocol egress and no CIDR egress" in fragment
    assert "Endpoint mode keeps security-group-referenced task egress" in fragment
    assert "32 characters" in fragment and "37" in fragment and "`bucket_prefix`" in fragment
    assert "`project_name` and `environment` have length validation" in fragment
    assert 'A bucket policy `Allow` with `Principal = "*"`' in fragment
    assert '- A bucket policy with `Principal = "*"`' not in fragment
