# Generate Phase: Infrastructure Artifact Generation

> Loaded by generate.md when generation-infra.json and aws-design.json exist.

**Execute ALL steps in order. Do not skip or optimize.**

## Overview

Transform the design (`aws-design.json`) and migration plan (`generation-infra.json`) into deployable Terraform configurations. Migration scripts are generated separately by `generate-artifacts-scripts.md`.

## Prerequisites

Read from `$MIGRATION_DIR/`:

- `aws-design.json` (REQUIRED) — AWS architecture design with cluster-level resource mappings
- `generation-infra.json` (REQUIRED) — Migration plan with timeline and service assignments
- `preferences.json` (REQUIRED) — User preferences including target region, sizing, compliance
- `gcp-resource-clusters.json` (REQUIRED) — Cluster dependency graph for ordering

Reference files (read as needed): `references/design-refs/index.md` and domain-specific files (compute.md, database.md, storage.md, networking.md, messaging.md, security.md, ai.md).

If any REQUIRED file is missing: **STOP**. Output: "Missing required artifact: [filename]. Complete the prior phase that produces it."

## Output Structure

Generate `$MIGRATION_DIR/terraform/` with only the files needed for domains that have resources in `aws-design.json`:

| File            | Domain            | Contains                                                                                                                                                                                                                                                                                                                                                                                                                |
| --------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `main.tf`       | core              | Provider config, backend, data sources                                                                                                                                                                                                                                                                                                                                                                                  |
| `variables.tf`  | core              | All input variables with types and defaults                                                                                                                                                                                                                                                                                                                                                                             |
| `outputs.tf`    | core              | Resource outputs and migration summary                                                                                                                                                                                                                                                                                                                                                                                  |
| `baseline.tf`   | security baseline | Account-wide security baseline: alternate contacts, password policy, S3 PAB, EBS encryption, Access Analyzer, IMDSv2 default, CloudTrail + S3 log bucket, AWS Budget, GuardDuty. Plus a compliance-conditional section (Config + Security Hub + standards) when `preferences.json.compliance` contains soc2/pci/hipaa/fedramp. Always emitted; users who want to skip it can delete this file before `terraform apply`. |
| `vpc.tf`        | networking        | VPC, subnets, NAT, security groups, route tables                                                                                                                                                                                                                                                                                                                                                                        |
| `security.tf`   | security          | IAM roles, policies, KMS keys, Secrets Manager                                                                                                                                                                                                                                                                                                                                                                          |
| `storage.tf`    | storage           | S3 buckets, EFS, backup vaults                                                                                                                                                                                                                                                                                                                                                                                          |
| `database.tf`   | database          | RDS/Aurora instances, parameter groups                                                                                                                                                                                                                                                                                                                                                                                  |
| `compute.tf`    | compute           | Fargate/ECS, Lambda, EC2, Elastic Beanstalk                                                                                                                                                                                                                                                                                                                                                                             |
| `monitoring.tf` | monitoring        | CloudWatch dashboards, alarms, log groups                                                                                                                                                                                                                                                                                                                                                                               |
| `README.md`     | core              | Cost tiers vs this Terraform (one stack; Balanced-aligned)                                                                                                                                                                                                                                                                                                                                                              |

## Step 0: Plan Generation Scope

Build a generation manifest: read all resources from `aws-design.json` clusters, assign each to its target .tf file by `aws_service`:

| AWS Service                                                                                                                                                                                                                                                                                                                             | Target File     |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| Account Alternate Contacts, IAM Account Password Policy, S3 Account Public Access Block, EBS Default Encryption, IAM Access Analyzer (ACCOUNT), EC2 Instance Metadata Defaults, CloudTrail, AWS Budgets, GuardDuty Detector, S3 buckets for CloudTrail and Config logs, AWS Config recorder/delivery/role, AWS Security Hub + standards | `baseline.tf`   |
| VPC, Subnet, NAT Gateway, Security Group, Route Table                                                                                                                                                                                                                                                                                   | `vpc.tf`        |
| IAM Role, IAM Policy, KMS Key, Secrets Manager                                                                                                                                                                                                                                                                                          | `security.tf`   |
| S3, EFS, Backup Vault                                                                                                                                                                                                                                                                                                                   | `storage.tf`    |
| RDS, Aurora, DynamoDB, ElastiCache                                                                                                                                                                                                                                                                                                      | `database.tf`   |
| Fargate, ECS, Lambda, EC2, Elastic Beanstalk                                                                                                                                                                                                                                                                                            | `compute.tf`    |
| CloudWatch, SNS (for alarms)                                                                                                                                                                                                                                                                                                            | `monitoring.tf` |

