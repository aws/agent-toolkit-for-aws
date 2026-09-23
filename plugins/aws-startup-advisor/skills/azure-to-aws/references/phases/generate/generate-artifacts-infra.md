---
_fragment: artifacts-infra
_of_phase: generate
_contributes:
  - terraform/main.tf
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
  `aws_config`, `confidence`, `azure_type`), `clusters[]` (workload grouping + tier),
  `deferred[]`, `target_region`, `cpu_architecture`.
- `preferences.json` (REQUIRED) — `design_constraints`, `data.availability`, licensing,
  identity, environment/region.
- `estimation-infra.json` (REQUIRED) — for the budget limit and the cost-tier README note.
- `azure-resource-inventory.json` (REQUIRED) — source `config` for attribute population and
  the module/naming provenance (`config.tf_module`, `config.tf_address`).

If any REQUIRED file is missing: **STOP** — "Missing required artifact: [filename]."

## Output structure

Generate `$MIGRATION_DIR/terraform/`, emitting only the domain files for domains that
have services in `aws-design.json`:

| File                       | Domain     | Contains                                                            |
| -------------------------- | ---------- | ------------------------------------------------------------------- |
| `main.tf`                  | core       | provider, S3 backend, data sources, cost-tier header                |
| `variables.tf`             | core       | all input variables (types, defaults, placeholder-guard validation) |
| `outputs.tf`               | core       | key resource outputs + `migration_summary`                          |
| `.gitignore`               | core       | tfstate/tfvars ignores                                              |
| `terraform.tfvars.example` | core       | one entry per variable, source-annotated                            |
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
  with `# TODO` substitution comments; the state bucket + lock table are emitted in
  `security.tf`, and README documents the two-step `init -backend=false` bootstrap).
- `provider "aws"`: `region = var.aws_region`, `default_tags` with Project,
  Environment, ManagedBy, MigrationId.
- Data sources: `aws_caller_identity`, `aws_region`, `aws_availability_zones`.

## Step 2: variables.tf + tfvars.example + .gitignore

- **Global vars (always):** `aws_region` (from `preferences.json` target region),
  `project_name`, `environment`, `migration_id`.
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
  `aws_iam_instance_profile` + `AWSElasticBeanstalkWebTier`). Emit `setting` blocks for
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
placeholder-guard validation, per-domain files via `aws_config`, App Service Plan fan-in,
Secrets Manager references, x86 default, and the `tf-best-practices` authoring hand-off
(Step 3.0). Post-write validation, the policy gate, and the `validation-report.json` write
now live in the orchestrator (`generate.md`, main window), not this worker fragment — the
`rw` worker cannot invoke skills or run terraform/python. The `tf-best-practices`
invocation is by contract; verify it is installed alongside this skill.
