# Monitoring Metrics for Amazon Timestream for InfluxDB

## CRITICAL RULE: NEVER INVENT METRIC NAMES
Only use metric names from the authoritative tables below.
If you are unsure whether a metric exists, say so explicitly.
Do NOT paraphrase, abbreviate, or PascalCase a metric name unless the
authoritative table shows it in that form.

---

## PART 1 — UNDERSTAND THE COVERAGE GAP FIRST

Before recommending any metric, determine:

1. Which engine? InfluxDB 2 (TSM) or InfluxDB 3 (Parquet/Arrow)?
2. Which deployment mode? SAZ, MAZ, Read Replica (v2 only)?
3. Which monitoring path? CloudWatch (managed, no scraping) or
   Prometheus /metrics endpoint (self-managed scraping)?

The coverage differs significantly:

| Deployment            | CloudWatch coverage        | /metrics endpoint coverage |
|-----------------------|---------------------------|---------------------------|
| InfluxDB 2 SAZ / MAZ  | RICH (see Part 2A)         | RICH (see Part 2B)         |
| InfluxDB 2 Read Replica | LIMITED: CPUUtilization, MemoryUtilization, DiskUtilization, ReplicaLag only | RICH (same as SAZ/MAZ) |
| InfluxDB 3 (all)      | LIMITED: CPUUtilization, MemoryUtilization only | RICH (see Part 3B) |

If the customer needs metrics not available in CloudWatch for their
deployment, tell them: "That metric is not available in CloudWatch for
this deployment type. Use the Prometheus /metrics endpoint instead."

---

## PART 2A — InfluxDB 2: CloudWatch Metric Names (AUTHORITATIVE)

Use these EXACT names when discussing CloudWatch. Format: CloudWatchName.

### Compute & Storage

- CPUUtilization
- MemoryUtilization
- DiskUtilization
- VolumeBytesUsed  ← storage consumed on EBS, NOT InfluxDB data size
- ReadIOpsPerSec, WriteIOpsPerSec, TotalIOpsPerSec
- ReadThroughput, WriteThroughput

### InfluxDB Engine (published to customer CloudWatch namespace)

- EngineUptime
- TotalBuckets
- WriteTimeouts
- ActiveTaskWorkers
- TaskExecutionFailures
- ActiveMemoryAllocation
- HeapMemoryUsage
- QueryRequestsTotal
- SeriesCardinality
- APIRequestRate
- QueryResponseVolume

### Read Replica only

- ReplicaLag  ← only available on Read Replica deployments

WRONG names (do NOT use): WriteRequestsTotal, QueryLatency,
StorageUtilization, influxdb_write_requests, ReadLatency, WriteLatency.

---

## PART 2B — InfluxDB 2: Prometheus /metrics Endpoint Names (AUTHORITATIVE)

Use these EXACT names when discussing the /metrics scrape endpoint.
These are Prometheus-format names (snake_case, with_total/_seconds/_bytes suffixes).

| Concern              | Metric name                                      |
|----------------------|--------------------------------------------------|
| Uptime               | influxdb_uptime_seconds                          |
| Bucket count         | influxdb_buckets_total                           |
| Write timeouts       | storage_writer_timeouts                          |
| Task workers active  | task_executor_total_runs_active                  |
| Task failures        | task_scheduler_total_execute_failure             |
| Memory (alloc)       | go_memstats_alloc_bytes                          |
| Memory (heap)        | go_memstats_heap_alloc_bytes                     |
| Query count          | qc_requests_total                                |
| Query exec duration  | qc_executing_duration_seconds  (histogram)       |
| Query all duration   | qc_all_duration_seconds        (histogram)       |
| Series cardinality   | storage_bucket_series_num                        |
| HTTP request rate    | http_api_requests_total                          |
| Query response bytes | http_query_response_bytes                        |
| Query read duration  | query_influxdb_source_read_request_duration_seconds (histogram) |

WRONG names (do NOT use): influxdb_write_requests, ReadLatency,
WriteLatency, QueryLatency, StorageUtilization, WriteRequestsTotal.

---

## PART 3A — InfluxDB 3: CloudWatch Metric Names (AUTHORITATIVE)

CloudWatch coverage for InfluxDB 3 is LIMITED to:

- CPUUtilization
- MemoryUtilization

All other monitoring for InfluxDB 3 must use the /metrics endpoint.
Do NOT tell a customer to find write throughput, query latency, or
cardinality in CloudWatch for InfluxDB 3 — those are not there.

