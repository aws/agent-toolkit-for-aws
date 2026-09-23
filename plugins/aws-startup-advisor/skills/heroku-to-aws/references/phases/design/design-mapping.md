---
_fragment: mapping-engine
_of_phase: design
_contributes:
  - aws-design.json
---

# Design Phase: Mapping Engine

> Self-contained mapping sub-file (the always-on path). Validates prerequisites,
> initializes the design structure, performs the single-pass resource mapping
> (Elastic Beanstalk/Fargate/RDS/ElastiCache/MSK/fast-path/deferred), designs the VPC + security
> groups, and adds Cedar/Fir notation + metadata. When the compute target preference
> selects EKS, formation mapping is handled by `design-eks.md` instead of the
> EB/Fargate branches below. The final artifact write, output checks, handoff gate, and
> phase-status update are owned by the assembler (`design-assemble.md`).

**Execute ALL steps in order. Do not skip or deviate.**

---

## Step 0: Validate Prerequisites

The entry gate (clarify completed, single active phase, inputs present + valid JSON) is
enforced by this phase's `_preconditions` frontmatter per `INTERPRETER.md` § Gate
protocol; proceed once it passes.

---

## Step 1: Initialize Design Output Structure

Create the `aws-design.json` output structure in memory:

```json
{
  "phase": "design",
  "design_source": "<discovery_source from inventory metadata>",
  "timestamp": "<current ISO 8601>",
  "metadata": {
    "total_services": 0,
    "total_apps_migrated": 0,
    "fir_workloads_detected": [],
    "fir_generation_note": ""
  },
  "services": [],
  "deferred": [],
  "warnings": [],
  "vpc_design": {}
}
```

Extract from `preferences.json`:

- `global.target_region` → used as `region` for all designed services
- `global.availability` → drives RDS vs Aurora and HA decisions
- `data.database_ha` → overrides availability for database specifically (if present)
- `data.redis_ha` → Redis HA configuration
- `operational.log_retention_days` → CloudWatch log retention
- `operational.cost_optimization` → narrative bias only in v1 (conservative/balanced/aggressive); does not invent instance sizes outside the sizing tables
- `workshop.cpu_architecture` → `"x86_64"` (default when absent) or `"arm64"` (Graviton-capable classes where tables provide them)

### CPU architecture resolution (workshop)

Resolve once before mapping formations:

1. `cpu_architecture` = `preferences.workshop.cpu_architecture` if set, else `"x86_64"`.
2. When `"arm64"`:
   - **Elastic Beanstalk**: use `ec2_instance_type_arm64` from the matched `dyno-eb-sizing.json` row when present; else use `ec2_instance_type` and append warning `architecture_fallback_x86` naming the formation.
   - **Fargate**: set `aws_config.cpu_architecture` to `"ARM64"` (task size from `dyno-fargate-sizing.json` unchanged — Fargate ARM is a runtime arch flag). Prefer Estimate rates `fargate.per_vcpu_hour_arm64` / `per_gb_mem_hour_arm64` when present.
   - **EKS**: use `node_type_arm64` from `eks-pod-sizing.json` when present; else `node_type` + `architecture_fallback_x86` warning.
   - **RDS / ElastiCache**: sizing tables already emit Graviton classes (`db.t4g.*`, `db.m6g.*`, `cache.t4g.*`, etc.) — leave as-is. Do not invent non-table classes.
3. When `"x86_64"`: use the default x86 columns (`ec2_instance_type`, `node_type`); for Fargate set `aws_config.cpu_architecture` to `"X86_64"` or omit (platform default).
4. Never invent instance types or rates. Honest fallback + warning only.

---

## Step 2: Single-Pass Resource Mapping

Process each resource in `heroku-resource-inventory.json`.resources[] in **input order**. For each resource, determine its `resource_type` and route to the appropriate mapping logic below.

**Processing order is deterministic**: first resource in → first mapping out. No reordering, no multi-pass.

---

### 2A: Formation Mapping (Elastic Beanstalk, Fargate, or EKS)

**Trigger**: `resource_type == "formation"`

**Prerequisites**:

- Read `preferences.json → design_constraints.compute_target`.
- Resolve `global_compute_target` as `compute_target.default` when present, else legacy `compute_target.value`, else `"elastic_beanstalk"`.
- Read `compute_target.overrides[]` when present. For each formation, an override matches when `override.formation` equals the resource's `resource_id`, `{heroku_app}:{process_type}`, or `{process_type}`.
- Resolve `formation_compute_target` for each formation as the matching override value when present, else `global_compute_target`.
- If `formation_compute_target` is absent or `"elastic_beanstalk"`: use `dyno-eb-sizing.json` and follow the Elastic Beanstalk mapping below, except persistent non-web formations with `quantity > 1` MUST resolve to Fargate for that formation to preserve horizontal worker capacity.
- If `formation_compute_target` is `"ecs-fargate"`: use `dyno-fargate-sizing.json` and follow the Fargate mapping below.
- If `global_compute_target` is `"eks-managed"` or `"eks-or-ecs"`: use `eks-pod-sizing.json` and load `phases/design/design-eks.md`. Follow the EKS branch logic in `design-eks.md` for ALL formations. Skip the EB/Fargate mapping below. Per-formation EKS overrides are not supported in v1; EKS remains a global compute target.

#### EKS Branch

When `global_compute_target` is `"eks-managed"` or `"eks-or-ecs"`, load and follow `references/phases/design/design-eks.md`. That file contains the complete EKS mapping logic. ALL formations are mapped to EKS. Return here after EKS mapping is complete (skip the EB/Fargate logic below).

**Fir intent precedence**: If `preferences.operational.fir_intent` is `"self_managed_eks_ecs"` AND `global_compute_target` is not an EKS value, the Fir intent does NOT automatically enable EKS for all formations. The Fir intent is compute-destination-only for Fir workloads and is handled as a deferred notation (no Terraform generation for Fir in v1). The resolved compute target plan takes precedence for non-Fir formations.

#### Release Process Check

Before mapping any non-EKS formation, extract `config.process_type`. If `process_type == "release"`, do NOT map it to persistent compute. Heroku release-phase commands are run-once deployment hooks (for example database migrations) and must exit. Add a warning:

> "Heroku release process `{heroku_app}:release` is a run-once deployment hook and was not mapped to persistent AWS compute. Implement it as a deployment hook or manual migration step."

Continue to the next resource.

#### Horizontal Non-Web Capacity Guard for EB Default

Before following the Elastic Beanstalk branch, extract `config.quantity` and `config.process_type`. If `formation_compute_target` is absent or `"elastic_beanstalk"`, AND `process_type != "web"`, AND `config.quantity > 1`, do NOT emit an EB SingleInstance environment for that formation. Follow the Fargate branch below for that formation and append warning:

> "Heroku formation `{heroku_app}:{process_type}` has quantity={quantity}. EB SingleInstance environments cannot preserve horizontal capacity for persistent non-web dynos, so this formation was routed to Fargate. Set quantity=1 or choose manual EB handling only if one worker instance is acceptable."

Continue with the next resource after the Fargate entry is appended. This guard is both a safety net and the Design-side enforcement of Q12c `system_forced` Fargate overrides.

#### Elastic Beanstalk Branch (default)

**Mapping logic:**

1. Extract `config.dyno_type`, `config.quantity`, `config.process_type` from the resource.

2. **Empty Procfile check**: If there are NO formation resources in the entire inventory for this app, reject the input. Record in `warnings[]` and skip.

3. **Dyno type lookup**: Match `config.dyno_type` (case-insensitive) against the `dyno-eb-sizing.json` knowledge (`rows.<dyno_type>`).

   - **If NOT found**: Reject this formation entry. Add to `warnings[]`:

     > "Unsupported dyno type: `{dyno_type}`. Cannot map to Elastic Beanstalk. Please contact support or provide manual sizing."

     Do NOT produce an EB mapping for this formation. Continue to next resource.

   - **If found**: Extract the instance type using the CPU architecture
     resolution above (`ec2_instance_type_arm64` when `cpu_architecture` is
     `arm64` and the column exists; otherwise `ec2_instance_type`).

4. **Environment type and tier**:

   - If `process_type == "web"` → `tier: "WebServer"`, `environment_type: "LoadBalanced"`, `min_instances: 1`, `max_instances: max(config.quantity, 2)`.
   - All other persistent non-web process types (worker, clock, custom) → `tier: "WebServer"`, `environment_type: "SingleInstance"`, `min_instances: 1`, `max_instances: 1`.

   **Note:** EB Worker tier (SQS-based polling) is NOT used. Heroku workers are persistent processes (Sidekiq, Celery, background job runners) that maintain their own connections to queues/databases. They are NOT HTTP-triggered. Map them to SingleInstance WebServer environments where they run continuously as Docker containers.

