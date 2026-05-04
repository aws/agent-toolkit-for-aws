# EC2 Right-Sizing with Compute Optimizer

## Prerequisites
Opt in first: `aws compute-optimizer update-enrollment-status --status Active`

## Metrics Analyzed

**Performance:** CPU utilization, memory utilization (requires CloudWatch agent), GPU utilization/memory (requires CloudWatch agent + NVIDIA GPU)

**Network:** NetworkIn/Out bytes/sec, packets in/out per second

**EBS:** Read/Write bytes/sec, Read/Write ops/sec

**Instance Store:** Disk read/write bytes/sec, disk read/write ops/sec

Memory metrics are critical — without them, instances with low memory may appear optimized. Memory metrics enable up to 4x more savings opportunities. Recommend CloudWatch agent installation.

## Finding Classifications

| Finding | Meaning |
|---------|---------|
| `Overprovisioned` | Can be downsized while meeting workload needs |
| `Underprovisioned` | Too small, risking performance issues |
| `Optimized` | Appropriately sized |
| `NotOptimized` | Could benefit from newer generation or family |

## Finding Reason Codes

Each finding includes reason codes explaining which metrics triggered it: `CPUOverprovisioned`, `CPUUnderprovisioned`, `MemoryOverprovisioned`, `MemoryUnderprovisioned`, `EBSThroughputOverprovisioned`, `NetworkBandwidthOverprovisioned`, `GPUOverprovisioned`, etc. Found in `findingReasonCodes` array.

## Lookback Periods

| Period | Datapoints | Cost |
|--------|-----------|------|
| 14-day (default) | ~4,032 | Free |
| 32-day | ~9,216 | Free (enhanced) |
| 93-day | ~26,784 | Paid (enhanced infrastructure metrics) |

Uses P99.5 percentile by default (excludes top 0.5% outliers). Default 20% CPU/memory headroom buffer.

## Migration Effort Levels

| Level | Example |
|-------|---------|
| Very Low | Same family size change (c5.large → c5.xlarge) |
| Low | Generation change (m5.xlarge → m6i.xlarge) |
| Medium | Family change (c5.xlarge → m5.xlarge) |
| High | Architecture change (x86 → Graviton/arm64) |

## Performance Risk Scale
0-1: Very Low | >1-2: Low | >2-3: Medium | >3-4: High

## Savings Estimation Modes

Check `effectiveRecommendationPreferences.savingsEstimationMode.source`:

- `PublicPricing`: On-Demand pricing (default)
- `CostExplorerRightsizing`: Incorporates SP/RI discounts
- `CostOptimizationHub`: Custom pricing

If only `savingsOpportunity` is present, calculation uses On-Demand. If `savingsOpportunityAfterDiscounts` is also present, compare both.

## CLI Commands

```bash
# Over-provisioned EC2 instances
aws compute-optimizer get-ec2-instance-recommendations \
  --filters Name=Finding,Values=Overprovisioned

# Idle resources (near-zero utilization)
aws compute-optimizer get-idle-recommendations

# Export to S3 for bulk analysis
aws compute-optimizer export-ec2-instance-recommendations \
  --s3-destination-config bucket=my-bucket,keyPrefix=ec2-recs \
  --file-format Csv
```

## Analyzing a Recommendation

When presenting a right-sizing recommendation to the user, include:

1. Current instance type and specs (vCPUs, memory)
2. Which metrics triggered the finding (with actual values)
3. Recommended instance type and specs
4. Monthly savings ($ and %) — calculate with a script, NEVER manually
5. Migration effort level and any platform differences (Xen→Nitro, x86→arm64)
6. Whether memory metrics were available (if not, recommend CloudWatch agent)
