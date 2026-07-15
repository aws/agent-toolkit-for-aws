# Troubleshooting

## When to Activate

User reports errors, connection failures, query problems, write failures, performance issues, or unexpected behavior with Timestream for InfluxDB.

## Diagnostic Workflow

1. **Identify the engine** — V2, V2 Read Replica, or V3. Error formats and APIs differ.
2. **Classify the error** — Connection, write, query, or operational.
3. **Check the error table below** for known issues and fixes.
4. **If not found**, check CloudWatch metrics (route to `monitoring`) and instance status.

## Connection Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `connection refused` on port 8086/8181 | Security group missing inbound rule | Add inbound rule for port 8086 (V2) or 8181 (V3) from client CIDR. For publicly accessible instances, the default SG blocks all inbound — you must explicitly allow traffic. For private instances, client must be in the same VPC or connected network |
| `TLS handshake failure` | Certificate mismatch or expired | Use the endpoint's TLS certificate; verify system CA bundle is current |
| `connection timeout` | Instance in different VPC or subnet | Verify VPC peering, route tables, and NACLs. Private instances are not reachable from the public internet |
| `401 Unauthorized` | Invalid or expired API token | Regenerate token via console or API. V2: org-scoped tokens. V3: database-scoped tokens |
| `connection reset by peer` | Instance restarting (maintenance) | Retry with backoff. Check if maintenance window is active |

## Write Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `413 Request Entity Too Large` | Batch exceeds max payload size | Reduce batch size. V2: 50MB max. V3: check current limits |
| `429 Too Many Requests` | Write rate limit exceeded | Implement exponential backoff. Consider larger instance type |
| `partial write: field type conflict` (V2) | Field type changed (int → float) | Field types are immutable per measurement in V2. Drop and recreate, or use a new field name |
| `write timeout` | Instance under heavy load or undersized | Check CPU/memory metrics. Scale up instance type or reduce write batch size |

## Query Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `500 Internal Server Error: datafusion error` (V3) | Query engine error, often with Parquet files | Check for corrupted Parquet segments. File a support ticket with the full error |
| `Execution error for 'deduplicate batches'` (V3) | Parquet object not found during deduplication | Known issue under high load. Retry the query. If persistent, contact support |
| `query timeout` | Query scanning too much data | Add time range filters. Use `LIMIT`. Check if indexes exist for filter columns |
| `memory allocation limit exceeded` (V2) | Flux query consuming too much memory | Add `\|> limit()` earlier in the pipeline. Reduce time range. Use `\|> aggregateWindow()` to downsample |
| `bucket not found` (V2) / `database not found` (V3) | Wrong bucket/database name or wrong API version | Verify the name. Ensure you're using the correct API (V2 API for V2, V3 API for V3) |

## Performance Issues

| Symptom | Likely Cause | Investigation |
|---------|-------------|---------------|
| Slow queries | Missing indexes, full table scans | V3: Check `EXPLAIN` output. Add field indexes for WHERE clause columns |
| High write latency | Instance undersized or disk I/O saturated | Check `WriteIOpsPerSec`, `WriteThroughput`, and `DiskUtilization` in CloudWatch (V2) or scrape `/metrics` (V3) |
| Increasing disk usage | No retention policy or retention too long | V2: Check bucket retention. V3: Check database retention period |
| Storage full on Read Replica Cluster | Storage cannot be scaled on RR clusters | Read Replica Clusters do not support storage scaling. Must create a new cluster with larger storage and migrate. V2 SAZ/MAZ instances do support scaling. |
| High CPU sustained | Compaction backlog or heavy query load | Check `qc_requests_total` and `qc_executing_duration_seconds` (V2 /metrics). Consider read replicas for query offloading |
| Replication lag (Read Replicas) | Write volume exceeding replication throughput | Monitor `ReplicaLag` metric. Scale up instance type |

## InfluxDB 3 Specific Issues

**S3 VPC Endpoint (V3 private subnets):**

- V3 requires an S3 VPC Gateway Endpoint in the same account VPC for private deployments
- See `references/troubleshooting/s3-vpc-endpoint.md` for details and fix
- Use `scripts/check_vpc_endpoints.sh` to verify

**Deduplication errors:**

- InfluxDB 3 deduplicates on all tags + timestamp
- If you see unexpected data loss, check if two writes have identical tag sets and timestamps
- Add a distinguishing tag or use nanosecond-precision timestamps

**Parquet errors under load:**

- `Object at location ... not found` during queries indicates a compaction race condition
- Retry the query. If persistent across multiple queries, file a support ticket
- Include: cluster ID, region, time of error, full error message, query that triggered it

**Processing Engine plugin failures:**

- Check plugin logs via the InfluxDB 3 API
- Common: Python dependency not available in the sandboxed environment
- Route to `processing-engine` for plugin-specific troubleshooting

## Escalation Path

If the issue cannot be resolved with the above:

1. Gather: instance/cluster ID, region, timestamps of errors, full error messages, CloudWatch metrics screenshots
2. Open an AWS Support case under Timestream for InfluxDB
3. For critical production issues, request Sev-2 with business impact description