> `baseline.tf` is always emitted. It is NOT driven by `aws-design.json` clusters — the resources are workload-independent account controls. The compliance-conditional subset (Config + Security Hub) is emitted within the same file when `preferences.json.compliance` contains soc2/pci/hipaa/fedramp. The `aws_budgets_budget` resource reads `estimation-infra.json` to set its `limit_amount`. See Step 1.5 below. Users who want to skip the baseline can delete `terraform/baseline.tf` before `terraform apply`.

**BigQuery / specialist-deferred:** If `aws_service` is **`Deferred — specialist engagement`**, **do not** generate Terraform for that resource (no Glue, Athena, Redshift, or EMR modules from the plugin). Optionally add **`terraform/README-BIGQUERY-DEFERRED.md`** with a short checklist: engage **AWS account team** and/or **data analytics migration partner** before implementing analytics infrastructure.

## Step 1: Generate main.tf

**Requirements:**

- **File header comment block (first lines in `main.tf`, before `terraform {`):** Explain that (1) this directory implements the **single** architecture in `aws-design.json`; (2) the migration report’s **Premium / Balanced / Optimized** figures are **three pricing scenarios** from `estimation-infra.json` for that same map — **not** three separate generated stacks; (3) **this Terraform is aligned with the Balanced cost scenario** (default sizing/HA posture used for the middle estimate); (4) **Premium** = higher HA / higher $ model; **Optimized** = cost-optimization assumptions — users must **edit IaC or add modules** to realize those postures. Point readers to `terraform/README.md` and the `migration_summary` output.
- `terraform` block: `required_version >= 1.5.0`, `hashicorp/aws ~> 5.80`, active S3 backend (see Step 1a below — do NOT comment it out)
- `provider "aws"` block: `region = var.aws_region`, `default_tags` with Project, Environment, ManagedBy, MigrationId
- Data sources: `aws_caller_identity`, `aws_region`, `aws_availability_zones`

## Step 1a: Remote state backend

Always emit an **active** (not commented-out) S3 backend block in `main.tf`. Local state is not safe for production — `terraform.tfstate` stores resource metadata and sensitive values in plaintext on the local filesystem.

Emit the following backend block inside the `terraform {}` block in `main.tf`:

```hcl
backend "s3" {
  # Bootstrap: these resources are created by baseline.tf.
  # First run: terraform init -backend=false && terraform apply \
  #   -target=aws_s3_bucket.tfstate \
  #   -target=aws_s3_bucket_versioning.tfstate \
  #   -target=aws_s3_bucket_server_side_encryption_configuration.tfstate \
  #   -target=aws_s3_bucket_public_access_block.tfstate \
  #   -target=aws_dynamodb_table.tfstate_lock
  # Then re-run: terraform init  (migrates local state to S3)
  bucket         = "<project_name>-<environment>-tfstate-<account_id>"  # TODO: substitute values
  key            = "migration/terraform.tfstate"
  region         = "<aws_region>"                                        # TODO: substitute target region
  dynamodb_table = "<project_name>-<environment>-tfstate-lock"          # TODO: substitute values
  encrypt        = true
}
```

Also emit the following resources in `baseline.tf` (append after the always-on resources):

```hcl
# Remote state backend infrastructure
resource "aws_s3_bucket" "tfstate" {
  bucket = "${var.project_name}-${var.environment}-tfstate-${data.aws_caller_identity.current.account_id}"
  tags   = merge(local.baseline_tags, { Component = "terraform-state" })
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "${var.project_name}-${var.environment}-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
  tags = merge(local.baseline_tags, { Component = "terraform-state" })
}
```

Add a **Bootstrap** section to `terraform/README.md` explaining the two-step init process.

## Step 1b: Generate terraform/README.md

**Always create** `$MIGRATION_DIR/terraform/README.md` when generating Terraform (same pass as Step 1).

**Required sections:**

