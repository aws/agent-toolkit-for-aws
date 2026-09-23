"""Tests for validate-terraform-policy.py (tf-best-practices, read-only verdict)."""

from __future__ import annotations

import importlib.util
import json
import subprocess  # nosec B404 — test-only, inputs are hardcoded literals
import sys
import tempfile
from pathlib import Path

PLUGIN_SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLUGIN_SKILL_ROOT / "scripts" / "validate-terraform-policy.py"
FIXTURES = PLUGIN_SKILL_ROOT / "fixtures" / "terraform-policy"
GOOD_FIXTURE = FIXTURES / "good-https-redirect"
BAD_HTTP_FORWARD = FIXTURES / "bad-http-forward"
INTERNAL_ALB = FIXTURES / "internal-alb-only"
BAD_RDS_PUBLIC_UNENCRYPTED = FIXTURES / "bad-rds-public-unencrypted"
GOOD_RDS_PRIVATE_ENCRYPTED = FIXTURES / "good-rds-private-encrypted"
BAD_DB_SG_PUBLIC = FIXTURES / "bad-db-sg-public"
GOOD_DB_SG_SCOPED = FIXTURES / "good-db-sg-scoped"
BAD_WILDCARD_IAM = FIXTURES / "bad-wildcard-iam"
GOOD_SCOPED_IAM = FIXTURES / "good-scoped-iam"
BAD_WILDCARD_IAM_LISTFORM = FIXTURES / "bad-wildcard-iam-listform"
GOOD_IAM_SCOPED_LIST = FIXTURES / "good-iam-scoped-list"
GOOD_INTERNET_NLB = FIXTURES / "good-internet-nlb"
BAD_SG_PUBLIC_SSH = FIXTURES / "bad-sg-public-ssh"
GOOD_SG_PUBLIC_WEBAPP = FIXTURES / "good-sg-public-webapp"
BAD_SG_PUBLIC_IPV6 = FIXTURES / "bad-sg-public-ipv6"
GOOD_SG_IPV6_SCOPED = FIXTURES / "good-sg-ipv6-scoped"
BAD_ELASTICACHE_UNENCRYPTED = FIXTURES / "bad-elasticache-unencrypted"
GOOD_ELASTICACHE_ENCRYPTED = FIXTURES / "good-elasticache-encrypted"
GOOD_QUOTED_PORT_HTTPS = FIXTURES / "good-quoted-port-https"
BAD_DB_SG_PUBLIC_QUOTED_PORT = FIXTURES / "bad-db-sg-public-quoted-port"
GOOD_HEROKU_EB_LB = FIXTURES / "good-heroku-eb-loadbalanced"
GOOD_HEROKU_EB_ONLY = FIXTURES / "good-heroku-eb-only"
GOOD_HEROKU_EB_SINGLEINSTANCE = FIXTURES / "good-heroku-eb-singleinstance"
GOOD_HEROKU_EB_CODEPIPELINE = FIXTURES / "good-heroku-eb-codepipeline"
BAD_HEROKU_EB_ELASTICACHE = FIXTURES / "bad-heroku-eb-elasticache"


