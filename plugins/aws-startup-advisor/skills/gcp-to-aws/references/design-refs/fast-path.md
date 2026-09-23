# Fast-Path: Direct GCP→AWS Mappings

**Confidence: `deterministic`** (1:1 mapping, no rubric evaluation needed)

## What `deterministic` vs `inferred` means

Use these labels **only** as defined here — they describe _how the mapping was chosen_, not whether the AWS architecture is "obvious."

| Label                  | Meaning                                                                                                                                                                                                                                                                               |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`deterministic`**    | The GCP **Terraform resource type** appears in the **Direct Mappings** table below, the row's **Conditions** are satisfied, and the AWS target is taken from that row. **No** 6-criteria rubric is run for that mapping.                                                              |
| **`inferred`**         | The resource type is **not** in Direct Mappings (or BigQuery / specialist gate applies). The agent loads the category file from `design-refs/index.md`, runs eliminators and the **6-criteria rubric** (and may apply **Preferred AWS Target Services**), then picks the AWS service. |
| **`billing_inferred`** | Billing-only design path: mappings from billing SKUs/service names — see `references/phases/design/design-billing.md`.                                                                                                                                                                |

### User-facing vocabulary (chat, MIGRATION_GUIDE, migration-report)

JSON artifacts **must** keep the `confidence` string values above. When speaking or writing **for end users**, lead with plain English — do **not** use "deterministic," "inferred," or "rubric" as the primary label unless the user asks for technical detail.

| JSON `confidence`  | Say this to users               | Optional one-line hint                                                                                                                              |
| ------------------ | ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `deterministic`    | **Standard pairing**            | Same AWS target for this GCP resource type whenever it matches our fixed list — quick to sanity-check.                                              |
| `inferred`         | **Tailored to your setup**      | Based on your Terraform configuration, how the resource fits the rest of your stack, and your migration preferences — review again if those change. |
| `billing_inferred` | **Estimated from billing only** | From GCP spend line items without full infrastructure detail — add Terraform for a tighter mapping.                                                 |

**BigQuery / specialist gate** rows still store `confidence: "inferred"` in JSON; in user-facing text you may say **Tailored to your setup** and emphasize **specialist engagement** (no automated AWS analytics target).

**Canonical reference:** This subsection — other phase files should point here instead of redefining wording.

**Common confusion:** `references/design-refs/index.md` lists a **typical AWS target** per GCP service. That is not automatically the same as **`deterministic`**. Confidence is `deterministic` only when the exact Terraform resource type appears in the Direct Mappings table above and its conditions are met; otherwise confidence is `inferred` via rubric evaluation.

**Add-ons (ALB, NAT, etc.):** A row may say "Fargate" while the architecture diagram also includes an **ALB** or **NAT Gateway** from **other** Terraform resources. Confidence is still per **resource row** — e.g. `google_cloud_run_service` = `inferred`; `google_compute_forwarding_rule` + backend = often `inferred` (see `networking.md`).

---

**Direct Mappings use confidence: `deterministic`** (fixed table lookup — no rubric for that resource)

## Direct Mappings Table