5. **Produce Elastic Beanstalk service entry**:

   ```json
   {
     "service_id": "eb:{heroku_app}:{process_type}",
     "source_resource_id": "{resource_id}",
     "heroku_app": "{heroku_app}",
     "aws_service": "Elastic Beanstalk",
     "confidence": "deterministic",
     "aws_config": {
       "region": "{target_region}",
       "platform": "Docker running on 64bit Amazon Linux 2023",
       "instance_type": "<from table per CPU architecture resolution>",
       "cpu_architecture": "<x86_64|arm64 from preferences.workshop>",
       "environment_type": "<LoadBalanced for web, SingleInstance for non-web>",
       "tier": "WebServer",
       "min_instances": 1,
       "max_instances": <max(config.quantity, 2) for web; 1 for non-web>,
       "process_type": "{process_type}",
       "deployment_policy": "Rolling"
     }
   }
   ```

6. **Multi-instance non-web safety check**: The EB branch MUST NOT emit SingleInstance environments for persistent non-web formations with `quantity > 1`; those formations are routed to Fargate by the Horizontal Non-Web Capacity Guard above.

7. **No separate ALB entry**: EB LoadBalanced environments include ALB automatically. SingleInstance environments have no ALB. Do NOT produce separate ALB service entries for any EB environment.

8. Append to `services[]`. Increment `metadata.total_services`.

#### Fargate Branch (override)

**Mapping logic:**

1. Extract `config.dyno_type`, `config.quantity`, `config.process_type` from the resource.

2. **Empty Procfile check**: If there are NO formation resources in the entire inventory for this app (i.e., no process types declared), reject the input:

   > "No process types declared for app `{app_name}`. At least one process type is required in the Procfile."

   Record this in `warnings[]` and skip the app's formations.

3. **Dyno type lookup**: Match `config.dyno_type` (case-insensitive) against the `dyno-fargate-sizing.json` knowledge (`rows.<dyno_type>`).

   - **If NOT found**: Reject this formation entry. Add to `warnings[]`:

     > "Unsupported dyno type: `{dyno_type}`. Cannot map to Fargate. Please contact support or provide manual sizing."

     Do NOT produce a Fargate mapping for this formation. Continue to next resource.

   - **If found**: Extract `fargate_cpu` and `fargate_memory` from the matched row.

4. **Desired count**: Set `desired_count` = `config.quantity`. Valid range: 0–100. If outside range, clamp to nearest boundary and add a warning.

5. **Produce Fargate service entry**:

   ```json
   {
     "service_id": "fargate:{heroku_app}:{process_type}",
     "source_resource_id": "{resource_id}",
     "heroku_app": "{heroku_app}",
     "aws_service": "Fargate",
     "confidence": "deterministic",
     "aws_config": {
       "region": "{target_region}",
       "task_cpu": <fargate_cpu>,
       "task_memory": <fargate_memory>,
       "cpu_architecture": "<X86_64|ARM64 from preferences.workshop>",
       "desired_count": <desired_count>,
       "container_image": "placeholder:{heroku_app}-{process_type}",
       "process_type": "{process_type}",
       "load_balancer": <true if process_type == "web", false otherwise>
     }
   }
   ```

6. **ALB for web process types**: If `process_type == "web"`, produce an additional ALB entry:

   ```json
   {
     "service_id": "alb:{heroku_app}:{process_type}",
     "source_resource_id": "{resource_id}",
     "heroku_app": "{heroku_app}",
     "aws_service": "ALB",
     "confidence": "deterministic",
     "aws_config": {
       "region": "{target_region}",
       "scheme": "internet-facing",
       "target_group": "fargate:{heroku_app}:{process_type}"
     }
   }
   ```

   Non-web process types (worker, clock, custom) do NOT get an ALB. Release process types are skipped because they are run-once deployment hooks.

7. Append entries to `services[]`. Increment `metadata.total_services`.

---

### 2B: Postgres Mapping (RDS / Aurora)

**Trigger**: `resource_type == "addon"` AND `config.addon_service == "heroku-postgresql"`

