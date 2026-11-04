# Athena `query_executions` — Query Library

A library of example SQL queries against the Amazon Athena `query_executions` system table, organized by use case. Read this file when a user needs a specific analysis; the parent `SKILL.md` carries the core patterns inline.

**Query path:** `"s3tablescatalog/aws-athena"."metadata"."query_executions"` (referenced below as `query_executions`; qualify with the full path when running).

**Reminders:** always filter on `submission_date_time` for partition pruning; the table is read-only (no INSERT/UPDATE/DELETE); only completed queries (`SUCCEEDED`, `FAILED`, `CANCELLED`) are present. Queries projecting `query_string` or `principal_arn` output sensitive data — confirm the query result location is SSE-KMS-encrypted and access-controlled before running. Pass untrusted values (query execution IDs, database/table names) as Athena execution parameters (`?` placeholders) rather than string-interpolating them, to avoid SQL injection into a table that holds sensitive text.

## Usage Analytics

**Query volume over time** — How many queries did we run last week:

```sql
SELECT
  COUNT(*) AS total_queries_last_week
FROM query_executions
WHERE submission_date_time >= DATE_TRUNC('week', CURRENT_TIMESTAMP) - INTERVAL '7' DAY
AND submission_date_time < DATE_TRUNC('week', CURRENT_TIMESTAMP)
```

**Average query volume** — How many queries do we run on average per day:

```sql
SELECT
  ROUND(CAST(COUNT(*) AS DOUBLE) / 30, 2) AS avg_queries_per_day
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
```

**Average query data scanned** — How much data do queries scan on average:

```sql
SELECT
  AVG(data_scanned_size) / POWER(1024.0, 2) AS avg_mb_scanned,
  AVG(data_scanned_size) / POWER(1024.0, 3) AS avg_gb_scanned
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
AND state_enum = 'SUCCEEDED'
```

**What is the distribution of data scanned by queries?** — Bucket queries into size ranges to understand the scan distribution. This histogram pattern (CASE size buckets, or `GROUP BY` a discrete numeric column, plus `SUM(COUNT(*)) OVER ()` for percent of total) generalizes to any numeric column — for example, `GROUP BY dpu_count` for a DPU-usage distribution, or bucket `LENGTH(query_string)` for query complexity:

```sql
SELECT
    CASE
        WHEN data_scanned_size = 0 THEN 'A 0 bytes (metadata only)'
        WHEN data_scanned_size < 1048576 THEN 'B < 1 MB'
        WHEN data_scanned_size < 104857600 THEN 'C 1 MB - 100 MB'
        WHEN data_scanned_size < 1073741824 THEN 'D 100 MB - 1 GB'
        WHEN data_scanned_size < 10737418240 THEN 'E 1 GB - 10 GB'
        WHEN data_scanned_size < 107374182400 THEN 'F 10 GB - 100 GB'
        ELSE 'G > 100 GB'
    END AS scan_size_bucket,
    COUNT(*) AS query_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
AND state_enum = 'SUCCEEDED'
GROUP BY 1
ORDER BY 1
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

**Query volume, data scanned, and DPU usage trends by work group** — Daily query count and total data scanned per work group. Is our usage increasing or decreasing? What work groups are increasing in query volume? What work groups are increasing in DPU usage:

```sql
SELECT
  work_group_name,
  CAST(submission_date_time AS DATE) AS query_date,
  COUNT(*) AS query_count,
  SUM(data_scanned_size) / POWER(1024.0, 3) AS total_gb_scanned,
  SUM(dpu_count) AS total_dpus_used
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '90' DAY
GROUP BY work_group_name, CAST(submission_date_time AS DATE)
ORDER BY work_group_name, query_date
```

**Peak usage hours** — Query volume by hour of day and day of week to identify peak periods. Using 28 days to capture exactly four weeks. At what time of day do we run the most queries:

```sql
SELECT
  DAY_OF_WEEK(submission_date_time) AS dow,
  HOUR(submission_date_time) AS hour_of_day,
  COUNT(*) AS query_count,
  SUM(data_scanned_size) / POWER(1024.0, 3) AS total_gb_scanned
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '28' DAY
GROUP BY DAY_OF_WEEK(submission_date_time), HOUR(submission_date_time)
ORDER BY query_count DESC
```

**Result reuse savings** — How much data scanned was avoided thanks to result reuse:

```sql
SELECT
  work_group_name,
  COUNT(*) AS total_count,
  COUNT(*) FILTER (WHERE reused_previous_result) AS reused_count,
  ROUND(100.0 * COUNT(*) FILTER (WHERE reused_previous_result) / COUNT(*), 2) AS reuse_percentage,
  SUM(data_scanned_size) FILTER (WHERE NOT reused_previous_result) / POWER(1024.0, 3) AS gb_scanned_without_reuse,
  AVG(data_scanned_size) FILTER (WHERE NOT reused_previous_result) * COUNT(*) FILTER (WHERE reused_previous_result) / POWER(1024.0, 3) AS estimated_gb_saved
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
AND state_enum = 'SUCCEEDED'
GROUP BY work_group_name
ORDER BY estimated_gb_saved DESC
```

**DPU consumption by work_group** — Total DPU-hours consumed per work_group for capacity analysis:

```sql
SELECT
  work_group_name,
  DATE_TRUNC('week', submission_date_time) AS week_start,
  SUM(dpu_count) AS total_dpus_allocated,
  SUM(dpu_count * COALESCE(total_execution_duration, 0) / 3600000.0) AS dpu_hours,
  COUNT(*) AS query_count
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '90' DAY
GROUP BY work_group_name, DATE_TRUNC('week', submission_date_time)
ORDER BY work_group_name, week_start
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