---

## PART 3B — InfluxDB 3: Prometheus /metrics Endpoint Names (AUTHORITATIVE)

### Tier 1 — Critical (always check these first)

| Concern                    | Metric name                                        |
|----------------------------|----------------------------------------------------|
| Write throughput (lines)   | influxdb3_write_lines_total                        |
| Write throughput (bytes)   | influxdb3_write_bytes_total                        |
| Rejected writes            | influxdb3_write_lines_rejected_total               |
| Query OOM errors           | query_datafusion_query_execution_ooms_total        |
| DataFusion memory pool     | datafusion_mem_pool_bytes                          |
| HTTP request count         | http_requests_total                                |
| HTTP request latency       | http_request_duration_seconds  (histogram)         |
| Query execution duration   | influxdb_iox_query_log_execute_duration_seconds    |
| Query max memory           | influxdb_iox_query_log_max_memory                  |

### Tier 2 — Performance Optimization

| Concern                    | Metric name                                        |
|----------------------------|----------------------------------------------------|
| Parquet cache size         | influxdb3_parquet_cache_size_bytes                 |
| Parquet cache accesses     | influxdb3_parquet_cache_access_total               |
| Object store op duration   | object_store_op_duration_seconds                   |
| Object store bytes         | object_store_transfer_bytes_total                  |
| Replication lag (MAZ only) | influxdb3_replica_ttbr_duration_seconds            |

### Tier 3 — Stability & Health

| Concern                    | Metric name                                        |
|----------------------------|----------------------------------------------------|
| Thread panics              | thread_panic_count_total                           |
| Catalog retries            | influxdb3_catalog_operation_retries_total          |
| Allocator memory           | jemalloc_memstats_bytes                            |
| gRPC duration (multi-node) | grpc_request_duration_seconds                      |

### InfluxDB 3 WAL / Ingest detail metrics (from /metrics)
influxdb3_wal_flush_latency_seconds, influxdb3_wal_bytes_flushed_total,
influxdb3_wal_rows_flushed_total, influxdb3_wal_flush_total,
influxdb3_snapshot_bytes_written_total, influxdb3_snapshot_total

### Important distinctions for InfluxDB 3 /metrics

- influxdb3_write_bytes_total = cumulative RAW BYTES WRITTEN, NOT database
  size on disk
- object_store_transfer_bytes_total = cumulative object store I/O
  (reads + writes combined), NOT current storage used
- For ACTUAL storage size: query the system table → SELECT * FROM
  system.parquet_files

---

## PART 4 — HOW TO GUIDE A CUSTOMER: DECISION TREE

### Path A — Customer wants CloudWatch monitoring (no scraping)

Step 1: Confirm engine and deployment type (v2 SAZ/MAZ, v2 Read Replica,
        v3).
Step 2: Tell them which metrics ARE available in CloudWatch for that type
        (use tables in Part 2A or 3A above).
Step 3: For metrics NOT in CloudWatch, tell them explicitly: "This metric
        is not published to CloudWatch for [deployment type]. You will
        need to scrape the /metrics endpoint to get it."
Step 4: For CloudWatch alerting/scaling, direct them to:
        https://docs.aws.amazon.com/timestream/latest/developerguide/timestream-influxdb-cloudwatch.html
Step 5: ⚠️ WARN about CloudWatch custom metric cost. A misconfigured
        Telegraf sending raw data (not just /metrics) as CloudWatch
        custom metrics can cause unexpectedly high bills.
        Always verify Telegraf is scraping only the /metrics endpoint,
        not forwarding raw write traffic.

### Path B — Customer wants to scrape the /metrics endpoint

Step 1: The endpoint is available at: http://`<instance-endpoint>`:8086/metrics
        (InfluxDB 2) or the configured HTTP port (InfluxDB 3).
Step 2: Authentication: pass the operator/admin token as a Bearer token
        in the Authorization header.
Step 3: Use a Prometheus scraper or Telegraf with inputs.prometheus
        plugin pointing to the /metrics URL.
Step 4: Use ONLY the metric names from Part 2B (v2) or Part 3B (v3).
Step 5: To store scraped metrics back into InfluxDB or forward to
        CloudWatch, use outputs.influxdb_v2 or outputs.cloudwatch in
        Telegraf — but verify output configuration carefully (see Step 5
        in Path A warning above).
Step 6: For InfluxDB 3 storage size specifically, use the SQL system
        table query instead of a /metrics metric:
        SELECT * FROM system.parquet_files
