# query_executions — column reference

Column reference for the `query_executions` Amazon Athena system table. Athena creates and manages this table automatically when system tables are enabled — there is no `CREATE TABLE` to run and the table cannot be written to. All names are `snake_case`; time columns are `timestamptz` in UTC. The table is partitioned by `DAY(submission_date_time)` and `work_group_name`. Query path: `"s3tablescatalog/aws-athena"."metadata"."query_executions"`. The authoritative column/schema reference is the [Athena `query_executions` system table doc](https://docs.aws.amazon.com/athena/latest/ug/athena-system-table-query-executions.html).

| Column | Type | Notes |
|---|---|---|
| `query_execution_id` | string | Globally unique identifier for the query execution. Join key to the console, APIs, CloudTrail. |
| `account_id` / `region_name` | string | 12-digit account (leading zeros preserved); Region. |
| `work_group_name` | string | Work group the query ran in. Partition column — filter on it when scoping to a work group. Primary cost/access grouping. |
| `catalog_name` / `database_name` | string | Default catalog and database of the query's execution context. Distinct from the same-named fields inside the `tables_accessed` struct — when referencing struct fields, name the unnested element and qualify through it (for example `accessed_table.catalog_name` after `CROSS JOIN UNNEST(tables_accessed) AS t(accessed_table)`). |
| `query_string` | string | Full SQL text, up to 256 KB. May contain PII/secrets — see Security. Use `SUBSTR(query_string, 1, 200)` for previews. Projecting this column copies the sensitive text into the query result location, so ensure that result location is SSE-KMS-encrypted and access-controlled. |
| `execution_parameters` | list\<string\> | Values bound to `?` placeholders in a parameterized query; null otherwise. |
| `principal_arn` | string | IAM user/role that ran the query. Not included in the `GetQueryExecution` response. |
| `submission_date_time` | timestamptz | Partition column (DAY transform). Primary time filter — always constrain on this for partition pruning. |
| `completion_date_time` | timestamptz | When the query reached a final state. |
| `state_enum` | string | `SUCCEEDED`, `FAILED`, `CANCELLED`. |
| `error_category_enum` / `error_type_enum` | int | Populated only when `state_enum = 'FAILED'` (NULL for `SUCCEEDED` and `CANCELLED`). Category: 1=system, 2=user, 3=other. A `FAILED` query with no recorded error carries a generic unknown error. |
| `error_message` / `error_retryable` | string / boolean | Failure detail. |
| `statement_type_enum` | string | `DDL`, `DML`, `UTILITY`. Filter `= 'DML'` for data-scan cost analysis. |
| `statement_subtype_enum` | string | `SELECT`, `CREATE_TABLE_AS_SELECT`, `INSERT`, `UNLOAD`, `CREATE_TABLE`, `ALTER_TABLE_ADD_PARTITION`, etc. |
| `data_scanned_size` | long | Primary Athena SQL cost driver ($/TB). 0 for metadata-only or cached queries. |
| `dpu_count` | double | DPUs allocated for queries that run in capacity reservations; NULL otherwise. |
| `total_execution_duration` | long | Wall-clock total, ms. Equals `query_queue_time_duration` + `service_pre_processing_duration` + `engine_execution_duration` + `service_processing_duration` (treat NULL components as 0). NULL when 0 ms. |
| `engine_execution_duration` | long | Engine compute time, ms. Includes `query_planning_duration`. |
| `query_planning_duration` | long | Planning (partition listing, etc.), ms. A subset of `engine_execution_duration` — do not add it when decomposing total. NULL when 0 ms. |
| `query_queue_time_duration` | long | Time waiting for resources, ms (concurrency limit signal). NULL when 0 ms (no wait). |
| `service_pre_processing_duration` | long | Pre-engine validation/optimization, ms. NULL when 0 ms. |
| `service_processing_duration` | long | Post-engine result finalization, ms. NULL when 0 ms. |
| `tables_accessed` | list\<struct\<catalog_name, database_name, table_name\>\> | Tables/views referenced in the SQL. `UNNEST` to flatten. Deduplicated (a table referenced twice appears once). |
| `reused_previous_result` | boolean | Whether this query reused a cached result (then `data_scanned_size` is 0). |
| `result_reuse_enabled` | boolean | Whether result reuse was allowed for the query. |
| `result_reuse_max_age_in_minutes` | int | Staleness tolerance when reuse is enabled. |
| `effective_engine_version` / `selected_engine_version` | string | Engine that ran vs. the work group's configured selection (may be `auto`). |
| `managed_query_results_enabled` | boolean | Whether Athena-managed result storage was used. |
| `result_encryption_option_enum` / `result_kms_key_arn` | string | Result encryption config. |
| `result_s3_acl_option_enum` / `result_expected_bucket_owner_account_id` / `result_output_location` | string | Result storage config and location. `result_output_location` falls back to the work group's output location; it can be NULL when Athena-managed query results are used. |
| `schema_version` | string | System-table schema version, for evolution handling. |

To confirm the live schema (for example, if columns were added), run `get-table` once — the schema is identical across accounts:

```bash
aws glue get-table --catalog-id "<ACCOUNT>:s3tablescatalog/aws-athena" --database-name "metadata" --name "query_executions" --region <REGION>
```