1. **What this directory is** — Implements one deployable baseline from `aws-design.json` (and `generation-infra.json` / `preferences.json` as applicable).
2. **Cost tiers in the migration report** — Premium, Balanced, and Optimized are **monthly cost scenarios** in `estimation-infra.json` for the **same** service mapping; order is high → mid → low estimate.
3. **Which scenario this Terraform matches** — **Balanced** (primary comparison to GCP; default migration posture in the advisor model). Premium and Optimized are **not** auto-generated as alternate roots.
4. **If you need Premium or Optimized in production** — Manually adjust instance classes, Multi-AZ, Spot mix, Reserved Instances / Savings Plans, storage classes, etc., then re-estimate.
5. **Artifacts** — Reference `estimation-infra.json`, `migration-report.html` / `MIGRATION_GUIDE.md` for full tier tables.

Keep it under one screen of text.

## Step 1.5: Generate baseline.tf

Always emitted. The baseline applies account-wide security controls that should be in place on any new AWS account. Users who do not want the baseline can delete `terraform/baseline.tf` before `terraform apply`.

1. **Compute retention.** Read `preferences.json.compliance` (array of strings; may be absent or empty). Compute `cloudtrail_retention_days` using this mapping, taking `max()` across all declared values (use 90 if the array is empty or absent):
   - absent / `[]` → 90
   - `soc2` → 365
   - `pci` → 365
   - `hipaa` → 2190
   - `fedramp` → 1095
   - `gdpr` → 365

2. **Compute budget limit.** Read `estimation-infra.json.projected_costs.breakdown.total.mid` (or the canonical equivalent). Compute `budget_limit = max(50, ceil(total_mid * 1.2))`. If `estimation-infra.json` is missing or unreadable, use `50` and emit an inline comment noting that the projection was unavailable.

3. **Choose file-header variant.** If `compliance` contains any of `soc2`, `pci`, `hipaa`, `fedramp`, emit the compliance-expansion header. Otherwise emit the base header. Both variants include a two-sentence provenance note stating per-unit rates were verified against the AWS Pricing API for us-east-1 on 2026-05-04. Substitute the resolved `cloudtrail_retention_days` value into the header.

4. **Emit `baseline.tf`** starting with the file-header comment block and a `locals` block containing the resolved `cloudtrail_retention_days` integer:

   ```hcl
   locals {
     cloudtrail_retention_days = <N>
   }
   ```

5. **Append the always-on resources**, in this order. Each resource carries the plugin's standard four default tags plus `Component = "security-baseline"`:
   - `aws_account_alternate_contact.operations` (ACCT.01, `email_address = var.operations_email` — fill-once variable, see Step 2)
   - `aws_account_alternate_contact.billing` (ACCT.01, `email_address = var.billing_email`)
   - `aws_account_alternate_contact.security` (ACCT.01, `email_address = var.security_email`)
   - `aws_iam_account_password_policy.baseline` (ACCT.06; `minimum_password_length = 14`, `password_reuse_prevention = 24`, `max_password_age = 90`, all four character-class requirements `true`, `hard_expiry = false`)
   - `aws_s3_account_public_access_block.baseline` (ACCT.08; all four flags `true`)
   - `aws_ebs_encryption_by_default.baseline` (defense-in-depth; `enabled = true`)
   - `aws_accessanalyzer_analyzer.baseline` (ACCT.11; `type = "ACCOUNT"`)
   - `aws_ec2_instance_metadata_defaults.baseline` (defense-in-depth; `http_tokens = "required"`, `http_put_response_hop_limit = 2`)
   - `aws_cloudtrail.baseline` (ACCT.07; multi-region, management events only, `enable_log_file_validation = true`)
   - `aws_s3_bucket.cloudtrail_logs` plus `aws_s3_bucket_public_access_block`, `aws_s3_bucket_server_side_encryption_configuration`, `aws_s3_bucket_versioning`, `aws_s3_bucket_lifecycle_configuration` (transitions driven by `local.cloudtrail_retention_days` per item 7), and `aws_s3_bucket_policy` restricting the CloudTrail service principal by `aws:SourceArn`
   - `aws_budgets_budget.monthly_spend` (ACCT.10; `limit_amount = "<budget_limit>"` from item 2; three `notification` blocks at 50/80/100% `ACTUAL`; `subscriber_email_addresses = [var.billing_email]` — same fill-once variable as the alternate contact, entered exactly once in tfvars)
   - `aws_guardduty_detector.baseline` (defense-in-depth; `enable = true`, `finding_publishing_frequency = "FIFTEEN_MINUTES"`)