def _load_validator_module():
    """Import the validator for unit-level tests (its filename is hyphenated, so
    it is not importable as a normal module name)."""
    spec = importlib.util.spec_from_file_location("validate_terraform_policy", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: @dataclass resolves annotations via sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator_module()


def run_policy_validator(terraform_dir: Path, json_out: Path | None = None) -> tuple[int, str]:
    cmd = [sys.executable, str(SCRIPT), str(terraform_dir)]
    if json_out is not None:
        cmd += ["--json", str(json_out)]
    result = subprocess.run(cmd, capture_output=True, text=True)  # nosec B603
    return result.returncode, result.stdout + result.stderr


def test_good_https_redirect_passes() -> None:
    code, out = run_policy_validator(GOOD_FIXTURE)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_bad_http_forward_fails() -> None:
    code, out = run_policy_validator(BAD_HTTP_FORWARD)
    assert code == 1, out
    assert "POLICY_FAIL" in out
    assert "redirect" in out.lower()


def test_heroku_eb_loadbalanced_passes() -> None:
    # EB compute fronted by a STANDALONE ALB (aws_lb_listener present) + RDS. Web
    # 80/443 open to 0.0.0.0/0 on the ALB is a legitimate web pattern and must NOT
    # be flagged; only admin/datastore ports are.
    code, out = run_policy_validator(GOOD_HEROKU_EB_LB)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_heroku_eb_only_passes_vacuously() -> None:
    # Pure EB LoadBalanced env, no standalone aws_lb — EB provisions the ALB from
    # setting blocks the static checker cannot read, so the ALB rules pass with no
    # listener to inspect. Documents that EB-managed ALB posture is authoring-only.
    code, out = run_policy_validator(GOOD_HEROKU_EB_ONLY)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_heroku_eb_singleinstance_passes() -> None:
    # EB SingleInstance: public-subnet instance, 80/443 open to the world, no ALB.
    # Web ports are not flagged (only admin/datastore ports are) → POLICY_OK.
    code, out = run_policy_validator(GOOD_HEROKU_EB_SINGLEINSTANCE)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_heroku_eb_codepipeline_required_wildcard_passes() -> None:
    # AWS does not support resource-level permissions for CreateStorageLocation;
    # its isolated Resource "*" statement is required, not an over-broad grant.
    code, out = run_policy_validator(GOOD_HEROKU_EB_CODEPIPELINE)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_required_wildcard_action_cannot_hide_other_actions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        terraform_dir = Path(tmp)
        (terraform_dir / "policy.tf").write_text(
            '''
resource "aws_iam_role_policy" "mixed" {
  role = "example-role"
  policy = jsonencode({
    Statement = [{
      Effect   = "Allow"
      Action   = ["elasticbeanstalk:CreateStorageLocation", "s3:*"]
      Resource = "*"
    }]
  })
}
'''
        )
        code, out = run_policy_validator(terraform_dir)
    assert code == 1, out
    assert "no_wildcard_iam" in out


def test_heroku_policy_check_runs_after_eks_fragment() -> None:
    phase_dir = (
        PLUGIN_SKILL_ROOT.parent
        / "heroku-to-aws"
        / "references"
        / "phases"
        / "generate"
    )
    phase = (phase_dir / "generate.md").read_text()
    terraform_fragment = (phase_dir / "generate-terraform.md").read_text()
    assembler = (phase_dir / "generate-assemble.md").read_text()

    assert phase.index("_id: eks-generate") < phase.index("_assemble:")
    assert "Defer the authoritative Terraform policy check to the assembler" in terraform_fragment
    assert "Authoritative Terraform policy check (after all Terraform producers)" in assembler
    assert "after `eks-generate`" in assembler


def test_heroku_eb_bad_elasticache_and_http_forward_fails() -> None:
    # BOTH the unencrypted-ElastiCache and the HTTP-forward violations must fire —
    # assert both rule IDs from --json so an alb_http_redirect regression can't hide
    # behind the elasticache failure.
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "verdict.json"
        code, _ = run_policy_validator(BAD_HEROKU_EB_ELASTICACHE, json_out=out_path)
        report = json.loads(out_path.read_text())
    assert code == 1
    assert report["policy_status"] == "POLICY_FAIL"
    rules = {v["rule"] for v in report["violations"]}
    assert "elasticache_encryption_at_rest" in rules, rules
    assert "alb_http_redirect" in rules, rules


def test_internal_alb_skips_https_requirement() -> None:
    code, out = run_policy_validator(INTERNAL_ALB)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_json_report_written_on_pass() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "verdict.json"
        code, _ = run_policy_validator(GOOD_FIXTURE, json_out=out_path)
        assert code == 0
        report = json.loads(out_path.read_text())
        assert report["policy_status"] == "POLICY_OK"
        assert report["violations"] == []


def test_json_report_written_on_fail() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "verdict.json"
        code, _ = run_policy_validator(BAD_HTTP_FORWARD, json_out=out_path)
        assert code == 1
        report = json.loads(out_path.read_text())
        assert report["policy_status"] == "POLICY_FAIL"
        rules = {v["rule"] for v in report["violations"]}
        assert "alb_http_redirect" in rules


def test_missing_directory_is_usage_error() -> None:
    code, out = run_policy_validator(Path("/nonexistent/terraform/dir"))
    assert code == 2, out
    assert "not_a_directory" in out


def test_no_tf_files_flagged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run_policy_validator(Path(tmp))
        assert code == 1, out
        assert "No .tf files" in out


def test_rds_public_and_unencrypted_fails() -> None:
    code, out = run_policy_validator(BAD_RDS_PUBLIC_UNENCRYPTED)
    assert code == 1, out
    assert "POLICY_FAIL" in out


def test_rds_public_unencrypted_reports_both_rules() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "verdict.json"
        run_policy_validator(BAD_RDS_PUBLIC_UNENCRYPTED, json_out=out_path)
        rules = {v["rule"] for v in json.loads(out_path.read_text())["violations"]}
        assert "rds_not_public" in rules
        assert "rds_encryption_at_rest" in rules


def test_rds_private_encrypted_passes() -> None:
    # Also proves variable-driven storage_encrypted fails open (not flagged).
    code, out = run_policy_validator(GOOD_RDS_PRIVATE_ENCRYPTED)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_db_sg_public_ingress_fails() -> None:
    code, out = run_policy_validator(BAD_DB_SG_PUBLIC)
    assert code == 1, out
    assert "db_sg_no_public_ingress" in out


def test_db_sg_scoped_passes() -> None:
    # Proves: app-SG-scoped DB ingress OK; public 443 not flagged as a DB port;
    # separate aws_vpc_security_group_ingress_rule fails open (not correlated).
    code, out = run_policy_validator(GOOD_DB_SG_SCOPED)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_wildcard_iam_fails() -> None:
    code, out = run_policy_validator(BAD_WILDCARD_IAM)
    assert code == 1, out
    assert "no_wildcard_iam" in out


def test_scoped_iam_passes() -> None:
    # Proves scoped policy OK and assume-role trust policy is not a wildcard hit.
    code, out = run_policy_validator(GOOD_SCOPED_IAM)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_wildcard_iam_listform_fails() -> None:
    # Regression: Resource = ["*"] (single-element list) must fail, like "*".
    code, out = run_policy_validator(BAD_WILDCARD_IAM_LISTFORM)
    assert code == 1, out
    assert "no_wildcard_iam" in out


def test_iam_scoped_list_passes() -> None:
    # A list of scoped actions / resource ARNs is not a wildcard — must pass.
    code, out = run_policy_validator(GOOD_IAM_SCOPED_LIST)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_internet_facing_nlb_not_flagged() -> None:
    # Regression: an internet-facing Network LB (L4) has no HTTPS:443 listener
    # by design and must NOT trip the ALB HTTPS rule.
    code, out = run_policy_validator(GOOD_INTERNET_NLB)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_sg_public_admin_ingress_fails() -> None:
    code, out = run_policy_validator(BAD_SG_PUBLIC_SSH)
    assert code == 1, out
    assert "sg_no_public_admin_ingress" in out


def test_sg_public_admin_ingress_reports_ssh_and_redis() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "verdict.json"
        run_policy_validator(BAD_SG_PUBLIC_SSH, json_out=out_path)
        summaries = " ".join(
            v["summary"] for v in json.loads(out_path.read_text())["violations"]
        )
        assert "22 (SSH)" in summaries
        assert "6379 (Redis)" in summaries


def test_sg_public_webapp_passes() -> None:
    # Public web ports (80/443), a high game-port range, and a privately-scoped
    # SSH rule must all pass — no false positive from the sensitive-port rule.
    code, out = run_policy_validator(GOOD_SG_PUBLIC_WEBAPP)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_sg_public_ipv6_ingress_fails() -> None:
    """Regression: ipv6_cidr_blocks = ["::/0"] is public exposure and must fail.

    The old checker searched r'cidr_blocks\\s*=\\s*\\[' which also matches the tail
    of `ipv6_cidr_blocks`, and never looked for ::/0 at all — so an SG opening
    SSH/Postgres to the entire IPv6 internet was reported POLICY_OK.
    """
    code, out = run_policy_validator(BAD_SG_PUBLIC_IPV6)
    assert code == 1, out
    assert "sg_no_public_admin_ingress" in out
    assert "db_sg_no_public_ingress" in out


def test_sg_public_ipv6_ingress_names_the_ipv6_cidr() -> None:
    # The report must say ::/0, not 0.0.0.0/0 — the IPv4 list here is benign.
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "verdict.json"
        run_policy_validator(BAD_SG_PUBLIC_IPV6, json_out=out_path)
        summaries = " ".join(
            v["summary"] for v in json.loads(out_path.read_text())["violations"]
        )
        assert "::/0" in summaries
        assert "22 (SSH)" in summaries
        assert "0.0.0.0/0" not in summaries


def test_ipv4_public_ingress_caught_when_ipv6_list_declared_first() -> None:
    """Regression: the pre-fix regex made the IPv4 check ORDER-DEPENDENT.

    r'cidr_blocks\\s*=\\s*\\[' matched the tail of `ipv6_cidr_blocks`, so when the
    IPv6 attribute came first the checker read the IPv6 list and never looked at
    cidr_blocks at all. A plain `0.0.0.0/0` on port 22 — the exact case this rule
    exists to catch, with no IPv6 exposure involved — silently returned
    POLICY_OK. Flipping the two lines was enough to make it fail correctly.
    """
    sg = """
resource "aws_security_group" "ipv4_ssh_open" {
  name   = "test-sg"
  vpc_id = "vpc-123"

  ingress {
    from_port        = 22
    to_port          = 22
    protocol         = "tcp"
    %s
  }
}
"""
    ipv6_first = 'ipv6_cidr_blocks = ["2001:db8:1234::/48"]\n    cidr_blocks      = ["0.0.0.0/0"]'
    ipv4_first = 'cidr_blocks      = ["0.0.0.0/0"]\n    ipv6_cidr_blocks = ["2001:db8:1234::/48"]'
    for label, attrs in (("ipv6-first", ipv6_first), ("ipv4-first", ipv4_first)):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "vpc.tf").write_text(sg % attrs, encoding="utf-8")
            code, out = run_policy_validator(Path(tmp))
            assert code == 1, f"{label}: 0.0.0.0/0 on SSH must fail, got: {out}"
            assert "22 (SSH)" in out, f"{label}: {out}"
            assert "0.0.0.0/0" in out, f"{label}: must name the IPv4 range, got: {out}"


