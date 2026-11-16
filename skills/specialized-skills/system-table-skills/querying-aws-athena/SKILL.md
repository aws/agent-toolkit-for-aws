---
name: querying-aws-athena
description: >-
  Runs SQL queries on Amazon Athena query history exported as an Apache Iceberg table in S3
  Tables. The query_executions system table captures per-query metadata (query text, IAM
  principal, work group, statement type, data scanned, timing breakdown, error details,
  tables accessed, result reuse, engine version) for every completed query. Applies when
  analyzing Athena usage and cost, finding who ran a query, auditing table access, tracking
  data scanned by user or work group, investigating slow or failed queries, detecting
  performance regressions, reporting query history beyond the 45-day API window, or enabling
  Athena system tables. Prefers the system table over the ListQueryExecutions and
  GetQueryExecution APIs at scale. Trigger phrases: Athena query history, who ran this query,
  data scanned by user, most queried tables, slowest queries, failed query analysis, Athena
  cost by work group, query audit trail, enable Athena system tables.
version: 1
argument-hint: "[query|'configure'|'status']"
---

# Query Amazon Athena System Tables

## Overview

**Works best with** the [AWS MCP server](https://docs.aws.amazon.com/aws-mcp/) for sandboxed execution and audit logging. All commands below use the AWS CLI and work in any environment with configured AWS credentials. Use IAM roles or temporary credentials; avoid long-lived access keys.

Amazon Athena system tables are Apache Iceberg tables that Athena automatically creates and populates with account usage data. The `query_executions` system table records one row per completed query with the metadata from `GetQueryExecution` plus additional fields that `GetQueryExecution` does not return. The tables are read-only and stored as fully managed Amazon S3 Tables in the service-managed `aws-athena` S3 table bucket in your account and Region, and are queryable with Athena SQL (the focus of this skill) or any other Iceberg-compatible engine, such as Amazon Redshift.

The system table is preferred over the raw Athena APIs (`ListQueryExecutions`, `GetQueryExecution`) because:

- `ListQueryExecutions` returns only query IDs and paginates; `GetQueryExecution` must then be called once per ID. Reconstructing "how much did each user scan last month" means thousands of sequential API calls. The system table answers it with one `GROUP BY`.
- The APIs offer no SQL, no aggregation, and no joins, and cover only a rolling 45-day window. The system table retains data for as long as you configure through S3 Tables record expiration and supports arbitrary SQL, including window functions and cross-table joins.
- `principal_arn` (the IAM user or role that ran the query) is not included in the `GetQueryExecution` response — obtaining it otherwise requires a CloudTrail join. It is a first-class column here.
- `tables_accessed` (the tables and views referenced by each query) is likewise not included in the `GetQueryExecution` response, enabling lineage and "who queried what table" analysis directly.

## Decision Tree

| User intent | Use this skill? | Column / approach | Alternative |
|---|---|---|---|
| How many queries ran, and cost/data-scanned trends | **Yes** | `data_scanned_size`, `submission_date_time` | — |
| Who ran a specific query, or who scans the most | **Yes** | `principal_arn` | — |
| Which tables are queried most / by whom | **Yes** | `tables_accessed` (UNNEST) | — |
| Slowest queries / time breakdown / regressions | **Yes** | timing `*_duration` columns | — |
| Failed-query analysis, error patterns | **Yes** | `state_enum`, `error_*` columns | — |
| Query history older than 45 days | **Yes** | system table (API window is 45 days) | — |
| Status of a single in-flight/running query | **No** | — | `GetQueryExecution` (system table has completed queries only) |
| Look up one known query by ID, ad hoc | **Maybe** | one-row `WHERE query_execution_id =` | `GetQueryExecution` (no setup) |
| Enable / disable the system table | **Yes** | see Enable section | — |
| Query the data *inside* S3 tables | **No** | — | `querying-data-lake` |

## Common Tasks

### 1. Check If Configured

Before querying, confirm the system table is enabled for the account and Region.

```bash
aws athena get-system-table-configuration --table-name ALL --region <REGION>
aws athena list-system-table-statuses --region <REGION>
```

**Interpret the response:**

- `get-system-table-configuration` returns a configuration record (with `CreatedAt`) → enabled.
- `ResourceNotFoundException` → not enabled. See Enable section below.
- `list-system-table-statuses` returns items with `Enabled: true` → publishing is on for that physical table (`QUERY_EXECUTIONS`).
- `Enabled: false` on every item → the account is not opted in.

The physical `query_executions` table is created by the ingestion pipeline on the first data delivery after enabling, so it may not exist immediately after opt-in even though the configuration shows enabled.

### 2. Enable (if not configured)

System tables are an account- and Region-level switch. The `TableName` parameter is always `ALL`; there is no per-work-group opt-in.

> **Before enabling — this captures sensitive data account-wide.** Enabling records the verbatim `query_string` (which may contain PII, secrets, or business logic) and the `principal_arn` for *every* completed query in *every* work group, including ones created later. Review [Data Sensitivity](#data-sensitivity) and decide on a customer-managed KMS key and Lake Formation column controls *before* turning it on.

**Enable with default encryption (SSE-S3)** — acceptable only for non-sensitive usage data. Because this table captures `query_string` and `principal_arn` verbatim, SSE-S3 is **not recommended for production**; prefer the customer-managed SSE-KMS form below whenever the query history may contain sensitive data:

```bash
aws athena create-system-table-configuration --table-name ALL --region <REGION>
```

**Enable with a customer-managed KMS key (SSE-KMS):**

```bash
aws athena create-system-table-configuration \
  --table-name ALL \
  --kms-key-arn arn:aws:kms:<REGION>:<ACCOUNT>:key/<KEY_ID> \
  --region <REGION>
```

The key policy must grant `kms:GenerateDataKey`, `kms:Decrypt`, and `kms:DescribeKey` to both `systemtables.athena.amazonaws.com` (writes) and `maintenance.s3tables.amazonaws.com` (S3 Tables maintenance). Scope each grant with a confused-deputy guard — `aws:SourceAccount` for the Athena principal and the S3 Tables encryption-context ARN for the maintenance principal:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EnableAthenaSystemTableKeyUsage",
      "Effect": "Allow",
      "Principal": { "Service": "systemtables.athena.amazonaws.com" },
      "Action": ["kms:GenerateDataKey", "kms:Decrypt", "kms:DescribeKey"],
      "Resource": "arn:aws:kms:<REGION>:<ACCOUNT>:key/<KEY_ID>",
      "Condition": { "StringEquals": { "aws:SourceAccount": "<ACCOUNT>" } }
    },
    {
      "Sid": "EnableS3TableMaintenanceKeyUsage",
      "Effect": "Allow",
      "Principal": { "Service": "maintenance.s3tables.amazonaws.com" },
      "Action": ["kms:GenerateDataKey", "kms:Decrypt", "kms:DescribeKey"],
      "Resource": "arn:aws:kms:<REGION>:<ACCOUNT>:key/<KEY_ID>",
      "Condition": {
        "StringLike": {
          "kms:EncryptionContext:aws:s3:arn": "arn:aws:s3tables:<REGION>:<ACCOUNT>:bucket/aws-athena/*"
        }
      }
    }
  ]
}
```

A customer-managed key is recommended when the usage data is sensitive. **Decide on the key before first enabling** — the key is immutable once the table has been created by the ingestion pipeline, so it cannot be changed on an existing table. If the query history may contain sensitive data, pass `--kms-key-arn` at enable time as shown above; if you enable with the default SSE-S3 and later need a customer-managed key, see [Configuring encryption](https://docs.aws.amazon.com/athena/latest/ug/athena-system-tables.html#athena-system-tables-configuring-encryption) in the Athena documentation.

**Integrate the S3 table bucket with AWS Glue Data Catalog** — a one-time step per account and Region, required before querying. If S3 Tables is already integrated with the Glue Data Catalog, no additional action is needed. See [Integrating Amazon S3 Tables with AWS Glue Data Catalog](https://docs.aws.amazon.com/glue/latest/dg/glue-federation-s3tables.html). To register the federated catalog directly:

```bash
aws glue create-catalog --region <REGION> --cli-input-json '{
  "Name": "s3tablescatalog",
  "CatalogInput": {
    "FederatedCatalog": {
      "Identifier": "arn:aws:s3tables:<REGION>:<ACCOUNT>:bucket/*",
      "ConnectionName": "aws:s3tables"
    }
  }
}'
```

Registering the catalog is account-wide S3 Tables federation, not an access grant — it exposes every S3 table bucket to Glue/Athena. Effective read access is still governed by the scoped IAM policy in Security Considerations.

**Disable (stops publishing; retains the table and all published data):**

```bash
aws athena delete-system-table-configuration --table-name ALL --region <REGION>
```

Disabling makes no S3 Tables API calls — the `query_executions` table and every row already written remain queryable. Re-enabling resumes publishing going forward with no backfill of the gap. Ingestion stops immediately on disable, so queries that completed shortly before disabling but were not yet delivered may be missing from the table.

### 3. Verify Permissions

Querying requires:

- Athena execution permissions (`athena:StartQueryExecution`, `athena:GetQueryResults`)
- S3 Tables read permissions on the `aws-athena` S3 table bucket (see least-privilege policy in Security Considerations)
- The S3 Tables federated catalog registered in Glue (`s3tablescatalog`)
- An Athena work group with a result location — either an explicit output location or Athena-managed query results — that SHOULD enforce SSE-KMS encryption, and MUST be encrypted and access-controlled for any query projecting `query_string` or `principal_arn`

Enabling and managing the configuration requires:

- **Config APIs** — `athena:CreateSystemTableConfiguration`, `athena:UpdateSystemTableConfiguration`, `athena:DeleteSystemTableConfiguration`, and `athena:GetSystemTableConfiguration` on `arn:<PARTITION>:athena:<REGION>:<ACCOUNT>:system-table/ALL`; `athena:ListSystemTableStatuses` on `arn:<PARTITION>:athena:<REGION>:<ACCOUNT>:system-table/*`.
- **S3 Tables** (Athena uses the caller's credentials to create the `aws-athena` S3 table bucket and attach its bucket policy) — `s3tables:CreateTableBucket` and `s3tables:PutTableBucketPolicy` on `arn:<PARTITION>:s3tables:<REGION>:<ACCOUNT>:bucket/aws-athena`.
- **KMS** (only when enabling with a customer managed key) — `kms:DescribeKey` on that key.
- **Glue** (to register the bucket with the Data Catalog) — `glue:CreateCatalog`, `glue:PassConnection`. Grant these least-privilege: querying users need the read pair (`GetSystemTableConfiguration`, `ListSystemTableStatuses`) and the S3 Tables read policy below, and also need AWS Glue Data Catalog read access to the `s3tablescatalog` catalog and `lakeformation:GetDataAccess` — plus `kms:Decrypt` and `kms:DescribeKey` on the key if system tables use a customer managed key. See [IAM permissions](https://docs.aws.amazon.com/athena/latest/ug/athena-system-tables.html#athena-system-tables-iam-permissions) in the Athena documentation. The mutating `Create`/`Update`/`Delete` actions enable, reconfigure, or disable capture account-wide, so limit them to a separate setup/admin role and scope them to the system-table resource ARN `arn:<PARTITION>:athena:<REGION>:<ACCOUNT>:system-table/ALL` rather than `*`.

If `CATALOG_NOT_FOUND` errors occur, the Glue integration is not registered — see step 2.

### 4. Identify the Target Table

The following system table is available:

| Table | What it captures | Grain |
|---|---|---|
| `query_executions` | Metadata for every completed Athena query: text, principal, work group, statement type, data scanned, timing breakdown, error detail, tables referenced, result reuse, engine version | one row per completed query |

**Query path:**

```sql
"s3tablescatalog/aws-athena"."metadata"."query_executions"
```

- S3 table bucket: `aws-athena` (one per account per Region) — namespace: `metadata`.
- Only completed queries are written: `SUCCEEDED`, `FAILED`, `CANCELLED`. `QUEUED` and `RUNNING` queries never appear — use `GetQueryExecution` for in-flight status.
- Data is delivered in batches at a fixed frequency; each completed query appears exactly once (no duplicates).
- Rows from different work groups are distinguished by the `work_group_name` column.

**Schema:** `query_executions` has 39 columns (query text, principal, work group, timing breakdown, error detail, tables accessed, result reuse, engine version, result config). Athena creates and manages the table automatically when system tables are enabled. See `references/schema.md` for the full column reference, or run `aws glue get-table --catalog-id "<ACCOUNT>:s3tablescatalog/aws-athena" --database-name "metadata" --name "query_executions" --region <REGION>` to confirm the live schema.

### 5. Query

**Constraints:**

- You MUST confirm the work group and its result location (an explicit output location, or Athena-managed query results) before executing.
- You SHOULD prefer a work group whose configuration enforces SSE-KMS encryption on query results. When a query projects `query_string` or `principal_arn`, you MUST confirm the result location is SSE-KMS-encrypted and access-controlled first — the results copy that sensitive data out of the governed table into the result bucket.
- You MUST always filter on `submission_date_time` to enable partition pruning and control cost; an unbounded scan of query history can itself be expensive.
- You SHOULD also filter on `work_group_name` when the question is about specific work groups — it is the second partition column, so this prunes further.
- You MUST wrap `total_execution_duration`, `query_queue_time_duration`, `service_pre_processing_duration`, `service_processing_duration`, and `query_planning_duration` in `COALESCE(col, 0)` before averaging, taking percentiles, filtering on thresholds, or adding them together: a 0 ms duration is stored as NULL, and aggregates skip NULLs (so `AVG` would average only the non-zero values and overstate the result).
- You MUST warn the user that the table is read-only: `INSERT`, `UPDATE`, and `DELETE` against it fail (no write access to the service-managed table).
- When substituting an untrusted value (a `query_execution_id`, database, or table name) into a query, validate its shape or bind it as an Athena execution parameter (`?` placeholder) instead of string-interpolating it — the table holds sensitive text, so injection here is high-impact.
- Every query you run against the system table is itself recorded in it; keep exploratory queries scoped.

The queries below are organized by intent. All reference the table by its short name `query_executions`; qualify it with the full path above when running.

These queries cover the core idioms — time-window filtering, `principal_arn` cost attribution, `tables_accessed` lineage, the timing breakdown, error triage, and the audit trail. **For the full library of 38 queries organized by use case, read `references/queries.md`.**

**Query volume over time** — How many queries did we run last week:

```sql
SELECT
  COUNT(*) AS total_queries_last_week
FROM query_executions
WHERE submission_date_time >= DATE_TRUNC('week', CURRENT_TIMESTAMP) - INTERVAL '7' DAY
AND submission_date_time < DATE_TRUNC('week', CURRENT_TIMESTAMP)
```

**Top data scanners** — Identify which principals (users) scan the most data over the past 30 days:

```sql
SELECT
  principal_arn,
  COUNT(*) AS query_count,
  SUM(data_scanned_size) AS total_bytes_scanned,
  SUM(data_scanned_size) / POWER(1024.0, 3) AS total_gb_scanned,
  AVG(data_scanned_size) / POWER(1024.0, 2) AS avg_mb_per_query
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
AND state_enum = 'SUCCEEDED'
GROUP BY principal_arn
ORDER BY total_bytes_scanned DESC
LIMIT 25
```

**Most queried tables** — Which tables are accessed most frequently:

```sql
SELECT
  accessed_table.catalog_name,
  accessed_table.database_name,
  accessed_table.table_name,
  COUNT(*) AS access_count,
  COUNT(DISTINCT principal_arn) AS distinct_principals
FROM query_executions
CROSS JOIN UNNEST(tables_accessed) AS t(accessed_table)
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
AND state_enum = 'SUCCEEDED'
GROUP BY 1, 2, 3
ORDER BY 4 DESC
LIMIT 50
```

**Slowest queries with time breakdown** — Top queries by total execution time. `total_sec = queue + pre_processing + engine + processing`; `planning_sec` is part of `engine_sec`, so do not add it separately:

```sql
SELECT
  query_execution_id,
  work_group_name,
  principal_arn,
  submission_date_time,
  COALESCE(total_execution_duration, 0) / 1000.0 AS total_sec,
  COALESCE(query_queue_time_duration, 0) / 1000.0 AS queue_sec,
  COALESCE(query_planning_duration, 0) / 1000.0 AS planning_sec, -- subset of engine_sec, not additive
  engine_execution_duration / 1000.0 AS engine_sec,
  COALESCE(service_pre_processing_duration, 0) / 1000.0 AS pre_processing_sec,
  COALESCE(service_processing_duration, 0) / 1000.0 AS processing_sec,
  data_scanned_size / POWER(1024.0, 3) AS gb_scanned,
  SUBSTR(query_string, 1, 200) AS query_preview
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
AND state_enum = 'SUCCEEDED'
ORDER BY total_execution_duration DESC
LIMIT 25
```

**Failed query patterns** — Most common error categories and messages grouped by work group:

```sql
SELECT
  work_group_name,
  error_category_enum,
  error_type_enum,
  ANY_VALUE(error_message) AS sample_error_message,
  COUNT(*) AS failure_count
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
AND state_enum = 'FAILED'
GROUP BY 1, 2, 3
ORDER BY failure_count DESC
LIMIT 25
```

**Query audit trail** — All queries with who ran them, when, and on which tables:

```sql
SELECT 
  submission_date_time,
  principal_arn,
  work_group_name,
  statement_type_enum,
  statement_subtype_enum,
  state_enum,
  tables_accessed,
  SUBSTR(query_string, 1, 500) AS query_preview
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
ORDER BY submission_date_time DESC
```

The full library of 38 queries — usage analytics, debugging and performance, and auditing and governance — is in `references/queries.md`. Read it when the user needs an analysis beyond the examples above.

### Routing: Athena SQL vs Direct API

| Scenario | Use |
|---|---|
| Aggregate/trend/ranking across many queries | Athena on `query_executions` |
| "Who ran what against which table" / lineage | Athena with `UNNEST(tables_accessed)` |
| History older than 45 days | Athena (the API window is 45 days) |
| Status of a single running query right now | Direct API: `GetQueryExecution` (table has completed queries only) |
| One-off lookup of a known query ID with no setup | Either — `GetQueryExecution` needs no configuration |
| Write/modify a row | Not possible — the table is read-only |

## Key Behaviors

- Supported within a single AWS account and Region; cross-account and cross-Region consolidation is not supported.
- Only completed activity is recorded; in-flight queries appear only after reaching a final state.
- Delivered data is immutable — no `INSERT`, `UPDATE`, or `DELETE`.
- No data is backfilled: only activity after the feature is enabled is captured, and disabling then re-enabling does not fill the gap.
- No default record expiration — configure it through S3 Tables to manage storage cost.
- Querying requires the S3 table bucket to be integrated with AWS Glue Data Catalog.

## Troubleshooting

| Error / symptom | Cause | Fix |
|---|---|---|
| `CATALOG_NOT_FOUND` | S3 Tables catalog not registered in Glue | Register `s3tablescatalog` (Enable, step 2), or S3 console > Table buckets > Enable integration |
| `ResourceNotFoundException` on `get-system-table-configuration` | Account not opted in | Run `create-system-table-configuration --table-name ALL` |
| Table does not exist shortly after enabling | Table is created lazily on first data delivery | Run an Athena query, then wait for the next delivery batch |
| Empty results though enabled | Data is batched; recent queries not yet delivered, or the time filter predates opt-in | Wait for the next delivery batch; widen `submission_date_time`; note there is no backfill before opt-in |
| Running/queued query missing | Only completed queries are written | Use `GetQueryExecution` for in-flight status |
| `INSERT`/`UPDATE`/`DELETE` fails with access denied | Table is read-only to the customer identity | Expected — the table is not writable |
| `AccessDenied` querying the table | Missing `s3tables:GetTable` / `GetTableData` | See Security Considerations |
| `TABLE_NOT_FOUND` although system tables are enabled and the table exists | System tables use a customer managed key and the querying principal lacks `kms:Decrypt` / `kms:DescribeKey` on it (Athena reports a missing table, not access denied) | Grant `kms:Decrypt` and `kms:DescribeKey` on the key to the querying principal |
| KMS change rejected | Encryption is immutable once the table has been created | Expected — the key cannot be changed on an existing table. Set it at enable time with `--kms-key-arn` (see Enable); for the encryption options, see [Configuring encryption](https://docs.aws.amazon.com/athena/latest/ug/athena-system-tables.html#athena-system-tables-configuring-encryption) |

## Security Considerations

### Least-Privilege IAM Policy

Scope read permissions to the `aws-athena` S3 table bucket ARN rather than using wildcards:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3tables:GetTable",
        "s3tables:GetTableMetadataLocation",
        "s3tables:GetTableData",
        "s3tables:GetNamespace",
        "s3tables:ListTables",
        "s3tables:ListNamespaces",
        "s3tables:GetTableBucket"
      ],
      "Resource": [
        "arn:aws:s3tables:<REGION>:<ACCOUNT>:bucket/aws-athena",
        "arn:aws:s3tables:<REGION>:<ACCOUNT>:bucket/aws-athena/*"
      ]
    }
  ]
}
```

> **The least-privilege read policy above still grants full, unmasked read of `query_string` and `principal_arn`.** Issue it only to trusted audit/analytics principals; for broader audiences, restrict those columns with AWS Lake Formation column-level permissions rather than widening the policy.

### Data Sensitivity

The system table captures query text and identities verbatim, so it is itself a sensitive asset:

- `query_string` is stored in full and unredacted. Literals in the SQL — PII in `WHERE` clauses, hardcoded credentials, business logic — are captured as written. `execution_parameters` likewise stores bound parameter values.
- `principal_arn` reveals which IAM users and roles run which queries.

Access to this data is customer-governed: Athena does not apply read permissions on the caller's behalf and does not mask data. After the S3 table bucket is registered with AWS Glue Data Catalog, read access is controlled with IAM or AWS Lake Formation, including table-, column-, and row-level permissions — for example, restricting the `query_string` and `principal_arn` columns to specific principals. Grant access on a least-privilege basis, treat the table as containing the most sensitive text that flows through any query, and steer users toward parameterized queries so secrets are not embedded in query text. Store query results in encrypted, access-controlled locations and avoid logging raw output containing these fields.

### Encryption for Query Results

The system table data is encrypted at rest with SSE-S3 or a customer-managed KMS key chosen at enable time (see Enable). All access is over TLS in transit by default; for defense in depth, enforce it with an `aws:SecureTransport` condition on the relevant resource policies. Separately, configure the Athena work group to encrypt query results at rest with SSE-KMS:

```json
{
  "ResultConfiguration": {
    "EncryptionConfiguration": {
      "EncryptionOption": "SSE_KMS",
      "KmsKey": "arn:aws:kms:<REGION>:<ACCOUNT>:key/<KEY_ID>"
    }
  }
}
```

### Audit Trail

Enable CloudTrail for Athena (`StartQueryExecution`, `GetQueryResults`, and the `*SystemTableConfiguration` calls) and for S3 Tables (`s3tables:GetTableData`) to retain a record of who queried the system table and who changed its configuration. Encrypt CloudTrail logs with SSE-KMS and store them in an access-logged bucket. If any Athena query metadata or results flow into CloudWatch Logs, encrypt those log groups with a customer-managed KMS key (`aws logs associate-kms-key`), since `query_string` and `principal_arn` are sensitive. Consider a CloudWatch/EventBridge alarm on the `*SystemTableConfiguration` events so enabling, reconfiguring, or disabling capture — or a KMS-key change — notifies the owning team. Encrypt that SNS topic with a customer-managed KMS key and restrict its subscriptions to authorized recipients.

## Additional Resources

- [Amazon Athena system tables](https://docs.aws.amazon.com/athena/latest/ug/athena-system-tables.html) — feature doc: overview, enabling, encryption, lifecycle, and best practices
- [query_executions system table reference](https://docs.aws.amazon.com/athena/latest/ug/athena-system-table-query-executions.html) — authoritative column/schema reference
- [Amazon Athena documentation](https://docs.aws.amazon.com/athena/latest/ug/what-is.html)
- [GetQueryExecution API reference](https://docs.aws.amazon.com/athena/latest/APIReference/API_GetQueryExecution.html) (the source shape the schema mirrors)
- [Amazon S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables.html)
- [Integrating Amazon S3 Tables with AWS Glue Data Catalog](https://docs.aws.amazon.com/glue/latest/dg/glue-federation-s3tables.html) (one-time integration required before querying)
- [S3 Tables record expiration](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-record-expiration.html) (customer-managed record expiration)
- [Athena work groups](https://docs.aws.amazon.com/athena/latest/ug/manage-queries-control-costs-with-workgroups.html)
- [IAM security best practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html) (least-privilege access to the system table)
- [AWS KMS best practices](https://docs.aws.amazon.com/kms/latest/developerguide/best-practices.html) (customer-managed key policy and grants)
- [AWS Lake Formation security best practices](https://docs.aws.amazon.com/lake-formation/latest/dg/security-best-practices.html) (column-level controls for `query_string`/`principal_arn`)