**Work group comparison** — Side-by-side comparison of work groups on key metrics: volume, average data scanned, failure rate, and average duration:

```sql
SELECT
  work_group_name,
  COUNT(*) AS total_queries,
  SUM(data_scanned_size) / POWER(1024, 3) AS total_gb_scanned,
  AVG(data_scanned_size) / POWER(1024, 2) AS avg_mb_per_query,
  ROUND(100.0 * COUNT(*) FILTER (WHERE state_enum = 'FAILED') / COUNT(*), 2) AS failure_rate_pct,
  AVG(COALESCE(total_execution_duration, 0)) / 1000.0 AS avg_duration_sec,
  APPROX_PERCENTILE(COALESCE(total_execution_duration, 0), 0.95) / 1000.0 AS p95_duration_sec,
  COUNT(DISTINCT principal_arn) AS distinct_principals
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
GROUP BY work_group_name
ORDER BY total_queries DESC
```

**Query complexity** — Histogram of query text length of `SELECT` queries. This can be used to identify generated or overly complex SQL:

```sql
SELECT
  CASE
    WHEN LENGTH(query_string) < 100 THEN 'A < 100 chars'
    WHEN LENGTH(query_string) < 500 THEN 'B 100-500 chars'
    WHEN LENGTH(query_string) < 2000 THEN 'C 500-2000 chars'
    WHEN LENGTH(query_string) < 10000 THEN 'D 2000-10000 chars'
    ELSE 'E > 10000 chars'
    END AS query_length_bucket,
  COUNT(*) AS query_count,
  AVG(COALESCE(total_execution_duration, 0)) / 1000.0 AS avg_duration_sec,
  AVG(data_scanned_size) / POWER(1024.0, 2) AS avg_mb_scanned
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
AND statement_subtype_enum = 'SELECT'
GROUP BY 1
ORDER BY 1
```

**Statement type breakdown** — Proportion of statement type (`DDL`, `DML`, `UTILITY`) and substatement type (`SELECT`, `ALTER TABLE ADD PARTITION`, `INSERT`) per work group:

```sql
SELECT
  work_group_name,
  statement_type_enum,
  statement_subtype_enum,
  COUNT(*) AS query_count,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY work_group_name), 2) AS pct_of_work_group
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
GROUP BY work_group_name, statement_type_enum, statement_subtype_enum
ORDER BY work_group_name, query_count DESC
```

**Data scanned percentiles by work group** — P50/P90/P99 data scanned per query to understand tail cost drivers:

```sql
SELECT
  work_group_name,
  COUNT(*) AS query_count,
  APPROX_PERCENTILE(data_scanned_size, 0.5) / POWER(1024, 3) AS p50_gb,
  APPROX_PERCENTILE(data_scanned_size, 0.9) / POWER(1024, 3) AS p90_gb,
  APPROX_PERCENTILE(data_scanned_size, 0.99) / POWER(1024, 3) AS p99_gb,
  MAX(data_scanned_size) / POWER(1024, 3) AS max_gb
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
AND state_enum <> 'FAILED' -- no charge for bytes scanned on FAILED queries
AND statement_type_enum = 'DML'
GROUP BY work_group_name
ORDER BY 5 DESC
```

