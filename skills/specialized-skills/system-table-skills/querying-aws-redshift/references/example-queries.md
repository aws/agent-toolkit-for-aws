# Example Queries Against Published `SYS_*` System Tables

Loaded on demand from `querying-aws-redshift` SKILL.md. Timing columns are **microseconds** — divide by 1,000,000 for seconds. Confirm the namespace from the status API before substituting it below; never hand-construct it.

## Top 10 longest-running queries in the last 7 days (Athena)

```sql
SELECT query_id,
       username,
       database_name,
       query_type,
       round(elapsed_time / 1000000.0, 2) AS elapsed_sec,
       round(queue_time / 1000000.0, 2) AS queue_sec,
       round(execution_time / 1000000.0, 2) AS exec_sec,
       start_time,
       substr(query_text, 1, 120) AS query_preview
FROM "s3tablescatalog/aws-redshift"."<NAMESPACE>"."sys_query_history"
WHERE start_time > current_timestamp - interval '7' day
  AND status = 'success'
ORDER BY elapsed_time DESC
LIMIT 10;
```

## Same query from Redshift (auto-mounted catalog)

```sql
SELECT query_id,
       username,
       database_name,
       query_type,
       round(elapsed_time / 1000000.0, 2) AS elapsed_sec,
       round(queue_time / 1000000.0, 2) AS queue_sec,
       round(execution_time / 1000000.0, 2) AS exec_sec,
       start_time,
       substring(query_text, 1, 120) AS query_preview
FROM "aws-redshift@s3tablescatalog"."<NAMESPACE>".sys_query_history
WHERE start_time > current_timestamp - interval '7 day'
  AND status = 'success'
ORDER BY elapsed_time DESC
LIMIT 10;
```

## Query volume and latency percentiles by hour

```sql
SELECT hour(start_time) AS hour_of_day,
       count(*) AS query_count,
       round(approx_percentile(elapsed_time, 0.50) / 1000000.0, 2) AS p50_sec,
       round(approx_percentile(elapsed_time, 0.95) / 1000000.0, 2) AS p95_sec
FROM "s3tablescatalog/aws-redshift"."<NAMESPACE>"."sys_query_history"
WHERE start_time > current_timestamp - interval '7' day
GROUP BY hour(start_time)
ORDER BY hour_of_day;
```

## Most expensive repeated query shapes

```sql
SELECT generic_query_hash,
       count(*) AS executions,
       round(sum(elapsed_time) / 1000000.0, 1) AS total_sec,
       round(avg(elapsed_time) / 1000000.0, 2) AS avg_sec,
       arbitrary(substr(query_text, 1, 120)) AS sample_query
FROM "s3tablescatalog/aws-redshift"."<NAMESPACE>"."sys_query_history"
WHERE start_time > current_timestamp - interval '7' day
  AND query_type = 'SELECT'
GROUP BY generic_query_hash
ORDER BY total_sec DESC
LIMIT 10;
```

## Failed authentication attempts

```sql
SELECT user_name,
       remote_host,
       count(*) AS failed_attempts,
       min(record_time) AS first_seen,
       max(record_time) AS last_seen
FROM "s3tablescatalog/aws-redshift"."<NAMESPACE>"."sys_connection_log"
WHERE event = 'authentication failure'
  AND record_time > current_timestamp - interval '30' day
GROUP BY user_name, remote_host
ORDER BY failed_attempts DESC
LIMIT 20;
```

## Reassemble full text of a long query

```sql
SELECT query_id,
       array_join(array_agg(text ORDER BY sequence), '') AS full_query_text
FROM "s3tablescatalog/aws-redshift"."<NAMESPACE>"."sys_query_text"
WHERE query_id = <QUERY_ID>
GROUP BY query_id;
```

## Correlate expensive queries with client origin

```sql
SELECT qh.query_id,
       qh.username,
       round(qh.elapsed_time / 1000000.0, 2) AS elapsed_sec,
       cl.remote_host,
       cl.application_name,
       cl.driver_version
FROM "s3tablescatalog/aws-redshift"."<NAMESPACE>"."sys_query_history" qh
LEFT JOIN "s3tablescatalog/aws-redshift"."<NAMESPACE>"."sys_connection_log" cl
       ON qh.session_id = cl.session_id
      AND cl.event = 'initiating session'
WHERE qh.start_time > current_timestamp - interval '1' day
ORDER BY qh.elapsed_time DESC
LIMIT 15;
```
