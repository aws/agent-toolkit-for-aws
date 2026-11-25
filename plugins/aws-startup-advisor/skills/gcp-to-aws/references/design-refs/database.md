# Database Services Design Rubric

**Applies to:** Cloud SQL, Firestore, BigQuery, Memorystore (Redis), Cloud Spanner

**Cloud SQL PostgreSQL/MySQL:** Always use this rubric (confidence = `inferred`). **Q6 (`design_constraints.availability`) selects RDS vs Aurora** — see mapping table below. Q12/Q13 tune sizing within that family; they never override Q6.

## Q6 → RDS vs Aurora (mandatory)

Read `preferences.json` → `design_constraints.availability` **before** selecting `aws_service`:

| `availability` | PostgreSQL target                 | MySQL target                 | `multi_az` in aws_config |
| -------------- | --------------------------------- | ---------------------------- | ------------------------ |
| `single-az`    | RDS PostgreSQL                    | RDS MySQL                    | `false`                  |
| `multi-az`     | RDS PostgreSQL                    | RDS MySQL                    | `true`                   |
| `multi-az-ha`  | Aurora PostgreSQL                 | Aurora MySQL                 | `true`                   |
| `multi-region` | Aurora PostgreSQL Global Database | Aurora MySQL Global Database | global cluster           |

Engine (PostgreSQL vs MySQL) comes from GCP `database_version`, not from Q12/Q13.

## Eliminators (Hard Blockers)

| GCP Service            | AWS                | Blocker                                                                                                                                                                                    |
| ---------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Firestore              | DynamoDB           | ACID transactions spanning >100 items required → use RDS (DynamoDB limit: 100 items/transaction)                                                                                           |
| BigQuery               | _(no auto-target)_ | **Plugin does not prescribe Athena/Redshift/Glue** — use `Deferred — specialist engagement` in design output; OLTP latency needs → Aurora or DynamoDB per workload review with specialists |
| Cloud SQL (PostgreSQL) | RDS or Aurora      | PostGIS extension → supported on both RDS PostgreSQL and Aurora PostgreSQL                                                                                                                 |

## Signals (Decision Criteria)

### Cloud SQL

- **Product family** → **Q6 only** (see table above). Do not default to Aurora.
- **RDS path** (`single-az`, `multi-az`): Size from current Cloud SQL tier, or from measured utilization when the inventory entry carries `utilization` (§ Measured sizing below: class from CPU and memory, then connections, then storage from `disk_bytes_used`); `database_traffic` and `db_io_workload` select optional read replicas and storage type (**gp3** default; **io2** / Provisioned IOPS when `db_io_workload = "high"`).
- **Aurora path** (`multi-az-ha`, `multi-region`): Apply Q12 traffic and Q13 I/O for Aurora Standard vs I/O-Optimized, read replicas, Serverless v2, or DSQL review.
- **Dev/low spend** → RDS `db.t4g.micro` or `db.t4g.small` single-AZ is appropriate when Q6 = Inconvenient — do not upsell to Aurora Serverless v2.
- **Migration tooling** — Read `preferences.json` → `design_constraints.db_size.value` (set by Q13b in Clarify) to select the right tool: `"<10GB"` → pg_dump/pg_restore; `"10-100GB"` or `"100-500GB"` → pgcopydb; `">500GB"` → HOLD in Generate for a separately reviewed workflow (AWS DMS full-load + CDC may be appropriate); `"unknown"` → HOLD in Generate until actual size and the maintenance window are verified

### Firestore

- **Flexible schema** + **NoSQL** → DynamoDB
- **Strong consistency required** → DynamoDB supports strongly consistent reads via `ConsistentRead` parameter
- **Real-time sync** + **offline support** → DynamoDB Streams + Amplify (app-level)

### BigQuery

**Do not use this rubric to pick an AWS product.** For any `google_bigquery_*` resource, follow **`design-infra.md` → BigQuery specialist gate** only: set `aws_service` to **`Deferred — specialist engagement`**, `human_expertise_required: true`, and direct the customer to **their AWS account team and/or a data analytics migration partner**. Do **not** output Athena, Redshift, Glue, EMR, or similar as the automated mapping in `aws-design.json`.

The sections below are **background for humans** after engagement — not for the agent to select automatically:

- Warehousing, SQL analytics, BI, and ML-on-data choices require assessment (e.g. query patterns, data volume, SLAs, cost model).
- **BigQuery ML** (`google_bigquery_ml_*`) uses the **same specialist gate** — no automated SageMaker/Redshift ML target from this plugin.

### Memorystore (Redis)

- **In-memory cache** → ElastiCache Valkey (fast-path, 1:1 mapping). Valkey is ElastiCache's default engine for new clusters, is compatible with Redis OSS commands, data structures, and clients, costs 20% less per node (33% less on ElastiCache Serverless), and is the only ElastiCache engine Database Savings Plans cover. Select Redis OSS only when the source depends on a Redis module or feature Valkey does not provide, and record why in the rationale. Emit `aws_config.engine: "valkey"` (or `"redis"` on the exception) and a Valkey `engine_version` (7.2 or later)
- **Cluster mode enabled** → ElastiCache Valkey with cluster mode
- **High availability required** → ElastiCache Valkey Multi-AZ with auto-failover
- **Redis module or Valkey-incompatible feature required** → ElastiCache Redis OSS (`aws_config.engine: "redis"`); note that Database Savings Plans then do not apply and Reserved Nodes are the commitment lever

### Cloud Spanner

- **Global strong consistency** → Aurora DSQL (distributed SQL with strong consistency across regions)
- **Single-region relational** → Aurora PostgreSQL (simpler, lower cost if global distribution not needed)
- **Key-value access patterns dominant** → DynamoDB Global Tables (if workload is mostly key-value lookups)

## 6-Criteria Rubric

Apply in order:

1. **Eliminators**: Does GCP config require AWS-unsupported features? If yes: switch
2. **Operational Model**: Apply **Q6 availability mapping** first.
   - `single-az` / `multi-az` → **RDS** (simpler, lower cost for dev and production with acceptable outage windows)
   - `multi-az-ha` / `multi-region` → **Aurora** (faster failover, Global Database when required)
3. **User Preference**: From `preferences.json`:
   - `design_constraints.database_traffic` — RDS: size writer/replicas; Aurora: replica count, Serverless v2, DSQL review when write-heavy-global **and** Q6 is Aurora tier
   - `design_constraints.db_io_workload` — RDS: gp3 vs io2; Aurora: Standard vs I/O-Optimized (**only when Q6 is Aurora tier**)
   - **Never** upgrade RDS → Aurora based on traffic or I/O alone
4. **Feature Parity**: Does GCP config need features unavailable in AWS?
   - Example: Cloud SQL with binary log replication → Aurora (full support) when Q6 requires Aurora tier
   - Example: Firestore with offline-first SDK → DynamoDB (plus app-level sync)
5. **Cluster Context**: Are other resources in cluster using RDS? Prefer same family
6. **Simplicity**: For Q6 Inconvenient/Significant Issue, prefer RDS over Aurora unless eliminators block

## Examples

### Example 1: Cloud SQL PostgreSQL (dev / low HA)

- GCP: `google_sql_database_instance` (database_version=POSTGRES_15, tier=db-f1-micro)
- Q6: `availability: "single-az"`
- Criterion 2: RDS PostgreSQL single-AZ
- Criterion 3: `db_io_workload: "low"` → gp3 storage
- → **AWS: RDS PostgreSQL (`db.t4g.micro`, single-AZ, gp3)**
- Confidence: `inferred`

### Example 2: Firestore (mobile app)

- GCP: `google_firestore_document` (root_path=users, auto_id=true)
- Signals: NoSQL, real-time, offline-first (inferred from Firestore choice)
- Criterion 1 (Eliminators): PASS (DynamoDB supports eventual consistency)
- Criterion 2 (Operational Model): DynamoDB (managed NoSQL)
- Criterion 3 (User Preference): NoSQL type detected from GCP resource → DynamoDB confirmed
- → **AWS: DynamoDB (on-demand billing for dev)**
- Confidence: `inferred`

### Example 3: BigQuery (analytics)

- GCP: `google_bigquery_dataset` (location=us, schema=[large table])
- **Agent output:** `aws_service`: **`Deferred — specialist engagement`**, `human_expertise_required`: **`true`**, `confidence`: **`inferred`**, `rubric_applied`: `["BigQuery specialist gate — no automated AWS service target"]`
- **User-facing:** Engage **AWS account team** and/or **data analytics migration partner** before choosing AWS analytics architecture. **Do not** state Athena vs Redshift vs Glue as the plugin’s recommendation.