6. **If `compliance` contains any of `soc2`, `pci`, `hipaa`, `fedramp`, append the compliance-conditional section**, wrapped in `########## Compliance-Conditional ##########` / `########## End Compliance-Conditional ##########` dividers:
   - `aws_iam_role.config` + `aws_iam_role_policy_attachment` for the managed policy `arn:aws:iam::aws:policy/service-role/AWS_ConfigRole` (note the underscore — `AWSConfigRole` without it is a deprecated policy name and fails apply)
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
   - On each `aws_account_alternate_contact.*`: a comment pointing at the tfvars fill-once variable (`# set var.operations_email in terraform.tfvars — plan fails until you do`).
   - On `aws_cloudtrail.baseline`: a collision warning for users who already have a trail in the region.
   - On `aws_budgets_budget.monthly_spend`: the limit-rationale comment (`max(50, ceil(total_mid * 1.2))`; $50 floor prevents alert noise; users may edit `limit_amount` directly post-apply).
   - On `aws_guardduty_detector.baseline`: a cost disclosure noting the 30-day free trial and ~$2–25/mo post-trial.
   - On `aws_config_configuration_recorder.baseline`: a cost disclosure ($0.003/CI continuous; $0.012/daily-CI as an opt-in for cost-sensitive users).
   - On `aws_securityhub_account.baseline`: a cost disclosure noting the 30-day free trial and ~$1–15/mo post-trial.
   - On every defense-in-depth resource (EBS encryption, IMDSv2 account default, GuardDuty, Config, Security Hub): the literal token `defense-in-depth` in the inline comment.

9. **compute.tf modification (runs during Step 3 compute domain, not here):** every `aws_launch_template` emitted for ECS-EC2, EKS node groups, or bare EC2 receives IMDSv2 enforcement unconditionally — the security baseline is always applied:

   ```hcl
   metadata_options {
     http_tokens                 = "required"
     http_put_response_hop_limit = 1
     http_endpoint               = "enabled"
     instance_metadata_tags      = "enabled"
   }
   ```

   Fargate, Lambda, and App Runner do not emit launch templates and are unaffected (no synthetic launch template is created). Hop limit `1` here is intentionally different from the account-level default `2` in `aws_ec2_instance_metadata_defaults.baseline` — strict on templates the plugin owns, permissive at the account default.

**Emission conditions**:

- Emit `baseline.tf` even when `aws-design.json` contains only AI or billing-only resources (no infrastructure clusters). The baseline is workload-independent.
- Do NOT probe for existing account resources (CloudTrail trails, Config recorders, Security Hub enrollment). Collision risk is surfaced by the inline comments listed in item 8.

## Step 2: Generate variables.tf

**Global variables (always include):** `aws_region` (from `preferences.json` target_region), `project_name`, `environment` (from `preferences.json`), `migration_id`, and the fill-once contact variables `operations_email`, `billing_email`, `security_email` (type `string`, **no default** — plan fails until set).

**Placeholder guards (REQUIRED):** `terraform validate` passes on syntactically valid placeholders — a user can `apply` with `TODO-ops@example.com` as their account security contact and never know. Every variable whose value cannot be inferred (the contact emails, ECR image URIs, and any other user-supplied value that ships with a placeholder in `terraform.tfvars.example`) MUST carry a `validation` block that rejects placeholder tokens, so the failure happens loudly at `terraform plan` with an actionable message:

```hcl
variable "billing_email" {
  description = "Billing contact + budget alert recipient (fill-in checklist #2)"
  type        = string
  validation {
    condition     = !strcontains(var.billing_email, "TODO") && !strcontains(var.billing_email, "example.com") && strcontains(var.billing_email, "@")
    error_message = "Set billing_email in terraform.tfvars to a real inbox (see MIGRATION_GUIDE.md fill-in checklist)."
  }
}
```

For non-email placeholders, reject the specific placeholder tokens the example ships with (`TODO`, `ACCOUNT_ID`, `<`). Error messages MUST name the tfvars key and point at the fill-in checklist. The backend block cannot use variables (Terraform limitation) — its `ACCOUNT_ID` placeholder is covered by the fill-in checklist row instead.

**Per-cluster variables:** Extract configurable values from `aws_config` in `aws-design.json`. Infer types (`string`, `number`, `bool`, `list(string)`, `map(string)`). Use `aws_config` values as defaults. Deduplicate shared variables. Add GCP source as comment (e.g., `# GCP source: db-custom-2-7680`).

