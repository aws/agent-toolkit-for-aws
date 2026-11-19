# MSF Pricing Calculator

## Overview

Estimate MSF application monthly cost for sizing decisions, budgeting, and optimization analysis. Prices, tables, and worked examples below are us-east-1 and show the billing model; they are not current rates.

## Get Current Rates

Before quoting a dollar figure, fetch the rates for the application's region from the Price List API (the `pricing` endpoint is called in `us-east-1` for every region):

```bash
aws pricing get-products --region us-east-1 --service-code AmazonKinesisAnalytics \
  --filters Type=TERM_MATCH,Field=regionCode,Value=<region> \
  --query 'PriceList[]' --output json
```

Use these usage types (prefixed with a region code, e.g. `USE1-`, `EUW1-`):

| Usage type suffix | Component |
|---|---|
| `KPU-Hour-Java` | KPU-hour for Apache Flink applications, including the orchestration KPU (not `KPU-Hour`, which is SQL applications) |
| `RunningApplicationStorage` | Running application storage, per GB-month |
| `DurableApplicationBackups` | Snapshots, per GB-month |

Apply the live rates to the formula below. If the API is unavailable, use the [MSF pricing page](https://aws.amazon.com/managed-service-apache-flink/pricing/), and say which source and region the estimate uses.

## Pricing Components

| Component | Price (us-east-1) | Notes |
|-----------|-------------------|-------|
| KPU-hour | $0.11 / KPU-hour | Per allocated KPU per running hour |
| Orchestration KPU | $0.11 / hour | 1 additional KPU per running app, **always billed** |
| Running application storage | $0.10 / GB-month | **50 GB is allocated and billed per application KPU** (not the orchestration KPU), regardless of state size: ~$5 per application KPU per month at 24/7 |
| Durable application backups (snapshots) | $0.023 / GB-month | Billed for total snapshot footprint |

There is **no separate charge for application code in S3** (your S3 bucket cost only) and **no per-API-call charge** for Flink REST API or `kinesisanalyticsv2` operations.

## Formula

```
KPU_count   = Parallelism / ParallelismPerKPU
Total_KPUs  = KPU_count + 1                                    # orchestration

KPU_cost     = Total_KPUs × $0.11 × hours_per_month              # Total_KPUs for the KPU charge only
storage_cost = KPU_count × 50 × $0.10 × hours_per_month / 730
backup_cost  = total_snapshot_GB × $0.023

monthly_total = KPU_cost + storage_cost + backup_cost
```

24/7 = 730 hours/month.

To check an estimate against a real bill: in Cost Explorer (service `Amazon Kinesis Analytics`), `RunningApplicationStorage` GB-Mo × 730 / 50 equals application KPU-hours, and total `KPU-Hour` minus that figure equals orchestration KPU-hours.

## Sizing → Cost Reference (24/7, KPU + running storage)

| Input Rate | Parallelism | PPK | KPUs (+orch) | Monthly |
|-----------|-------------|-----|--------------|---------|
| < 5 MB/s | 2 | 1 | 2+1=3 | $251 |
| 5–20 MB/s | 4 | 1 | 4+1=5 | $422 |
| 20–50 MB/s | 8 | 2 | 4+1=5 | $422 |
| 50–100 MB/s | 16 | 2 | 8+1=9 | $763 |
| 100–200 MB/s | 32 | 2 | 16+1=17 | $1,445 |
| 200–500 MB/s | 64 | 4 | 16+1=17 | $1,445 |
| > 500 MB/s | 128+ | 4 | 32+1=33+ | $2,810+ |

Monthly = KPU charge for all KPUs + $5 running storage per application KPU.

These assume stateless-to-moderate stateful workloads. Stateful workloads (keyed windows with large state) typically require PPK=1, doubling KPU count and cost vs. the stateless equivalent.

## Worked Examples

**Small / development (Parallelism=2, PPK=1, 24/7, negligible state, no snapshots):**

- KPU count: 2 / 1 = 2 application KPUs, plus 1 orchestration KPU = **3 billed KPUs**
- KPU cost: 3 × $0.11 × 730 = **$240.90**
- Running application storage: 2 × 50 × $0.10 = **$10.00**
- Snapshot cost: $0 (none retained)
- **Total: ~$251/month**

The orchestration KPU is the most common sizing mistake at this scale: it raises the bill from $171 to $251, a 47% increase, and is 32% of the total. Always include it.

**Medium production (8 parallel, PPK=1, 24/7, 5 GB state):**

- KPUs: 8 + 1 = 9 → 9 × $0.11 × 730 = **$722.70**
- Storage: 8 × 50 × $0.10 = **$40.00**
- Snapshots: 5 GB × $0.023 = $0.12
- **Total: ~$763/month**

**Enterprise with autoscaling (avg 16 KPU, peak 32 KPU 20% of time, 60 GB state):**

- Peak: 33 × $0.11 × 146 = $530
- Off-peak: 17 × $0.11 × 584 = $1,092
- Storage: (32 × 146 + 16 × 584) × 50 / 730 × $0.10 = $96.00
- Snapshots: 60 GB × $0.023 = $1.38
- **Total: ~$1,719/month**

## Cost Optimization Levers

Ranked by typical impact:

1. **Right-size PPK for workload**: Stateless apps at PPK=2 cost half of PPK=1 at the same parallelism. Rule of thumb: stateless → PPK=2; stateful → PPK=1.
2. **Stop non-prod when idle**: Dev/test apps run 200h/month vs 730h is a 73% reduction. Snapshot before stop, restore on start.
3. **Enable autoscaling for variable load**: 30–50% average reduction for spiky workloads with predictable off-peaks.
4. **Match Parallelism to source partitions**: Idle subtasks waste KPUs. Parallelism > shard/partition count creates them.
5. **Snapshot retention strategy**: Without retention, a streaming app's snapshot footprint grows monotonically.
6. **Always remember the orchestration KPU**: At 1–2 application KPU sizing it's ~32–48% of the bill — easy to under-estimate.

## Common Mistakes

| Mistake | Impact |
|---------|--------|
| Forgetting orchestration KPU | Under-estimates by 1 KPU = $80/month at 24/7 |
| Treating running storage as free | Under-estimates by $5 per application KPU per month (~6% of KPU cost) |
| Confusing Parallelism with KPU count | Wrong with PPK > 1; KPUs = Parallelism / PPK |
| Quoting the us-east-1 figures above as current or for another region | Rates vary by region and change over time; fetch them as in [Get Current Rates](#get-current-rates) |
| Estimating peak as average | Autoscaling jobs have asymmetric peak/off-peak — calculate separately |
| Ignoring CloudWatch metric cardinality cost | OPERATOR/PARALLELISM metric levels add custom-metric cost (not MSF cost). See [monitoring-and-metrics.md](monitoring-and-metrics.md) |

## References

- [MSF Pricing](https://aws.amazon.com/managed-service-apache-flink/pricing/)
- [resource-optimization.md](resource-optimization.md) — KPU sizing inputs for the calculator
- [scaling-decisions.md](scaling-decisions.md) — cost impact of scaling actions
