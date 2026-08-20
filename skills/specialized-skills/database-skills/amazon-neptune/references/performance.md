# Neptune Performance and Cost Optimization

## Instance sizing

Neptune uses r-series (memory-optimized) instances. The graph must fit in
memory for best performance — Neptune caches the working set in the buffer pool.

| Instance | vCPU | RAM | Use for |
|---|---|---|---|
| db.r6g.large | 2 | 16 GB | Dev/test, small graphs |
| db.r6g.xlarge | 4 | 32 GB | Small production (< 10GB graph) |
| db.r6g.2xlarge | 8 | 64 GB | Medium production |
| db.r6g.4xlarge | 16 | 128 GB | Large graphs, complex traversals |
| db.r6g.8xlarge | 32 | 256 GB | Very large graphs |

**Rule of thumb**: provision RAM ≥ 2× your graph data size. If your graph
is 20 GB, use at least a db.r6g.2xlarge (64 GB RAM).

## Neptune Serverless vs. provisioned

| Factor | Serverless | Provisioned |
|---|---|---|
| Traffic pattern | Spiky, unpredictable | Steady, predictable |
| Cold start tolerance | Yes | N/A |
| Cost at low utilization | Lower (scales to ~0) | Higher (always-on) |
| Latency predictability | Variable | Consistent |
| Max capacity | 128 NCUs | Instance-bound |

Use Serverless for: dev/test environments, infrequent batch jobs, new projects
with unknown traffic.

Use provisioned for: production apps with SLA requirements, sustained load.

## Read replicas

Add read replicas to scale read throughput and reduce load on the primary:

```bash
aws neptune create-db-instance \
  --db-instance-identifier neptune-reader-1 \
  --db-instance-class db.r6g.xlarge \
  --engine neptune \
  --db-cluster-identifier your-cluster \
  --tags Key=created_by,Value=neptune-skill Key=generation_model,Value=<model-id>
```

Route read queries to the **reader endpoint** — Neptune load-balances across
all replicas automatically.

## Query optimization

### Use has() filters before traversal steps

```groovy
// Filters the SOURCE set first (Seattle people), then traverses — fewer edges:
g.V().hasLabel('Person').has('city', 'Seattle').out('KNOWS')   // friends of Seattle people

// Filters the TARGET after traversal — a DIFFERENT result set, not just slower:
g.V().hasLabel('Person').out('KNOWS').has('city', 'Seattle')   // Seattle-dwelling friends
```

Filter placement changes **which** vertices the predicate applies to (source
vs. target), so it affects correctness, not just performance. When a predicate
applies to the source vertex, push it before `out()` to shrink the working set
early; do not move a `has()` across a traversal step if that would change which
vertices it filters.

### Place limit() early in traversal

```groovy
// ❌ Traverses full graph, returns 10
g.V().hasLabel('Person').repeat(out('KNOWS')).times(3).limit(10)

// ✅ Limits fan-out at each step
g.V().hasLabel('Person').limit(100)
  .repeat(out('KNOWS').limit(10))
  .times(3)
  .limit(10)
```

### Use simplePath() to avoid cycles

```groovy
// Without simplePath(), traversal can loop forever in cyclic graphs
g.V().has('Account', 'id', 'A1')
  .repeat(out('SENT_TO').simplePath())  // simplePath prevents revisiting
  .times(5)
  .values('id')
```

### Profile slow queries

```groovy
// Add .profile() to any traversal
g.V().hasLabel('Person').out('KNOWS').out('KNOWS').profile()

// Key metrics to watch:
// traversedEdges — high = too much fan-out
// elementCount — high = too many vertices loaded
// duration — per step, identifies bottleneck
```

## Cost optimization

### Use Neptune Serverless for non-production

Serverless scales to near-zero when idle. For dev/test clusters that run
8 hours/day, cost is ~60-70% lower than always-on provisioned instances.

### Choose the right storage type

Neptune uses SSD-backed distributed storage billed per GB-month. Storage
auto-grows — there is no manual allocation.

- Delete unused graph data with periodic TTL jobs (Neptune has no built-in TTL)
- Archive cold data to S3; reload into Neptune Analytics for batch analysis

### Right-size reader replicas

Reader replicas can use a **different (smaller) instance class** than the
writer. This is a common cost optimization — use a large writer for writes
and smaller readers for read-heavy workloads. Avoid over-provisioning readers
for infrequent read workloads — Neptune Serverless is often cheaper.

### Monitor with CloudWatch

Key metrics:

```
GremlinRequestsPerSec — query throughput
GremlinErrors          — error rate
BufferCacheHitRatio    — target > 95%; below this = working set exceeds RAM
CPUUtilization         — sustained > 80% = need larger instance
FreeableMemory         — low = need more RAM
DBClusterReplicaLag    — replication lag to read replicas
```

```bash
# Alert on low cache hit ratio
aws cloudwatch put-metric-alarm \
  --alarm-name NeptuneBufferCacheHitRatioLow \
  --metric-name BufferCacheHitRatio \
  --namespace AWS/Neptune \
  --statistic Average \
  --period 300 \
  --threshold 90 \
  --comparison-operator LessThanThreshold \
  --evaluation-periods 3 \
  --alarm-actions arn:aws:sns:...
```

## Common Mistakes

1. **Under-provisioning RAM** — graph should fit in memory (2× data size rule).
2. **Not using reader endpoint** — read queries should go to reader, not cluster endpoint.
3. **Over-provisioning readers** — readers can be smaller than writer instance.
4. **Ignoring BufferCacheHitRatio** — below 95% means working set exceeds RAM.
5. **Using Serverless for latency-sensitive production** — cold starts add seconds.

## Additional Resources

- AWS docs: "Neptune instance types", "Neptune Serverless", "Neptune CloudWatch metrics"
- Related sub-skills: `troubleshooting` (slow queries), `querying` (optimization patterns)
- CloudWatch dashboard: create one with GremlinRequestsPerSec, BufferCacheHitRatio, CPUUtilization