def test_sg_ipv6_scoped_passes() -> None:
    # Public web over ::/0 is fine; SSH/Postgres over a scoped IPv6 prefix must
    # not fire. Guards against over-matching any ipv6_cidr_blocks value.
    code, out = run_policy_validator(GOOD_SG_IPV6_SCOPED)
    assert code == 0, out
    assert "POLICY_OK" in out


def _sg_fixture(attrs: str, port: int = 22) -> str:
    return f"""
resource "aws_security_group" "under_test" {{
  name   = "sg"
  vpc_id = "vpc-123"

  ingress {{
    from_port = {port}
    to_port   = {port}
    protocol  = "tcp"
    {attrs}
  }}
}}
"""


def _verdict(tf_body: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "vpc.tf").write_text(tf_body, encoding="utf-8")
        return run_policy_validator(Path(tmp))


def test_cidr_attribute_sharing_line_with_opening_brace_is_read() -> None:
    """Regression: a line-anchored pattern alone hides an attribute that shares
    its block's opening line, which is valid HCL:

        ingress { cidr_blocks = ["0.0.0.0/0"]

    An earlier revision of this fix used a bare `^\\s*` anchor and traded the
    ipv6 tail-match bug for this false negative (main: POLICY_FAIL -> POLICY_OK).
    The `(?:^|\\{)` alternation keeps both properties.
    """
    body = """
resource "aws_security_group" "brace_same_line" {
  name   = "sg"
  vpc_id = "vpc-123"

  ingress { cidr_blocks = ["0.0.0.0/0"]
    from_port = 22
    to_port   = 22
    protocol  = "tcp"
  }
}
"""
    code, out = _verdict(body)
    assert code == 1, f"0.0.0.0/0 on the brace line must fail, got: {out}"
    assert "22 (SSH)" in out, out


