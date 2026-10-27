---
_fragment: artifacts-infra
_of_phase: generate
_contributes:
  - terraform/main.tf
  - terraform/baseline.tf
  - terraform/variables.tf
  - terraform/outputs.tf
  - terraform/.gitignore
  - terraform/terraform.tfvars.example
---

# Generate — Terraform Configurations

> **Fragment unit.** See `generate.md` for how it is composed into the phase.

Emits idiomatic replacement Terraform for the designed architecture. Where the
customer supplied IaC, its module structure and naming inform the output — that is
what the _declared intent_ half of discovery was for, and it is why IaC stays a
first-class source even when live discovery is authoritative for state.

Per-domain `.tf` files (compute, data, network, security) are emitted as the design
requires. They are the **open tail**: this fragment lists in `_contributes` only what
it writes unconditionally (the five core files); the domain files are governed by
this prose and the phase's `_assert`s.

Secrets are never inlined. A Key Vault entry becomes a Secrets Manager reference, and
the value stays where it was.

**Execute the steps in order. Do not skip or optimize.**

## Inputs

Read from `$MIGRATION_DIR/`:

- `aws-design.json` (REQUIRED) — `services[]` (per-resource mappings with `aws_service`,
  `aws_config`, `confidence`, `azure_type`; **may be empty** when every discovered resource
  was deferred or skipped — `design.md` allows that, Estimate carries it through, and this
  fragment then emits the core files plus `baseline.tf` only), `clusters[]` (workload
  grouping + tier), `deferred[]`, `target_region`, `cpu_architecture`.
- `preferences.json` (REQUIRED) — `design_constraints`, `data.availability`, licensing,
  identity, environment/region.
- `estimation-infra.json` (REQUIRED) — for the budget limit and the cost-tier README note.
- `azure-resource-inventory.json` (REQUIRED) — source `config` for attribute population and
  the module/naming provenance (`config.tf_module`, `config.tf_address`).

If any REQUIRED file is missing: **STOP** — "Missing required artifact: [filename]."

## Output structure

Generate `$MIGRATION_DIR/terraform/`, emitting only the domain files for domains that
have services in `aws-design.json`:

| File                       | Domain            | Contains                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| -------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `main.tf`                  | core              | provider, S3 backend, data sources, cost-tier header                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `baseline.tf`              | security baseline | Account-wide security baseline: alternate contacts, password policy, S3 public-access block, EBS encryption, Access Analyzer, IMDSv2 default, CloudTrail + S3 log bucket, AWS Budget, GuardDuty, and the remote-state bucket + lock table. Plus Config + Security Hub when `design_constraints.compliance` contains soc2, pci, hipaa, or fedramp. Always emitted, including when the design has no infrastructure clusters. Opting out is the three-step procedure in Step 1.5 § "Opting out of the baseline" — deleting the whole file alone breaks the root. |
| `variables.tf`             | core              | all input variables (types, defaults, placeholder-guard validation)                                                                                                                                                                                                                                                                                                                                                                                                     |
| `outputs.tf`               | core              | key resource outputs + `migration_summary`                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `.gitignore`               | core              | tfstate/tfvars ignores                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `terraform.tfvars.example` | core              | one entry per variable, source-annotated                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `network.tf`               | networking | VPC, subnets, security groups, ALB/NLB, NAT                         |
| `compute.tf`               | compute    | Elastic Beanstalk, ECS/Fargate, EKS, EC2, Lambda                    |
| `data.tf`                  | data       | RDS/Aurora, ElastiCache, DynamoDB                                   |
| `storage.tf`               | storage    | S3, EFS/FSx                                                         |
| `messaging.tf`             | messaging  | SQS, SNS, Kinesis/MSK                                               |
| `security.tf`              | security   | IAM roles, KMS keys, Secrets Manager references                     |
| `README.md`                | core       | cost-tier vs Terraform note (one stack, Balanced-aligned)           |

## Step 0: Build the generation manifest

Walk `aws-design.json` `services[]`. Assign each service to a target `.tf` file by
`aws_service` (canonical AWS service on the mapping):

