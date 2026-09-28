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
- **RDS path** (`single-az`, `multi-az`): Size from current Cloud SQL tier; `database_traffic` and `db_io_workload` select instance class, optional read replicas, and storage type (**gp3** default; **io2** / Provisioned IOPS when `db_io_workload = "high"`).
- **Aurora path** (`multi-az-ha`, `multi-region`): Apply Q12 traffic and Q13 I/O for Aurora Standard vs I/O-Optimized, read replicas, Serverless v2, or DSQL review.
- **Dev/low spend** → RDS `db.t4g.micro` or `db.t4g.small` single-AZ is appropriate when Q6 = Inconvenient — do not upsell to Aurora Serverless v2.
- **Migration tooling** — Read `preferences.json` → `design_constraints.db_size.value` (set by Q13b in Clarify) to select the right tool: `"<10GB"` → pg_dump/pg_restore; `"10-100GB"` or `"100-500GB"` → pgcopydb; `">500GB"` → AWS DMS strongly recommended; `"unknown"` → default to pgcopydb

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

- **In-memory cache** → ElastiCache Redis (fast-path, 1:1 mapping)
- **Cluster mode enabled** → ElastiCache Redis with cluster mode
- **High availability required** → ElastiCache Redis Multi-AZ with auto-failover

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
    "storage_type": "gp3"
  },
  "confidence": "inferred",
  "human_expertise_required": false,
  "rationale": "Q6 single-az → RDS PostgreSQL; dev-tier sizing from Cloud SQL config; gp3 for low I/O",
  "rubric_applied": [
    "User Preference: availability=single-az",
    "Operational Model: RDS over Aurora for low-HA workload",
    "Simplicity: RDS PostgreSQL single-AZ"
  ]
}
```