## Step 2b: Generate terraform.tfvars.example and .gitignore

Always emit `$MIGRATION_DIR/terraform/terraform.tfvars.example` alongside `variables.tf`. Populate it with actual values from `aws-design.json`, `preferences.json`, and `estimation-infra.json` where available. Use descriptive placeholder strings (not empty values) for anything that cannot be inferred. Format:

```hcl
# Copy this file to terraform.tfvars and fill in the values before running terraform plan.
# Do NOT commit terraform.tfvars to source control — it may contain sensitive values.

aws_region   = "<target_region>"   # from preferences.json target_region
project_name = "<your-project>"    # TODO: set your project name
environment  = "production"        # TODO: dev | staging | production
migration_id = "<MMDD-HHMM>"       # from migration run ID

# One entry per variable in variables.tf, with source annotation as comment
```

Also emit `$MIGRATION_DIR/terraform/.gitignore` with:

```
# Never commit actual variable values — may contain sensitive data
terraform.tfvars
*.tfvars
!terraform.tfvars.example
.terraform/
*.tfstate
*.tfstate.backup
```

## Step 3: Generate Per-Domain .tf Files

### Step 3.0: Apply AWS authoring posture (before writing)

**Before generating any `.tf`, invoke the `tf-best-practices` skill for its authoring posture** —
it is the single source of truth for "what good AWS Terraform looks like." Treat it as a **black
box**: pass the context below and follow whatever posture it returns. Do **not** reach into its
files or assume how it is organized internally — it evolves independently.

> Invoke the **`tf-best-practices`** skill, telling it you are **about to author `terraform/`**
> (the authoring/pre-generation context), and emit Terraform that satisfies every rule it
> returns.

**Pass the caller context** the skill needs (these are gcp-to-aws's to supply; the skill reads
none of our artifacts itself):

- **`compliance`** — the value of `preferences.json` → `design_constraints.compliance` (array;
  may be empty/absent). Empty ⇒ the skill emits no compliance-conditional hardening, keeping the
  stack minimal and immediately applyable.
- **`aws_config` values** — instance classes, CPU/memory, storage sizes, engine versions from
  each resource's `aws_config` in `aws-design.json`. Populate resource attributes from these;
  the skill's posture constrains the shape, not the numbers.

**Do not re-specify the skill's posture here** — the skill owns it. Step 3.1 covers only the
source-glue and resource wiring the skill does not (and should not) know about.

### Step 3.1: gcp-to-aws generation rules (source glue — NOT AWS posture)

For each domain with resources in the generation manifest:

**General rules:**

- Consult `references/design-refs/*.md` for AWS configuration best practices
- A single GCP resource may map to multiple AWS resources (1:Many expansion)
- Use `gcp_config` / `aws_config` values from `aws-design.json` to populate resource attributes
- For `confidence: "inferred"` resources, add comment: `# Tailored to your setup — verify configuration (JSON confidence: inferred)`
- For `confidence: "deterministic"` resources, optional comment: `# Standard pairing (fixed mapping list)`
- Include `secondary_resources` from the cluster (IAM roles, security groups)
- Tag every resource: Project, Environment, ManagedBy, MigrationId

**GCP-source-specific rules (these stay here — the skill is source-agnostic and cannot own them):**

- **Cloud SQL `authorized_networks` → warning:** if a source `google_sql_database_instance` has
  `authorized_networks` containing `0.0.0.0/0`, emit a `warnings[]` entry in `aws-design.json`:
  "Cloud SQL authorized_networks includes 0.0.0.0/0 — mapped to private RDS with no public
  access." (The skill already mandates a private, non-`0.0.0.0/0` RDS; this warning just records
  that the source was public and was intentionally not carried over.)
- **Monitoring alarms** derive from `generation-infra.json` success_metrics (a gcp-to-aws
  artifact); wire them into the CloudWatch dashboard/alarms the skill's monitoring baseline calls
  for.
- **Domain resource wiring** the skill's rules assume you emit — DB subnet group + parameter
  group; per-service Fargate/Lambda IAM roles; compute auto-scaling — populated with this
  migration's `aws_config` values.