def test_noncanonical_ipv6_zero_prefix_spellings_fire() -> None:
    """`::/0` has many legal spellings and Terraform normalises none of them, so
    the check canonicalises via ipaddress rather than substring-matching text."""
    for spelling in ("::/0", "::0/0", "0:0:0:0:0:0:0:0/0", "0000:0000:0000:0000:0000:0000:0000:0000/0"):
        code, out = _verdict(_sg_fixture(f'ipv6_cidr_blocks = ["{spelling}"]'))
        assert code == 1, f"{spelling} is the whole IPv6 internet, must fail: {out}"
        assert "sg_no_public_admin_ingress" in out, f"{spelling}: {out}"


def test_scoped_and_nonliteral_cidrs_still_fail_open() -> None:
    """The canonicalising check must not widen what counts as public: scoped
    prefixes and non-literal values stay unflagged (documented fail-open)."""
    for spelling in ("10.0.0.0/8", "2001:db8:1234::/48", "0.0.0.0/1", "128.0.0.0/1"):
        attr = "ipv6_cidr_blocks" if ":" in spelling else "cidr_blocks"
        code, out = _verdict(_sg_fixture(f'{attr} = ["{spelling}"]'))
        assert code == 0, f"{spelling} is not the whole internet, must pass: {out}"
    for nonliteral in ("var.admin_cidrs", "[var.cidr]", "local.allowed"):
        inner = nonliteral if nonliteral.startswith("[") else f"[{nonliteral}]"
        code, out = _verdict(_sg_fixture(f"cidr_blocks = {inner}"))
        assert code == 0, f"non-literal {nonliteral} must fail open: {out}"