**Prerequisites**: the `postgres-rds-sizing.json` knowledge (loaded per the phase's `_knowledge` `_when`).

**Mapping logic:**

1. Extract `config.plan`, `config.connection_pooling` from the resource.

2. **Plan lookup**: Match `config.plan` (case-insensitive) against the Postgres Plan Table.

   - **If NOT found**: Halt mapping for this add-on. Add to `warnings[]`:

     > "Unrecognized heroku-postgresql plan tier: `{plan}`. Cannot determine AWS sizing. Deferring to specialist engagement."

     Add a deferred entry (see Step 2F for format). Continue to next resource.

3. **Determine availability preference**:

   - Use `preferences.data.database_ha` if set; otherwise use `preferences.global.availability`.
   - **If unset or unrecognized value** (not one of: `single-az`, `multi-az`, `multi-az-ha`, `multi-region`):
     - Default to `multi-az`.
     - Add warning: "Availability preference unset or unrecognized. Defaulting to multi-az with RDS PostgreSQL."

4. **Service selection**:

   - `single-az` or `multi-az` → **RDS PostgreSQL** (use "Recommended RDS Instance Class" column)
   - `multi-az-ha` or `multi-region` → **Aurora PostgreSQL** (use "Recommended Aurora Instance Class" column)

5. **Instance class**: Read directly from the matched table row. The table already provides the minimum adequate instance class.

6. **Storage**: Read the Storage column from the matched row. Configure storage allocation ≥ this value.

7. **Multi-AZ deployment**: If availability is `multi-az`, `multi-az-ha`, or `multi-region`, set `multi_az: true`.

8. **Connection pooling → RDS Proxy**: If `config.connection_pooling == true`, set `rds_proxy: true`.

9. **Produce RDS/Aurora entry**:

   ```json
   {
     "service_id": "rds:{heroku_app}:postgres",
     "source_resource_id": "{resource_id}",
     "heroku_app": "{heroku_app}",
     "aws_service": "RDS PostgreSQL" | "Aurora PostgreSQL",
     "confidence": "deterministic",
     "aws_config": {
       "region": "{target_region}",
       "instance_class": "<from table>",
       "multi_az": <true|false>,
       "storage_gb": <from table, numeric>,
       "engine_version": "15",
       "rds_proxy": <true|false>
     }
   }
   ```

10. Append to `services[]`. Increment `metadata.total_services`.

---

### 2C: Redis Mapping (ElastiCache)

**Trigger**: `resource_type == "addon"` AND `config.addon_service == "heroku-redis"`

**Prerequisites**: the `redis-elasticache-sizing.json` knowledge (loaded per the phase's `_knowledge` `_when`).

**Mapping logic:**

1. Extract `config.plan`, `config.ha_enabled`, `config.encryption_in_transit`, `config.redis_version` from the resource.

2. **Plan lookup**: Match `config.plan` (case-insensitive) against the Redis Plan Table.

   - **If NOT found**: Report error. Add to `warnings[]`:

     > "Unrecognized heroku-redis plan tier: `{plan}`. Cannot determine ElastiCache node type. Deferring to specialist engagement."

     Add a deferred entry. Continue to next resource.

3. **Node type**: Read "Recommended ElastiCache Node Type" from the matched row.

4. **High availability**:

   - If the source plan HA column is "Yes" (or `config.ha_enabled == true`):
     - Set `multi_az: true`
     - Set `automatic_failover: true`
   - Otherwise:
     - Set `multi_az: false`
     - Set `automatic_failover: false`

5. **Engine version**: Use the source plan's Redis Version column. Select a compatible ElastiCache engine version (same major version). For example, source `7.0` → ElastiCache `7.0`.

6. **Encryption in-transit**: If `config.encryption_in_transit == true` (or table Encryption column is "Yes"), set `transit_encryption: true`.

7. **Produce ElastiCache entry**:

   ```json
   {
     "service_id": "elasticache:{heroku_app}:redis",
     "source_resource_id": "{resource_id}",
     "heroku_app": "{heroku_app}",
     "aws_service": "ElastiCache Redis",
     "confidence": "deterministic",
     "aws_config": {
       "region": "{target_region}",
       "node_type": "<from table>",
       "multi_az": <true|false>,
       "automatic_failover": <true|false>,
       "transit_encryption": <true|false>,
       "engine_version": "<compatible version>"
     }
   }
   ```

8. Append to `services[]`. Increment `metadata.total_services`.

---

### 2D: Kafka Mapping (MSK)

**Trigger**: `resource_type == "addon"` AND `config.addon_service == "heroku-kafka"`

**Prerequisites**: the `kafka-msk-sizing.json` knowledge (loaded per the phase's `_knowledge` `_when`).

**Mapping logic:**

1. Extract `config.plan` and topology fields (`config.topics`, `config.partitions`, `config.replication_factor`) from the resource. If topology fields are missing, use the table's Max Topics, Max Partitions, and default replication factor.

2. **Plan lookup**: Match `config.plan` (case-insensitive) against the Kafka Plan Table.

   - **If NOT found**: Report error. Add to `warnings[]`:

     > "Unrecognized heroku-kafka plan tier: `{plan}`. Cannot determine MSK broker instance type. Deferring to specialist engagement."

     Add a deferred entry. Continue to next resource.

3. **Broker instance type**: Read "Recommended MSK Broker Instance Type" from the matched row.

4. **Storage per broker**: Read "Recommended Storage Per Broker" from the matched row.

5. **Broker count and availability zones**:

   - Basic plans: minimum **2 brokers** across **2 AZs**.
   - Standard/Extended/Private plans: **3 brokers** across **3 AZs**.
   - Never fewer than 2 brokers or 2 AZs.

6. **Topology preservation**:

   - `max_topics`: From table row or `config.topics` (whichever is available).
   - `max_partitions`: From table row or `config.partitions`.
   - `replication_factor`: From `config.replication_factor` or table default (3 for standard/extended/private, 2 for basic).

7. **Produce MSK entry**:

   ```json
   {
     "service_id": "msk:{heroku_app}:kafka",
     "source_resource_id": "{resource_id}",
     "heroku_app": "{heroku_app}",
     "aws_service": "Amazon MSK",
     "confidence": "deterministic",
     "aws_config": {
       "region": "{target_region}",
       "broker_instance_type": "<from table>",
       "storage_per_broker_gb": <from table, numeric>,
       "broker_count": <2 or 3>,
       "availability_zones": <2 or 3>,
       "max_topics": <preserved>,
       "max_partitions": <preserved>,
       "replication_factor": <preserved>
     }
   }
   ```

8. Append to `services[]`. Increment `metadata.total_services`.

---

### 2E: Fast-Path Table Mapping (Other Add-Ons)

**Trigger**: `resource_type == "addon"` AND `config.addon_service` is NOT one of: `heroku-postgresql`, `heroku-redis`, `heroku-kafka`

**Prerequisites**: the `fast-path-addons.json` knowledge (loaded per the phase's `_knowledge` `_when`).

**Mapping logic:**

1. Extract `config.addon_service` (the add-on name to match).

2. **Normalize the add-on name** before matching. Terraform `heroku_addon` resources use a `plan` attribute in the format `service:plan-tier` (e.g., `"heroku-postgresql:standard-0"`, `"papertrail:choklad"`). The `addon_service` extracted from this is a lowercase slug. app.json and billing data may use display names. Apply this normalization:

   - Strip the `heroku-` prefix if present (e.g., `heroku-scheduler` → `scheduler`)
   - Replace hyphens with spaces (e.g., `bonsai-elasticsearch` → `bonsai elasticsearch`)
   - The match is then case-insensitive against the fast-path table

   **Common Terraform/app.json slug → display name mappings:**

   | Terraform/app.json Label | Normalized for Fast-Path Match |
   | ------------------------ | ------------------------------ |
   | `papertrail`             | `papertrail`                   |
   | `sendgrid`               | `sendgrid`                     |
   | `heroku-scheduler`       | `heroku scheduler`             |
   | `memcachier`             | `memcachier`                   |
   | `bucketeer`              | `bucketeer`                    |
   | `cloudamqp`              | `cloudamqp`                    |
   | `bonsai`                 | `bonsai elasticsearch` *       |
   | `scout`                  | `scout apm` *                  |
   | `rollbar`                | `rollbar`                      |
   | `newrelic`               | `new relic` *                  |
   | `twilio`                 | `twilio`                       |
   | `cloudinary`             | `cloudinary`                   |
   | `sentry`                 | `sentry`                       |

   \* These require special-case mapping because the Terraform/app.json slug differs from the display name. If the slug does not directly match after normalization, check if it is a known prefix of a fast-path entry (e.g., `bonsai` is a known prefix for `bonsai elasticsearch`). Known prefix mappings are:
   - `bonsai` → `bonsai elasticsearch`
   - `scout` → `scout apm`
   - `newrelic` or `new-relic` → `new relic`

3. **Exact case-insensitive match** the normalized name against the Fast-Path Table "Heroku Add-On" column.

   **CRITICAL**: Only exact full-string matches count. Partial matches are NOT valid.

   - "Paper" does NOT match "Papertrail"
   - "papertrail" DOES match "Papertrail" (case-insensitive)
   - "Papertrail Pro" does NOT match "Papertrail"
   - "New Relic APM" does NOT match "New Relic"

4. **If matched — Single mapping** (Mapping Type = "Single"):

   Produce one service entry:

   ```json
   {
     "service_id": "<aws_service_snake_case>:{heroku_app}:{addon_service}",
     "source_resource_id": "{resource_id}",
     "heroku_app": "{heroku_app}",
     "aws_service": "<AWS Service from table>",
     "confidence": "deterministic",
     "aws_config": {
       "region": "{target_region}",
       "log_group": "/heroku/{heroku_app}",
       "retention_days": <from preferences.operational.log_retention_days or 30>
     }
   }
   ```

   Adjust `aws_config` fields based on the specific AWS service (e.g., `log_group` and `retention_days` for CloudWatch Logs; `bucket_name` placeholder for S3; etc.).

5. **If matched — Composite mapping** (Mapping Type = "Composite"):

   Produce a **single** service entry listing all AWS services in the composite:

   ```json
   {
     "service_id": "<primary_service_snake_case>:{heroku_app}:{addon_service}",
     "source_resource_id": "{resource_id}",
     "heroku_app": "{heroku_app}",
     "aws_service": "<All AWS Services joined by ' + '>",
     "confidence": "deterministic",
     "aws_config": {
       "region": "{target_region}",
       "services": ["<Service1>", "<Service2>"]
     }
   }
   ```

   All services in the composite must appear. A single `"deterministic"` confidence covers the group.

6. **If NOT matched** (no exact case-insensitive match):

   Route to **Specialist Gate** (Step 2F).

7. Append matched entries to `services[]`. Increment `metadata.total_services`.

---

### 2F: Specialist Gate (Deferred Add-Ons)

**Trigger**: Any add-on that fails lookup in Steps 2B, 2C, 2D, or 2E.

**Record format:**

```json
{
  "addon_name": "<config.addon_service>",
  "addon_plan": "<config.plan>",
  "provider": "<config.provider>",
  "reason": "Not found in Fast_Path_Table" | "Unrecognized plan tier: {plan}",
  "recommendation": "Engage AWS account team for replacement selection"
}
```

**Required fields** (all must be present):

- `addon_name`: The add-on service name
- `addon_plan`: The specific plan tier
- `provider`: The add-on provider
- `reason`: Why the mapping was deferred
- `recommendation`: Actionable next step

Append to `deferred[]` in the design output.

---

### 2G: Pipeline Detection (Detect-Only Warning)

**Trigger**: `resource_type == "pipeline"`

**Action**: Do NOT produce any service mapping. Add a warning to `warnings[]`:

> "Pipeline '{config.pipeline_name}' detected — CI/CD mapping requires manual configuration"

Pipelines are detect-only in v1. No AWS services are designed for them.

---

### 2H: Space / VPC Design

**Trigger**: `resource_type == "space"`

Processing is deferred to Step 3 (VPC Design) below. Collect all space resources during the pass, then handle VPC design after all resources are mapped.

---

## Step 3: VPC Design

After all resources have been processed in Step 2, design the VPC configuration.

### 3A: Determine VPC Mode

Examine all space resources collected from the inventory:

- **If any space has `config.peering.detected == true`** with a valid `vpc_id`:
  - Mode = `existing_vpc`
  - Use `config.peering.vpc_id` from the space resource
  - Use subnet IDs from `preferences.network.subnet_ids`

- **If no peering detected** (or no space resources at all):
  - Mode = `new_vpc`
  - Generate a new VPC design

### 3B: Existing VPC (Peering Detected)

```json
{
  "mode": "existing_vpc",
  "existing_vpc_id": "<vpc_id from space config>",
  "subnet_ids": ["<from preferences.network.subnet_ids>"],
  "security_groups": [<see 3D below>]
}
```

### 3C: New VPC (No Peering)

Generate a VPC design that includes:

- **CIDR block**: Default `10.0.0.0/16` (or user-specified if in preferences)
- **Subnets**: At least 2 subnets across separate availability zones:
  - `10.0.1.0/24` in AZ-a (public)
  - `10.0.2.0/24` in AZ-b (public)
  - `10.0.3.0/24` in AZ-a (private)
  - `10.0.4.0/24` in AZ-b (private)
- **Route table**: Default route `0.0.0.0/0` → Internet Gateway (for public subnets)
- **Internet Gateway**: One IGW attached to the VPC

```json
{
  "mode": "new_vpc",
  "cidr_block": "10.0.0.0/16",
  "subnets": [
    {"cidr": "10.0.1.0/24", "az": "a", "type": "public"},
    {"cidr": "10.0.2.0/24", "az": "b", "type": "public"},
    {"cidr": "10.0.3.0/24", "az": "a", "type": "private"},
    {"cidr": "10.0.4.0/24", "az": "b", "type": "private"}
  ],
  "route_table": {"destination": "0.0.0.0/0", "target": "internet_gateway"},
  "internet_gateway": true,
  "security_groups": [<see 3D below>]
}
```

### 3D: Security Groups (Private Space Migrations)

When migrating from a Private Space (regardless of peering mode), generate security groups with **restricted inbound rules**:

- Inbound traffic is allowed **only** from declared dependency CIDRs and ports.
- All other inbound traffic is denied by default (implicit deny).
- Outbound allows all traffic (default egress).

Determine declared dependencies from:

- Space peering CIDRs (`config.peering.peer_cidr`)
- Database ports (5432 for Postgres)
- Redis ports (6379)
- Kafka ports (9092)
- Application ports (443 for HTTPS, 80 for HTTP)

```json
{
  "name": "heroku-migrated-app-sg",
  "inbound_rules": [
    { "port": 443, "protocol": "tcp", "cidr": "<peer_cidr or app CIDR>" },
    { "port": 5432, "protocol": "tcp", "cidr": "<vpc_cidr>" },
    { "port": 6379, "protocol": "tcp", "cidr": "<vpc_cidr>" },
    { "port": 9092, "protocol": "tcp", "cidr": "<vpc_cidr>" }
  ],
  "outbound_rules": [
    { "port": 0, "protocol": "-1", "cidr": "0.0.0.0/0" }
  ]
}
```

Only include ports for services that are actually present in the design. If no Postgres → no 5432 rule. If no Redis → no 6379 rule.

### 3E: No Private Space — Default Security Group

If no Private Space exists, produce a standard security group:

```json
{
  "name": "heroku-migrated-app-sg",
  "inbound_rules": [
    { "port": 443, "protocol": "tcp", "cidr": "0.0.0.0/0" },
    { "port": 80, "protocol": "tcp", "cidr": "0.0.0.0/0" }
  ],
  "outbound_rules": [
    { "port": 0, "protocol": "-1", "cidr": "0.0.0.0/0" }
  ]
}
```

Set the completed `vpc_design` object in the design output.

---

## Step 4: Cedar/Fir Notation

After all resources are mapped:

1. Scan `heroku-resource-inventory.json`.apps[] for any app with `heroku_generation == "fir"`.

2. **If Fir workloads exist**:
   - Add each Fir app name to `metadata.fir_workloads_detected[]`.
   - Set `metadata.fir_generation_note`: "Fir-generation workloads detected. No Fir-specific Terraform (ARM/Graviton instance targeting, CNB buildpack configuration) is generated in v1. These workloads are deferred to a future version."
   - Add a warning: "Fir-generation workloads deferred to future version: {comma-separated app names}"

3. **If NO Fir workloads**:
   - Set `metadata.fir_workloads_detected` to `[]`.
   - Set `metadata.fir_generation_note`: "No Fir workloads detected; all Cedar generation."

4. **CRITICAL CONSTRAINT**: Do NOT produce ARM/Graviton instance targeting or CNB buildpack configuration in ANY output, regardless of `heroku_generation` value. Fir detection is **detect-only** in v1.

---

## Step 5: Finalize Metadata

1. Count total unique apps with at least one mapped service → `metadata.total_apps_migrated`.
2. Count total entries in `services[]` → `metadata.total_services`.
3. Set `timestamp` to current ISO 8601.
4. Set `design_source` from inventory metadata `discovery_sources[0]` (or "terraform" if source is unclear).

When Steps 0–5 are complete (the in-memory design object is fully populated), control passes
to the assembler (`design-assemble.md`) to write `aws-design.json`, run the output checks +
handoff gate, and update phase status.
