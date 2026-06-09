# Cost and Usage Reporting

Guide for understanding, monitoring, and optimizing ElastiCache costs across serverless and node-based deployments.

## Cost Spike Investigation

When a user reports unexpected cost increase, follow this sequence:

1. **Identify which component spiked.** Check Cost Explorer grouped by usage type:

   ```bash
   aws ce get-cost-and-usage \
     --time-period Start=<spike-start>,End=<today> \
     --granularity DAILY \
     --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon ElastiCache"]}}' \
     --metrics "UnblendedCost" \
     --group-by Type=DIMENSION,Key=USAGE_TYPE
   ```

2. **Map the usage type to the cause:**
   - `ElastiCache:ECPU` spiked: check `ElastiCacheProcessingUnits` metric (serverless only) for traffic increase or inefficient commands. For node-based clusters, use command-level metrics such as `GetTypeCmds`, `SetTypeCmds`, etc.
   - `ElastiCache:DataStorage` spiked: check `BytesUsedForCache` for data growth without TTLs
   - `ElastiCache:NodeUsage` spiked: new nodes added (scaling event or parameter change)
   - `DataTransfer` spiked: cross-AZ traffic increased (new replicas, or app moved AZs)
   - `CloudWatch:Logs` spiked: log delivery enabled recently (see log-delivery.md cost warning)
3. **Correlate with timeline.** Check `describe-events` and CloudTrail for changes around the spike start date.

## Serverless Cost Drivers

| Cost Component | Description | How to Monitor |
|---------------|-------------|----------------|
| ECPUs consumed | ElastiCache Processing Units measure compute consumption per command; charged per million ECPUs | CloudWatch `ElastiCacheProcessingUnits` metric; `ThrottledCmds` indicates hitting limits |
| Data storage (GB) | Billed per GB-hour of data stored in the cache | CloudWatch `BytesUsedForCache` metric |
| Network transfer | Standard AWS data transfer charges for cross-AZ and internet-bound traffic | AWS Cost Explorer with usage type filters |

**Serverless minimum cost:** Approximately $6/month for a Valkey serverless cache with minimal traffic in us-east-1. Serverless Valkey caches bill for a minimum of 100 MB storage even with zero stored data, resulting in a baseline cost when the cache exists (Memcached and Redis OSS serverless bill for a minimum of 1 GB).

**Minimum usage limits (pre-scaling):** When you set a minimum usage limit (for ECPUs/second or data storage), you are charged for that minimum even if your actual usage is lower. For example, setting a minimum of 100,000 ECPUs/second costs 360 million ECPUs/hour at the per-ECPU rate for your engine (Valkey rates are lower than Redis OSS). Use `scripts/price_calculator.py --engine valkey --mode serverless` to calculate the exact hourly cost for your region. Be aware of this when configuring pre-scaling minimums to avoid unexpected charges.

## Node-Based Cost Drivers

| Cost Component | Description | How to Monitor |
|---------------|-------------|----------------|
| Instance hours | Billed per node per hour based on instance type; primary + replicas each incur charges | AWS Cost Explorer filtered by ElastiCache service |
| Reserved node discounts | Reserved nodes save approximately 30-55% depending on term length and payment option (run `python3 scripts/price_calculator.py --mode node --node-type <type> --nodes <N> --show-ri-options` for current estimates) | Reserved node utilization in Cost Explorer |
| Snapshot storage | Automated and manual backups stored in S3; one free snapshot per node, additional snapshots charged per GB | Snapshot count and size via DescribeSnapshots |
| Data transfer | Cross-AZ replication traffic and internet-bound transfer | Cost Explorer usage type filters |

## Hidden Costs

These costs are easy to overlook during initial planning:

- **Log delivery charges**: Enabling slow log or engine log delivery incurs charges. CloudWatch Logs and Kinesis Data Firehose are mutually exclusive destinations (you choose one per log type, not both). When using CloudWatch Logs, standard ingestion and storage charges apply. When using Kinesis Data Firehose, Firehose delivery charges apply in addition to CloudWatch Logs vended-log charges. Monitor the relevant cost line items in Cost Explorer.
- **Cross-AZ data transfer for replicas**: Node-based clusters with replicas in different Availability Zones incur cross-AZ data transfer charges for replication traffic. This is typically small but scales with write throughput.
- **ENI costs for Lambda**: Lambda functions in a VPC use Elastic Network Interfaces. While ENIs are free, the VPC attachment adds cold start latency that can increase Lambda duration costs.
- **Secrets Manager rotation**: If using RBAC with Secrets Manager, rotation Lambda invocations and API calls add minor cost.
- **Extended Support charges**: Running Redis OSS engines past their end of standard support date automatically enrolls them in Extended Support at additional cost. Redis OSS v4 and v5 enter Extended Support on Feb 1, 2026; Redis OSS v6 on Feb 1, 2027. Extended Support has tiered Y1/Y2/Y3 premiums and lasts up to 3 years. Upgrade to a supported version or migrate to Valkey to avoid these charges.

## Cost Optimization Strategies

### Serverless

- **Set CacheUsageLimits** to cap spend: configure `DataStorage.Maximum` (GB) and `ECPUPerSecond.Maximum` in the cache configuration to prevent runaway costs. Commands exceeding the ECPU limit are throttled (monitor `ThrottledCmds`).
- **Monitor ECPU utilization patterns**: if ECPU consumption is consistently low and predictable, evaluate whether node-based with reserved instances would be cheaper. Run `scripts/price_calculator.py --mode serverless --data-gb <N> --ops-per-sec <N>` and `--mode node --node-type <type> --nodes <N> --show-ri-options` to compare.
- **Optimize command efficiency**: use pipelining to batch commands (reduces round trips and ECPU overhead), prefer MGET/MSET over individual GET/SET for bulk operations, and use appropriate data structures (HGETALL vs multiple GETs).

### Node-Based

- **Right-size instances**: if `EngineCPUUtilization` is consistently below 20% and `DatabaseMemoryUsagePercentage` is below 30%, the instance is over-provisioned. Scale down to a smaller node type.
- **Use reserved nodes for steady-state workloads**: Reserved nodes save approximately 30-55% depending on term length and payment option (run `python3 scripts/price_calculator.py --mode node --node-type <type> --nodes <N> --show-ri-options` for current estimates).
- **Enable data tiering for large datasets**: for r6gd instance types, data tiering moves less-frequently-accessed data to SSD, allowing larger datasets on fewer nodes.
- **Cluster mode enabled for horizontal scaling**: instead of scaling up to larger (more expensive) node types, scale out with more shards on smaller nodes.

### General

- **Review eviction metrics**: high evictions (`Evictions` > 0 sustained) may indicate the cache is undersized. Evictions force re-computation of cached values, adding load to the backing store. Sizing up or increasing TTL diversity can reduce evictions.
- **Check hit rate**: a low cache hit rate means the cache is not effectively serving its purpose. Use the `CacheHitRate` metric directly (available for both serverless and node-based). For node-based, you can also calculate hit rate from `CacheHits / (CacheHits + CacheMisses)`. Target > 80%. Investigate key design, TTL strategy, and whether the right data is being cached.
- **Use Valkey instead of Redis OSS**: Valkey is 33% cheaper for serverless and 20% cheaper for node-based, with API compatibility. The in-place upgrade to Valkey is zero-downtime for Multi-AZ replication groups with Redis OSS 5.0.6+. Single-node clusters must first be converted to a replication group before upgrading. Upgrading from earlier Redis OSS versions may experience brief unavailability during DNS propagation.

## Serverless vs Node-Based Cost Decision

Use actual usage data to decide:

- **Switch to node-based when:** ECPU consumption is steady and predictable, and `scripts/price_calculator.py --mode node --node-type <type> --nodes <N> --show-ri-options` shows node-based with 1-year reservation is 30%+ cheaper than current serverless spend.
- **Stay on serverless when:** Traffic is bursty or growing unpredictably, utilization swings by more than 3x between peak and trough, or the team cannot commit to capacity planning.
- **Switch to serverless when:** Node-based CPU is below 20% and memory below 30% sustained (over-provisioned), or traffic has become highly variable after an initially steady workload.

Run `scripts/price_calculator.py --mode serverless --data-gb <N> --ops-per-sec <N>` and `--mode node --node-type <type> --nodes <N> --show-ri-options` to get a concrete comparison.

## Valkey Savings Summary

| Deployment | Valkey Savings vs Redis OSS |
|------------|---------------------------|
| Serverless | 33% lower cost |
| Node-based | 20% lower cost |

For organizations running Redis OSS workloads, migrating to Valkey is the single highest-impact cost optimization. The migration is a zero-downtime in-place engine upgrade for Multi-AZ replication groups with Redis OSS 5.0.6+ (see the migration sub-skill).

## Cost Estimation Tool

Use the bundled price calculator for detailed estimates:

```bash
# Quick serverless estimate
python3 scripts/price_calculator.py --engine valkey --data-gb 5 --ops-per-sec 1000

# Node-based estimate with reserved pricing options
python3 scripts/price_calculator.py --mode node --engine valkey --node-type <type> --nodes <N> --show-ri-options

# Node-based estimate with specific instance type
python3 scripts/price_calculator.py --mode node --engine valkey --node-type cache.r7g.xlarge --nodes 3

# Interactive mode
python3 scripts/price_calculator.py --interactive
```

## Metrics Collection

Use the bundled metrics collector to gather CloudWatch metrics for cost analysis and capacity planning:

```bash
# Collect metrics for a cache (last 7 days by default)
# Positional args: <endpoint> [port] [output_prefix]
bash scripts/collect_metrics.sh <endpoint> 6379 <output-prefix>

# Example: collect from a serverless endpoint
bash scripts/collect_metrics.sh my-cache.serverless.use1.cache.amazonaws.com 6379 my-cache

# Example: collect from a node-based endpoint
bash scripts/collect_metrics.sh my-cluster.abc123.use1.cache.amazonaws.com 6379 my-cluster
```

## Serverless Migration Cost Estimation

Use the serverless estimator to project costs when evaluating a migration from node-based to serverless (or vice versa):

```bash
# Estimate serverless cost from a cluster inventory CSV
python3 scripts/serverless_estimator.py --input clusters.csv

# Estimate with per-command stats for higher accuracy
python3 scripts/serverless_estimator.py --input clusters.csv --commandstats stats.csv
```

For actual spend on existing resources, use the AWS CLI:

```bash
aws ce get-cost-and-usage \
  --time-period Start=2026-04-01,End=2026-04-16 \
  --granularity DAILY \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon ElastiCache"]}}' \
  --metrics "UnblendedCost" "UsageQuantity" \
  --group-by Type=DIMENSION,Key=USAGE_TYPE
```

## Cost Allocation Tags

Use tags to attribute ElastiCache costs to teams, applications, and environments in AWS Cost Explorer.

| Tag Key | Example Value | Purpose |
|---------|--------------|---------|
| `aws:elasticache:serverlessCacheName` | my-cache | Auto-applied by AWS; identifies the serverless cache resource |
| `aws:elasticache:replicationGroupId` | my-cluster | Auto-applied by AWS; identifies the node-based cluster resource |
| `Environment` | dev / staging / prod | Cost allocation by environment |
| `Application` | order-service | Cost allocation by consuming application |
| `Owner` | team-platform | Accountability and chargeback |
| `managed_by` | aws-skills | Skill attribution; tracks resources created via this skill |

Activate these tags in the AWS Billing console under **Cost Allocation Tags** to make them available in Cost Explorer reports and budgets. The `aws:elasticache:*` tags are auto-applied by the service and only need activation, not manual tagging.
