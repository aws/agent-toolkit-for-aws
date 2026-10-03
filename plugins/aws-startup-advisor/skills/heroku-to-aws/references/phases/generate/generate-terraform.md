---
_fragment: terraform
_of_phase: generate
_contributes:
  - terraform/main.tf
  - terraform/baseline.tf
  - terraform/variables.tf
  - terraform/outputs.tf
  - terraform/security.tf
  - terraform/beanstalk.tf
  - terraform/pipeline.tf
  - .github/workflows/deploy-eb.yml
  - terraform/.gitignore
  - terraform/terraform.tfvars.example
---

# Generate Phase: Terraform Configuration Generation

**Execute ALL steps in order. Do not skip or optimize.**

## Overview

Transform `aws-design.json` into review-ready Terraform HCL configurations. Produces a `terraform/` directory in `$MIGRATION_DIR/` containing valid, `terraform validate`-passing configurations for all designed AWS resources, plus the selected Elastic Beanstalk deploy artifact when EB is present. Elastic Beanstalk configurations require customer-supplied application port and health check path values before `terraform plan` can succeed.

## Output Structure

Generate `$MIGRATION_DIR/terraform/` with the following file organization. Only emit domain files that have resources in `aws-design.json`:

| File           | Domain     | Contains                                                                                                                               |
| -------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `main.tf`      | core       | Provider config, backend, data sources                                                                                                 |
| `baseline.tf`  | security   | Account-wide security baseline (contacts, CloudTrail, GuardDuty, budget, IMDSv2 default; compliance-conditional Config + Security Hub) |
| `variables.tf` | core       | All input variables with types and defaults                                                                                            |
| `outputs.tf`   | core       | Resource outputs and migration summary                                                                                                 |
| `vpc.tf`       | networking | VPC, subnets, route tables, internet gateway, NAT, peering                                                                             |
| `compute.tf`   | compute    | ECS cluster, Fargate task definitions, services, ALBs                                                                                  |
| `beanstalk.tf` | compute    | Elastic Beanstalk applications and environments                                                                                        |
| `pipeline.tf`  | deploy     | Optional CodePipeline source-to-EB deploy path                                                                                         |
| `database.tf`  | database   | RDS/Aurora instances, parameter groups, RDS Proxy                                                                                      |
| `cache.tf`     | cache      | ElastiCache replication groups, subnet groups                                                                                          |
| `messaging.tf` | messaging  | MSK clusters, configurations                                                                                                           |
| `dns.tf`       | dns        | Route 53 records for every custom domain (each routed to its own app's EB/Fargate web endpoint in its own zone), ACM certificate with DNS validation, weighted Heroku↔AWS cutover (only when `data.dns_strategy == "route53"` and an EB/Fargate web service exists) |
| `security.tf`  | security   | Security groups, IAM roles/policies                                                                                                    |

**File emission rules:**

- `main.tf`, `baseline.tf`, `variables.tf`, `outputs.tf` — ALWAYS emitted (`baseline.tf` is workload-independent; opting out takes two steps — delete the file AND remove its three contact variables — documented in MIGRATION_GUIDE.md Phase 1)
- `vpc.tf` — Emitted when `vpc_design` is present in `aws-design.json` (either existing or new VPC)
- `compute.tf` — Emitted when `aws_service` contains "Fargate" or "ALB" entries
- `beanstalk.tf` — Emitted when `aws_service` contains "Elastic Beanstalk" entries
- `.github/workflows/deploy-eb.yml` — Emitted when `aws_service` contains "Elastic Beanstalk" entries and `preferences.design_constraints.eb_deploy_method.value` is `"github_actions"` or absent (default)
- `pipeline.tf` — Emitted only when `aws_service` contains "Elastic Beanstalk" entries and `preferences.design_constraints.eb_deploy_method.value` is `"codepipeline"`
- `database.tf` — Emitted when `aws_service` contains "RDS" or "Aurora" entries
- `cache.tf` — Emitted when `aws_service` contains "ElastiCache" entries
- `messaging.tf` — Emitted when `aws_service` contains "MSK" entries
- `dns.tf` — Emitted when `preferences.data.dns_strategy == "route53"` (Clarify Q10 writes it under `data`, not `global` — `clarify-assemble.md`) AND at least one inventory `resource_type: "domain"` hostname resolves to an Elastic Beanstalk or Fargate web service (`generate-docs.md` Step 0 `eligible_hostnames[]`). Owns the ACM certificate too, so `compute.tf` / `beanstalk.tf` reference it instead of `var.acm_certificate_arn` (see Step 6 and Step 6.5). When `dns_strategy` is anything other than `"route53"`, no custom domain was discovered, or the design is EKS (no EB/Fargate web service exists — `design-eks.md` "All-or-Nothing Rule"), no `dns.tf` is written and the guide's cutover section gives manual record instructions.
- `security.tf` — ALWAYS emitted (security groups required for all deployments)

**Service-to-file routing:**

| AWS Service in `aws-design.json`   | Target File                                                                                                     |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Fargate, ALB                       | `compute.tf`                                                                                                    |
| Elastic Beanstalk                  | `beanstalk.tf`; plus `.github/workflows/deploy-eb.yml` for `github_actions` or `pipeline.tf` for `codepipeline` |
| RDS PostgreSQL, Aurora PostgreSQL  | `database.tf`                                                                                                   |
| ElastiCache Redis                  | `cache.tf`                                                                                                      |
| Amazon MSK                         | `messaging.tf`                                                                                                  |
| VPC, Subnet, Route Table, IGW, NAT | `vpc.tf`                                                                                                        |
| Security Group, IAM Role/Policy    | `security.tf`                                                                                                   |
| CloudWatch Logs                    | `compute.tf`                                                                                                    |
| Route 53 + ACM (from `preferences.data.dns_strategy == "route53"` and inventory `domain` resources whose app has an EB or Fargate web service — not an `aws-design.json` service) | `dns.tf` |

**Unmapped services:** If `aws-design.json` contains a `service_id` with an `aws_service` value that has no Terraform resource mapping in this file (e.g., CloudWatch + X-Ray composite, Amazon SES, Amazon SNS), **skip** that resource and record a warning in `generation-warnings.json` (which is ALWAYS written — see Step 10 — with an empty `warnings` array when nothing is skipped). Do NOT halt generation.

---

## Step 0: Apply AWS authoring posture (before writing any `.tf`)

**Before generating any Terraform, invoke the `tf-best-practices` skill for its authoring posture** — it is the single source of truth for "what good AWS Terraform looks like." Treat it as a **black box**: pass the caller context below and emit Terraform that satisfies every rule it returns. Do **not** reach into its files or re-specify its rules here — it evolves independently.

> Invoke the **`tf-best-practices`** skill, telling it you are **about to author `terraform/`** (the pre-generation context).

**Pass the caller context** (heroku-to-aws supplies these; the skill reads none of our artifacts):

- **`compliance`** — the normalized compliance array (see Step 1.5 item 0 for the scalar/absent/`"none"`/`"unknown"` normalization). Empty ⇒ no compliance-conditional hardening.
- **`aws_config` values** — instance classes, CPU/memory, storage, engine versions from each service's `aws_config` in `aws-design.json`. The posture constrains the shape, not the numbers.

The Elastic Beanstalk / Fargate / RDS / ElastiCache / MSK wiring in the steps below is heroku-to-aws's source glue (value population + EB `setting` blocks); the _security posture_ on those resources is owned by the skill. Following the posture makes the Step 12 policy gate pass by construction.

---

## Step 1: Generate `main.tf`

```hcl
# Heroku-to-AWS Migration — Terraform Configuration
#
# Generated by the heroku-to-aws migration skill.
# This configuration implements the architecture designed in aws-design.json.
#
# Apply sequence:
#   1. terraform init
#   2. terraform plan -out=tfplan
#   3. terraform apply tfplan

terraform {
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
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      MigrationId = var.migration_id
      Source      = "heroku-to-aws"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}
```

**Customization rules:**

- `region` value: Use `var.aws_region` (populated from `preferences.json.global.target_region`)
- `MigrationId` tag: Use the migration run ID from `.phase-status.json`

---

## Step 1.5: Generate `baseline.tf`

Always emitted. The baseline applies account-wide security controls that should be in place on any new AWS account. Users who do not want the baseline delete `terraform/baseline.tf` AND remove its three contact email variables from `variables.tf`/tfvars (they have no defaults, so plan fails on them even unreferenced) — MIGRATION_GUIDE.md Phase 1 documents both steps. It is workload-independent: emit it regardless of which services `aws-design.json` contains.

0. **Normalize compliance.** Read `preferences.json.global.compliance`. It is a scalar string (`"none"`, `"soc2"`, `"hipaa"`, `"pci"`) or, when the user specified multiple frameworks in Clarify Q2 option E, an array of strings. Normalize to an array: absent, `"none"`, or `"unknown"` → `[]` (an absent or unconfirmed answer is not a framework); scalar → single-element array; array → lowercase as-is, dropping any `"none"`/`"unknown"` entries. Every reference to `compliance` below means this normalized array.

1. **Compute retention.** Compute `cloudtrail_retention_days` from the normalized `compliance` array using this mapping, taking `max()` across all declared values (use 90 if the array is empty):
   - `[]` → 90
   - `soc2` → 365
   - `pci` → 365
   - `hipaa` → 2190
   - `fedramp` → 1095
   - `gdpr` → 365
   - unrecognized value → 365 (conservative), and note the unrecognized framework in the `baseline.tf` file-header comment (item 3) — do NOT add it to `generation-warnings.json`, whose entries are service-shaped and feed the every-service-accounted-for gate

2. **Compute budget limit.** Read `estimation-infra.json.projected_costs.aws_monthly_balanced` (the Balanced-tier monthly total — the same key this skill's Estimate postconditions assert is a positive number). Compute `budget_limit = max(50, ceil(aws_monthly_balanced * 1.2))`. If `estimation-infra.json` is missing or the key is unreadable, use `50` and emit an inline comment noting that the projection was unavailable.

3. **Choose file-header variant.** If `compliance` contains any of `soc2`, `pci`, `hipaa`, `fedramp`, emit the compliance-expansion header. Otherwise emit the base header. Both variants include a two-sentence provenance note stating per-unit rates in the cost-disclosure comments were verified against the AWS Pricing API for us-east-1 on 2026-05-04. Substitute the resolved `cloudtrail_retention_days` value into the header. When item 1 encountered an unrecognized compliance value, append one header line naming it and the conservative 365-day retention applied (e.g. `# Unrecognized compliance framework "iso27001" — applied conservative 365-day CloudTrail retention`).

4. **Emit `baseline.tf`** starting with the file-header comment block and a `locals` block containing the resolved `cloudtrail_retention_days` integer:

   ```hcl
   locals {
     cloudtrail_retention_days = <N>
   }
   ```

5. **Append the always-on resources**, in this order. Provider `default_tags` (Step 1) supply the standard tags; each baseline resource additionally carries `tags = { Component = "security-baseline" }` where the resource type supports tags:
   - `aws_account_alternate_contact.operations` (ACCT.01; `alternate_contact_type = "OPERATIONS"`, `email_address = var.operations_email` — fill-once variable, see Step 2. `name`, `title`, and `phone_number` are ALSO required by this resource type: pin `name = "Operations Contact"`, `title = "Operations"`, and the placeholder `phone_number = "+1-555-0100"` with an inline comment telling the user to update the phone number post-apply — see the golden HCL below)
   - `aws_account_alternate_contact.billing` (ACCT.01; `alternate_contact_type = "BILLING"`, `email_address = var.billing_email`; pinned `name = "Billing Contact"`, `title = "Billing"`, same placeholder phone pattern)
   - `aws_account_alternate_contact.security` (ACCT.01; `alternate_contact_type = "SECURITY"`, `email_address = var.security_email`; pinned `name = "Security Contact"`, `title = "Security"`, same placeholder phone pattern)
   - `aws_iam_account_password_policy.baseline` (ACCT.06; `minimum_password_length = 14`, `password_reuse_prevention = 24`, `max_password_age = 90`, all four character-class requirements `true`, `hard_expiry = false`)
   - `aws_s3_account_public_access_block.baseline` (ACCT.08; all four flags `true`)
   - `aws_ebs_encryption_by_default.baseline` (defense-in-depth; `enabled = true`)
   - `aws_accessanalyzer_analyzer.baseline` (ACCT.11; `type = "ACCOUNT"`)
   - `aws_ec2_instance_metadata_defaults.baseline` (defense-in-depth; `http_tokens = "required"`, `http_put_response_hop_limit = 2`)
   - `aws_cloudtrail.baseline` (ACCT.07; `name = "${var.project_name}-baseline"` — MUST match the `aws:SourceArn` in the bucket policy exactly, see the golden HCL; multi-region, management events only, `enable_log_file_validation = true`, `depends_on = [aws_s3_bucket_policy.cloudtrail_logs]` — CloudTrail validates the bucket policy at create time)
   - `aws_s3_bucket.cloudtrail_logs` plus `aws_s3_bucket_public_access_block`, `aws_s3_bucket_server_side_encryption_configuration`, `aws_s3_bucket_versioning`, `aws_s3_bucket_lifecycle_configuration` (transitions driven by `local.cloudtrail_retention_days` per item 7), and `aws_s3_bucket_policy` restricting the CloudTrail service principal by `aws:SourceArn`
   - `aws_budgets_budget.monthly_spend` (ACCT.10; `limit_amount = "<budget_limit>"` from item 2; three `notification` blocks at 50/80/100% `ACTUAL`; `subscriber_email_addresses = [var.billing_email]` — same fill-once variable as the alternate contact, entered exactly once in tfvars)
   - `aws_guardduty_detector.baseline` (defense-in-depth; `enable = true`, `finding_publishing_frequency = "FIFTEEN_MINUTES"`)

6. **If `compliance` contains any of `soc2`, `pci`, `hipaa`, `fedramp`, append the compliance-conditional section**, wrapped in `########## Compliance-Conditional ##########` / `########## End Compliance-Conditional ##########` dividers:
   - `aws_iam_role.config` (trust policy for `config.amazonaws.com` — see the golden HCL below) + `aws_iam_role_policy_attachment` for the managed policy `arn:aws:iam::aws:policy/service-role/AWS_ConfigRole` (note the underscore — `AWSConfigRole` without it is a different, deprecated policy name and fails apply)
   - `aws_config_configuration_recorder.baseline` with `recording_group { all_supported = true, include_global_resource_types = true }`
   - `aws_config_delivery_channel.baseline` pointing at the Config S3 bucket
   - `aws_config_configuration_recorder_status.baseline` with `is_enabled = true`
   - `aws_s3_bucket.config_logs` plus PAB, SSE, versioning, lifecycle (same `local.cloudtrail_retention_days`), and a bucket policy allowing the `config.amazonaws.com` service principal
   - `aws_securityhub_account.baseline`
   - `aws_securityhub_standards_subscription.fsbp` (always emitted in this section)
   - `aws_securityhub_standards_subscription.pci_dss` (only if `compliance` contains `pci`)

   Do NOT emit an NIST 800-53 standards subscription, even if `compliance` contains `hipaa` or `fedramp`. Security Hub does not provide a HIPAA-specific standard; FedRAMP attestation is out-of-band.

7. **Lifecycle rule adjustment.** Omit the `STANDARD_IA` transition block when the resolved retention is less than 90 days. Omit the `GLACIER` transition block when retention is less than 365 days. Both rules apply to both the CloudTrail log bucket and (when emitted) the Config log bucket.

8. **Attach inline HCL comments**:
   - On each `aws_account_alternate_contact.*`: a comment pointing at the tfvars fill-once variable (`# set var.operations_email in terraform.tfvars — plan fails until you do`) and noting the phone number is a placeholder to update post-apply.
   - On `aws_cloudtrail.baseline`: a collision warning for users who already have a trail in the region.
   - On `aws_budgets_budget.monthly_spend`: the limit-rationale comment (`max(50, ceil(aws_monthly_balanced * 1.2))`; $50 floor prevents alert noise; users may edit `limit_amount` directly post-apply).
   - On `aws_guardduty_detector.baseline`: a cost disclosure noting the 30-day free trial and ~$2–25/mo post-trial.
   - On `aws_config_configuration_recorder.baseline`: a cost disclosure ($0.003/CI continuous; $0.012/daily-CI as an opt-in for cost-sensitive users).
   - On `aws_securityhub_account.baseline`: a cost disclosure noting the 30-day free trial and ~$1–15/mo post-trial.
   - On every defense-in-depth resource (EBS encryption, IMDSv2 account default, GuardDuty, Config, Security Hub): the literal token `defense-in-depth` in the inline comment.

**Golden HCL for the shapes agents get wrong.** The resource lists above name types; the shapes below have required arguments, policy documents, or cross-resource name/ordering couplings that must not be improvised. Match them exactly (identifiers/region values may vary, but the trail name and the `aws:SourceArn` conditions must agree):

```hcl
# Alternate contact — all four of name / title / email_address / phone_number are REQUIRED
resource "aws_account_alternate_contact" "operations" {
  alternate_contact_type = "OPERATIONS"
  name                   = "Operations Contact"
  title                  = "Operations"
  email_address          = var.operations_email
  phone_number           = "+1-555-0100" # placeholder — update post-apply with a real number
}

# CloudTrail log bucket policy — service principal scoped by SourceArn
data "aws_iam_policy_document" "cloudtrail_logs" {
  statement {
    sid       = "AWSCloudTrailAclCheck"
    effect    = "Allow"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.cloudtrail_logs.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:trail/${var.project_name}-baseline"]
    }
  }
  statement {
    sid       = "AWSCloudTrailWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.cloudtrail_logs.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:trail/${var.project_name}-baseline"]
    }
  }
}

# The policy document must be ATTACHED, and the trail name must match the
# SourceArn above exactly — CloudTrail validates the bucket policy at create
# time, so the trail depends_on the attachment.
resource "aws_s3_bucket_policy" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  policy = data.aws_iam_policy_document.cloudtrail_logs.json
}

resource "aws_cloudtrail" "baseline" {
  # Trail already in this region? See the collision warning in item 8.
  name                          = "${var.project_name}-baseline" # MUST match the SourceArn conditions above
  s3_bucket_name                = aws_s3_bucket.cloudtrail_logs.id
  is_multi_region_trail         = true
  enable_log_file_validation    = true
  include_global_service_events = true

  depends_on = [aws_s3_bucket_policy.cloudtrail_logs]
}

# Config role — trust policy + the CURRENT managed policy name (underscore)
resource "aws_iam_role" "config" {
  name = "${var.project_name}-config-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "config.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "config" {
  role       = aws_iam_role.config.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWS_ConfigRole"
}

# Lifecycle configuration — every rule needs a filter (or prefix) block
resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  rule {
    id     = "retention"
    status = "Enabled"
    filter {} # applies to the whole bucket
    expiration {
      days = local.cloudtrail_retention_days
    }
    # STANDARD_IA / GLACIER transition blocks per item 7's thresholds
  }
}
```

**EKS launch-template rider (runs in the eks-generate fragment, not here):** when the design routes compute to EKS with self-managed node groups, the `aws_launch_template` emitted by `generate-eks.md` receives IMDSv2 enforcement unconditionally:

```hcl
metadata_options {
  http_tokens                 = "required"
  http_put_response_hop_limit = 1
  http_endpoint               = "enabled"
  instance_metadata_tags      = "enabled"
}
```

Fargate and Elastic Beanstalk do not emit launch templates in this skill and are unaffected (no synthetic launch template is created). Hop limit `1` here is intentionally different from the account-level default `2` in `aws_ec2_instance_metadata_defaults.baseline` — strict on templates the plugin owns, permissive at the account default.

**Emission conditions**:

- Emit `baseline.tf` for every design, including EB-only, Fargate-only, and EKS designs. The baseline is workload-independent.
- Do NOT probe for existing account resources (CloudTrail trails, Config recorders, Security Hub enrollment). Collision risk is surfaced by the inline comments listed in item 8.

---

## Step 2: Generate `variables.tf`

**Always include these global variables:**

```hcl
variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "<preferences.json.global.target_region>"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "<heroku_app_name or migration_id>"
}

variable "environment" {
  description = "Environment name (e.g., production, staging)"
  type        = string
  default     = "<preferences.json.global.environment_naming>"
}

variable "migration_id" {
  description = "Migration run identifier"
  type        = string
  default     = "<migration_id from .phase-status.json>"
}

variable "writers_quiesced" {
  description = "Phase 6 sets this true in terraform.tfvars before any apply during failback or rollback, and leaves it true until the next intentional handoff. Fargate desired_count becomes 0. Elastic Beanstalk cannot represent 0 instances (aws:autoscaling:asg MinSize is 1-10000); the guide drains that Auto Scaling group directly and does not apply the Beanstalk environment while this is true."
  type        = bool
  default     = false
}
```

**Baseline contact variables (always include — `baseline.tf` depends on them):** the three fill-once contact emails referenced by `baseline.tf`'s alternate contacts and budget alerts. They intentionally have no `default` — `terraform plan` must fail until the customer supplies real values — and each carries a `validation` block rejecting placeholder tokens, so a copied-through `TODO-ops@example.com` fails loudly at `terraform plan` instead of silently becoming the account's security contact:

```hcl
variable "operations_email" {
  description = "Operations contact for AWS account alternate contacts (MIGRATION_GUIDE.md Phase 1)"
  type        = string

  validation {
    condition     = !strcontains(var.operations_email, "TODO") && !strcontains(var.operations_email, "example.com") && strcontains(var.operations_email, "@")
    error_message = "Set operations_email in terraform.tfvars to a real inbox (see MIGRATION_GUIDE.md Phase 1, Security baseline contacts)."
  }
}

variable "billing_email" {
  description = "Billing contact + budget alert recipient (MIGRATION_GUIDE.md Phase 1)"
  type        = string

  validation {
    condition     = !strcontains(var.billing_email, "TODO") && !strcontains(var.billing_email, "example.com") && strcontains(var.billing_email, "@")
    error_message = "Set billing_email in terraform.tfvars to a real inbox (see MIGRATION_GUIDE.md Phase 1, Security baseline contacts)."
  }
}

variable "security_email" {
  description = "Security contact for AWS account alternate contacts (MIGRATION_GUIDE.md Phase 1)"
  type        = string

  validation {
    condition     = !strcontains(var.security_email, "TODO") && !strcontains(var.security_email, "example.com") && strcontains(var.security_email, "@")
    error_message = "Set security_email in terraform.tfvars to a real inbox (see MIGRATION_GUIDE.md Phase 1, Security baseline contacts)."
  }
}
```

**Per-service variables** — Extract from `aws-design.json` `aws_config` for each designed service. Include:

- Compute: `container_image_*` (one per Fargate service), `desired_count_*`, EB `instance_type_*`, `min_instances_*`, `max_instances_*`
- Database: `db_instance_class`, `db_storage_gb`, `db_engine_version`, `db_multi_az`
- Cache: `cache_node_type`, `cache_engine_version`, `cache_multi_az`
- Messaging: `msk_broker_instance_type`, `msk_broker_count`, `msk_storage_gb`
- Network: `vpc_id` (when referencing existing), `subnet_ids` (when referencing existing), `vpc_cidr` (when creating new)

**Elastic Beanstalk web runtime inputs** — For each service where `aws_service ==
"Elastic Beanstalk"` and `aws_config.process_type == "web"`, sanitize the app name
by replacing `-` with `_`, then emit that app's two variables below. Do not emit
these variables for non-web Elastic Beanstalk services. The variables intentionally
have no `default`: the generator has no evidence for either application-specific
value, and `terraform plan -input=false` must fail with Terraform's
required-variable diagnostic until the customer supplies both values.

```hcl
variable "eb_application_port_<app_sanitized>_web" {
  description = "Exact port value the <heroku_app> Elastic Beanstalk web process listens on"
  type        = string

  validation {
    condition = (
      can(regex("^[1-9][0-9]{0,4}$", var.eb_application_port_<app_sanitized>_web)) &&
      try(tonumber(var.eb_application_port_<app_sanitized>_web) <= 65535, false)
    )
    error_message = "Elastic Beanstalk application port must be an integer from 1 through 65535."
  }
}

variable "eb_health_check_path_<app_sanitized>_web" {
  description = "Exact HTTP health check path for the <heroku_app> Elastic Beanstalk web environment"
  type        = string

  validation {
    condition = (
      startswith(var.eb_health_check_path_<app_sanitized>_web, "/") &&
      length(var.eb_health_check_path_<app_sanitized>_web) <= 1024
    )
    error_message = "Elastic Beanstalk health check path must start with / and contain at most 1024 characters."
  }
}
```

Preserve both customer values exactly. Reference each variable directly from the
corresponding app's Elastic Beanstalk setting. Validate but do not trim, normalize,
convert, or replace either value, and do not derive a fallback from the source
repository.

**Naming convention:** `<resource_type>_<heroku_app>_<attribute>` (sanitize app names: replace `-` with `_`).

Use `aws_config` values from `aws-design.json` as defaults. Add Heroku source as comment:

```hcl
variable "fargate_cpu_my_web_app_web" {
  description = "Fargate CPU units for my-web-app web process"
  type        = number
  default     = 512
  # Heroku source: standard-2x dyno
}
```

---

## Step 3: Generate `outputs.tf`

```hcl
output "migration_summary" {
  description = "Summary of migrated Heroku resources"
  value = {
    source_platform   = "heroku"
    target_region     = var.aws_region
    migration_id      = var.migration_id
    services_migrated = <count of services in aws-design.json>
  }
}
```

Add per-service outputs for connection information:

```hcl
# Compute outputs — one per web app, suffixed with <app_sanitized>.
# Fargate web outputs: emit once per `alb:{heroku_app}:web` service.
output "alb_dns_name_<app_sanitized>" {
  description = "ALB DNS name for <heroku_app>'s Fargate web traffic"
  value       = aws_lb.<app_sanitized>_web.dns_name
}

# EB web outputs: emit once per `eb:{heroku_app}:web` service, only when a web process exists. Worker-only apps have no public EB CNAME.
output "eb_environment_url_<app_sanitized>" {
  description = "Elastic Beanstalk web environment CNAME for <heroku_app>"
  value       = aws_elastic_beanstalk_environment.<app_sanitized>_web.cname
}

# Database outputs
output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint"
  value       = aws_db_instance.postgres.endpoint
  sensitive   = true
}

output "rds_proxy_endpoint" {
  description = "RDS Proxy endpoint for connection pooling"
  value       = aws_db_proxy.postgres.endpoint
  sensitive   = true
}

# Cache outputs
output "elasticache_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
  sensitive   = true
}

# Messaging outputs
output "msk_bootstrap_brokers" {
  description = "MSK bootstrap broker connection string"
  value       = aws_msk_cluster.kafka.bootstrap_brokers_tls
  sensitive   = true
}

# {{IF has_route53_dns}}
# DNS outputs
output "dns_cutover" {
  description = "Per hostname: the Heroku app it belongs to, the zone it lives in, the AWS endpoint it cuts over to, and where Route 53 currently sends traffic"
  value = {
    for h in local.custom_domains : h => {
      heroku_app    = local.aws_targets[h].heroku_app
      zone_id       = var.hosted_zone_ids[h]
      aws_target    = local.aws_targets[h].name
      aws_weight    = var.cutover_weight
      heroku_weight = 100 - var.cutover_weight
      apex          = local.is_apex[h]
    }
  }
}
# {{ENDIF}}
```

Only emit outputs for services present in `aws-design.json`. Mark connection strings as `sensitive = true`.

Compute outputs are per web app and reference the Step 6 / Step 6.5 resource names (`aws_lb.<app_sanitized>_web`, `aws_elastic_beanstalk_environment.<app_sanitized>_web`) — never a shared `alb_dns_name` / `eb_environment_url`, so a production/staging pair gets two distinct outputs and `generate-docs.md` Step 0 `dns_hostnames[].output_name` names each hostname's own.

---

## Step 4: Generate `vpc.tf`

Read `aws-design.json.vpc_design.mode` to determine which path to follow.

### Path A: Existing VPC (peering detected — `mode: "existing_vpc"`)

When `vpc_design.mode == "existing_vpc"`, reference the existing VPC and subnets as data sources or variables. Do NOT create new VPC resources.

```hcl
# VPC — Referencing existing VPC from Heroku Private Space peering
# Heroku source: Private Space with VPC peering to vpc-0123456789abcdef0

variable "existing_vpc_id" {
  description = "Existing AWS VPC ID (from Heroku Private Space peering)"
  type        = string
  default     = "<vpc_design.existing_vpc_id>"
}

variable "existing_subnet_ids" {
  description = "Existing subnet IDs within the peered VPC"
  type        = list(string)
  default     = <vpc_design.subnet_ids as HCL list>
}

data "aws_vpc" "existing" {
  id = var.existing_vpc_id
}

data "aws_subnet" "existing" {
  for_each = toset(var.existing_subnet_ids)
  id       = each.value
}
```

### Path B: New VPC (no peering — `mode: "new_vpc"`)

When `vpc_design.mode == "new_vpc"`, generate a complete VPC configuration:

```hcl
# VPC — New VPC for Heroku migration (no Private Space peering detected)

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.project_name}-${var.environment}-vpc"
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the new VPC"
  type        = string
  default     = "10.0.0.0/16"
}

# Public subnets (for ALB)
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-${var.environment}-public-${count.index + 1}"
    Tier = "public"
  }
}

# Private subnets (for Fargate, RDS, ElastiCache, MSK)
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${var.project_name}-${var.environment}-private-${count.index + 1}"
    Tier = "private"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project_name}-${var.environment}-igw"
  }
}

# NAT Gateway (for private subnet internet access)
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "${var.project_name}-${var.environment}-nat-eip"
  }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name = "${var.project_name}-${var.environment}-nat"
  }

  depends_on = [aws_internet_gateway.main]
}

# Route Tables
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-public-rt"
  }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-private-rt"
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
```

**VPC rules:**

- Always use at least 2 subnets across separate AZs (per Requirement 9.4)
- Public subnets host ALBs; private subnets host Fargate, databases, caches, and messaging
- Single NAT gateway for cost optimization (user can expand for HA post-apply)

---

## Step 5: Generate `security.tf`

Generate security groups based on `aws-design.json.vpc_design.security_groups` and the services present.

### Private Space Migration (restricted inbound rules)

When the source inventory contains Private Space resources, generate security groups that restrict inbound traffic to declared dependency CIDRs/ports only:

```hcl
# Security Groups — Restricted inbound for Private Space migration
# Only declared dependency CIDRs and ports are permitted inbound.

resource "aws_security_group" "app" {
  name_prefix = "${var.project_name}-${var.environment}-app-"
  vpc_id      = <vpc_id_reference>
  description = "Security group for migrated Heroku app (Private Space)"

  # Inbound: Only declared dependencies
  dynamic "ingress" {
    for_each = var.app_ingress_rules
    content {
      from_port   = ingress.value.port
      to_port     = ingress.value.port
      protocol    = ingress.value.protocol
      cidr_blocks = [ingress.value.cidr]
      description = ingress.value.description
    }
  }

  # Outbound: Allow all (required for Fargate tasks to pull images, etc.)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-app-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

variable "app_ingress_rules" {
  description = "Ingress rules for application security group (from Private Space dependencies)"
  type = list(object({
    port        = number
    protocol    = string
    cidr        = string
    description = string
  }))
  default = [
    # Populated from aws-design.json vpc_design.security_groups[].inbound_rules
    # Example:
    # { port = 443, protocol = "tcp", cidr = "0.0.0.0/0", description = "HTTPS from internet" },
    # { port = 5432, protocol = "tcp", cidr = "10.0.0.0/16", description = "PostgreSQL from VPC" }
  ]
}
```

### Standard Migration (no Private Space)

When no Private Space is involved, generate standard security groups:

```hcl
# ALB Security Group
resource "aws_security_group" "alb" {
  name_prefix = "${var.project_name}-${var.environment}-alb-"
  vpc_id      = <vpc_id_reference>
  description = "Security group for Application Load Balancer"

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTPS from internet"
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP from internet (redirects to HTTPS)"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-alb-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Application Security Group
resource "aws_security_group" "app" {
  name_prefix = "${var.project_name}-${var.environment}-app-"
  vpc_id      = <vpc_id_reference>
  description = "Security group for migrated application compute"

  # {{IF has_fargate}}
  ingress {
    from_port       = 0
    to_port         = 65535
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "Traffic from Terraform-managed ALB (Fargate path only)"
  }
  # {{ENDIF}}
  # For EB-only designs, omit ingress here. EB manages load balancer-to-instance ingress;
  # SingleInstance non-web environments do not need inbound traffic.

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-app-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Database Security Group
resource "aws_security_group" "database" {
  name_prefix = "${var.project_name}-${var.environment}-db-"
  vpc_id      = <vpc_id_reference>
  description = "Security group for RDS/Aurora databases"

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
    description     = "PostgreSQL from application compute"
  }

  # {{IF migration_approach == "interim_cutover_data_first"}}
  # INTERIM ONLY — Heroku app still on Heroku, reaching this database.
  # Bounded allowlist, never 0.0.0.0/0. Populate interim_heroku_ingress_cidrs in
  # terraform.tfvars from MIGRATION_GUIDE.md "Interim Database Exposure" Step 2:
  # Private Space peering CIDRs, Private Space stable outbound IPs, or a
  # static-egress proxy add-on's IPs. Empty (the default) emits no rule.
  # Reset to [] and delete this block only after the Phase 6 rollback window (72 h at
  # cutover_weight = 100) — MIGRATION_GUIDE.md "Interim Database Exposure" Step 4 / Phase 7.
  # Never at cutover: after the Phase 2 database handoff Heroku dynos reach the primary over
  # this path, and a rollback depends on it.
  dynamic "ingress" {
    for_each = length(var.interim_heroku_ingress_cidrs) > 0 ? [1] : []
    content {
      from_port   = 5432
      to_port     = 5432
      protocol    = "tcp"
      cidr_blocks = var.interim_heroku_ingress_cidrs
      description = "INTERIM: PostgreSQL from Heroku static egress — remove after the rollback window"
    }
  }
  # {{ENDIF}}

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-db-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Cache Security Group
resource "aws_security_group" "cache" {
  name_prefix = "${var.project_name}-${var.environment}-cache-"
  vpc_id      = <vpc_id_reference>
  description = "Security group for ElastiCache"

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
    description     = "Redis from application compute"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-cache-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Messaging Security Group (MSK)
resource "aws_security_group" "messaging" {
  name_prefix = "${var.project_name}-${var.environment}-msk-"
  vpc_id      = <vpc_id_reference>
  description = "Security group for Amazon MSK"

  ingress {
    from_port       = 9094
    to_port         = 9094
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
    description     = "Kafka TLS from application compute"
  }

  ingress {
    from_port       = 9092
    to_port         = 9092
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
    description     = "Kafka plaintext from application compute"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-msk-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# {{IF migration_approach == "interim_cutover_data_first"}}
variable "interim_heroku_ingress_cidrs" {
  description = "INTERIM ONLY: bounded allowlist for the Heroku app's egress addresses while it still runs on Heroku — /32 host addresses on Paths B and C, or the Private Space CIDRs on Path A. Empty (default) emits no interim ingress rule. See MIGRATION_GUIDE.md 'Interim Database Exposure' Step 2."
  type        = list(string)
  default     = []

  validation {
    condition     = !contains(var.interim_heroku_ingress_cidrs, "0.0.0.0/0")
    error_message = "interim_heroku_ingress_cidrs must be a bounded allowlist of specific addresses; 0.0.0.0/0 is not permitted for a database port."
  }

  # Rejecting only the literal 0.0.0.0/0 would still admit an equivalent split
  # (0.0.0.0/1 + 128.0.0.0/1, and so on down to /7), so constrain the SHAPE: every
  # entry must be a well-formed CIDR with a prefix of /8 or longer. That admits
  # everything the guide prescribes — /32 host addresses and Private Space ranges,
  # up to a whole RFC 1918 10.0.0.0/8 — while no combination of permitted entries
  # can cover the internet without hundreds of lines.
  validation {
    condition = alltrue([
      for cidr in var.interim_heroku_ingress_cidrs :
      can(cidrnetmask(cidr)) && can(regex("/(8|9|[12][0-9]|3[0-2])$", cidr))
    ])
    error_message = "Each entry in interim_heroku_ingress_cidrs must be a valid IPv4 CIDR with a prefix of /8 or longer; broader prefixes cover too much of the internet for a database port."
  }
}
# {{ENDIF}}
```

**Security group rules:**

- Only emit security groups for services present in `aws-design.json`
- App SG allows traffic from Terraform-managed ALB SG for the Fargate path. For EB web environments, EB manages the load balancer security group and instance ingress rule; SingleInstance non-web environments do not need inbound traffic.
- Database/Cache/MSK SGs allow traffic from the app SG only
- ALB SG allows 80 and 443 from 0.0.0.0/0
- All SGs allow all outbound (compute needs ECR/source bundle access, package downloads, and service connectivity)
- When `migration_approach == "interim_cutover_data_first"`, the database SG additionally emits one gated `dynamic "ingress"` for the Heroku app's egress addresses. It is a bounded CIDR allowlist driven by `interim_heroku_ingress_cidrs`, defaults to emitting nothing, and must never contain `0.0.0.0/0` — the variable's `validation` block enforces this.

### IAM Roles

Generate ECS task execution and task roles:

```hcl
# ECS Task Execution Role
resource "aws_iam_role" "ecs_execution" {
  name = "${var.project_name}-${var.environment}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = {
    Name = "${var.project_name}-${var.environment}-ecs-execution"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ECS Task Role (application permissions)
resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-${var.environment}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = {
    Name = "${var.project_name}-${var.environment}-ecs-task"
  }
}
```

---

## Step 6: Generate `compute.tf`

For each service in `aws-design.json` where `aws_service` is "Fargate" or "ALB":

### ECS Cluster

```hcl
# ECS Cluster for migrated Heroku applications
resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-cluster"
  }
}
```

### CloudWatch Log Groups (per Fargate service)

```hcl
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.project_name}-${var.environment}/<process_type>"
  retention_in_days = <preferences.json.operational.log_retention_days || 30>

  tags = {
    Name        = "${var.project_name}-${var.environment}-<process_type>-logs"
    HerokuApp   = "<heroku_app>"
    ProcessType = "<process_type>"
  }
}
```

### Fargate Task Definitions

Generate one task definition per formation entry in `aws-design.json`:

```hcl
# Fargate Task Definition — <heroku_app>:<process_type>
# Heroku source: <dyno_type> dyno, quantity <desired_count>
resource "aws_ecs_task_definition" "<app_sanitized>_<process_type>" {
  family                   = "${var.project_name}-${var.environment}-<process_type>"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = <aws_config.task_cpu>
  memory                   = <aws_config.task_memory>
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name  = "<process_type>"
    image = var.<container_image_variable>
    portMappings = [
      {
        containerPort = <port: 8080 for web, omit for workers>
        hostPort      = <port: 8080 for web, omit for workers>
        protocol      = "tcp"
      }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.<ref>.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "<process_type>"
      }
    }
    essential = true
  }])

  tags = {
    Name        = "${var.project_name}-${var.environment}-<process_type>-task"
    HerokuApp   = "<heroku_app>"
    ProcessType = "<process_type>"
  }
}
```

**Task definition rules:**

- `cpu` and `memory` come from `aws_config.task_cpu` and `aws_config.task_memory` (mapped from Dyno Type Table)
- `portMappings` included only for `web` process types (port 8080 default)
- Workers, clock, and custom process types: no `portMappings`. Release process types are run-once hooks and should not be generated as persistent services.
- Container image: use variable reference (placeholder image at generation time)

### Fargate Services

```hcl
# Fargate Service — <heroku_app>:<process_type>
resource "aws_ecs_service" "<app_sanitized>_<process_type>" {
  name            = "${var.project_name}-${var.environment}-<process_type>"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.<app_sanitized>_<process_type>.arn
  # 0 while var.writers_quiesced is true, so a later apply (DNS rollback, a repair)
  # cannot restart tasks that Phase 6 scaled to zero. Set the variable back to false
  # only at the next intentional handoff.
  desired_count   = var.writers_quiesced ? 0 : <aws_config.desired_count>
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = <private_subnet_references>
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  # Load balancer block included ONLY for web process types
  load_balancer {
    target_group_arn = aws_lb_target_group.<app_sanitized>_web.arn
    container_name   = "web"
    container_port   = 8080
  }

  depends_on = [aws_lb_listener.https]

  tags = {
    Name        = "${var.project_name}-${var.environment}-<process_type>-svc"
    HerokuApp   = "<heroku_app>"
    ProcessType = "<process_type>"
  }
}
```

**Service rules:**

- `desired_count` from `aws_config.desired_count` (maps directly from Heroku formation quantity, 0–100)
- `load_balancer` block included ONLY when `aws_config.load_balancer == true` (web process types)
- Workers, clock, and custom processes: omit `load_balancer` block and `depends_on`. Release process types are skipped because they are run-once hooks.
- `assign_public_ip = false` — tasks run in private subnets behind NAT

### Application Load Balancer (web process types only)

Generate ALB resources only when `aws-design.json` contains ALB service entries:

```hcl
# Application Load Balancer — <heroku_app> web traffic
# Heroku source: web dyno routing
resource "aws_lb" "<app_sanitized>_web" {
  name               = "${var.project_name}-${var.environment}-alb"
  internal           = <false for internet-facing, true for internal>
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = <public_subnet_references>

  tags = {
    Name      = "${var.project_name}-${var.environment}-alb"
    HerokuApp = "<heroku_app>"
  }
}

resource "aws_lb_target_group" "<app_sanitized>_web" {
  name        = "${var.project_name}-${var.environment}-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = <vpc_id_reference>
  target_type = "ip"

  health_check {
    enabled             = true
    healthy_threshold   = 3
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    path                = "/"
    protocol            = "HTTP"
    matcher             = "200-399"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-tg"
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.<app_sanitized>_web.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  # {{IF has_route53_dns}}
  certificate_arn   = aws_acm_certificate_validation.app.certificate_arn
  # {{ELSE}}
  certificate_arn   = var.acm_certificate_arn
  # {{ENDIF}}

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.<app_sanitized>_web.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.<app_sanitized>_web.arn
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

# {{IF NOT has_route53_dns}}
variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate for HTTPS listener"
  type        = string
  # TODO: Provide your ACM certificate ARN
}
# {{ENDIF}}
```

**ALB rules:**

- `scheme` from `aws_config.scheme` in `aws-design.json` (default: "internet-facing")
- HTTP listener always redirects to HTTPS
- TLS 1.3 policy for new deployments
- Health check path defaults to `/` (user should customize)
- ACM certificate: when `dns.tf` is emitted (`has_route53_dns`), the listener uses the certificate `dns.tf` issues and validates; otherwise `var.acm_certificate_arn` with a TODO marker

---

## Step 6.5: Generate `beanstalk.tf` and EB deploy artifacts

Skip this step if no services in `aws-design.json` have `aws_service: "Elastic Beanstalk"`.

Read `preferences.design_constraints.eb_deploy_method.value`; default to `"github_actions"` when the field is absent. Always generate `beanstalk.tf` for EB services, then generate exactly one deploy path:

- `"github_actions"` → generate `$MIGRATION_DIR/.github/workflows/deploy-eb.yml`
- `"codepipeline"` → generate `$MIGRATION_DIR/terraform/pipeline.tf`
- `"manual"` → generate neither deploy automation artifact; document CLI deployment in `MIGRATION_GUIDE.md`

### `beanstalk.tf` — EB Application and Environments

```hcl
# Select the latest Elastic Beanstalk Docker platform for Amazon Linux 2023.
# The regex intentionally constrains the lookup to Docker on AL2023 while
# avoiding a hardcoded platform version that can go stale.
data "aws_elastic_beanstalk_solution_stack" "docker" {
  most_recent = true
  name_regex  = "^64bit Amazon Linux 2023 .* running Docker$"
}

resource "aws_elastic_beanstalk_application" "<app_name>" {
  name        = var.project_name
  description = "Migrated from Heroku app: <heroku_app>"
}

resource "aws_elastic_beanstalk_environment" "<app_name>_<process_type>" {
  name                = "${var.project_name}-<process_type>"
  application         = aws_elastic_beanstalk_application.<app_name>.name
  solution_stack_name = data.aws_elastic_beanstalk_solution_stack.docker.name
  tier                = "WebServer"

  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "InstanceType"
    value     = var.eb_instance_type_<app_name>_<process_type>
  }

  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "IamInstanceProfile"
    value     = aws_iam_instance_profile.eb_<app_name>.name
  }

  # MinSize cannot be 0: this option accepts 1–10000, so a quiesced environment is NOT
  # expressed here. Phase 6 drains the Auto Scaling group with the ASG API and must not
  # apply this resource while var.writers_quiesced is true — an apply restores MinSize
  # and starts writers again.
  setting {
    namespace = "aws:autoscaling:asg"
    name      = "MinSize"
    value     = var.eb_min_instances_<app_name>_<process_type>
  }

  setting {
    namespace = "aws:autoscaling:asg"
    name      = "MaxSize"
    value     = var.eb_max_instances_<app_name>_<process_type>
  }

  setting {
    namespace = "aws:elasticbeanstalk:environment"
    name      = "EnvironmentType"
    value     = "<LoadBalanced for web, SingleInstance for worker/clock/custom>"
  }

  # {{IF process_type == "web"}}
  setting {
    namespace = "aws:elasticbeanstalk:environment:process:default"
    name      = "HealthCheckPath"
    value     = var.eb_health_check_path_<app_sanitized>_web
  }
  # {{IF has_route53_dns}}
  # HTTPS on the EB load balancer, using the certificate dns.tf issues. Without this a
  # custom domain pointed at the environment serves plain HTTP only.
  setting {
    namespace = "aws:elasticbeanstalk:environment"
    name      = "LoadBalancerType"
    value     = "application"
  }
  setting {
    namespace = "aws:elbv2:listener:443"
    name      = "ListenerEnabled"
    value     = "true"
  }
  setting {
    namespace = "aws:elbv2:listener:443"
    name      = "Protocol"
    value     = "HTTPS"
  }
  setting {
    namespace = "aws:elbv2:listener:443"
    name      = "SSLCertificateArns"
    value     = aws_acm_certificate_validation.app.certificate_arn
  }
  setting {
    namespace = "aws:elbv2:listener:443"
    name      = "SSLPolicy"
    value     = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  }
  # {{ENDIF}}
  # {{ENDIF}}

  # {{IF process_type != "web"}}
  setting {
    namespace = "aws:elasticbeanstalk:healthreporting:system"
    name      = "SystemType"
    value     = "basic"
  }
  # {{ENDIF}}

  setting {
    namespace = "aws:ec2:vpc"
    name      = "VPCId"
    value     = <vpc_id from vpc_design>
  }

  setting {
    namespace = "aws:ec2:vpc"
    name      = "Subnets"
    value     = <comma-separated subnet IDs>
  }

  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "SecurityGroups"
    value     = aws_security_group.app.id
  }

  setting {
    namespace = "aws:elasticbeanstalk:command"
    name      = "DeploymentPolicy"
    value     = var.eb_deployment_policy
  }

  # {{IF process_type == "web"}}
  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name      = "PORT"
    value     = var.eb_application_port_<app_sanitized>_web
  }
  # {{ENDIF}}

  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name      = "PROCESS_TYPE"
    value     = "<process_type>"
  }

  # Emit one environmentsecrets setting per sensitive Heroku config var.
  setting {
    namespace = "aws:elasticbeanstalk:application:environmentsecrets"
    name      = "DATABASE_URL"
    value     = "<secret-or-parameter-arn>"
  }
}

resource "aws_iam_instance_profile" "eb_<app_name>" {
  name = "${var.project_name}-eb-profile"
  role = aws_iam_role.eb_instance_<app_name>.name
}

resource "aws_iam_role" "eb_instance_<app_name>" {
  name = "${var.project_name}-eb-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eb_web_tier_<app_name>" {
  role       = aws_iam_role.eb_instance_<app_name>.name
  policy_arn = "arn:aws:iam::aws:policy/AWSElasticBeanstalkWebTier"
}

resource "aws_iam_role_policy" "eb_read_secrets_<app_name>" {
  name = "${var.project_name}-eb-read-secrets"
  role = aws_iam_role.eb_instance_<app_name>.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "ssm:GetParameter",
        "ssm:GetParameters"
      ]
      Resource = [
        "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}/*",
        "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/*"
      ]
    }]
  })
}
```

**Per-environment rules:**

- Web process types: `environment_type = "LoadBalanced"`; EB auto-provisions the ALB.
- Worker/clock/custom process types: `environment_type = "SingleInstance"`; no ALB, no public endpoint, persistent Docker CMD process.
- Do NOT use EB Worker tier. Heroku workers are persistent processes, not SQS consumers.
- Do NOT generate persistent EB environments for `release` process types. Heroku release-phase commands are run-once deployment hooks and must be handled manually or by a deployment hook.
- Use `data.aws_elastic_beanstalk_solution_stack.docker.name`, not a hardcoded platform version.

### `.github/workflows/deploy-eb.yml` — GitHub Actions EB Deploy (Default)

Emit this file when `eb_deploy_method.value` is `"github_actions"` or absent. The workflow uses GitHub OIDC role assumption, packages the source bundle, creates one EB application version, and updates every generated EB environment for the app (web, worker, clock, custom).

```yaml
name: Deploy Elastic Beanstalk

on:
  push:
    branches: [main]

permissions:
  id-token: write
  contents: read

env:
  AWS_REGION: <target_region>
  EB_APPLICATION_NAME: <app_name>
  EB_ENVIRONMENTS: "<space-separated EB environment names from aws-design.json>"

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Package source bundle
        run: |
          zip -r app.zip . -x '.git/*' 'node_modules/*'

      - name: Create application version
        run: |
          VERSION_LABEL="${GITHUB_SHA}-${GITHUB_RUN_NUMBER}"
          BUCKET="$(aws elasticbeanstalk create-storage-location --query S3Bucket --output text)"
          aws s3 cp app.zip "s3://${BUCKET}/${EB_APPLICATION_NAME}/${VERSION_LABEL}.zip"
          aws elasticbeanstalk create-application-version \
            --application-name "${EB_APPLICATION_NAME}" \
            --version-label "${VERSION_LABEL}" \
            --source-bundle "S3Bucket=${BUCKET},S3Key=${EB_APPLICATION_NAME}/${VERSION_LABEL}.zip"
          for ENVIRONMENT in ${EB_ENVIRONMENTS}; do
            aws elasticbeanstalk update-environment \
              --environment-name "${ENVIRONMENT}" \
              --version-label "${VERSION_LABEL}"
          done
```

**GitHub Actions rules:**

- Emit one workflow per repository/migration, not one per EB environment.
- `EB_ENVIRONMENTS` MUST include every generated EB environment for the app, not only `<app_name>-web`.
- The workflow assumes a GitHub OIDC role through `secrets.AWS_ROLE_ARN`; document the required role setup in `MIGRATION_GUIDE.md`.
- Do not emit `pipeline.tf` when this method is selected.

### `pipeline.tf` — CodePipeline GitHub Source to EB Deploy (Optional)

Emit this file only when `eb_deploy_method.value` is `"codepipeline"`.

```hcl
resource "aws_codepipeline" "<app_name>_deploy" {
  name     = "${var.project_name}-deploy"
  role_arn = aws_iam_role.codepipeline_<app_name>.arn

  artifact_store {
    location = aws_s3_bucket.pipeline_artifacts_<app_name>.bucket
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source_output"]

      configuration = {
        ConnectionArn    = var.github_connection_arn
        FullRepositoryId = var.github_repo
        BranchName       = var.github_branch
      }
    }
  }

  stage {
    name = "Deploy"

    # Emit one action per generated EB environment for this app (web, worker, clock, custom).
    action {
      name            = "Deploy_<process_type>"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "ElasticBeanstalk"
      input_artifacts = ["source_output"]
      version         = "1"
      run_order       = 1

      configuration = {
        ApplicationName = aws_elastic_beanstalk_application.<app_name>.name
        EnvironmentName = aws_elastic_beanstalk_environment.<app_name>_<process_type>.name
      }
    }
  }
}

resource "aws_s3_bucket" "pipeline_artifacts_<app_name>" {
  bucket_prefix = "${var.project_name}-artifacts-"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "pipeline_artifacts_<app_name>" {
  bucket = aws_s3_bucket.pipeline_artifacts_<app_name>.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_iam_role" "codepipeline_<app_name>" {
  name = "${var.project_name}-codepipeline"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "codepipeline.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "codepipeline_policy_<app_name>" {
  name = "${var.project_name}-codepipeline-policy"
  role = aws_iam_role.codepipeline_<app_name>.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "codestar-connections:UseConnection",
          "codeconnections:UseConnection"
        ]
        Resource = var.github_connection_arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetBucketVersioning"
        ]
        Resource = [
          aws_s3_bucket.pipeline_artifacts_<app_name>.arn,
          "${aws_s3_bucket.pipeline_artifacts_<app_name>.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "elasticbeanstalk:CreateApplicationVersion",
          "elasticbeanstalk:DescribeApplications",
          "elasticbeanstalk:DescribeApplicationVersions",
          "elasticbeanstalk:DescribeEnvironments",
          "elasticbeanstalk:UpdateEnvironment"
        ]
        Resource = [
          "arn:aws:elasticbeanstalk:${var.aws_region}:${data.aws_caller_identity.current.account_id}:application/<app_name>",
          "arn:aws:elasticbeanstalk:${var.aws_region}:${data.aws_caller_identity.current.account_id}:applicationversion/<app_name>/*",
          "arn:aws:elasticbeanstalk:${var.aws_region}:${data.aws_caller_identity.current.account_id}:environment/<app_name>/*"
        ]
      },
      {
        # AWS does not support resource-level permissions for this action.
        Effect   = "Allow"
        Action   = "elasticbeanstalk:CreateStorageLocation"
        Resource = "*"
      }
    ]
  })
}
```

**CodePipeline rules:**

- CodePipeline is an explicit override, not the EB default.
- Emit one Deploy action per generated EB environment for the app; do not update only the web environment.
- The CodeStar/CodeConnections GitHub connection still requires one-time authorization in the AWS console.

---

## Step 7: Generate `database.tf`

For each service in `aws-design.json` where `aws_service` is "RDS PostgreSQL" or "Aurora PostgreSQL":

### DB Subnet Group (always needed for database services)

```hcl
resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-${var.environment}-db-subnet"
  subnet_ids = <private_subnet_references>

  tags = {
    Name = "${var.project_name}-${var.environment}-db-subnet"
  }
}
```

### RDS PostgreSQL (when `aws_service == "RDS PostgreSQL"`)

```hcl
# RDS PostgreSQL — <heroku_app>
# Heroku source: heroku-postgresql:<plan>
resource "aws_db_instance" "<app_sanitized>_postgres" {
  identifier     = "${var.project_name}-${var.environment}-postgres"
  engine         = "postgres"
  engine_version = "<aws_config.engine_version>"
  instance_class = "<aws_config.instance_class>"

  allocated_storage     = <aws_config.storage_gb>
  max_allocated_storage = <aws_config.storage_gb * 2>
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  multi_az               = <aws_config.multi_az>
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]

  # {{IF migration_approach == "interim_cutover_data_first"}}
  # INTERIM ONLY — defaults to false (private). Only Paths B and C in
  # MIGRATION_GUIDE.md "Interim Database Exposure" Step 2 need this true, and
  # they also require the DB subnet group to sit in internet-gateway-routed
  # subnets. Path A (Private Space VPC peering) keeps this false.
  publicly_accessible = var.interim_db_public_access
  # {{ENDIF}}

  backup_retention_period = 7
  backup_window           = "<preferences.json.global.maintenance_window formatted>"
  maintenance_window      = "<preferences.json.global.maintenance_window formatted>"

  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project_name}-${var.environment}-postgres-final"

  parameter_group_name = aws_db_parameter_group.<app_sanitized>_postgres.name

  tags = {
    Name      = "${var.project_name}-${var.environment}-postgres"
    HerokuApp = "<heroku_app>"
  }
}

resource "aws_db_parameter_group" "<app_sanitized>_postgres" {
  name   = "${var.project_name}-${var.environment}-postgres-params"
  family = "postgres<major_version>"

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  # {{IF migration_approach == "interim_cutover_data_first"}}
  # Prerequisite for interim Heroku access: reject any non-TLS connection.
  # Static parameter — takes effect on the next instance reboot.
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }
  # {{ENDIF}}

  tags = {
    Name = "${var.project_name}-${var.environment}-postgres-params"
  }
}

variable "db_name" {
  description = "PostgreSQL database name"
  type        = string
  default     = "app"
}

variable "db_username" {
  description = "PostgreSQL master username"
  type        = string
  sensitive   = true
}

variable "db_password" {
  description = "PostgreSQL master password"
  type        = string
  sensitive   = true
}

# {{IF migration_approach == "interim_cutover_data_first"}}
variable "interim_db_public_access" {
  description = "INTERIM ONLY: expose the database on a public endpoint while the app still runs on Heroku. Leave false unless MIGRATION_GUIDE.md 'Interim Database Exposure' Step 2 Path B or C applies. Reset to false after the Phase 6 rollback window (MIGRATION_GUIDE.md 'Interim Database Exposure' Step 4), never at cutover."
  type        = bool
  default     = false
}
# {{ENDIF}}
```

### Aurora PostgreSQL (when `aws_service == "Aurora PostgreSQL"`)

```hcl
# Aurora PostgreSQL — <heroku_app>
# Heroku source: heroku-postgresql:<plan> (multi-az-ha/multi-region availability)
resource "aws_rds_cluster" "<app_sanitized>_aurora" {
  cluster_identifier = "${var.project_name}-${var.environment}-aurora"
  engine             = "aurora-postgresql"
  engine_version     = "<aws_config.engine_version>"

  database_name   = var.db_name
  master_username = var.db_username
  master_password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]

  backup_retention_period = 7
  preferred_backup_window = "<preferences.json.global.maintenance_window formatted>"
  storage_encrypted       = true

  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project_name}-${var.environment}-aurora-final"

  # {{IF migration_approach == "interim_cutover_data_first"}}
  # Prerequisite for interim Heroku access: reject any non-TLS connection.
  # On Aurora, rds.force_ssl is a CLUSTER-level parameter, so it needs its own
  # aws_rds_cluster_parameter_group — attaching the instance-level
  # aws_db_parameter_group used by the RDS branch does not work here.
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.<app_sanitized>_aurora.name
  # {{ENDIF}}

  tags = {
    Name      = "${var.project_name}-${var.environment}-aurora"
    HerokuApp = "<heroku_app>"
  }
}

# {{IF migration_approach == "interim_cutover_data_first"}}
# INTERIM ONLY — enforces TLS on the cluster for the duration of the interim
# window. Aurora PostgreSQL 16 and older default rds.force_ssl to 0 (OFF), unlike
# RDS for PostgreSQL 15+ which defaults to 1, so on this branch the parameter must
# be set explicitly or the database accepts plaintext connections.
# In a cluster parameter group this parameter is DYNAMIC: no apply_method and no
# reboot are required, which is why this block has neither.
resource "aws_rds_cluster_parameter_group" "<app_sanitized>_aurora" {
  name   = "${var.project_name}-${var.environment}-aurora-cluster-params"
  family = "aurora-postgresql<major_version>"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-aurora-cluster-params"
  }
}
# {{ENDIF}}

resource "aws_rds_cluster_instance" "<app_sanitized>_aurora" {
  count              = 2
  identifier         = "${var.project_name}-${var.environment}-aurora-${count.index + 1}"
  cluster_identifier = aws_rds_cluster.<app_sanitized>_aurora.id
  instance_class     = "<aws_config.instance_class>"
  engine             = aws_rds_cluster.<app_sanitized>_aurora.engine
  engine_version     = aws_rds_cluster.<app_sanitized>_aurora.engine_version

  # {{IF migration_approach == "interim_cutover_data_first"}}
  # INTERIM ONLY — defaults to false (private). On Aurora, public access is an
  # INSTANCE-level attribute, so it belongs here rather than on aws_rds_cluster.
  # Only Paths B and C in MIGRATION_GUIDE.md "Interim Database Exposure" Step 2
  # need this true, and they also require the DB subnet group to sit in
  # internet-gateway-routed subnets. Path A (Private Space VPC peering) keeps it
  # false.
  publicly_accessible = var.interim_db_public_access
  # {{ENDIF}}

  tags = {
    Name = "${var.project_name}-${var.environment}-aurora-${count.index + 1}"
  }
}
```

### RDS Proxy (when `aws_config.rds_proxy == true`)

```hcl
# RDS Proxy — Connection pooling replacement for Heroku connection pooling
resource "aws_db_proxy" "<app_sanitized>_postgres" {
  name                   = "${var.project_name}-${var.environment}-proxy"
  debug_logging          = false
  engine_family          = "POSTGRESQL"
  idle_client_timeout    = 1800
  require_tls            = true
  role_arn               = aws_iam_role.rds_proxy.arn
  vpc_security_group_ids = [aws_security_group.database.id]
  vpc_subnet_ids         = <private_subnet_references>

  auth {
    auth_scheme = "SECRETS"
    iam_auth    = "DISABLED"
    secret_arn  = aws_secretsmanager_secret.db_credentials.arn
  }

  tags = {
    Name      = "${var.project_name}-${var.environment}-proxy"
    HerokuApp = "<heroku_app>"
  }
}

resource "aws_db_proxy_default_target_group" "<app_sanitized>_postgres" {
  db_proxy_name = aws_db_proxy.<app_sanitized>_postgres.name

  connection_pool_config {
    max_connections_percent = 100
  }
}

resource "aws_db_proxy_target" "<app_sanitized>_postgres" {
  db_proxy_name          = aws_db_proxy.<app_sanitized>_postgres.name
  target_group_name      = aws_db_proxy_default_target_group.<app_sanitized>_postgres.name
  db_instance_identifier = aws_db_instance.<app_sanitized>_postgres.identifier
}

# Secrets Manager for RDS Proxy authentication
resource "aws_secretsmanager_secret" "db_credentials" {
  name = "${var.project_name}-${var.environment}/db-credentials"

  tags = {
    Name = "${var.project_name}-${var.environment}-db-credentials"
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = var.db_username
    password = var.db_password
  })
}

# IAM Role for RDS Proxy
resource "aws_iam_role" "rds_proxy" {
  name = "${var.project_name}-${var.environment}-rds-proxy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "rds.amazonaws.com"
      }
    }]
  })

  tags = {
    Name = "${var.project_name}-${var.environment}-rds-proxy-role"
  }
}

resource "aws_iam_role_policy" "rds_proxy_secrets" {
  name = "secrets-access"
  role = aws_iam_role.rds_proxy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ]
      Resource = [aws_secretsmanager_secret.db_credentials.arn]
    }]
  })
}
```

**Database rules:**

- Storage encrypted by default (`storage_encrypted = true`)
- Final snapshot enabled (`skip_final_snapshot = false`)
- `max_allocated_storage` set to 2× initial for auto-scaling headroom
- Aurora always has 2 instances (writer + reader) for HA
- RDS Proxy emitted ONLY when `aws_config.rds_proxy == true` (connection pooling was enabled on source)
- Credentials stored in Secrets Manager (not inline)

---

## Step 8: Generate `cache.tf`

For each service in `aws-design.json` where `aws_service` is "ElastiCache Redis":

```hcl
# ElastiCache Redis — <heroku_app>
# Heroku source: heroku-redis:<plan>

resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project_name}-${var.environment}-cache-subnet"
  subnet_ids = <private_subnet_references>

  tags = {
    Name = "${var.project_name}-${var.environment}-cache-subnet"
  }
}

resource "aws_elasticache_replication_group" "<app_sanitized>_redis" {
  replication_group_id = "${var.project_name}-${var.environment}-redis"
  description          = "Redis cluster for ${var.project_name} (migrated from Heroku Redis)"

  engine               = "redis"
  engine_version       = "<aws_config.engine_version>"
  node_type            = "<aws_config.node_type>"
  num_cache_clusters   = <2 if multi_az else 1>
  port                 = 6379

  # High Availability
  automatic_failover_enabled = <aws_config.automatic_failover>
  multi_az_enabled           = <aws_config.multi_az>

  # Encryption
  at_rest_encryption_enabled = true
  transit_encryption_enabled = <aws_config.transit_encryption>

  # Network
  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.cache.id]

  # Maintenance
  maintenance_window       = "<preferences.json.global.maintenance_window formatted>"
  snapshot_retention_limit = 7
  snapshot_window          = "03:00-05:00"

  # Parameter group
  parameter_group_name = aws_elasticache_parameter_group.<app_sanitized>_redis.name

  tags = {
    Name      = "${var.project_name}-${var.environment}-redis"
    HerokuApp = "<heroku_app>"
  }
}

resource "aws_elasticache_parameter_group" "<app_sanitized>_redis" {
  name   = "${var.project_name}-${var.environment}-redis-params"
  family = "redis<major_version>"

  parameter {
    name  = "maxmemory-policy"
    value = "volatile-lru"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-redis-params"
  }
}
```

**ElastiCache rules:**

- `automatic_failover_enabled` and `multi_az_enabled`: Set to `true` if and only if source Heroku Redis has HA enabled (`aws_config.automatic_failover == true`)
- `transit_encryption_enabled`: Set to `true` if and only if source has encryption-in-transit (`aws_config.transit_encryption == true`)
- `at_rest_encryption_enabled`: Always `true` (security best practice)
- `num_cache_clusters`: 2 when Multi-AZ enabled, 1 when single-AZ
- `engine_version`: Matches source Redis version from `aws_config.engine_version`
- `node_type`: From `aws_config.node_type` (mapped from Redis Plan Table)

---

## Step 9: Generate `messaging.tf`

For each service in `aws-design.json` where `aws_service` is "Amazon MSK":

```hcl
# Amazon MSK — <heroku_app>
# Heroku source: heroku-kafka:<plan>

resource "aws_msk_configuration" "<app_sanitized>_kafka" {
  name              = "${var.project_name}-${var.environment}-msk-config"
  kafka_versions    = ["<aws_config.kafka_version || 3.5.1>"]
  server_properties = <<PROPERTIES
auto.create.topics.enable=false
default.replication.factor=<aws_config.replication_factor || 3>
num.partitions=<aws_config.default_partitions || 3>
min.insync.replicas=2
log.retention.hours=<preferences.json.data.kafka_retention_days * 24>
PROPERTIES

  tags = {
    Name = "${var.project_name}-${var.environment}-msk-config"
  }
}

resource "aws_msk_cluster" "<app_sanitized>_kafka" {
  cluster_name           = "${var.project_name}-${var.environment}-msk"
  kafka_version          = "<aws_config.kafka_version || 3.5.1>"
  number_of_broker_nodes = <aws_config.broker_count || 2>

  broker_node_group_info {
    instance_type   = "<aws_config.broker_instance_type>"
    client_subnets  = <private_subnet_references — one per AZ, matching broker count>
    security_groups = [aws_security_group.messaging.id]

    storage_info {
      ebs_storage_info {
        volume_size = <aws_config.storage_gb>
      }
    }
  }

  encryption_info {
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }

  configuration_info {
    arn      = aws_msk_configuration.<app_sanitized>_kafka.arn
    revision = aws_msk_configuration.<app_sanitized>_kafka.latest_revision
  }

  logging_info {
    broker_logs {
      cloudwatch_logs {
        enabled   = true
        log_group = aws_cloudwatch_log_group.msk.name
      }
    }
  }

  tags = {
    Name      = "${var.project_name}-${var.environment}-msk"
    HerokuApp = "<heroku_app>"
  }
}

resource "aws_cloudwatch_log_group" "msk" {
  name              = "/msk/${var.project_name}-${var.environment}"
  retention_in_days = <preferences.json.operational.log_retention_days || 30>

  tags = {
    Name = "${var.project_name}-${var.environment}-msk-logs"
  }
}
```

**MSK rules:**

- `number_of_broker_nodes`: Minimum 2, always spread across ≥ 2 AZs (per Requirement 7.4)
- `broker_instance_type`: From `aws_config.broker_instance_type` (mapped from Kafka Plan Table)
- `volume_size`: From `aws_config.storage_gb` (meets or exceeds source plan storage)
- Encryption in-transit and in-cluster always enabled for MSK
- `client_subnets` must match the number of broker nodes and span multiple AZs
- Kafka retention set from `preferences.json.data.kafka_retention_days`
- `replication_factor` and partition counts preserved from source plan topology

---

## Step 9.5: Generate `dns.tf` (Route 53 cutover — only when `dns_strategy == "route53"`)

**Emit when** `preferences.data.dns_strategy == "route53"` (the field Clarify Q10 writes — `clarify-assemble.md` `"data"` block; `global.dns_strategy` does not exist) AND `generate-docs.md` Step 0 `eligible_hostnames[]` is non-empty — that is, at least one inventory `resource_type: "domain"` hostname belongs to a Heroku app whose **web** formation landed on Elastic Beanstalk or Fargate. Set `has_route53_dns = true` for the rest of this file; it switches the ALB listener (Step 6) and EB web environments (Step 6.5) onto the certificate issued here. Otherwise skip this step, leave `has_route53_dns = false`, and let `generate-docs.md` § Phase 5 give manual-record instructions.

**A previous `dns.tf` is not left in place.** A same-directory rerun that leaves Route 53 (external DNS, or an EKS design) keeps the last execution pack. Skipping emission does not remove `terraform/dns.tf`, and `generate.md` requires that file to be absent. Before the read-only gate:

1. If `terraform/dns.tf` does not exist, continue.
2. If it exists, stop. Do not delete it. Show the user the file and ask whether they edited it after the previous generation.
3. When they edited it, they reconcile those edits into the manual DNS path in the guide, then remove `terraform/dns.tf` themselves. The generator does not delete an edited file.
4. When they confirm it is the unmodified previous generation and this run should not own DNS, they remove `terraform/dns.tf`. The generator still does not delete it.
5. Run the gate only after the file is absent. The absence check stays; a leftover file is still `GATE_FAIL`.

**Never for an EKS design.** `design-eks.md` "All-or-Nothing Rule" puts every formation on EKS, so an EKS design has no EB or Fargate web service, `eligible_hostnames[]` is empty, and this step does not run — there is no Beanstalk fallback to fall into. The EKS web Service's endpoint exists only after the Phase 3 `kubectl apply`, so its DNS/TLS handoff is the manual branch of the guide (`generate-docs.md` § Phase 5 "DNS Cutover (your current DNS provider)" with `has_eks`). Do not emit `dns.tf`, and never reference an `aws_elastic_beanstalk_environment` or `aws_lb` that no other step declared.

**What this file buys the user.** Cutover and rollback become one variable: `cutover_weight` 0 → 10 → 50 → 100 shifts traffic from Heroku to AWS one `terraform apply` at a time, and editing it back to 0 is the rollback — no hand-edited records, no "which TTL did we set" at 2 a.m. The value lives in `terraform.tfvars` and nowhere else: every cutover and rollback step edits that line and runs `terraform apply -input=false`, never a `-var` override, because Terraform re-reads `terraform.tfvars` on every apply and the next ordinary apply would silently put the traffic back where the file says. The one exception is a Phase 6 database failback while `writers_quiesced` is true and the design includes Elastic Beanstalk. `aws_route53_record.aws` reads `aws_elastic_beanstalk_environment.*.cname` through `local.aws_targets`, so `terraform apply -target` on those records still plans the environment. The guide changes the weights with `aws route53 change-resource-record-sets` and does not apply a saved plan that changes `aws_elastic_beanstalk_environment`. The weight still lives in `terraform.tfvars`; the exception is that Route 53 API call, not `-var` and not `-target`. The ACM certificate is issued and validated in the same apply, so HTTPS works the moment the first weighted record resolves to AWS.

**Inputs.** `local.custom_domains` = every hostname in `generate-docs.md` Step 0 `eligible_hostnames[]` (deduplicated; `*.herokuapp.com` hostnames were never recorded). Each hostname keeps the associations the inventory and design already carry: the domain resource's `heroku_app` (`domain:{app_name}:{hostname}`) selects that app's **web** formation in `aws-design.json` — `alb:{app}:web` → `aws_lb.<app_sanitized>_web` (Step 6), `eb:{app}:web` → `aws_elastic_beanstalk_environment.<app_sanitized>_web` (Step 6.5) — and the generator writes that pairing out as a literal `local.aws_targets` entry. There is **no shared scalar target**: a production/staging pair or a mixed EB/Fargate inventory routes each hostname to its own app's endpoint. Hostnames whose app has no EB/Fargate web formation (`target_kind` `eks` or `none`) are left out of `dns.tf` and appended to `generation-warnings.json` (Step 10 schema; `service_id: "domain:<app>:<hostname>"`, `aws_service: "Route 53"`, reason `"no Elastic Beanstalk or Fargate web service for heroku_app <app>"`, recommendation `"create this record manually — MIGRATION_GUIDE.md Phase 5 manual DNS branch"`). Zones are per hostname too: `hosted_zone_ids` maps every hostname to the zone that is authoritative for it, so `admin.example.org` and `www.example.com` can live in different hosted zones. Heroku's DNS targets are **not** in the inventory today (`heroku domains` prints them as "DNS Target"; discovery records only `hostname` and `sni_endpoint`), so they are a required variable with a placeholder guard; the apex additionally needs the A records Heroku's target currently resolves to (`heroku_apex_ips`, see the apex comment in the file).

```hcl
# dns.tf — Route 53 records, ACM certificate, weighted Heroku→AWS cutover.
# cutover_weight = 0 sends everything to Heroku; 100 sends everything to AWS; rollback = 0.
# Set it in terraform.tfvars only (never `-var`): the next plain apply re-reads the file.
#
# PRECONDITION (MIGRATION_GUIDE.md Phase 1 § "DNS preparation (Route 53)"): every zone in
# hosted_zone_ids is AUTHORITATIVE for its hostnames before the first apply, and any existing
# simple record for a hostname below has been converted to the weighted "heroku" member and
# imported. The ACM validation here blocks the Phase 1 apply until the validation records
# resolve from the public internet, which only happens if Route 53 answers for the zone; and
# Route 53 refuses to create a weighted record next to a simple record of the same name/type.

variable "hosted_zone_ids" {
  description = "hostname → id of the Route 53 hosted zone that is AUTHORITATIVE for it (`aws route53 list-hosted-zones-by-name --dns-name <zone>`). One entry per custom domain; hostnames under different zones get different ids."
  type        = map(string)
  validation {
    condition     = alltrue([for h, z in var.hosted_zone_ids : can(regex("^Z[A-Z0-9]{8,32}$", z))])
    error_message = "Every hosted_zone_ids value must be a Route 53 zone id (starts with Z). Replace the placeholders in terraform.tfvars."
  }
}

variable "heroku_dns_targets" {
  description = "hostname → Heroku DNS target (the 'DNS Target' column of `heroku domains -a <app>`): <haiku>.herokudns.com on the Common Runtime and Fir, <haiku>.<haiku>.herokuspace.com in a Cedar Private Space. One entry per non-apex custom domain (the apex uses heroku_apex_ips)."
  type        = map(string)
  validation {
    condition     = alltrue([for h, t in var.heroku_dns_targets : can(regex("\\.herokudns\\.com$|\\.herokuapp\\.com$|\\.herokussl\\.com$|\\.herokuspace\\.com$", t))])
    error_message = "Every heroku_dns_targets value must be a Heroku DNS target: …herokudns.com, …herokuapp.com, …herokussl.com, or <haiku>.<haiku>.herokuspace.com for a Cedar Private Space. Copy them from `heroku domains`."
  }
}

variable "heroku_apex_ips" {
  description = "apex hostname → IPv4 addresses its Heroku DNS target resolves to right now (`dig +short A <heroku DNS target>`). Required for every hostname that equals its zone name; leave {} when there is no apex. Heroku publishes no stable inbound IPs — re-resolve before every weight change and before any rollback (MIGRATION_GUIDE.md Phase 1 § DNS preparation)."
  type        = map(list(string))
  default     = {}
  validation {
    condition = alltrue([
      for h, ips in var.heroku_apex_ips :
      length(ips) > 0 && alltrue([for ip in ips : can(regex("^((25[0-5]|2[0-4][0-9]|1?[0-9]?[0-9])\\.){3}(25[0-5]|2[0-4][0-9]|1?[0-9]?[0-9])$", ip))])
    ])
    error_message = "Every heroku_apex_ips entry must be a non-empty list of IPv4 addresses. Resolve them with `dig +short A <heroku DNS target>`."
  }
}

variable "cutover_weight" {
  description = "Share of traffic (0-100) Route 53 sends to AWS. 0 = all Heroku (safe default), 100 = all AWS. Set it in terraform.tfvars (never -var) and lower it there to roll back, so the next apply cannot silently revert it."
  type        = number
  default     = 0
  validation {
    condition     = var.cutover_weight >= 0 && var.cutover_weight <= 100 && floor(var.cutover_weight) == var.cutover_weight
    error_message = "cutover_weight must be a whole number from 0 to 100."
  }
}

locals {
  custom_domains = toset([<comma-separated quoted hostnames from eligible_hostnames[]>])

  # A hostname is an apex when it IS its own zone's name. Route 53 cannot CNAME an apex, so the
  # apex is a weighted A pair (apex_heroku / apex_aws below) instead of a weighted CNAME pair.
  is_apex = { for h in local.custom_domains : h => (h == trimsuffix(data.aws_route53_zone.by_host[h].name, ".")) }

  # GENERATOR-EMITTED LITERAL — one entry per hostname, resolved from the domain resource's
  # heroku_app and that app's web formation in aws-design.json. Never a shared value: two apps
  # must never be sent to the same endpoint, and a worker-only app has no entry here at all.
  aws_targets = {
    # {{FOR host IN eligible_hostnames}}
    # {{IF host.target_kind == "alb"}}
    "<host.hostname>" = {
      heroku_app = "<host.heroku_app>"
      name       = aws_lb.<host.app_sanitized>_web.dns_name
      zone_id    = aws_lb.<host.app_sanitized>_web.zone_id
    }
    # {{ELSE}} (host.target_kind == "eb")
    "<host.hostname>" = {
      heroku_app = "<host.heroku_app>"
      name       = aws_elastic_beanstalk_environment.<host.app_sanitized>_web.cname
      zone_id    = data.aws_elastic_beanstalk_hosted_zone.current.id
    }
    # {{ENDIF}}
    # {{ENDFOR}}
  }
}

# One lookup per hostname: the plan fails early if a zone id is wrong, and each hostname's apex
# test uses its own zone's name.
data "aws_route53_zone" "by_host" {
  for_each = local.custom_domains
  zone_id  = var.hosted_zone_ids[each.key]
}

# {{IF any eligible_hostnames[] entry has target_kind == "eb"}}
data "aws_elastic_beanstalk_hosted_zone" "current" {}
# {{ENDIF}}

# --- Certificate: issued for every custom domain, validated via Route 53 in the same apply.
# Each validation CNAME goes to the zone that is authoritative for that hostname.
resource "aws_acm_certificate" "app" {
  domain_name               = sort(tolist(local.custom_domains))[0]
  subject_alternative_names = slice(sort(tolist(local.custom_domains)), 1, length(local.custom_domains))
  validation_method         = "DNS"
  lifecycle {
    create_before_destroy = true
  }
  tags = { Name = "${var.project_name}-${var.environment}-cert" }
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.app.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }
  zone_id         = var.hosted_zone_ids[each.key]
  name            = each.value.name
  type            = each.value.type
  ttl             = 60
  records         = [each.value.record]
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "app" {
  certificate_arn         = aws_acm_certificate.app.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# --- Non-apex hostnames: weighted CNAME pair. Both records share name+type; Route 53 splits
# traffic by weight. A weight of 0 is never returned while the other is > 0, so
# cutover_weight = 0 is "all Heroku" and 100 is "all AWS" with no record churn in between.
# If the zone already held a simple CNAME for the hostname, the guide converts it in place to
# this "heroku" member and imports it (import id: <ZONE_ID>_<hostname>_CNAME_heroku) before the
# first apply — Route 53 will not create a weighted record beside a simple one.
resource "aws_route53_record" "heroku" {
  for_each = { for h in local.custom_domains : h => h if !local.is_apex[h] }
  zone_id        = var.hosted_zone_ids[each.key]
  name           = each.key
  type           = "CNAME"
  ttl            = 60
  records        = [var.heroku_dns_targets[each.key]]
  set_identifier = "heroku"
  weighted_routing_policy {
    weight = 100 - var.cutover_weight
  }
}

resource "aws_route53_record" "aws" {
  for_each = { for h in local.custom_domains : h => h if !local.is_apex[h] }
  zone_id        = var.hosted_zone_ids[each.key]
  name           = each.key
  type           = "CNAME"
  ttl            = 60
  records        = [local.aws_targets[each.key].name]
  set_identifier = "aws"
  weighted_routing_policy {
    weight = var.cutover_weight
  }
}

# --- Apex hostname: Route 53 cannot CNAME or ALIAS an apex to an external host, so the only
# authoritative apex answer that points at Heroku is an A record with the addresses Heroku's
# DNS target resolves to today. Both members are weighted, so the apex moves with the same
# cutover_weight as every other hostname, there is an authoritative apex answer at every weight,
# and rollback is a weight change — never a delete plus an edit at a provider that no longer
# serves the zone. Pinned IPs are a bounded stopgap (Heroku publishes no stable inbound IPs):
# the guide re-resolves them before each weight change and keeps the window short.
resource "aws_route53_record" "apex_heroku" {
  for_each = { for h in local.custom_domains : h => h if local.is_apex[h] }
  zone_id        = var.hosted_zone_ids[each.key]
  name           = each.key
  type           = "A"
  ttl            = 60
  records        = var.heroku_apex_ips[each.key]
  set_identifier = "heroku"
  weighted_routing_policy {
    weight = 100 - var.cutover_weight
  }
  lifecycle {
    precondition {
      condition     = contains(keys(var.heroku_apex_ips), each.key)
      error_message = "${each.key} is the zone apex: add heroku_apex_ips[\"${each.key}\"] = [<dig +short A <its Heroku DNS target>>] to terraform.tfvars."
    }
  }
}

resource "aws_route53_record" "apex_aws" {
  for_each = { for h in local.custom_domains : h => h if local.is_apex[h] }
  zone_id        = var.hosted_zone_ids[each.key]
  name           = each.key
  type           = "A"
  set_identifier = "aws"
  alias {
    name                   = local.aws_targets[each.key].name
    zone_id                = local.aws_targets[each.key].zone_id
    evaluate_target_health = true
  }
  weighted_routing_policy {
    weight = var.cutover_weight
  }
}
```

**Rules:**

- `for_each` keys are hostnames, so `terraform state` and `plan` output read in the user's own vocabulary ("www.example.com"), not indices.
- `local.aws_targets` is emitted per hostname from `eligible_hostnames[]` and references only resources this run declares (`aws_lb.<app_sanitized>_web` from Step 6, `aws_elastic_beanstalk_environment.<app_sanitized>_web` from Step 6.5). Never collapse it to one value, and never reference a Beanstalk environment for an app that has none.
- `hosted_zone_ids` and `heroku_dns_targets` must cover every hostname in `local.custom_domains` (`heroku_dns_targets` every non-apex one); a missing key fails `plan` with a clear message rather than silently routing 100 % to AWS. `heroku_apex_ips` must cover every apex; the `apex_heroku` precondition names the missing hostname.
- Route 53 must be **authoritative** for every zone in `hosted_zone_ids` before the Phase 1 apply (guide Phase 1 § "DNS preparation (Route 53)"): `aws_acm_certificate_validation` waits for the validation CNAMEs to resolve publicly, which never happens while another provider answers for the zone.
- Existing simple records for a hostname are **converted and imported**, never overwritten: the guide turns a simple CNAME into the weighted `heroku` member in one `change-resource-record-sets` ChangeBatch and the user runs `terraform import 'aws_route53_record.heroku["<host>"]' <ZONE_ID>_<host>_CNAME_heroku` (apex: `aws_route53_record.apex_heroku["<host>"]`, id `<ZONE_ID>_<host>_A_heroku`). `allow_overwrite = true` stays limited to the ACM validation records.
- The apex is never deleted by a weight change: `apex_heroku` + `apex_aws` exist at every `cutover_weight`, so rollback keeps an authoritative apex answer.
- TTL 60 on every record this file creates. The guide tells the user to lower the TTL at their current provider to 60 **before** moving the zone so the first weighted step propagates in minutes.
- Never emit `aws_route53_zone` as a resource: the user may already serve other records from the zone, and importing it is theirs to decide. The data source makes the zone a precondition the plan checks.
- `allow_overwrite = true` only on the ACM validation records — re-issuing a certificate must not fail on a stale `_acme-challenge`-style record.
- When `has_route53_dns` is true, remove `var.acm_certificate_arn` from `variables.tf` and from `terraform.tfvars.example` (Step 11); the listener and EB settings reference `aws_acm_certificate_validation.app.certificate_arn` instead.

## Step 10: Handle Unmapped Resources and Warnings

**Always write `$MIGRATION_DIR/generation-warnings.json`** — it is a mandatory
artifact of this phase (part of generate's `_produces` floor), a manifest that
records whatever could NOT be generated. Write it even when nothing was skipped:
in that case the `warnings` array is EMPTY (`"warnings": []`). A consumer can then
rely on the file always existing rather than testing for its absence.

For any `service_id` in `aws-design.json` whose `aws_service` does not have a
Terraform resource mapping defined in Steps 4–9 above:

1. **Skip** the resource — do NOT generate Terraform for it
2. **Append** the skip as an entry in `generation-warnings.json`'s `warnings` array

If every service mapped successfully, still write the file with an empty
`warnings` array.

### `generation-warnings.json` Schema

```json
{
  "generated_at": "<ISO 8601 timestamp>",
  "migration_id": "<migration_id>",
  "warnings": [
    {
      "service_id": "<service_id from aws-design.json>",
      "aws_service": "<aws_service value>",
      "heroku_app": "<heroku_app>",
      "source_resource_id": "<source_resource_id>",
      "reason": "No Terraform resource mapping available for <aws_service>",
      "recommendation": "Configure this service manually in the AWS Console or add a custom Terraform module"
    }
  ],
  "total_warnings": <count>,
  "total_services_generated": <count of successfully generated services>,
  "total_services_skipped": <count of skipped services>
}
```

**Warning scenarios that produce entries:**

- CloudWatch Logs mapped from Papertrail (no standalone Terraform needed — integrated into `compute.tf` log configuration)
- CloudWatch + X-Ray composite mappings (Scout APM, New Relic)
- Amazon SES (SendGrid mapping)
- Amazon SNS (Twilio mapping)
- Amazon EventBridge Scheduler (Heroku Scheduler mapping)
- ElastiCache Memcached (Memcachier mapping)
- Amazon MQ (CloudAMQP mapping)
- Amazon OpenSearch (Bonsai Elasticsearch mapping)
- S3 + CloudFront composite (Cloudinary mapping)

**Exception:** If `aws_service == "CloudWatch Logs"` and it maps from a logging add-on (Papertrail, Rollbar, Sentry), the log group is already emitted in `compute.tf` Step 6. Do NOT log a warning for this case.

---

## Step 11: Generate `.gitignore` and `terraform.tfvars.example`

### `$MIGRATION_DIR/terraform/.gitignore`

```
# Terraform state and providers
.terraform/
*.tfstate
*.tfstate.backup
.terraform.lock.hcl

# Variable values (may contain secrets)
terraform.tfvars
*.auto.tfvars
!terraform.tfvars.example

# Crash logs
crash.log
crash.*.log

# Plan files
*.tfplan
```

### `$MIGRATION_DIR/terraform/terraform.tfvars.example`

```hcl
# Copy this file to terraform.tfvars and fill in values before running terraform plan.
# Do NOT commit terraform.tfvars to source control — it may contain sensitive values.

aws_region   = "<target_region>"
project_name = "<project_name>"
environment  = "<environment>"
migration_id = "<migration_id>"

# Security baseline contacts (always required — plan fails until all three are real inboxes)
operations_email = "TODO-ops@example.com"      # AWS account operations alternate contact
billing_email    = "TODO-billing@example.com"  # billing alternate contact + budget alert recipient
security_email   = "TODO-security@example.com" # security alternate contact

# false until Phase 6. true keeps Fargate desired_count at 0 across later applies.
# Always present, including when dns.tf is not generated: the failback edit
# `sed`s this line, and a missing line leaves the variable at its default false.
# Leave it true until the next intentional handoff. Elastic Beanstalk still cannot store
# 0 instances; while this is true, do not apply aws_elastic_beanstalk_environment.
writers_quiesced = false

# Database credentials (required if RDS/Aurora is in the design)
# db_username = "app_user"
# db_password = "CHANGE_ME"

# {{IF has_route53_dns}}
# DNS (dns.tf) — required. One entry PER HOSTNAME in each map (hostnames may live in different
# zones and belong to different Heroku apps). Zone ids: `aws route53 list-hosted-zones-by-name
# --dns-name <zone>` — the zone must already be authoritative (MIGRATION_GUIDE.md Phase 1 § DNS
# preparation). Heroku DNS targets: `heroku domains -a <app>` ("DNS Target" column). Apex IPs:
# `dig +short A <heroku DNS target>`, re-resolved before every weight change.
# hosted_zone_ids = {
#   "www.example.com"   = "Z0123456789ABCDEFGHIJ"
#   "example.com"       = "Z0123456789ABCDEFGHIJ"
#   "admin.example.org" = "Z0987654321JIHGFEDCBA"
# }
# heroku_dns_targets = {
#   "www.example.com"   = "whispering-willow-1234.herokudns.com"
#   "admin.example.org" = "quiet-meadow-5678.herokudns.com"
# }
# heroku_apex_ips = {                       # only for hostnames that equal their zone name
#   "example.com" = ["203.0.113.10", "203.0.113.11"]
# }
# cutover_weight is deliberately NOT commented out: this line is the single source of truth for
# where traffic goes. MIGRATION_GUIDE.md Phase 5 raises it 10 → 50 → 100 by editing it here and
# running a plain `terraform apply`; Phase 6 rollback sets it back to 0 the same way. Never pass
# it as `-var` — the next apply re-reads this file and would silently undo the override.
cutover_weight = 0
# {{ELSE}}
# ACM certificate (required if ALB is in the design)
# acm_certificate_arn = "arn:aws:acm:<region>:<account_id>:certificate/<cert-id>"
# {{ENDIF}}

# Container images (one per Fargate service)
# container_image_<app>_<process_type> = "<account_id>.dkr.ecr.<region>.amazonaws.com/<repo>:<tag>"

# {{IF has_beanstalk_web}}
# Elastic Beanstalk web runtime settings (one required pair per web app; no defaults).
# Repeat these assignments for every Elastic Beanstalk web app, replacing
# <app_sanitized> with its hyphen-to-underscore app name. Leaving any assignment
# absent makes `terraform plan -input=false` stop with a required-variable diagnostic.
# eb_application_port_<app_sanitized>_web  = <quoted application listen port>
# eb_health_check_path_<app_sanitized>_web = <quoted HTTP health check path>
# {{ENDIF}}

# Elastic Beanstalk CodePipeline deploy (only when eb_deploy_method = "codepipeline")
# github_connection_arn = "arn:aws:codestar-connections:<region>:<account_id>:connection/<id>"
# github_repo           = "owner/repository"
# github_branch         = "main"

# Existing VPC (only if Private Space peering is detected)
# existing_vpc_id     = "vpc-0123456789abcdef0"
# existing_subnet_ids = ["subnet-aaa", "subnet-bbb"]

# {{IF migration_approach == "interim_cutover_data_first"}}
# Interim Heroku -> RDS access. Bounded allowlist only, never 0.0.0.0/0.
# Source the addresses per MIGRATION_GUIDE.md "Interim Database Exposure" Step 2,
# then reset both to their defaults after the Phase 6 rollback window (Interim Database
# Exposure Step 4), not at cutover.
# interim_heroku_ingress_cidrs = ["203.0.113.10/32", "203.0.113.11/32"]
# interim_db_public_access     = false
# {{ENDIF}}
```

---

## Step 12: Validate Generated Configuration

After all files are written:

1. **Syntax check**: Verify all `.tf` files are syntactically valid HCL
2. **Reference integrity**: Ensure all `resource` references resolve to declared resources within the same configuration
3. **Variable completeness**: Every `var.*` reference has a corresponding `variable` block in `variables.tf`
4. **Output references**: Every `output` references a declared resource attribute
5. **Tag consistency**: Every resource has the default tags (applied via provider `default_tags`)
6. **Security baseline**: `baseline.tf` exists and contains the full always-on resource list from Step 1.5 (three `aws_account_alternate_contact`, password policy, S3 account PAB, EBS default encryption, Access Analyzer, IMDSv2 account default, CloudTrail + log bucket, budget, GuardDuty); its `locals.cloudtrail_retention_days` is a positive integer; the compliance-conditional section is present exactly when the normalized `compliance` array contains soc2/pci/hipaa/fedramp; the three contact email variables are declared without defaults and with placeholder-rejecting validation blocks
7. **Elastic Beanstalk web runtime inputs**: For every EB web service, verify its per-app `eb_application_port_<app>_web` and `eb_health_check_path_<app>_web` variables are declared without defaults, include the required validation blocks, and are referenced directly by that app's `PORT` and `HealthCheckPath` settings. Verify non-web EB services do not require these variables. Do not report an EB web configuration as ready to plan until the customer has supplied both values for every web app.

8. **Defer the authoritative Terraform policy check to the assembler.** Author
   `terraform/` to satisfy the Step 0 posture, but do not write
   `validation-report.json` here. The assembler runs after every fragment,
   including conditional `eks-generate`, and owns the checker, retry loop, and
   canonical v2 report (see `generate-assemble.md` Step 3).

> Scope note: `validate-terraform-policy.py` inspects standalone `aws_lb_listener` blocks. An
> Elastic Beanstalk **LoadBalanced** environment's ALB is provisioned by EB from
> `aws_elastic_beanstalk_environment` `setting` blocks, which the static checker does not read —
> so a pure-EB design passes the ALB rules vacuously (there is no standalone listener to inspect).
> That is a known limitation, not a bypass: EB TLS/listener posture is authoring-only here.

When this fragment's files are written, control returns to `generate.md`. After all
other fragments finish, `generate-assemble.md` validates the final Terraform
directory and runs the phase completion handoff gate per its `_postconditions`.
