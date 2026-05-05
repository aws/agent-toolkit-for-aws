# Savings Plans

> **Pricing note:** All prices shown are approximate as of early 2026 and may change. Always verify current pricing via the Price List API before reporting to users.

## Plan Types

| Type | Discount | Flexibility | Covers |
|------|----------|-------------|--------|
| Compute SP | Up to 66% | Any family, size, region, OS | EC2, Fargate, Lambda |
| EC2 Instance SP | Up to 72% | Any size, OS within family+region | EC2 only |
| Database SP | Up to 35% | Any engine, family, size, region | Aurora, RDS, DynamoDB, ElastiCache, DocumentDB, Neptune, Keyspaces, Timestream, DMS, OpenSearch |
| SageMaker SP | Up to 64% | Any family, size, region | SageMaker |

Default recommendation: **Compute SP** for most users. The 6% discount gap vs EC2 Instance SP is not worth the inflexibility.

Default payment: **No Upfront** for first-time buyers to minimize risk.

## How Recommendations Are Calculated

The recommendation engine analyzes usage over a lookback period (7, 30, or 60 days), considering every usage hour including nights and weekends. It selects a commitment ($/hr) that maximizes savings while maintaining high utilization.

**Utilization** = committed dollars used ÷ committed dollars purchased. Target >95%.

**Savings** = On-Demand cost − (SP cost + remaining On-Demand cost).

Savings compare to On-Demand prices only. The `estimatedMonthlyCost` and `estimatedMonthlySavings` in Cost Optimization Hub are monthly figures. The `EstimatedOnDemandCostWithCurrentCommitment` in additional details covers the lookback period — do NOT conflate lookback-period costs with monthly costs.

## SP vs Reserved Instances

| Feature | Savings Plans | Reserved Instances |
|---------|--------------|-------------------|
| Flexibility | High (Compute SP covers EC2+Fargate+Lambda) | Low (service-specific) |
| Capacity reservation | No | Yes (AZ-scoped RI — Standard or Convertible) |
| Marketplace resale | No | Yes (Standard RI only) |
| AWS recommendation | Preferred | Legacy, still supported |

SPs apply AFTER RI discounts. SPs do NOT apply to Spot usage.

Use RIs only when: capacity reservation needed in specific AZ, want to sell on Marketplace, or very stable single-instance-type workload.

## Gotchas

- **7-day return window (conditional):** SPs with hourly commitment ≤$100, purchased in the past 7 days AND in the same calendar month, can be returned for a full refund. Usage covered by the returned plan is re-rated to On-Demand. Outside this window, commitment is binding for the full term.
- Compute SP does NOT cover RDS — use Database SP
- SP doesn't provide capacity reservation — use ODCR separately
- EKS control plane ($0.10/hr) is NOT covered by any SP
- DynamoDB Reserved Capacity is deprecated in favor of Database SP
- Start with Cost Explorer recommendations — they analyze actual usage patterns

## CLI Commands

```bash
# Get SP purchase recommendation
aws ce get-savings-plans-purchase-recommendation \
  --savings-plans-type COMPUTE_SP \
  --term-in-years ONE_YEAR \
  --payment-option NO_UPFRONT \
  --lookback-period-in-days SIXTY_DAYS

# Check utilization
aws ce get-savings-plans-utilization \
  --time-period Start=2026-03-01,End=2026-04-01 \
  --granularity MONTHLY

# Check coverage
aws ce get-savings-plans-coverage \
  --time-period Start=2026-03-01,End=2026-04-01 \
  --granularity MONTHLY
```