| AWS service (from the mapping)                                   | Target file    |
| ---------------------------------------------------------------- | -------------- |
| VPC, VPC subnet, Security Group, ALB, NLB, NAT Gateway, Route 53 | `network.tf`   |
| Elastic Beanstalk, ECS, Fargate, EKS, EC2, Lambda                | `compute.tf`   |
| RDS PostgreSQL, RDS MySQL, Aurora, ElastiCache, DynamoDB         | `data.tf`      |
| S3, EFS, FSx                                                     | `storage.tf`   |
| SQS, SNS, Kinesis, MSK                                           | `messaging.tf` |
| IAM Role, KMS, Secrets Manager, ECR                              | `security.tf`  |

Rules:

- **A service with `aws_service: "Deferred — specialist engagement"` is NOT generated.**
  It is carried to `generation-warnings.json` by the assembler and named in the guide.
  Optionally add `terraform/README-DEFERRED.md` with a one-line checklist.
- **A skipped service (config source / observability) emits no resource** — its
  contribution was already folded into its parent (see the App Service Plan fan-in rule).
- **`baseline.tf` is not a service mapping.** Emit it even when every service is skipped
  or deferred and `clusters[]` is empty. Core files plus `baseline.tf` are a complete
  generate in that case; do not invent a domain file to satisfy a file count.
- Every generated service must be accounted for as one element of the assembler's
  `generated[]` array (`{ azure_id, azure_type, aws_service, target_file }`, per
  `generate-assemble.md`); the assembler enforces this.

## Step 1: main.tf

- **Header comment block** (before `terraform {`): state that (1) this directory
  implements the **single** architecture in `aws-design.json`; (2) the report's
  Premium / Balanced / Optimized figures are **three pricing scenarios** on the same
  map from `estimation-infra.json`, not three stacks; (3) this Terraform is aligned
  with the **Balanced** scenario; (4) Premium/Optimized require editing the IaC.
- `terraform` block: `required_version >= 1.5.0`, `hashicorp/aws ~> 5.80`, and an
  **active** (not commented-out) S3 backend block (bucket/key/region/dynamodb_table
  with `# TODO` substitution comments). The state bucket and lock table are created by
  the delimited **Remote State** section of `baseline.tf` (`aws_s3_bucket.tfstate`,
  `aws_dynamodb_table.tfstate_lock`). README documents the two-step `init -backend=false`
  bootstrap that targets those resources, and the baseline opt-out procedure (Step 1.5
  § "Opting out of the baseline"), which keeps that section.
- `provider "aws"`: `region = var.aws_region`, `default_tags` with Project,
  Environment, ManagedBy, MigrationId.
- Data sources: `aws_caller_identity`, `aws_region`, `aws_availability_zones`,
  `aws_partition` (`data "aws_partition" "current" {}` — every AWS-managed policy ARN is
  built from `data.aws_partition.current.partition`, never a literal `arn:aws:`, so a
  `fedramp` design that targets GovCloud resolves to `arn:aws-us-gov:`).

## Step 1.5: Generate baseline.tf

Always emitted, including when `aws-design.json` has no infrastructure clusters and no
generatable services. The baseline is workload-independent account controls. It is not
driven by `clusters[]`. Users who do not want it follow § "Opting out of the baseline"
below — deleting the file alone is not a complete opt-out, because the file also owns the
remote-state producers and the three contact variables have no defaults. Do not probe for
an existing trail, Config recorder, or Security Hub enrollment; collision risk is an
inline comment.

This is the same account file `gcp-to-aws` emits. Read compliance from Azure's field,
`preferences.json` → `design_constraints.compliance`, not from a root `compliance` key.
If the value is an object, use its `value` array. Normalize `[]`, absent, and `["none"]`
as no frameworks. `["unknown"]` does not add Config or Security Hub.

1. **Compute retention.** Take `max()` across declared frameworks (90 if none apply):
   absent / `[]` / `none` → 90; `soc2` → 365; `pci` → 365; `hipaa` → 2190;
   `fedramp` → 1095; `gdpr` → 365.