def test_cidr_named_only_in_a_comment_is_not_an_allowed_range() -> None:
    """False positive: a correctly-scoped SG that merely MENTIONS 0.0.0.0/0 in a
    comment inside the list was reported POLICY_FAIL, blocking a valid migration.

    Also pins the opposite direction — stripping comments must not swallow a real
    entry that follows one, which a naive split-on-comma would have done.
    """
    scoped_with_comment = """
    cidr_blocks = [
      # TODO: was 0.0.0.0/0
      "10.0.0.0/8",
    ]"""
    code, out = _verdict(_sg_fixture(scoped_with_comment, port=3389))
    assert code == 0, f"a commented CIDR is not an allowed range: {out}"

    comment_then_real = """
    cidr_blocks = [
      # temporary, remove before prod
      "0.0.0.0/0",
    ]"""
    code, out = _verdict(_sg_fixture(comment_then_real, port=3389))
    assert code == 1, f"a real 0.0.0.0/0 after a comment must still fire: {out}"
    assert "3389 (RDP)" in out, out


def test_commented_out_cidr_attribute_is_not_read() -> None:
    # A commented-out attribute must not be read as set; the live value here is
    # an SG reference, so this SG is correctly scoped and must pass.
    body = _sg_fixture('# cidr_blocks = ["0.0.0.0/0"]\n    security_groups = ["sg-abc123"]')
    code, out = _verdict(body)
    assert code == 0, f"commented-out cidr_blocks must not fire: {out}"


def test_comment_marker_inside_string_does_not_swallow_real_cidr() -> None:
    """False negative: comment stripping must share the lexer, not re-scan with a
    regex. A regex sees the `/*` inside the description STRING as a comment
    opener and deletes everything up to the `*/` in the later line comment —
    including the live `cidr_blocks = ["0.0.0.0/0"]` between them, reporting a
    public SSH ingress as POLICY_OK. The lexer knows string interiors are not
    comment openers, so the public range survives stripping and fires.
    """
    body = _sg_fixture(
        'description = "temp /* migration window"\n'
        '    cidr_blocks = ["0.0.0.0/0"]\n'
        "    # closes */ in runbook"
    )
    code, out = _verdict(body)
    assert code == 1, f"0.0.0.0/0 after a string containing /* must still fire: {out}"
    assert "22 (SSH)" in out, out


def test_elasticache_unencrypted_fails() -> None:
    code, out = run_policy_validator(BAD_ELASTICACHE_UNENCRYPTED)
    assert code == 1, out
    assert "elasticache_encryption_at_rest" in out