**Work group growth rate** — Month-over-month growth in query count per work group:

```sql
WITH monthly AS (
  SELECT
    work_group_name,
    DATE_TRUNC('month', submission_date_time) AS month,
    COUNT(*) AS query_count
  FROM query_executions
  WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '6' MONTH
  GROUP BY work_group_name, DATE_TRUNC('month', submission_date_time)
)
SELECT
  work_group_name,
  month,
  query_count,
  LAG(query_count) OVER (PARTITION BY work_group_name ORDER BY month) AS prev_month_count,
  ROUND(100.0 * (query_count - LAG(query_count) OVER (PARTITION BY work_group_name ORDER BY month)) / LAG(query_count) OVER (PARTITION BY work_group_name ORDER BY month), 2) AS growth_pct
FROM monthly
ORDER BY work_group_name, month
```

**Managed query results adoption over time** — Track adoption of managed query results week over week:

```sql
SELECT
  DATE_TRUNC('week', submission_date_time) AS week_start,
  work_group_name,
  COUNT(*) AS total_queries,
  COUNT(*) FILTER (WHERE managed_query_results_enabled) AS managed_results_count,
  ROUND(100.0 * COUNT(*) FILTER (WHERE managed_query_results_enabled) / COUNT(*), 2) AS managed_results_pct
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '90' DAY
GROUP BY DATE_TRUNC('week', submission_date_time), work_group_name
ORDER BY work_group_name, week_start
```

**Substatement type distribution** — Breakdown of substatement types to understand actual workload composition. Substatement type examples are `SELECT`, `CREATE_TABLE_AS_SELECT`, `UNLOAD`, `CREATE_TABLE`, `ALTER_TABLE_ADD_PARTITION`:

```sql
SELECT
  work_group_name,
  statement_type_enum,
  statement_subtype_enum,
  COUNT(*) AS query_count,
  AVG(data_scanned_size) / POWER(1024.0, 2) AS avg_mb_scanned,
  AVG(COALESCE(total_execution_duration, 0)) / 1000.0 AS avg_duration_sec
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
GROUP BY work_group_name, statement_type_enum, statement_subtype_enum
ORDER BY work_group_name, query_count DESC
```

## Debugging & Performance

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

**Which queries scanned the most data?** — Top queries ranked by data scanned:

```sql
SELECT
  query_execution_id,
  work_group_name,
  principal_arn,
  submission_date_time,
  data_scanned_size / POWER(1024, 3) AS gb_scanned,
  COALESCE(total_execution_duration, 0) / 1000.0 AS duration_sec,
  SUBSTR(query_string, 1, 200) AS query_preview
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
AND state_enum = 'SUCCEEDED'
ORDER BY data_scanned_size DESC
LIMIT 25
```

**Which tables result in the most failed queries?** — Tables most frequently accessed by queries that fail:

```sql
SELECT
  accessed_table.catalog_name,
  accessed_table.database_name,
  accessed_table.table_name,
  COUNT(*) AS failed_query_count
FROM query_executions
CROSS JOIN UNNEST(tables_accessed) AS t(accessed_table)
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
AND state_enum = 'FAILED'
GROUP BY 1, 2, 3
ORDER BY 4 DESC
LIMIT 25
```

**Planning time outliers** — Queries with the longest planning time. This can be caused by queries that need to list many partitions on S3:

```sql
SELECT
  query_execution_id,
  work_group_name,
  submission_date_time,
  COALESCE(query_planning_duration, 0) / 1000.0 AS planning_sec,
  COALESCE(query_queue_time_duration, 0) / 1000.0 AS queue_sec,
  COALESCE(total_execution_duration, 0) / 1000.0 AS total_sec,
  ROUND(100.0 * COALESCE(query_planning_duration, 0) / NULLIF(COALESCE(total_execution_duration, 0), 0), 2) AS planning_pct_of_total,
  SUBSTR(query_string, 1, 200) AS query_preview
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
AND state_enum = 'SUCCEEDED'
ORDER BY query_planning_duration DESC
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

**Average execution time trend by work group** — Detect performance regressions by tracking weekly avg/p95 execution time:

```sql
SELECT
  work_group_name,
  DATE_TRUNC('week', submission_date_time) AS week_start,
  COUNT(*) AS query_count,
  AVG(COALESCE(total_execution_duration, 0)) / 1000.0 AS avg_duration_sec,
  APPROX_PERCENTILE(COALESCE(total_execution_duration, 0), 0.95) / 1000.0 AS p95_duration_sec,
  AVG(data_scanned_size) / POWER(1024, 2) AS avg_mb_scanned
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '90' DAY
AND state_enum = 'SUCCEEDED'
GROUP BY 1, 2
ORDER BY 1, 2
```

**Queue spike detection** — Hours where average queue time exceeds 2x the rolling average. This indicates periods where the full account quota is used:

```sql
WITH hourly_queue AS (
  SELECT
    DATE_TRUNC('hour', submission_date_time) AS hour,
    AVG(COALESCE(query_queue_time_duration, 0)) AS avg_queue_ms,
    COUNT(*) AS query_count
  FROM query_executions
  WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '14' DAY
  GROUP BY 1
),
with_baseline AS (
  SELECT
    *,
    AVG(avg_queue_ms) OVER (
      ORDER BY hour
      RANGE BETWEEN INTERVAL '7' DAY PRECEDING AND INTERVAL '1' HOUR PRECEDING
    ) AS rolling_avg_queue_ms
    FROM hourly_queue
)
SELECT
  hour,
  query_count,
  avg_queue_ms / 1000.0 AS avg_queue_sec,
  rolling_avg_queue_ms / 1000.0 AS rolling_avg_queue_sec,
  ROUND(avg_queue_ms / rolling_avg_queue_ms, 2) AS spike_ratio
FROM with_baseline
WHERE avg_queue_ms > 2 * rolling_avg_queue_ms
AND rolling_avg_queue_ms > 0
ORDER BY spike_ratio DESC
LIMIT 25
```

**Error spike detection** — Hours where failure rate exceeds 2x the rolling average:

```sql
WITH hourly_errors AS (
  SELECT
    work_group_name,
    DATE_TRUNC('hour', submission_date_time) AS hour,
    COUNT(*) AS total_queries,
    COUNT(*) FILTER (WHERE state_enum = 'FAILED') AS failed_queries,
    100.0 * COUNT(*) FILTER (WHERE state_enum = 'FAILED') / COUNT(*) AS failure_rate
  FROM query_executions
  WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '14' DAY
  GROUP BY work_group_name, DATE_TRUNC('hour', submission_date_time)
),
with_baseline AS (
  SELECT
    *,
    AVG(failure_rate) OVER (
      PARTITION BY work_group_name
      ORDER BY hour
      RANGE BETWEEN INTERVAL '7' DAY PRECEDING AND INTERVAL '1' HOUR PRECEDING
    ) AS rolling_avg_failure_rate
  FROM hourly_errors
)
SELECT
  work_group_name,
  hour,
  total_queries,
  failed_queries,
  ROUND(failure_rate, 2) AS failure_rate_pct,
  ROUND(rolling_avg_failure_rate, 2) AS rolling_avg_pct,
  ROUND(failure_rate / rolling_avg_failure_rate, 2) AS spike_ratio