- **CPU architecture (Graviton/ARM64):** read each compute resource's
  `graviton.target_architecture` from `aws-design.json` (see `references/shared/graviton.md`).
  When `arm64`: emit `aws_ecs_task_definition` with
  `runtime_platform { cpu_architecture = "ARM64" operating_system_family = "LINUX" }`,
  `aws_lambda_function` with `architectures = ["arm64"]`, the Graviton instance type from
  `aws_config` (e.g., `m7g.xlarge`) on EC2/EKS launch templates, and for Elastic Beanstalk the
  `t4g.*` `InstanceType` setting on `aws_elastic_beanstalk_environment` — add inline comment
  `# Graviton (ARM64) — ~15-20% cheaper than x86; build images with --platform linux/arm64`.
  When `x86_64`: emit x86 types with a comment citing the blocker from `graviton.caveats`.
  EKS arm64 node groups are single-arch on dev tier.

**Domain-specific wiring** (posture is owned by the `tf-best-practices` skill — these rows list
only the gcp-to-aws resource wiring / value population per domain; for every security rule,
follow the posture the skill returned in Step 3.0):

| Domain     | gcp-to-aws wiring (skill owns the posture)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Networking | Emit the VPC/subnets/NAT/SGs and (for compliance) flow logs per the skill's posture; populate CIDRs/AZ count from design. Wire an internet-facing ALB only if the design has one.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Security   | Emit per-service Fargate/Lambda IAM roles and Secrets Manager resources per the skill's posture (least-privilege, no plaintext master password, compliance-conditional rotation/KMS). Populate ARNs/role names from the cluster's `secondary_resources`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Storage    | Emit S3 buckets per the skill's posture (versioning, SSE, block-public-access, CloudFront/OAC for public, compliance-conditional access logging). Populate bucket names/lifecycle from design.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Database   | Emit RDS/Aurora per the skill's posture (private, encrypted, `deletion_protection`, master-password-via-Secrets-Manager, DB-port SG scoping). Populate engine/version/instance class from `aws_config`; add the Cloud SQL `authorized_networks` warning (Step 3.1) when applicable.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| Compute    | Emit Fargate/EKS/ECR per the skill's posture (private subnets, EKS private endpoint, ECR scan-on-push). Populate task CPU/memory and autoscaling from `aws_config`. Apply Graviton/ARM64 wiring from the CPU architecture rule above. **Elastic Beanstalk** (App Engine → EB): emit one `aws_elastic_beanstalk_application` for the app and one `aws_elastic_beanstalk_environment` per `source_service` (from `aws_config`). Resolve `solution_stack_name` with a **Terraform `data` source** (self-updating, needs no generate-time credentials, cannot go stale in the committed file) — do not paste `aws_config.platform` verbatim (it is a human-readable label like `"Python 3.12 running on 64bit Amazon Linux 2023"`): emit `data "aws_elastic_beanstalk_solution_stack" "<svc>" { most_recent = true, name_regex = "64bit Amazon Linux 2023 (.*) running Python 3.12" }` (build `name_regex` from the language + version in `platform`) and reference `.name`. Fallback only if a `data` source can't be used: `aws elasticbeanstalk list-available-solution-stacks` at generate time. Also emit the EB **instance profile** this environment references — `aws_iam_role` (EC2 trust) + `aws_iam_instance_profile` + the managed-policy attachment (`AWSElasticBeanstalkWebTier`, plus `AWSElasticBeanstalkWorkerTier`/`AWSElasticBeanstalkMulticontainerDocker` as the platform needs) — since EB does not auto-create it in Terraform; do not reference an instance profile that no resource emits. Emit `setting` blocks for: `aws:autoscaling:launchconfiguration/IamInstanceProfile` (the instance profile just emitted); `aws:autoscaling:launchconfiguration/SecurityGroups` (an SG for the instances, required when they sit in private subnets); `aws:autoscaling:launchconfiguration/InstanceType` (from `instance_type`); `aws:elasticbeanstalk:environment/EnvironmentType` (from `environment_type`); **when `environment_type == "LoadBalanced"`, also `aws:elasticbeanstalk:environment/LoadBalancerType = application`** (ALB, not the Classic default) plus `aws:autoscaling:asg/MinSize` (from `min_instances`) and `MaxSize` (from `max_instances`); `aws:ec2:vpc/VPCId`, `Subnets`, and `ELBSubnets` — for **LoadBalanced**, instances in private subnets + ALB in public (`ELBScheme` public); for **SingleInstance** (no ALB) put the instance in a **public** subnet with `AssociatePublicIpAddress=true` so it is reachable; and `aws:elasticbeanstalk:application:environment` for env vars. ARM64: pick the `t4g.*` instance type from `aws_config` per the Graviton rule. See `design-refs/elastic-beanstalk.md`. |
| Monitoring | Emit CloudWatch log groups/dashboard/alarms per the skill's monitoring baseline; source alarm thresholds from `generation-infra.json` success_metrics.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |

## Step 4: Generate outputs.tf

Output identifiers for key resources (VPC ID, database endpoint, ECS cluster name, etc.) plus a **`migration_summary` output** (object) including at minimum:

| Key                                   | Type / example | Purpose                                                                                                                                                        |
| ------------------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `aws_region`                          | string         | From `var.aws_region`                                                                                                                                          |
| `environment`                         | string         | From `var.environment`                                                                                                                                         |
| `migration_id`                        | string         | From `var.migration_id`                                                                                                                                        |
| `service_count`                       | number         | Count of primary logical services / resources represented                                                                                                      |
| `aligned_with_estimate_tier`          | string         | Always **`"balanced"`** for this advisor — generated IaC matches the **Balanced** scenario in `estimation-infra.json`                                          |
| `cost_scenarios_modeled_in_terraform` | string         | e.g. **`"design_baseline_only"`** — only one stack generated; Premium/Optimized exist as **pricing** scenarios in estimates, not as additional Terraform trees |

Add VPC ID or other IDs when known from resources. Descriptions on every output.

**Example shape:**

```hcl
output "migration_summary" {
  description = "Migration run metadata and cost-tier alignment (Balanced baseline)"
  value = {
    aws_region                            = var.aws_region
    environment                           = var.environment
    migration_id                          = var.migration_id
    service_count                         = <number>
    aligned_with_estimate_tier            = "balanced"
    cost_scenarios_modeled_in_terraform   = "design_baseline_only"
  }
}
```

## Step 5: Self-Check

Verify these quality rules before reporting completion:

**Security posture (owned by the `tf-best-practices` skill; the Step 6 policy gate re-verifies the statically-checkable subset):**

- [ ] Generated Terraform satisfies the authoring posture the `tf-best-practices` skill returned at Step 3.0, for the `compliance` context passed. (The skill defines the rules; do not re-enumerate them here.)

**gcp-to-aws generation self-check (caller-specific — not owned by the skill):**

- [ ] No default VPC references — all resources use the created VPC
- [ ] No hardcoded credentials in any .tf file
- [ ] Tags on every resource (Project, Environment, ManagedBy, MigrationId)
- [ ] Every variable has `type` and `description`
- [ ] Every output has `description`
- [ ] Region from `var.aws_region`, never hardcoded
- [ ] `terraform/README.md` exists with cost-tier vs Terraform explanation
- [ ] `main.tf` begins with the required cost-tier / Balanced alignment comment block
- [ ] `migration_summary` output includes `aligned_with_estimate_tier` and `cost_scenarios_modeled_in_terraform`

