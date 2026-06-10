# MSF Pricing Calculator

## Overview

Estimate MSF application monthly cost for sizing decisions, budgeting, and optimization analysis. All prices below are us-east-1 — verify against [MSF pricing page](https://aws.amazon.com/managed-service-apache-flink/pricing/) for other regions.

## Pricing Components

| Component | Price (us-east-1) | Notes |
|-----------|-------------------|-------|
| KPU-hour | $0.11 / KPU-hour | Per allocated KPU per running hour |
| Orchestration KPU | $0.11 / hour | 1 additional KPU per running app, **always billed** |
| Running application storage | $0.10 / GB-month | **50 GB per KPU is included free.** Only the bytes *above* `KPU_count × 50 GB` are billable. Do not bill the 50 GB allocation itself. |
| Durable application backups (snapshots) | $0.023 / GB-month | Billed for total snapshot footprint |

There is **no separate charge for application code in S3** (your S3 bucket cost only) and **no per-API-call charge** for Flink REST API or `kinesisanalyticsv2` operations.

## Formula

```
KPU_count   = Parallelism / ParallelismPerKPU
Total_KPUs  = KPU_count + 1                                    # orchestration

KPU_cost     = Total_KPUs × $0.11 × hours_per_month
storage_cost = max(0, state_GB - KPU_count × 50) × $0.10
backup_cost  = total_snapshot_GB × $0.023

monthly_total = KPU_cost + storage_cost + backup_cost
```

24/7 = 730 hours/month. Most production apps stay under the 50 GB/KPU storage included tier.

## Sizing → Cost Reference (24/7, $0 storage)

| Input Rate | Parallelism | PPK | KPUs (+orch) | Monthly |
|-----------|-------------|-----|--------------|---------|
| < 5 MB/s | 2 | 1 | 2+1=3 | $241 |
| 5–20 MB/s | 4 | 1 | 4+1=5 | $402 |
| 20–50 MB/s | 8 | 2 | 4+1=5 | $402 |
| 50–100 MB/s | 16 | 2 | 8+1=9 | $723 |
| 100–200 MB/s | 32 | 2 | 16+1=17 | $1,365 |
| 200–500 MB/s | 64 | 4 | 16+1=17 | $1,365 |
| > 500 MB/s | 128+ | 4 | 32+1=33+ | $2,650+ |

These assume stateless-to-moderate stateful workloads. Stateful workloads (keyed windows with large state) typically require PPK=1, doubling KPU count and cost vs. the stateless equivalent.

## Worked Examples

**Small / development (Parallelism=2, PPK=1, 24/7, negligible state, no snapshots):**

- KPU count: 2 / 1 = 2 application KPUs, plus 1 orchestration KPU = **3 billed KPUs**
- KPU cost: 3 × $0.11 × 730 = **$240.90**
- Running application storage: state ≤ 2 × 50 GB included → **$0** (the 50 GB/KPU allocation is *included*, not separately billable; do **not** multiply 50 × $0.10 per KPU)
- Snapshot cost: $0 (none retained)
- **Total: ~$241/month**

The orchestration KPU is the most common sizing mistake at this scale: it raises the bill from $158 (2 KPUs) to $241 (3 KPUs), a 52% increase. Always include it.

**Medium production (8 parallel, PPK=1, 24/7, 5 GB state):**

- KPUs: 8 + 1 = 9 → 9 × $0.11 × 730 = **$722.70**
- Storage: 5 GB ≤ 8 × 50 GB included → $0
- Snapshots: 5 GB × $0.023 = $0.12
- **Total: ~$723/month**

**Enterprise with autoscaling (avg 16 KPU, peak 32 KPU 20% of time, 60 GB state):**

- Peak: 33 × $0.11 × 146 = $530
- Off-peak: 17 × $0.11 × 584 = $1,092
- Snapshots: 60 GB × $0.023 = $1.38
- **Total: ~$1,623/month**

## Cost Optimization Levers

Ranked by typical impact:

1. **Right-size PPK for workload**: Stateless apps at PPK=2 cost half of PPK=1 at the same parallelism. Rule of thumb: stateless → PPK=2; stateful → PPK=1.
2. **Stop non-prod when idle**: Dev/test apps run 200h/month vs 730h is a 73% reduction. Snapshot before stop, restore on start.
3. **Enable autoscaling for variable load**: 30–50% average reduction for spiky workloads with predictable off-peaks.
4. **Match Parallelism to source partitions**: Idle subtasks waste KPUs. Parallelism > shard/partition count creates them.
5. **Snapshot retention strategy**: Without retention, a streaming app's snapshot footprint grows monotonically.
6. **Always remember the orchestration KPU**: At 1–2 KPU sizing it's 33–50% of the bill — easy to under-estimate.

## Common Mistakes

| Mistake | Impact |
|---------|--------|
| Forgetting orchestration KPU | Under-estimates by 1 KPU = $80/month at 24/7 |
| Confusing Parallelism with KPU count | Wrong with PPK > 1; KPUs = Parallelism / PPK |
| Using us-east-1 prices for other regions | Prices vary; check the pricing page |
| Estimating peak as average | Autoscaling jobs have asymmetric peak/off-peak — calculate separately |
| Ignoring CloudWatch metric cardinality cost | OPERATOR/PARALLELISM metric levels add custom-metric cost (not MSF cost). See [monitoring-and-metrics.md](monitoring-and-metrics.md) |

## References

- [MSF Pricing](https://aws.amazon.com/managed-service-apache-flink/pricing/)
- [resource-optimization.md](resource-optimization.md) — KPU sizing inputs for the calculator
- [scaling-decisions.md](scaling-decisions.md) — cost impact of scaling actions