FROM with_baseline
WHERE failure_rate > 2 * rolling_avg_failure_rate
AND rolling_avg_failure_rate > 0
AND total_queries >= 10  -- ignore low-volume hours
ORDER BY spike_ratio DESC
LIMIT 25
```

**Multi-table join complexity** — Queries accessing 5+ tables in a single execution — candidates for optimization or materialization:

```sql
SELECT
  query_execution_id,
  work_group_name,
  principal_arn,
  submission_date_time,
  CARDINALITY(tables_accessed) AS tables_count,
  COALESCE(total_execution_duration, 0) / 1000.0 AS duration_sec,
  data_scanned_size / POWER(1024, 3) AS gb_scanned,
  SUBSTR(query_string, 1, 300) AS query_preview
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
AND state_enum = 'SUCCEEDED'
AND CARDINALITY(tables_accessed) >= 5
ORDER BY CARDINALITY(tables_accessed) DESC, total_execution_duration DESC
LIMIT 25
```

**DPU efficiency** — Data scanned per DPU-second — low ratios may indicate over-provisioned queries:

```sql
SELECT
  work_group_name,
  query_execution_id,
  principal_arn,
  submission_date_time,
  dpu_count,
  data_scanned_size / POWER(1024.0, 2) AS mb_scanned,
  engine_execution_duration / 1000.0 AS engine_sec,
  data_scanned_size / POWER(1024.0, 2) / (dpu_count * engine_execution_duration / 1000.0) AS mb_per_dpu_second,
  SUBSTR(query_string, 1, 200) AS query_preview
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
AND state_enum = 'SUCCEEDED'
AND dpu_count > 0
AND data_scanned_size > 0
AND engine_execution_duration > 0
ORDER BY mb_per_dpu_second ASC
LIMIT 25
```

**Repeated identical queries without result reuse** — Same query text run multiple times in a short window without result reuse enabled. Either query result reuse was not enabled on these queries, or the time window was too short:

```sql
WITH query_groups AS (
  SELECT
    work_group_name,
    query_string,
    COUNT(*) AS repetition_count,
    MIN(submission_date_time) AS first_run,
    MAX(submission_date_time) AS last_run,
    SUM(data_scanned_size) / POWER(1024.0, 2) AS total_mb_scanned
  FROM query_executions
  WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
  AND state_enum = 'SUCCEEDED'
  AND statement_type_enum = 'DML'
  AND NOT result_reuse_enabled
  AND NOT reused_previous_result
  GROUP BY work_group_name, query_string
  HAVING COUNT(*) >= 3
)
SELECT
  work_group_name,
  repetition_count,
  total_mb_scanned,
  DATE_DIFF('minute', first_run, last_run) AS window_minutes,
  SUBSTR(query_string, 1, 200) AS query_preview
FROM query_groups
ORDER BY repetition_count DESC
LIMIT 25
```

## Auditing & Governance

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

**Find the principal that ran a specific query** — Look up a specific query execution by ID and find out who ran it, and in what work group:

```sql
SELECT
  query_execution_id,
  principal_arn,
  work_group_name,
  submission_date_time,
  completion_date_time,
  state_enum,
  statement_type_enum,
  data_scanned_size / POWER(1024.0, 2) AS mb_scanned,
  COALESCE(total_execution_duration, 0) / 1000.0 AS duration_sec,
  error_message,
  tables_accessed,
  query_string
FROM query_executions
WHERE query_execution_id = '<query-execution-id>' -- replace with the actual ID
```

**Sensitive table access log** — All queries touching specific sensitive tables. Replace the filter values with the target database and table names:

```sql
SELECT
  query_execution_id,
  submission_date_time,
  principal_arn,
  work_group_name,
  statement_type_enum,
  accessed_table.catalog_name,
  accessed_table.database_name,
  accessed_table.table_name,
  SUBSTR(query_string, 1, 300) AS query_preview
FROM query_executions
CROSS JOIN UNNEST(tables_accessed) AS t(accessed_table)
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
  AND accessed_table.database_name = 'sensitive_db' -- replace with the database
  AND accessed_table.table_name IN ('pii_table', 'financial_data') -- replace with the tables
ORDER BY submission_date_time DESC
```

**After-hours activity** — Queries submitted outside business hours by human principals (not service roles):

```sql
SELECT
  query_execution_id,
  submission_date_time,
  principal_arn,
  work_group_name,
  statement_type_enum,
  SUBSTR(query_string, 1, 200) AS query_preview
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
  AND (
    HOUR(submission_date_time) < 8 -- time is in UTC, change for local time zone
    OR HOUR(submission_date_time) >= 20 -- time is in UTC, change for local time zone
    OR DAY_OF_WEEK(submission_date_time) IN (6, 7)  -- Saturday, Sunday
  )
  AND principal_arn NOT LIKE '%:assumed-role/service-%' -- exclude service roles
  AND principal_arn NOT LIKE '%:assumed-role/lambda-%' -- exclude Lambda
ORDER BY submission_date_time DESC
```

**New principal detection** — First-ever query per principal (user) — surface new identities appearing in work groups. This query intentionally omits the `submission_date_time` partition filter in the inner CTE — finding a principal's true first appearance requires scanning all history, so it is the deliberate exception to the partition-pruning rule and can be expensive on large tables:

```sql
WITH first_seen AS (
  SELECT
    principal_arn,
    work_group_name,
    MIN(submission_date_time) AS first_query_time,
    COUNT(*) AS total_queries_since
  FROM query_executions
  GROUP BY principal_arn, work_group_name
)
SELECT
  principal_arn,
  work_group_name,
  first_query_time,
  total_queries_since