def test_elasticache_encrypted_passes() -> None:
    # Encrypted RG passes; variable-driven RG fails open (not flagged).
    code, out = run_policy_validator(GOOD_ELASTICACHE_ENCRYPTED)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_block_form_forward_https_listener_does_not_false_fail() -> None:
    """Regression: a valid HTTPS listener whose default_action uses a NESTED
    forward { ... } block before `type` must NOT be misparsed as missing/wrong.

    The old r'default_action{[^}]*?type' regex stopped at the first '}' (the end
    of the nested block) and failed to read `type`, producing a false POLICY_FAIL.
    """
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "compute.tf").write_text(
            """
resource "aws_lb" "app" {
  name     = "app-alb"
  internal = false
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.app.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  # Placeholder — the checker only tests for the presence of `certificate_arn`,
  # not its value (see has_certificate_arn). A literal ACM ARN here trips secret
  # scanners for no benefit, so use a variable reference.
  certificate_arn   = var.acm_certificate_arn

  default_action {
    forward {
      target_group {
        arn = aws_lb_target_group.app.arn
      }
    }
    type = "forward"
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.app.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
""",
            encoding="utf-8",
        )
        code, out = run_policy_validator(Path(tmp))
        assert code == 0, f"block-form forward should pass, got: {out}"
        assert "POLICY_OK" in out


def test_quoted_port_https_listener_passes() -> None:
    """Regression: Terraform accepts a quoted integer for number arguments, so a
    correct HTTPS listener written as port = "443" must NOT be falsely flagged.

    Reading only bare integers left port=None, so https_ok was empty and a valid
    stack failed with rule=alb_https_listener.
    """
    code, out = run_policy_validator(GOOD_QUOTED_PORT_HTTPS)
    assert code == 0, out
    assert "POLICY_OK" in out


def test_quoted_port_db_sg_public_ingress_fails() -> None:
    """Regression: from_port / to_port = "5432" with cidr_blocks = ["0.0.0.0/0"]
    is a world-open database and must fire, not silently pass."""
    code, out = run_policy_validator(BAD_DB_SG_PUBLIC_QUOTED_PORT)
    assert code == 1, out
    assert "db_sg_no_public_ingress" in out


def test_quoted_port_sg_public_admin_ingress_fails() -> None:
    """Same quoted-port regression for the sensitive-port rule (SSH on 22)."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "vpc.tf").write_text(
            """
