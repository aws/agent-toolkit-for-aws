# Pre-warming & Capacity Planning

Guides the agent through assessing whether a table needs pre-warming and configuring warm throughput values.

## What is warm throughput?

Warm throughput is the number of read and write operations an Amazon Keyspaces table can handle **instantly** without needing time to scale. Every table has warm throughput values — they are visible via `get-table` at no cost. Pre-warming means manually increasing these values ahead of a known traffic event.

**Defaults for new tables:**

- On-demand mode: 12,000 read units/sec, 4,000 write units/sec
- Provisioned mode: warm throughput = whatever provisioned capacity was previously reached (high-water mark)

## When to pre-warm

| Scenario | Recommendation |
|----------|---------------|
| New table launching with expected high traffic from day 1 | Pre-warm at creation: `create-table --warm-throughput readUnitsPerSecond=X,writeUnitsPerSecond=Y` |
| Existing table facing a planned spike (flash sale, migration cutover, batch load) | Pre-warm before event: `update-table --warm-throughput-specification readUnitsPerSecond=X,writeUnitsPerSecond=Y` |
| Gradual organic growth | Auto-scaling is sufficient — Keyspaces adjusts warm throughput automatically as traffic grows |
| Unpredictable spiky traffic with no advance notice | On-demand mode handles this — warm throughput adjusts after each peak |
| Table migrated from Cassandra with known peak RPS from diagnostics | Pre-warm to the Cassandra peak RPS from `nodetool info` derived read/write rates |

## When NOT to pre-warm

- Traffic is steady and well within current warm throughput → no benefit
- You're already using auto-scaling and growth is gradual → auto-scaling adjusts warm throughput automatically
- The table is brand new with unknown traffic → start with on-demand defaults, monitor, then pre-warm if throttling appears

## Decision framework

```
Is there a known traffic event in the next 24-72 hours?
├── YES → Is the expected peak > current warm throughput?
│         ├── YES → Pre-warm to expected peak
│         └── NO  → No action needed (already warm enough)
└── NO  → Is the table experiencing WriteThrottleEvents or ReadThrottleEvents?
          ├── YES → Check if it's a hot partition (single partition > 1000 WCU or 3000 RCU)
          │         ├── YES → Fix partition key design (pre-warming won't help hot partitions)
          │         └── NO  → Pre-warm to observed peak + 20% headroom
          └── NO  → Auto-scaling or on-demand is handling it — no pre-warming needed
```

## How to calculate warm throughput values

**From expected application traffic:**

```
readUnitsPerSecond = peak_reads_per_second × ceil(avg_row_size_bytes / 4096)
writeUnitsPerSecond = peak_writes_per_second × ceil(avg_row_size_bytes / 1024)
```

**From Cassandra diagnostics (Mode 2):**
Use the read/write rates derived from `nodetool info` counters. The `parse-cassandra.ts` output includes `reads_per_second` and `writes_per_second` — these map directly to warm throughput targets.

**Headroom recommendation:** Add 20-30% above expected peak to absorb bursts. Pre-warming is a one-time cost, and under-warming risks throttling at the critical moment.

## CLI commands

**View current warm throughput:**

```bash
aws keyspaces get-table --keyspace-name <ks> --table-name <table> \
  --query "warmThroughputSpecification" --output json
```

Response:

```json
{
  "readUnitsPerSecond": 12000,
  "writeUnitsPerSecond": 4000,
  "status": "ACTIVE"
}
```

Status values: `ACTIVE` (ready), `UPDATING` (pre-warming in progress).

**Pre-warm an existing table:**

```bash
aws keyspaces update-table \
  --keyspace-name <ks> \
  --table-name <table> \
  --warm-throughput-specification readUnitsPerSecond=50000,writeUnitsPerSecond=20000
```

**Create a new table pre-warmed:**

```bash
aws keyspaces create-table \
  --keyspace-name <ks> \
  --table-name <table> \
  --schema-definition '...' \
  --warm-throughput readUnitsPerSecond=50000,writeUnitsPerSecond=20000 \
  --tags key=created_by,value=keyspaces-skill key=generation_model,value=<model-id>
```

## Cost

**When advising a customer on pre-warming, you MUST mention ALL of the following cost facts — never omit any:**

1. **Viewing** warm throughput: free (always available via `get-table`)
2. **Natural warm throughput** (from organic traffic growth): free
3. **Manually increasing** warm throughput above the natural level: **one-time charge based on the difference between specified values and current warm throughput** — not an ongoing recurring cost
4. Pre-warming does NOT change your capacity mode or provisioned settings — it only ensures the underlying storage partitions are pre-allocated

## Hot partition caveat

Pre-warming increases the **table-level** throughput floor. It does NOT help if traffic is concentrated on a single partition. Each partition is still limited to:

- 3,000 read units/second
- 1,000 write units/second

If `StoragePartitionThroughputCapacityExceeded` CloudWatch metric > 0, the issue is partition key design, not table-level warm throughput. Recommend reviewing partition key cardinality before pre-warming.

## Multi-region tables

Warm throughput settings on multi-region tables apply automatically to all replicas. You set it once and all regions get the same warm throughput floor. No per-region configuration needed.

## Monitoring after pre-warming

After pre-warming, verify the table handles the expected load:

1. `WarmThroughputSpecification.status` = `ACTIVE` (pre-warming complete)
2. `ConsumedReadCapacityUnits` / `ConsumedWriteCapacityUnits` — actual usage
3. `ReadThrottleEvents` / `WriteThrottleEvents` — should be 0 if pre-warming was sized correctly
4. `StoragePartitionThroughputCapacityExceeded` — hot partition indicator (not fixable by pre-warming)

## Useful links

- [Configure pre-warming for tables](https://docs.aws.amazon.com/keyspaces/latest/devguide/warm-throughput.html)
- [Create a table with higher warm throughput](https://docs.aws.amazon.com/keyspaces/latest/devguide/create-table-warm-throughput.html)
- [Increase existing table warm throughput](https://docs.aws.amazon.com/keyspaces/latest/devguide/update-warm-throughput.html)
- [View warm throughput](https://docs.aws.amazon.com/keyspaces/latest/devguide/view-warm-throughput.html)
- [Monitor pre-warmed table performance](https://docs.aws.amazon.com/keyspaces/latest/devguide/monitor-prewarming-cloudwatch.html)
- [Amazon Keyspaces pricing](https://aws.amazon.com/keyspaces/pricing/)