### Example 4: Cloud SQL PostgreSQL (production Multi-AZ RDS)

- GCP: `google_sql_database_instance` (database_version=POSTGRES_15, tier=db-custom-2-7680)
- Q6: `availability: "multi-az"`
- Criterion 3: `database_traffic: "read-heavy"` → optional RDS read replica
- → **AWS: RDS PostgreSQL Multi-AZ + optional read replica**
- Confidence: `inferred`

### Example 5: Cloud SQL PostgreSQL (mission-critical)

- GCP: `google_sql_database_instance` (database_version=POSTGRES_15)
- Q6: `availability: "multi-az-ha"`
- Criterion 3: `db_io_workload: "high"` → Aurora I/O-Optimized
- → **AWS: Aurora PostgreSQL Multi-AZ, I/O-Optimized storage**
- Confidence: `inferred`

## Measured sizing (Cloud SQL → RDS class, storage, RDS Proxy)

On the RDS path, the instance class, allocated storage and the RDS Proxy decision come from the inventory entry's `utilization` object (Cloud Monitoring, `discover-live.md` rows 21e–21n) through the same script `design-refs/compute.md` § Measured sizing runs; its `cloudsql_database` decisions carry `instance_class`, `storage`, `rds_proxy`, `sizing_provenance` and the same `declared_reason` / `sizing_note` / `sized_from` fields. Copy `instance_class` and `storage.allocated_gib` / `storage_type` / `iops` / `throughput_mbps` into `aws_config`, `rds_proxy` into `aws_config.rds_proxy`, and the provenance fields onto the mapping. The classes, the Cloud SQL tier specs (`db-f1-micro` 0.2 reserved vCPU / 0.6 GiB, `db-custom-{vcpu}-{mb}`, legacy `db-n1-*`) and the `max_connections` formula live in `knowledge/design/instance-catalog.json`; `rds_proxy`, `storage` and `memory_saturated_p95_min` in `knowledge/estimate/rightsizing-thresholds.json`.

The rule, for checking a decision by hand:

1. **Anchor.** Like-for-like class = the smallest class in the mapped RDS family (`db.t4g` for the shared-core tiers, so `db-f1-micro` → `db.t4g.micro` as Example 1 says; `db.m7g` for standard/custom; `db.r7g` for highmem or custom above 6 GiB per vCPU) whose vCPU and memory are both at or above the tier's. Recorded as `like_for_like` on every decision.
2. **Gate.** Same as compute (`cost_optimization`, `sizing_exemptions[]`, `coverage`, numeric memory) except that Cloud SQL never has `idle` or `mig_member`. A gated database keeps the anchor with `sizing_provenance: "declared"` and its `declared_reason`.
3. **Class from CPU and memory first.** `required_vcpu = (reserved_vcpu or vcpu) × cpu.p95 × headroom_factor`, `required_memory_gib = memory_gib × memory.p95 × headroom_factor`; smallest class at or below the anchor meeting both; `step_cap` applies as for compute. **Measured sizing never picks a class above like-for-like.** When `memory.p95 >= 0.90` the class stays like-for-like, `sizing_provenance` stays `"measured"`, and `sizing_note: "memory_saturated"` records that the declared class is the floor, not evidence of need: Cloud SQL counts page cache, and a 0.6 GB `db-f1-micro` reads 0.99–1.0 all month, so `× 1.3` headroom would otherwise upsize it.
4. **Then connections.** `max_connections` is the catalog **formula** on the picked class's `DBInstanceClassMemory` (MySQL `memory_bytes / 12582880`; PostgreSQL `min(memory_bytes / 9531392, 5000)`), never a stored integer — and `memory_bytes` is **not** the advertised class memory: RDS first subtracts what it reserves for the OS and its own processes (AWS documents about 630 on db.m7g.large MySQL, not 683, and about 60 on db.t3.micro), so the script models `DBInstanceClassMemory = (memory_gib − 0.25 − 0.045 × memory_gib) × 2^30` from the catalog's `reserved_memory` fit to those anchors. A `connections.p95` within 10% of the modeled limit gets a warning to confirm the real value (`SHOW GLOBAL VARIABLES LIKE 'max_connections'`) or add RDS Proxy. PostgreSQL `connections.p95` is `num_backends` summed over every `database` label, system databases included. Add RDS Proxy (`aws_config.rds_proxy: true`) only when `connections.p95` exceeds `max_connections` **and** `cpu.p95 <= 0.50`; a busy database with many connections (`cpu.p95 > 0.50`) needs a larger class, not a proxy: it is already at like-for-like, measured sizing never picks above it, so the decision carries `sizing_note: "connections_bound"` and a warning to review by hand. A `connections` block with no data skips the proxy decision and says so. **`rds_proxy: true` is a recommendation only in this version:** Estimate does not price it (no RDS Proxy rate in this skill) and Generate does not emit `aws_db_proxy`; the report's Known limitations (Appendix I) names each such database and the manual step (add RDS Proxy, about $0.015 per vCPU-hour of the target class, or raise `max_connections` in a parameter group). No `db.t4g` switch in v1: a measured database stays in its like-for-like family, and the EC2 credit table does not apply.
5. **Storage.** `allocated_gib = disk_bytes_used.max × 1.5`, rounded up to the next 10 GiB, never below the engine minimum (20 GiB gp3; live: 87 MB used → 20 GiB). When the class stayed declared or `disk_bytes_used` was not captured, the provisioned disk is the upper bound: `config.disk_size_gb` (the IaC inventory's canonical key), else the live capture's `settings.dataDiskSizeGb`, else raw `settings.disk_size`; `max(N, 20)` with `basis: "declared"`. Design copies `storage.allocated_gib` to **`aws_config.allocated_storage`** — the key the Estimate RDS recipe prices and Terraform's `allocated_storage` argument — never to a second storage key. Write gp3 with the catalog's 3000 IOPS / 125 MB/s and a warning that v1 did not measure IOPS (shrinking from a large PD-SSD drops the IOPS that disk size was buying). Without `disk_bytes_used`, or when the class stayed declared (step 2), allocated storage falls back to the provisioned Cloud SQL disk as an upper bound (`storage.basis: "declared"`).

Worked examples (`fixtures/gcp-utilization-capture/after-design/sizing-decisions.json`): the live `db-f1-micro` PostgreSQL at cpu 0.11 / memory 1.0 / 5 backends → `db.t4g.micro`, `memory_saturated`, `max_connections` 79, no proxy, 20 GiB gp3. A `db-custom-2-8192` MySQL at cpu 0.30 / memory 0.51 / 37 connections → `db.m7g.large` (the family minimum is also the anchor), `max_connections` 630, no proxy, 12 GiB used → 20 GiB gp3.

## Output Schema

```json
{
  "gcp_type": "google_sql_database_instance",
  "gcp_address": "dev-postgres-db",
  "gcp_config": {
    "database_version": "POSTGRES_15",
    "tier": "db-f1-micro"
  },
  "aws_service": "RDS PostgreSQL",
  "aws_config": {
    "engine_version": "15",
    "instance_class": "db.t4g.micro",
    "multi_az": false,
    "storage_type": "gp3",
    "allocated_storage": 20,
    "iops": 3000,
    "throughput_mbps": 125,
    "rds_proxy": false
  },
  "sizing_provenance": "measured",
  "sizing_note": "memory_saturated",
  "like_for_like": "db.t4g.micro",
  "sized_from": {
    "cpu_p95": 0.1086,
    "memory_p95": 0.9999,
    "window_days": 30,
    "required_vcpu": 0.03,
    "required_memory_gib": 0.6,
    "like_for_like": "db.t4g.micro",
    "uncapped": "db.t4g.micro",
    "capped": "db.t4g.micro",
    "step_cap": 2,
    "connections_p95": 5.0,
    "max_connections": 79
  },
  "confidence": "inferred",
  "human_expertise_required": false,
  "rationale": "Q6 single-az → RDS PostgreSQL; measured sizing: db.t4g.micro is the like-for-like floor (memory saturated), 5 backends vs 79 max_connections, 20 GiB gp3 minimum",
  "rubric_applied": [
    "User Preference: availability=single-az",
    "Operational Model: RDS over Aurora for low-HA workload",
    "Simplicity: RDS PostgreSQL single-AZ"
  ]
}
```