- [ ] `baseline.tf` exists.
- [ ] `baseline.tf` contains `aws_account_alternate_contact` for each of OPERATIONS, BILLING, SECURITY, plus `aws_iam_account_password_policy`, `aws_s3_account_public_access_block`, `aws_ebs_encryption_by_default`, `aws_cloudtrail`, `aws_guardduty_detector`, `aws_accessanalyzer_analyzer`, `aws_ec2_instance_metadata_defaults`, and `aws_budgets_budget`.
- [ ] `baseline.tf` contains a `locals` block with `cloudtrail_retention_days` set to a positive integer, and the lifecycle `expiration.days` on `aws_s3_bucket_lifecycle_configuration.cloudtrail_logs` equals `local.cloudtrail_retention_days`.
- [ ] `aws_budgets_budget.monthly_spend.limit_amount` equals `max(50, ceil(estimation-infra.json.projected_costs.breakdown.total.mid * 1.2))` as a string.
- [ ] If `compute.tf` contains any `aws_launch_template`, every such launch template has `metadata_options { http_tokens = "required", http_put_response_hop_limit = 1 }` — this applies unconditionally (the security baseline is always emitted).
- [ ] Every `aws_ecr_repository` in `compute.tf` has `image_scanning_configuration { scan_on_push = true }`.
- [ ] If `compliance` contains soc2/pci/hipaa/fedramp, `baseline.tf` contains `aws_config_configuration_recorder`, `aws_config_delivery_channel`, `aws_config_configuration_recorder_status`, `aws_securityhub_account`, `aws_securityhub_standards_subscription` for FSBP.
- [ ] If `compliance` contains pci, an additional `aws_securityhub_standards_subscription` for PCI DSS exists.
- [ ] `baseline.tf` does NOT contain any `aws_securityhub_standards_subscription` whose `standards_arn` references `nist-800-53`, regardless of compliance values.
- [ ] If `compliance` is empty, absent, or contains only gdpr, `baseline.tf` does NOT contain any `aws_config_*` or `aws_securityhub_*` resources.
- [ ] `baseline.tf` does NOT contain any invented SSB control IDs. Search for `ACCT.IAM`, `ACCT.S3`, `ACCT.EBS`, `ACCT.CT`, `ACCT.GD`, `ACCT.CFG`, `ACCT.SH`, `WKLD.EC2.01` — all MUST have zero matches. Only bare `ACCT.01` through `ACCT.13` identifiers are permitted.
- [ ] `baseline.tf` does NOT mention "Trusted Advisor" anywhere (Trusted Advisor is docs-action only and out of scope).
- [ ] Security Hub subscribes to FSBP (always when the compliance-conditional section is emitted) and PCI DSS (only when `compliance` contains `pci`). No other standards subscriptions.

## Step 6: Validate generated Terraform (fmt / init / validate / policy)

After the Step 5 self-check, validate `$MIGRATION_DIR/terraform` and write
`$MIGRATION_DIR/validation-report.json`.

**Invoke the `tf-best-practices` skill for the post-writing validation context** — tell it the
`terraform/` directory has been written and pass `$MIGRATION_DIR/terraform` as the target dir.
Treat it as a **black box**: follow the validation protocol and policy verdict it returns (exit
codes, `violations[]` shape). Do **not** reach into its internal files — it evolves
independently.

> The authoring posture was already applied at **Step 3.0**, so the generated Terraform should
> pass by construction; this step re-verifies the statically checkable subset and produces the
> machine-readable verdict.

This phase is the **caller** in that protocol. `tf-best-practices` is a read-only verdict
producer — it reports whether the Terraform passes. This phase owns everything the skill does
NOT: pass `$MIGRATION_DIR/terraform` as the target dir, run the fmt/init/validate stages, apply
the fix-and-retry edits to the reported `violations[]` sites (budget 3), run the retry/skip/abort
prompt, and write `validation-report.json`.

Caller responsibilities specific to this phase (not owned by the skill):

- Record the skill's policy verdict into `validation-report.json` as `policy_status`
  (+ `policy_violations` on failure). The verdict is recorded independently of the fmt/init/
  validate outcome, so a policy failure is never masked by `passed_degraded_offline`.
- An unresolved `POLICY_FAIL` that the user does not `skip`/`abort` sets top-level
  `status: "policy_failed"` and blocks Phase Completion (see below).

## Phase Completion

Report generated files to the parent orchestrator. **Do NOT update `.phase-status.json`** — the parent `generate.md` handles phase completion.

Before reporting completion, enforce artifact output gate:

- `terraform/` directory exists.
- At minimum: `terraform/main.tf`, `terraform/variables.tf`, and `terraform/outputs.tf` exist.
- At least one domain file exists among: `vpc.tf`, `security.tf`, `storage.tf`, `database.tf`, `compute.tf`, `monitoring.tf`.
- `terraform/baseline.tf` MUST exist (baseline is always emitted).
- `validation-report.json` MUST exist with `policy_status: "POLICY_OK"` (per Step 6). A
  `POLICY_FAIL` that was not resolved blocks completion unless the user explicitly chose
  `skip`/`abort` in the Step 6 retry loop.

If this gate fails: STOP and output: "generate-artifacts-infra did not produce required Terraform artifacts; do not complete Generate Stage 2."

```
Generated terraform artifacts:
- terraform/README.md
- terraform/main.tf
- terraform/variables.tf
- terraform/outputs.tf
- terraform/[domain].tf (for each domain with resources)
- validation-report.json (status: <validation_status>)

Total: [N] Terraform files
Validation: <validation_status> (attempts=<N>, errors_fixed=<N>)
TODO markers: [N] items requiring manual configuration
```