2. **Compute budget limit.** Read `estimation-infra.json` → `projected_costs.aws_monthly_balanced`
   (the Balanced total this skill's Estimate asserts). `budget_limit = max(50, ceil(aws_monthly_balanced * 1.2))`.
   If the file or key is missing, use `50` and say so in an inline comment. That
   limit is a floor on the priced workload. Estimate does not roll CloudTrail log
   storage, GuardDuty, or Config and Security Hub into `aws_monthly_balanced`, so
   the budget is not a price of those controls.
3. **Header.** If compliance contains `soc2`, `pci`, `hipaa`, or `fedramp`, emit the
   compliance-expansion header. Otherwise emit the base header. Both name the resolved
   `cloudtrail_retention_days` and note that per-unit rates in the cost comments were
   verified against the AWS Pricing API for us-east-1 on 2026-05-04.
4. **Start the file** with that header and:

   ```hcl
   locals {
     cloudtrail_retention_days = <N>
     baseline_tags = {
       Project     = var.project_name
       Environment = var.environment
       ManagedBy   = "terraform"
       MigrationId = var.migration_id
       Component   = "security-baseline"
     }
   }
   ```

5. **Always-on resources**, in this order. Tag each with `local.baseline_tags` where the
   type supports tags. `aws_account_alternate_contact` requires `name`, `title`, and
   `phone_number` as well as the email: pin the name and title, and set
   `phone_number = "+1-555-0100"` with a comment to replace it after apply.
   - `aws_account_alternate_contact.operations` (ACCT.01; `email_address = var.operations_email`)
   - `aws_account_alternate_contact.billing` (ACCT.01; `email_address = var.billing_email`)
   - `aws_account_alternate_contact.security` (ACCT.01; `email_address = var.security_email`)
   - `aws_iam_account_password_policy.baseline` (ACCT.06; length 14, reuse prevention 24,
     max age 90, all four character classes, `hard_expiry = false`)
   - `aws_s3_account_public_access_block.baseline` (ACCT.08; all four flags `true`)
   - `aws_ebs_encryption_by_default.baseline` (defense-in-depth; `enabled = true`)
   - `aws_accessanalyzer_analyzer.baseline` (ACCT.11; `type = "ACCOUNT"`)
   - `aws_ec2_instance_metadata_defaults.baseline` (defense-in-depth; `http_tokens = "required"`,
     `http_put_response_hop_limit = 2`)
   - `aws_cloudtrail.baseline` (ACCT.07; name `${var.project_name}-baseline`, which must
     match the bucket policy `aws:SourceArn`; multi-region; management events only;
     `enable_log_file_validation = true`; `depends_on` the bucket policy)
   - `aws_s3_bucket.cloudtrail_logs` plus public-access block, SSE, versioning, lifecycle
     (expiration `local.cloudtrail_retention_days`), and a bucket policy restricting
     `cloudtrail.amazonaws.com` by `aws:SourceArn`
   - `aws_budgets_budget.monthly_spend` (ACCT.10; `limit_amount` from item 2; notifications
     at 50/80/100% ACTUAL to `var.billing_email`)
   - `aws_guardduty_detector.baseline` (defense-in-depth; `enable = true`;
     `finding_publishing_frequency = "FIFTEEN_MINUTES"`)
6. **Compliance-conditional**, only when compliance contains `soc2`, `pci`, `hipaa`, or
   `fedramp`, emitted directly after the always-on resources and **before** the Remote
   State section (item 7), wrapped in `########## Compliance-Conditional ##########` /
   `########## End Compliance-Conditional ##########`:
   - `aws_iam_role.config` trusted by `config.amazonaws.com`, plus an
     `aws_iam_role_policy_attachment` whose `policy_arn` is derived from the target
     partition, never hard-coded:
     `"arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWS_ConfigRole"`
     (the `data "aws_partition" "current"` source is emitted in `main.tf`, Step 1). This
     resolves to `arn:aws:…` in commercial regions and `arn:aws-us-gov:…` in GovCloud —
     required for `fedramp`, whose region choice lands in GovCloud, where a literal
     `arn:aws:` ARN cannot be attached. Same pattern as the GCP emitter. The underscore in
     `AWS_ConfigRole` is required; `AWSConfigRole` is a deprecated name and fails apply.
   - `aws_config_configuration_recorder.baseline` with `all_supported = true` and
     `include_global_resource_types = true`
   - `aws_config_delivery_channel.baseline` and `aws_config_configuration_recorder_status.baseline`
   - `aws_s3_bucket.config_logs` plus public-access block, SSE, versioning, lifecycle, and a
     bucket policy for `config.amazonaws.com`
   - `aws_securityhub_account.baseline`
   - `aws_securityhub_standards_subscription.fsbp` always in this section
   - `aws_securityhub_standards_subscription.pci_dss` only when compliance contains `pci`
   - Do not emit a NIST 800-53 subscription, including for `hipaa` or `fedramp`
7. **Remote state**, always the **final** section of the file — after the always-on
   resources and after the compliance-conditional section when one was emitted (same
   resources GCP puts in this file; do not also emit them in `security.tf`), wrapped in
   `########## Remote State — keep this section when opting out of the baseline ##########` /
   `########## End Remote State ##########`:
   `aws_s3_bucket.tfstate`, versioning, SSE (`aws:kms`), public-access block, and
   `aws_dynamodb_table.tfstate_lock` (`PAY_PER_REQUEST`, hash key `LockID`). Bucket name
   `${var.project_name}-${var.environment}-tfstate-${data.aws_caller_identity.current.account_id}`.
   Lock table name `${var.project_name}-${var.environment}-tfstate-lock`. Tag with a
   literal `{ Component = "terraform-state" }` (the provider `default_tags` supply the
   rest) — **not** `local.baseline_tags`, no `local.cloudtrail_retention_days`, and no
   `var.*_email` reference, so the section stands alone once everything outside the two
   markers is removed. Nothing follows `########## End Remote State ##########`.
8. **Lifecycle.** Omit the `STANDARD_IA` transition when retention is under 90 days. Omit
   `GLACIER` when retention is under 365 days. Apply both rules to the CloudTrail bucket
   and, when emitted, the Config bucket.
9. **Comments.** Each alternate contact points at its tfvars variable. CloudTrail warns
   about an existing trail. The budget states `max(50, ceil(aws_monthly_balanced * 1.2))`.
   GuardDuty notes the 30-day trial and about $2–25/month after. Config notes
   $0.003 per configuration item. Security Hub notes the 30-day trial and about $1–15/month
   after. Every defense-in-depth resource (EBS encryption, IMDSv2, GuardDuty, Config,
   Security Hub) includes the literal token `defense-in-depth`.
10. **Launch templates** (Step 3, not in this file): every `aws_launch_template` for
    ECS-EC2, EKS nodes, or EC2 sets `http_tokens = "required"` and
    `http_put_response_hop_limit = 1`. Fargate and Lambda get no synthetic launch template.

`gdpr` changes retention only. It does not add Config or Security Hub. An empty compliance
value emits none of the `aws_config_*` or `aws_securityhub_*` resources.

### Opting out of the baseline

The opt-out is an operator action on the emitted root, after Generate and before
`terraform apply`. It has three steps, and all three are needed — the first alone leaves a
root that does not plan:

1. **In `terraform/baseline.tf`, delete everything outside the
   `########## Remote State` / `########## End Remote State` markers** — the header, the
   `locals` block, the always-on resources, and the whole
   `########## Compliance-Conditional` … `########## End Compliance-Conditional` section
   when present (its Config bucket lifecycle reads `local.cloudtrail_retention_days`, so
   leaving it behind without the `locals` block does not plan, and leaving it behind at all
   is not an opt-out). Keep only the Remote State section: `main.tf`'s active S3 backend
   and the README bootstrap both depend on `aws_s3_bucket.tfstate` and
   `aws_dynamodb_table.tfstate_lock`, and nothing else declares them. Deleting the whole
   file removes the backend's producers.
2. **Remove `operations_email`, `billing_email`, and `security_email`** from
   `variables.tf` and their rows from `terraform.tfvars.example`. They have no defaults,
   so left in place `terraform plan` fails on them even though nothing references them;
   they are referenced only from `baseline.tf`, so removing them leaves no dangling
   `var.*`.
3. **Leave `main.tf`, `variables.tf`'s other inputs, and the domain files untouched.**
   `data.aws_partition.current` stays in `main.tf` whether or not Config is emitted.

Write this procedure, as three numbered steps, into `terraform/README.md` next to the
bootstrap section; `generate-artifacts-docs.md` points the runbook's Prerequisites at it.
The emitter keeps the procedure valid by construction: the Remote State section is
self-contained and is always the last section of the file, after the compliance-conditional
section when one exists (items 6–7), and the three contact variables are referenced only
inside `baseline.tf` (Step 2) — never from `security.tf`, a domain file, or an output.

## Step 2: variables.tf + tfvars.example + .gitignore

- **Global vars (always):** `aws_region` (from `preferences.json` target region),
  `project_name`, `environment`, `migration_id`, and the fill-once contacts
  `operations_email`, `billing_email`, `security_email` (`type = string`, **no default**).
  Put all three in `terraform.tfvars.example` with `example.com` placeholders so the
  placeholder guard below rejects them at plan. Reference the three **only from
  `baseline.tf`** (alternate contacts, budget subscriber) — never from a domain file or an
  output — so the opt-out in Step 1.5 can remove them without leaving a dangling `var.*`.
- **Per-service vars:** extract configurable values from each service's `aws_config`
  (instance classes, sizes, engine versions, capacities). Infer types; use `aws_config`
  values as defaults; deduplicate shared vars. Annotate each with its Azure source as a
  comment, e.g. `# Azure source: Standard_D2s_v3 (Microsoft.DBforPostgreSQL/flexibleServers)`.
- **Placeholder guards (REQUIRED):** every variable that ships a placeholder in
  `terraform.tfvars.example` and whose value cannot be inferred MUST carry a `validation`
  block rejecting the placeholder token (`TODO`, `ACCOUNT_ID`, `<`, `example.com`), so the
  failure happens loudly at `terraform plan` with a message naming the tfvars key. This is
  the azure-specific fill-once set: any DB admin credential is a Secrets Manager reference,
  never a variable default.
- Emit `terraform.tfvars.example` (one line per variable, source-annotated, descriptive
  placeholders — never empty) and `.gitignore` (`terraform.tfvars`, `*.tfvars`,
  `!terraform.tfvars.example`, `.terraform/`, `*.tfstate*`).

## Step 3: Per-domain .tf files

### Step 3.0 — Apply AWS authoring posture (before writing)

**Before generating any `.tf`, invoke the `tf-best-practices` skill** for its authoring
posture — it is the single source of truth for "what good AWS Terraform looks like."
Treat it as a **black box**: tell it you are about to author `terraform/` (the
authoring/pre-generation context), pass the caller context below, and emit Terraform
that satisfies whatever posture it returns. Do NOT reach into its files.

Caller context to pass:

- **`compliance`** — `preferences.json` → `design_constraints.compliance` (array; may be
  empty/absent). `[]`, absent, and `["none"]` ⇒ no compliance-conditional hardening.
  `["unknown"]` ⇒ same catalog as none, plus the report caveat. Named frameworks ⇒
  hardening from `tf-best-practices`.
- **`aws_config` values** — instance classes, CPU/memory, storage, engine versions per
  service. The posture constrains shape, not numbers.

### Step 3.1 — azure-source glue (NOT AWS posture)

For each domain with services in the manifest, populate resource attributes from
`aws_config` and apply these azure-specific rules the skill cannot own:

- **Confidence comments:** `confidence: inferred` → `# Tailored to your setup — verify
  (JSON confidence: inferred)`; `deterministic` → optional `# Standard pairing`.
- **CPU architecture:** read `aws-design.json` `cpu_architecture` (azure default is
  **x86_64**, not Graviton — Windows/.NET fleets). `cpu_architecture` governs **COMPUTE
  ONLY** (ECS/Lambda/EC2/EKS/Elastic Beanstalk). Emit x86 instance/compute classes and, on
  compute, an inline note citing the x86 rationale. Only emit ARM64 (`arm64` Lambda,
  `ARM64` ECS `runtime_platform`, Graviton instance types) when the design explicitly set
  Graviton as an optimization.
  - **Managed DB/cache default to Graviton regardless of `cpu_architecture`; the x86 opt-out
    does NOT propagate to database/cache.** Emit the exact Graviton class the design/estimate
    chose (e.g. `db.m6g.large`, `cache.t4g.*`) so generate == estimate == design — never
    rewrite a managed RDS/Aurora/ElastiCache class to x86 because the fleet opted out. This is
    the shared graviton limitation (Graviton on managed DB/cache has no compatibility risk, so
    the opt-out is a consistency choice that stops at compute), matching gcp.
- **App Service Plan fan-in (critical):** one `Microsoft.Web/serverfarms` maps to ONE
  compute target (one `aws_elastic_beanstalk_environment` or one Fargate service), sized
  from the PLAN's SKU + instance count — NOT one per web app. Each `Microsoft.Web/sites`
  folded into the plan contributes its runtime + app settings to that single target's
  configuration; it emits **no** compute resource of its own. Never multiply compute by
  the app count. (This is why the fan-in fold happened in Design; honor it here.)
- **Secrets:** a Key Vault secret becomes an `aws_secretsmanager_secret` +
  `aws_secretsmanager_secret_version` whose value is a placeholder/`var` reference or a
  `# fill in Secrets Manager` note — **never** the source secret value. A Key Vault _key_
  becomes a `aws_kms_key`. App settings that referenced a Key Vault secret reference the
  Secrets Manager ARN.
- **Storage:** a Blob Storage container/account becomes an `aws_s3_bucket` emitted per the
  skill's posture. **Every** emitted `aws_s3_bucket` gets a matching
  `aws_s3_bucket_versioning` set to `Enabled`, PLUS server-side encryption
  (`aws_s3_bucket_server_side_encryption_configuration`) and an
  `aws_s3_bucket_public_access_block` (all four flags `true`) — and CloudFront/OAC for a
  public bucket, compliance-conditional access logging. Never emit a bare `aws_s3_bucket`
  without its versioning/SSE/public-access-block companions. Populate bucket names/lifecycle
  from design.
- **Availability:** read `preferences.json` `data.availability`. `multi-az-ha` /
  `multi-region` → Aurora (or Multi-AZ RDS) per the design; `single-az` → single-AZ RDS.
  Do not upgrade beyond what the design chose.
- **Elastic Beanstalk** (App Service → EB): emit one `aws_elastic_beanstalk_application`
  and one `aws_elastic_beanstalk_environment`, resolving `solution_stack_name` with a
  `data "aws_elastic_beanstalk_solution_stack"` source (do not paste a human-readable
  platform label). Emit the EB instance profile it references (`aws_iam_role` +
  `aws_iam_instance_profile` + an `aws_iam_role_policy_attachment` whose `policy_arn` is
  `"arn:${data.aws_partition.current.partition}:iam::aws:policy/AWSElasticBeanstalkWebTier"`
  — partition-derived like the Config role in Step 1.5, never a literal `arn:aws:`, so a
  `fedramp` App Service design resolves to `arn:aws-us-gov:`). Emit `setting` blocks for
  IamInstanceProfile, SecurityGroups, InstanceType, EnvironmentType, VPCId/Subnets, and
  (LoadBalanced) `LoadBalancerType = application`.
- **Networking:** emit VPC/subnets/SGs from the design; wire an ALB only if the design has
  a public edge (App Gateway / Front Door / public LB). **Do not double-count** an ALB the
  EB environment already provisions — the double-balancer trap.
- **Tag every resource:** Project, Environment, ManagedBy, MigrationId.

## Step 4: outputs.tf

Output identifiers for key resources (VPC ID, DB endpoint, EB env URL, EKS cluster name)
plus a **`migration_summary`** object with at least: `aws_region`, `environment`,
`migration_id`, `service_count` (resources actually emitted in this `terraform/`),
`accounted_count` (= `generation-warnings.json.accounted`: generated + deferred +
skipped/folded — the SAME figure the report body states, so the Terraform summary, the
report body, and `generation-warnings.json` all agree), `aligned_with_estimate_tier` =
`"balanced"`, `cost_scenarios_modeled_in_terraform` = `"design_baseline_only"`.
Description on every output.

## Step 5: Self-check

- [ ] No default-VPC references; all resources use the created VPC.
- [ ] No secret VALUE from the inventory in any `.tf`; secrets are Secrets Manager refs.
- [ ] No leftover `{{VARIABLE}}` tokens; user-supplied values are `var.*` with validation.
- [ ] Every variable has `type` + `description`; every output has `description`.
- [ ] Region from `var.aws_region`, never hardcoded.
- [ ] Exactly ONE compute target per App Service Plan (fan-in honored).
- [ ] Every `aws_s3_bucket` has a matching `aws_s3_bucket_versioning` (Enabled), SSE, and
      public-access-block resource — no bare bucket.
- [ ] `terraform/README.md` exists with the cost-tier vs Terraform note.
- [ ] `main.tf` begins with the Balanced-alignment header block.
- [ ] `baseline.tf` exists even when `aws-design.json` has no infrastructure clusters.
- [ ] `baseline.tf` contains `aws_account_alternate_contact` for OPERATIONS, BILLING, and
      SECURITY, plus `aws_iam_account_password_policy`, `aws_s3_account_public_access_block`,
      `aws_ebs_encryption_by_default`, `aws_cloudtrail`, `aws_guardduty_detector`,
      `aws_accessanalyzer_analyzer`, `aws_ec2_instance_metadata_defaults`,
      `aws_budgets_budget`, `aws_s3_bucket.tfstate`, and `aws_dynamodb_table.tfstate_lock`.
- [ ] `cloudtrail_retention_days` is a positive integer, and the CloudTrail log lifecycle
      expiration equals `local.cloudtrail_retention_days`.
- [ ] `aws_budgets_budget.monthly_spend.limit_amount` equals
      `max(50, ceil(projected_costs.aws_monthly_balanced * 1.2))` as a string.
- [ ] When compliance contains soc2, pci, hipaa, or fedramp, `baseline.tf` contains the
      Config recorder, delivery channel, recorder status, Security Hub account, and the
      FSBP standards subscription. PCI adds the PCI DSS subscription. No `nist-800-53`
      subscription. Empty compliance, `none`, or only `gdpr` emits no `aws_config_*` or
      `aws_securityhub_*` resources.
- [ ] `baseline.tf` does not contain invented control IDs (`ACCT.IAM`, `ACCT.S3`,
      `ACCT.EBS`, `ACCT.CT`, `ACCT.GD`, `ACCT.CFG`, `ACCT.SH`, `WKLD.EC2.01`) and does not
      mention Trusted Advisor.
- [ ] The state bucket and lock table are not also declared in `security.tf`.
- [ ] The opt-out holds by construction: `baseline.tf`'s remote-state resources sit inside
      the `########## Remote State` / `########## End Remote State` markers, that section is
      the last thing in the file (the `########## End Compliance-Conditional ##########`
      marker, when present, precedes `########## Remote State`; nothing follows
      `########## End Remote State ##########`), and the section references neither
      `local.baseline_tags`, `local.cloudtrail_retention_days`, nor any `var.*_email`;
      `var.operations_email`,
      `var.billing_email`, and `var.security_email` appear in no file other than
      `baseline.tf` (and their declarations in `variables.tf`); `terraform/README.md`
      carries the three-step opt-out next to the bootstrap section.
- [ ] `main.tf` declares `data "aws_partition" "current"`, and no `.tf` file contains a
      literal `arn:aws:` for an AWS-managed policy — the Config role attachment reads
      `arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWS_ConfigRole`
      and the Elastic Beanstalk instance-profile attachment, when emitted, reads
      `arn:${data.aws_partition.current.partition}:iam::aws:policy/AWSElasticBeanstalkWebTier`.
- [ ] When `aws-design.json` `services[]` is empty (every resource deferred or skipped), the
      output is the core files plus `baseline.tf`, `aws_budgets_budget.monthly_spend` is
      `"50"` (Balanced total is 0), and no domain file was invented.

## Step 6: Validation is the orchestrator's job (main window) — NOT this worker

This fragment (and the whole Generate phase WORK) runs in the file-only `rw` worker,
which cannot invoke skills or run `terraform`/`python`. So this worker emits `terraform/`
**only**: it does NOT invoke the `tf-best-practices` policy gate, does NOT pin any verdict
path, and does NOT write `validation-report.json`. The orchestrator (`generate.md`, main
window) owns Terraform validation, the policy gate, and the single canonical
`$MIGRATION_DIR/validation-report.json` write after the worker returns — passing only the
terraform DIR to the skill and merging the policy verdict into the report as
`policy_status`. See `generate.md` § "Step: Run the phase" step 4.

## Phase completion

Report generated files to the parent orchestrator. **Do NOT update `.phase-status.json`**
— `generate.md` handles phase completion. The assembler proves nothing was dropped.

## Status — implemented (build step: Generate)

Emitters implemented, following gcp-to-aws's `generate-artifacts-infra.md` structure
adapted to azure artifacts: generation manifest, main/variables/outputs core files with
placeholder-guard validation, `baseline.tf` (always, including a design with no
infrastructure clusters or an empty `services[]`; partition-derived Config policy ARN; a
self-contained Remote State section and a three-step opt-out that leaves a usable root),
per-domain files via `aws_config`, App Service Plan fan-in,
Secrets Manager references, x86 default, and the `tf-best-practices` authoring hand-off
(Step 3.0). Post-write validation, the policy gate, and the `validation-report.json` write
now live in the orchestrator (`generate.md`, main window), not this worker fragment — the
`rw` worker cannot invoke skills or run terraform/python. The `tf-best-practices`
invocation is by contract; verify it is installed alongside this skill.