| GCP Service                                 | AWS Service          | Conditions                                                                   | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------- | -------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `google_storage_bucket`                     | S3                   | Always                                                                       | 1:1 mapping; preserve ACL/versioning/lifecycle rules                                                                                                                                                                                                                                                                                                                                                                                                            |
| `google_cloud_run_service`                  | Fargate              | Always                                                                       | Preferred container runtime target                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `google_cloud_run_v2_service`               | Fargate              | Always                                                                       | v2 API variant of Cloud Run                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `google_cloudfunctions_function`            | Lambda               | Always                                                                       | Gen 1 function mapping                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `google_cloudfunctions2_function`           | Lambda               | Always                                                                       | Gen 2 function mapping                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `google_sql_database_instance` (SQL Server) | RDS SQL Server       | Always                                                                       | Always provisioned (no serverless)                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `google_compute_network`                    | VPC                  | Always                                                                       | 1:1; preserve CIDR ranges                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `google_compute_firewall`                   | Security Group       | Always                                                                       | 1:1 rule mapping; adjust CIDR if needed                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `google_dns_managed_zone`                   | Route 53 Hosted Zone | Always                                                                       | Preserve zone name and records                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `google_service_account`                    | IAM Role             | Always                                                                       | Map permissions directly; adjust service principals                                                                                                                                                                                                                                                                                                                                                                                                             |
| `google_secret_manager_secret`              | Secrets Manager      | Always                                                                       | Create secret metadata and IAM-scoped access                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `google_secret_manager_secret_version`      | Secrets Manager      | Always                                                                       | Carry current value or explicit migration TODO                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `google_redis_instance`                     | ElastiCache Redis    | Always                                                                       | 1:1 mapping; preserve cluster mode and node type                                                                                                                                                                                                                                                                                                                                                                                                                |
| `google_app_engine_application`             | Elastic Beanstalk    | (`compute_model` absent or `"managed_platform"`) **and** `compute` ≠ `"eks"` | PaaS-to-PaaS. One EB environment **per App Engine service**; read `runtime`/`instance_class`/scaling from the `*_app_version` resources (see `elastic-beanstalk.md`). If `compute_model: "container_orchestration"` or `"serverless"`, use rubric in `compute.md` (confidence: `inferred`). If `compute: "eks"` (Q5 = multi-cloud), the row does not match — App Engine follows the container path to **EKS** via the rubric, same portability override as GKE. |

### Cloud SQL PostgreSQL / MySQL — NOT in Direct Mappings

**Do not** assign `google_sql_database_instance` (PostgreSQL or MySQL) from this table. Always use **Pass 2** + `database.md` rubric with confidence = **`inferred`**.

**Q6 (`design_constraints.availability`) is the only selector for RDS vs Aurora:**

| `availability` value | AWS target (match engine from GCP)                 |
| -------------------- | -------------------------------------------------- |
| `single-az`          | **RDS PostgreSQL** or **RDS MySQL**                |
| `multi-az`           | **RDS PostgreSQL** or **RDS MySQL** Multi-AZ       |
| `multi-az-ha`        | **Aurora PostgreSQL** or **Aurora MySQL** Multi-AZ |
| `multi-region`       | **Aurora Global Database** (engine per GCP)        |

Q12 (traffic) and Q13 (I/O) tune sizing and storage **within** the family Q6 chose — they never upgrade Inconvenient/Significant Issue workloads to Aurora.

## Skip Mappings Table

These GCP resources do **not** require AWS equivalents in v1.0:

| GCP Service                              | Reason                                                                                                                                                                                                                              |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `google_project`                         | AWS account structure (manual, not IaC)                                                                                                                                                                                             |
| `google_monitoring_*`                    | Fallback to CloudWatch (managed)                                                                                                                                                                                                    |
| `google_logging_*`                       | Fallback to CloudWatch Logs (managed)                                                                                                                                                                                               |
| `google_compute_address`                 | Elastic IPs managed by ALB/NAT (not standalone)                                                                                                                                                                                     |
| `google_identity_platform_*`             | Auth provider — keep existing solution, do not migrate to AWS Cognito or any AWS auth                                                                                                                                               |
| `google_firebase_auth_*`                 | Auth provider — keep existing solution, do not migrate to AWS Cognito or any AWS auth                                                                                                                                               |
| `google_app_engine_standard_app_version` | **Config source, not a standalone target.** Carries `runtime`/`instance_class`/scaling/`env_variables` that feed the parent's App Engine → Elastic Beanstalk mapping (see note below). Skip as its own resource; log to `warnings`. |
| `google_app_engine_flexible_app_version` | **Config source, not a standalone target.** Same as the standard variant (Flexible uses `resources` + `flexible_runtime_settings`). Skip as its own resource; log to `warnings`.                                                    |