resource "aws_security_group" "bad" {
  name = "bad-ssh-sg"

  ingress {
    from_port   = "22"
    to_port     = "22"
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
""",
            encoding="utf-8",
        )
        code, out = run_policy_validator(Path(tmp))
        assert code == 1, out
        assert "sg_no_public_admin_ingress" in out
        assert "22 (SSH)" in out


def test_attr_int_reads_bare_and_quoted_integers() -> None:
    assert VALIDATOR._attr_int("  port = 443\n", "port") == 443
    assert VALIDATOR._attr_int('  port = "443"\n', "port") == 443
    assert VALIDATOR._attr_int('  from_port = "0"\n', "from_port") == 0


def test_attr_int_rejects_non_literal_quoted_values() -> None:
    """Precision guard: a quoted value must be ENTIRELY digits. Anything else is
    non-literal and must return None so the rules keep failing open."""
    for body in (
        '  port = "443x"\n',
        '  port = "x443"\n',
        '  port = "443-444"\n',
        '  port = "${var.port}"\n',
        '  port = " 443"\n',
        '  port = ""\n',
        "  port = var.port\n",
        "  port = local.ports[0]\n",
    ):
        assert VALIDATOR._attr_int(body, "port") is None, body


def test_attr_int_absent_attribute_is_none() -> None:
    assert VALIDATOR._attr_int('  protocol = "HTTPS"\n', "port") is None


# A listener whose own `port`/`protocol` are written AFTER its default_action.
# Valid HCL — `terraform fmt` does not reorder attributes relative to blocks — and
# the nested redirect carries both a `port` and a `protocol`, so a whole-body read
# returns the redirect's 443/HTTPS instead of the listener's own 80/HTTP.
_LISTENER_ATTRS_AFTER_NESTED_BLOCK = """{
  load_balancer_arn = aws_lb.app.arn

  default_action {
    type = "redirect"
    redirect {
      port     = "443"
      protocol = "HTTPS"
    }
  }

  port     = 80
  protocol = "HTTP"
}"""


def test_attrs_read_from_own_block_not_nested_block() -> None:
    """Accepting quoted integers makes a nested `port = "443"` a match candidate
    where a bare-only pattern could never match one, so reads are scoped to the
    block's own attributes. Pinned for both readers: _attr_string had the same
    whole-body weakness before this change and shares the scoping now."""
    assert VALIDATOR._attr_int(_LISTENER_ATTRS_AFTER_NESTED_BLOCK, "port") == 80
    assert (
        VALIDATOR._attr_string(_LISTENER_ATTRS_AFTER_NESTED_BLOCK, "protocol") == "HTTP"
    )


def test_attr_nested_only_value_is_not_promoted() -> None:
    """An attribute that exists ONLY inside a nested block is absent from the
    enclosing block — returning the nested value would invent an attribute.

    Written as `terraform fmt` emits it (one attribute per line), which is the form
    that actually reaches the line-anchored pattern; a collapsed one-line
    `redirect { port = "443" }` never matches and so would not exercise scoping."""
    body = '{\n  default_action {\n    redirect {\n      port = "443"\n    }\n  }\n}'
    assert VALIDATOR._attr_int(body, "port") is None


def test_attr_interpolation_does_not_hide_later_attributes() -> None:
    """`${...}` braces are balanced, so an interpolated value earlier in the body
    must not make a following top-level attribute unreadable."""
    body = '{\n  identifier        = "${var.project}-db"\n  storage_encrypted = true\n}'
    assert VALIDATOR._attr_string(body, "storage_encrypted") == "true"


def test_quote_nested_in_interpolation_does_not_end_the_string() -> None:
    """A `"` inside `${...}` opens a NESTED string; it must not end the outer one.

    Regression guard: the first lexer set `state = "code"` on any `"` seen in a
    string, so an inner string's closing quote ended the outer string and the rest
    of the line was scanned as code — putting textual braces back into the depth
    count. That is the exact failure class the lexer was added to close, reached by
    a different route, and it is reachable from ordinary HCL (`replace(v, "{", "")`,
    `templatefile("t.tpl", {"a"="{"})`).

    Both directions matter: an opening brace skews depth (the attribute is judged
    nested and skipped), a closing brace truncates the body outright.
    """
    for label, body in (
        ("open brace in nested quote", '{\n  identifier = "${lookup(var.m, "a{b")}"\n  port = 80\n}'),
        ("close brace in nested quote", '{\n  n = "${replace(v, "}", "")}"\n  port = 80\n}'),
        ("both braces in nested quote", '{\n  n = "${replace(v, "{}", "")}"\n  port = 80\n}'),
        ("nested quote, no brace", '{\n  a = "${lookup(var.tags, "Name")}"\n  port = 80\n}'),
        ("two interpolations", '{\n  a = "${f("x{")}-${g("y}")}"\n  port = 80\n}'),
    ):
        assert VALIDATOR._attr_int(body, "port") == 80, label


def test_lexically_irrelevant_braces_do_not_hide_attributes() -> None:
    """A brace in a comment, string, or heredoc is not a block delimiter, so it must
    not shift a real top-level attribute out of scope.

    Regression guard: an earlier revision counted raw `{`/`}` and DID hide the
    attribute here. For these rules a hidden attribute means a MISSED violation
    (`publicly_accessible = true` read as absent, hence compliant), so "fail open"
    is the wrong default — the value is a plain top-level literal, not ambiguous."""
    for label, body in (
        ("hash comment", '{\n  # primary { instance\n  port = 80\n}'),
        ("slash comment", '{\n  // primary { instance\n  port = 80\n}'),
        ("block comment", '{\n  /* primary { instance */\n  port = 80\n}'),
        ("string", '{\n  identifier = "primary { db"\n  port = 80\n}'),
        ("unbalanced string", '{\n  name = "a { b"\n  port = 80\n}'),
        ("heredoc", '{\n  policy = <<EOT\n  { not code }\nEOT\n  port = 80\n}'),
    ):
        assert VALIDATOR._attr_int(body, "port") == 80, label


def test_extraction_not_truncated_by_lexically_irrelevant_closing_brace() -> None:
    """A `}` in a comment, string, or heredoc body is not a delimiter, so it must
    not end the resource body early.

    Regression guard: raw brace counting in `_extract_braced_block` truncated the
    body before `publicly_accessible = true`, so the resource reached the rules
    with the offending attribute already discarded — zero violations."""
    for label, filler in (
        ("hash comment", "  # capacity review } pending"),
        ("slash comment", "  // capacity review } pending"),
        ("block comment", "  /* capacity review } pending */"),
        ("string", '  identifier = "primary } db"'),
        ("heredoc", "  description = <<EOT\n  a closing } brace\nEOT"),
        ("closing brace in a quote nested in an interpolation", '  n = "${replace(v, "}", "")}"'),
    ):
        content = (
            'resource "aws_db_instance" "pg" {\n'
            f"{filler}\n"
            "  publicly_accessible = true\n"
            "}\n"
        )
        blocks = VALIDATOR._extract_blocks(content, "aws_db_instance")
        assert len(blocks) == 1, label
        assert (
            VALIDATOR._attr_string(blocks[0][1], "publicly_accessible") == "true"
        ), label


def test_regular_heredoc_terminator_must_be_unindented() -> None:
    """`<<TAG` requires the terminator at column 0; only `<<-TAG` tolerates
    indentation. Treating both as tolerant exits a regular heredoc early, so its
    body text is read as real code — here an in-heredoc `port = 443` was returned
    instead of the listener's own `port = 80`."""
    regular = '{\n  policy = <<EOT\n  EOT\n  port = 443\nEOT\n  port = 80\n}'
    assert VALIDATOR._attr_int(regular, "port") == 80
    indented = '{\n  policy = <<-EOT\n  { not code }\n  EOT\n  port = 80\n}'
    assert VALIDATOR._attr_int(indented, "port") == 80


def test_attribute_presence_probe_matches_value_scoping() -> None:
    """`_has_own_attr` must agree with `_attr_string` about what counts as set.

    The encryption rules read "attribute present but unreadable" as
    variable-driven and skip. If presence counted a commented-out assignment the
    reader ignores, a resource whose attribute is genuinely ABSENT — hence
    unencrypted by default — would be skipped instead of flagged."""
    only_commented = '{\n  identifier = "pg"\n  /*\n  storage_encrypted = false\n  */\n}'
    assert VALIDATOR._has_own_attr(only_commented, "storage_encrypted") is False
    assert VALIDATOR._attr_string(only_commented, "storage_encrypted") is None
    real = '{\n  storage_encrypted = var.encrypt\n}'
    assert VALIDATOR._has_own_attr(real, "storage_encrypted") is True
    assert VALIDATOR._attr_string(real, "storage_encrypted") is None


def test_commented_out_resource_is_not_extracted() -> None:
    """A commented-out resource declaration is not a resource."""
    content = (
        '# resource "aws_db_instance" "ghost" {\n'
        "#   publicly_accessible = true\n"
        "# }\n"
    )
    assert VALIDATOR._extract_blocks(content, "aws_db_instance") == []


def test_commented_out_attribute_is_not_read() -> None:
    """An attribute that only appears inside a comment is not set."""
    assert VALIDATOR._attr_int("{\n  # port = 443\n}", "port") is None
    assert VALIDATOR._attr_int("{\n  // port = 443\n}", "port") is None
    assert VALIDATOR._attr_int("{\n  /*\n  port = 443\n  */\n}", "port") is None
    assert (
        VALIDATOR._attr_string('{\n  /*\n  protocol = "HTTPS"\n  */\n}', "protocol")
        is None
    )


def test_every_fixture_matches_its_good_bad_prefix() -> None:
    """Enforce the naming invariant the fixture set relies on: `good-*` (and the
    internal-ALB case) must be POLICY_OK, `bad-*` must be POLICY_FAIL. Without
    this, each fixture is wired up by hand and a new one added without its own
    test would silently get no coverage."""
    fixture_dirs = sorted(d for d in FIXTURES.iterdir() if d.is_dir())
    # Exact, not `>=`: a floor cannot detect fixtures being deleted down to it,
    # which is the removal this assertion exists to catch. Update deliberately
    # when adding or removing a fixture.
    assert len(fixture_dirs) == 28, f"fixture count changed: {[d.name for d in fixture_dirs]}"
    for fixture in fixture_dirs:
        code, out = run_policy_validator(fixture)
        if fixture.name.startswith("bad-"):
            assert code == 1, f"{fixture.name} must FAIL: {out}"
            assert "POLICY_FAIL" in out, f"{fixture.name}: {out}"
        else:
            assert code == 0, f"{fixture.name} must pass: {out}"
            assert "POLICY_OK" in out, f"{fixture.name}: {out}"
