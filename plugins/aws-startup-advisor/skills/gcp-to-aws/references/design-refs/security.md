# Security Services Design Rubric

**Applies to:** Secret Manager and encryption/identity-adjacent security resources.

## Account-Wide Security Baseline

The plugin always emits `baseline.tf` with account-wide security controls — GuardDuty, CloudTrail (multi-region, log file validation), IMDSv2 enforcement, EBS encryption by default, S3 public access block, Access Analyzer, and budget alerts. For compliance stacks (soc2/pci/hipaa/fedramp), Config and Security Hub are added conditionally. `compliance: ["unknown"]` (not confirmed in Clarify) adds **no** conditional controls — treat it as the baseline-only case; the report carries the unconfirmed-compliance caveat.

**Do not duplicate these controls in `security.tf` or other domain files.** See `references/phases/generate/generate-artifacts-infra.md` Step 1.5 for the full baseline specification.

---

## Deterministic mappings

| GCP Service Type                       | AWS Service     | Notes                                                                                      |
| -------------------------------------- | --------------- | ------------------------------------------------------------------------------------------ |
| `google_secret_manager_secret`         | Secrets Manager | Create one secret metadata resource.                                                       |
| `google_secret_manager_secret_version` | Secrets Manager | Represent current value as a secret version or migration TODO if plaintext is unavailable. |

## Secret migration rules

1. Never place cleartext secrets directly in generated Terraform variable defaults.
2. Generate Secrets Manager resources and reference them from compute/database resources via ARN, not plaintext environment values.
3. If source secret values are not available from discovery inputs, generate TODO placeholders with explicit migration steps.
4. Add least-privilege IAM access scoped to specific secret ARNs.

---

## Security Group Patterns

Apply these patterns when generating `vpc.tf`. Start with no access and add only what is needed.

| Component    | Default Inbound                 | Default Outbound   |
| ------------ | ------------------------------- | ------------------ |
| ALB          | 443 from 0.0.0.0/0; 80 redirect | Fargate SG only    |
| Fargate      | ALB SG only (on app port)       | 443 (HTTPS), DB SG |
| EKS nodes    | ALB SG only (on app port)       | 443 (HTTPS), DB SG |
| RDS/Aurora   | Fargate SG only (on DB port)    | None               |
| ElastiCache  | Fargate SG only (on cache port) | None               |
| Lambda (VPC) | None                            | 443, DB SG         |

**Hard rules:**

- Never emit a security group ingress rule with `cidr_blocks = ["0.0.0.0/0"]` for ports 22 (SSH), 3389 (RDP), or 5900 (VNC). Emit a commented-out placeholder pointing to SSM Session Manager instead.
- ALB port 80 must redirect to 443 — never forward HTTP directly.
- All compute (Fargate, EKS nodes, EC2) must be in private subnets. ALB is the only public-facing component.

---

## IaC Security Scanning

After generating Terraform, recommend running a security scanner before `terraform apply`:

| Tool        | Purpose                                      | Command                   |
| ----------- | -------------------------------------------- | ------------------------- |
| **checkov** | Multi-framework IaC scanner (Terraform, etc) | `checkov -d terraform/`   |
| **tfsec**   | Terraform-specific security scanner          | `tfsec terraform/`        |
| **trivy**   | IaC + container image scanning               | `trivy config terraform/` |

Include this recommendation in the generated `terraform/README.md` under a "Before You Apply" section. Do not block artifact generation on scanner availability — recommend it as a post-generation step.

---

## Costing handoff

When `aws_service = "Secrets Manager"` is selected, estimate:

- Per-secret monthly storage cost
- API call cost (per 10K requests)

Use `shared/pricing-cache.md` first; use `estimate-infra.md` MCP fallback recipes only if needed.