FROM first_seen
WHERE first_query_time >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
ORDER BY first_query_time DESC
```

**Work group access patterns** — Which principals are active in which work groups — detect unexpected cross-work group usage:

```sql
WITH principal_work_groups AS (
  SELECT
    principal_arn,
    ARRAY_AGG(DISTINCT work_group_name) AS work_groups_used,
    CARDINALITY(ARRAY_AGG(DISTINCT work_group_name)) AS work_group_count
  FROM query_executions
  WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
  GROUP BY principal_arn
)
SELECT
  principal_arn,
  work_group_count,
  work_groups_used
FROM principal_work_groups
WHERE work_group_count > 1
ORDER BY work_group_count DESC
```

**Query submission burst detection** — Principals submitting more than N queries within a 1-minute window, possibly indicating runaway automation:

```sql
WITH minutely AS (
  SELECT
    principal_arn,
    work_group_name,
    DATE_TRUNC('minute', submission_date_time) AS minute,
    COUNT(*) AS queries_in_minute
  FROM query_executions
  WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '7' DAY
  GROUP BY principal_arn, work_group_name, DATE_TRUNC('minute', submission_date_time)
)
SELECT
  principal_arn,
  work_group_name,
  minute,
  queries_in_minute
FROM minutely
WHERE queries_in_minute > 50 -- adjust threshold as needed
ORDER BY queries_in_minute DESC
LIMIT 25
```

**Table access breadth per principal** — Number of distinct tables accessed per principal over 30 days — unusually high breadth may warrant review:

```sql
SELECT
  principal_arn,
  COUNT(DISTINCT accessed_table.catalog_name || '.' || accessed_table.database_name || '.' || accessed_table.table_name) AS distinct_tables,
  COUNT(*) AS total_queries,
  COUNT(DISTINCT accessed_table.database_name) AS distinct_databases
FROM query_executions
CROSS JOIN UNNEST(tables_accessed) AS t(accessed_table)
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
GROUP BY principal_arn
ORDER BY distinct_tables DESC
LIMIT 25
```

**Failed query ratio by principal** — Principals with high failure rates may indicate misconfigured tooling or permissions issues:

```sql
SELECT
  principal_arn,
  work_group_name,
  COUNT(*) AS total_queries,
  COUNT(*) FILTER (WHERE state_enum = 'FAILED') AS failed_queries,
  ROUND(100.0 * COUNT(*) FILTER (WHERE state_enum = 'FAILED') / COUNT(*), 2) AS failure_rate_pct
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
GROUP BY principal_arn, work_group_name
HAVING COUNT(*) >= 10  -- only principals with meaningful volume
ORDER BY failure_rate_pct DESC
LIMIT 25
```

**Work group SLA compliance** — Percentage of queries completing within target thresholds per work group:

```sql
SELECT
  work_group_name,
  COUNT(*) AS total_queries,
  ROUND(100.0 * COUNT(*) FILTER (WHERE COALESCE(total_execution_duration, 0) <= 5000) / COUNT(*), 2) AS pct_under_5s,
  ROUND(100.0 * COUNT(*) FILTER (WHERE COALESCE(total_execution_duration, 0) <= 30000) / COUNT(*), 2) AS pct_under_30s,
  ROUND(100.0 * COUNT(*) FILTER (WHERE COALESCE(total_execution_duration, 0) <= 60000) / COUNT(*), 2) AS pct_under_60s,
  ROUND(100.0 * COUNT(*) FILTER (WHERE COALESCE(total_execution_duration, 0) <= 300000) / COUNT(*), 2) AS pct_under_5m,
  APPROX_PERCENTILE(COALESCE(total_execution_duration, 0), 0.5) / 1000.0 AS p50_sec,
  APPROX_PERCENTILE(COALESCE(total_execution_duration, 0), 0.99) / 1000.0 AS p99_sec
FROM query_executions
WHERE submission_date_time >= CURRENT_TIMESTAMP - INTERVAL '30' DAY
AND state_enum = 'SUCCEEDED'
GROUP BY work_group_name
ORDER BY pct_under_30s ASC
```
