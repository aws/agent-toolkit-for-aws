# EBS Volume Optimization

> **Pricing note:** All prices shown are us-east-1 approximate as of early 2026. Prices vary by region and may change. Always verify current pricing via the Price List API before reporting to users.

## Volume Type Comparison

### gp2 vs gp3

- gp2: IOPS tied to volume size (3 IOPS/GB). Uses burst buffer — can burst to 3,000 IOPS temporarily, then drops to baseline when credits depleted. A 100 GB gp2 volume has only 300 IOPS baseline.
- gp3: ~20% lower per-GB cost ($0.08 vs $0.10 in us-east-1; verify regional prices via Price List API). Consistent 3,000 IOPS + 125 MB/s baseline included for ANY volume size. No burst buffer. IOPS and throughput provisioned independently.

**gp2 → gp3 migration is almost always a win:** lower cost, consistent performance, no burst buffer management.

### io1 vs io2
Same price ($0.125/GB + $0.065/PIOPS in us-east-1). io2 offers: higher durability (99.999% vs 99.8%), max IOPS up to 64K (or 256K with Block Express on Nitro instances) vs 64K for io1, Multi-Attach. Always prefer io2 over io1.

## Compute Optimizer for EBS

Prerequisites: supported type (gp2/gp3/io1/io2), attached and in-use for full lookback, ≥24h CloudWatch metrics, no modification in past 24h.

Metrics: Read/Write IOPS (Max + Avg), Read/Write Bytes/sec (Max + Avg). 5-minute samples.

Findings: `NotOptimized` (can improve), `Optimized` (may still recommend type migration for cost/durability).

```bash
aws compute-optimizer get-ebs-volume-recommendations \
  --filters Name=Finding,Values=NotOptimized
```

## Root Volume Considerations

- Root volumes contain the OS — modifications require extra caution
- Many modern instance types support Elastic Volumes for online modification
- Some older types may require scheduled restart
- Always verify instance type supports online modification before proceeding

## Savings Formulas

**io1/io2:**
Savings = (current_GB × $/GB + current_PIOPS × $/PIOPS) − (recommended_GB × $/GB + recommended_PIOPS × $/PIOPS)

**gp2→gp3:**
Savings = (current_GB × gp2_$/GB) − (current_GB × gp3_$/GB + max(0, needed_IOPS − 3000) × gp3_$/IOPS + max(0, needed_throughput_MBps − 125) × gp3_$/throughput_MBps)

Look up regional prices via Price List API (see `references/pricing-lookup.md`). Prices vary significantly by region. `needed_IOPS` and `needed_throughput_MBps`: use Compute Optimizer recommended values when available, otherwise observed P99 from CloudWatch.

## Gotchas

- gp2 burst buffer depletion causes sudden performance drops — common cause of unexplained latency
- Volume modifications are online (no detach needed) but take time to complete
- Storage can only be increased, not decreased
- After modification, must wait 6 hours before another modification
