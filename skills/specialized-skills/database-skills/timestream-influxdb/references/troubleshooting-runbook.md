# Troubleshooting Runbook

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
| `TLS handshake failure` | Certificate mismatch or expired | Use the endpoint's TLS certificate; verify the system CA bundle is up to date |
| `connection timeout` | Instance in different VPC or subnet | Verify VPC peering, route tables, and NACLs. Private instances are not reachable from the public internet |
| `401 Unauthorized` | Invalid, expired, or incorrectly scoped API token | Verify the documented token type and scope for the engine variant, regenerate it through the documented console or API flow, immediately store the replacement in AWS Secrets Manager, update authorized clients, and revoke the superseded token. Follow the [getting-started token workflow](getting-started.md#3-retrieve-token) |
| `connection reset by peer` | Instance restarting (maintenance) | Retry with backoff. Check if maintenance window is active |

## Write Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `413 Request Entity Too Large` | Batch exceeds max payload size | Check the documented payload limit for the selected engine variant, then reduce the batch size below that limit |
| `429 Too Many Requests` | Write rate limit exceeded | Validate line-protocol writes as required by [security best practices](security-best-practices.md#network-isolation). Apply client-side rate and concurrency limits plus exponential backoff with jitter; honor `Retry-After` only when the service documentation defines it. Before resizing, verify supported instance classes and workload limits |
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

- Verify the [private-cluster S3 prerequisites](https://docs.aws.amazon.com/timestream/latest/developerguide/s3-vpc-endpoint-private-clusters.html) and read `publiclyAccessible` from `GetDbCluster` before diagnosing
- When the documentation requires an S3 VPC endpoint, inspect its type, state, service name, VPC ownership, and `RouteTableIds`, plus every selected subnet's effective route table
- See [S3 VPC endpoint troubleshooting](s3-vpc-endpoint-troubleshooting.md) for details and remediation

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