**Note — App Engine app_version resources are config sources for the EB mapping.** `google_app_engine_standard_app_version` and `google_app_engine_flexible_app_version` are skipped as standalone resources (above), **but their config is read** to build the parent's mapping: `runtime`, `instance_class`, `env_variables`, and scaling live on the _version_ resource, not on the parent `google_app_engine_application`. Discovery classifies them SECONDARY (`configuration`); because they link to the parent only by shared `project` (no ID reference), `serves[]` may be empty and they may cluster separately, so the **App Engine fan-out** step in `phases/design/design-infra.md` locates them by scanning the full inventory and emits **one EB environment per App Engine service** (grouping multiple versions of a service into one), so a multi-service app does not collapse into a single mapping. On the non-EB paths (Q7b container-orchestration/serverless, `compute: "eks"` multi-cloud, ambiguous attribution, or no parent) they are simply skipped like any other Skip Mapping — logged to `warnings`, never sent through the rubric or the unknown-type STOP. See `elastic-beanstalk.md` → "Where the config comes from (Terraform)".

## Preferred AWS Target Services

For the workload categories below, always steer toward the **preferred** AWS service. If rubric evaluation or LLM reasoning would select a non-preferred service, substitute the preferred alternative instead.

| Workload Category       | Preferred AWS Target                                                                                        | Rationale                                                                                  |
| ----------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Containerized workloads | Fargate (default), Lambda (event-driven), EKS (K8s required)                                                | Deeper integration with VPC, ALB, IAM, and auto-scaling than lighter-weight alternatives   |
| PaaS / managed platform | Elastic Beanstalk — **only when `compute_model` is absent or `"managed_platform"` and `compute` ≠ `"eks"`** | Preserves managed platform model; AWS manages deployments, scaling, patching, monitoring   |
| Third-party auth in use | Keep existing auth provider                                                                                 | Startups using Auth0, Firebase Auth, Clerk, etc. should preserve their existing investment |

**Enforcement:** Check every resource mapping against this table before writing to `aws-design.json` or `aws-design-billing.json`. If a mapping would select a non-preferred service, substitute the preferred alternative.

**Enforcement exemption (App Engine + explicit compute_model):** When the user set `compute_model: "container_orchestration"` or `"serverless"` (Q7b = B/C), the App Engine eliminator in `compute.md` intentionally routes the resource to Fargate/Lambda. **Do not** apply the PaaS row to re-substitute Elastic Beanstalk in that case — the PaaS row's condition (`compute_model` absent or `"managed_platform"`) is already false, so it does not match. This mirrors how Cloud Run is exempt (always Containerized) and Cloud SQL is exempt (Q6 governs RDS-vs-Aurora).

**Enforcement exemption (App Engine + `compute: "eks"` / Q5 = multi-cloud):** When `compute: "eks"` is set (Q5 = multi-cloud), Q7b does not fire and App Engine routes to **EKS** via the container path (see `compute.md` App Engine section). **Do not** apply the PaaS row to re-substitute Elastic Beanstalk in that case — the PaaS row's condition (`compute` ≠ `"eks"`) is already false, so it does not match. This is the same top-level portability override that forces GKE to EKS.

**Precedence:** Match resources to the **first applicable row**. Cloud Run matches "Containerized workloads" regardless of `compute_model`. The "PaaS / managed platform" row applies to App Engine resources **only when its `compute_model` condition holds** (absent or `"managed_platform"`) **and `compute` ≠ `"eks"`**; an App Engine resource with `compute_model: "container_orchestration"`/`"serverless"` — or with `compute: "eks"` (multi-cloud) — matches no row here and keeps its rubric-selected target (Fargate/Lambda, or EKS under multi-cloud).

**Exception:** For Cloud SQL PostgreSQL/MySQL, **Q6 availability always overrides** any implicit Aurora preference. Do not substitute Aurora when `availability` is `single-az` or `multi-az`.

## Secondary Behavior Lookups

For resources in the Skip Mappings table but present in inventory:

1. Log as "secondary resource, no AWS equivalent needed"
2. Do not include in aws-design.json
3. Note in aws-design.json warnings array

---

**Workflow:**

1. Extract GCP resource type
2. Look up in Direct Mappings table
3. If found and condition met: assign AWS service (confidence = deterministic)
4. If `google_sql_database_instance` (PostgreSQL/MySQL): skip Direct Mappings → apply `database.md` rubric (confidence = inferred)
5. If found in Skip Mappings: skip it (confidence = n/a)
6. If not found: use `design-refs/index.md` to determine category → apply rubric in that category's file
