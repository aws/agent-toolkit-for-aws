# Per-Service Cost Optimization

> **Pricing note:** All prices shown are us-east-1 approximate as of early 2026. Prices vary by region and may change. Always verify current pricing via the Price List API before reporting to users.

Quick wins that don't require commitment purchases. Prioritize by estimated savings.

## S3: Storage Class Optimization

| Strategy | Savings | When |
|----------|---------|------|
| Intelligent-Tiering | Auto-optimized | Unknown access patterns, objects ≥128KB |
| Lifecycle to S3-IA | ~45% storage | Known infrequent access after 30+ days |
| Lifecycle to Glacier IR | ~68% storage | Archive after 90+ days, retrieval in minutes |
| Lifecycle to Deep Archive | ~95% storage | Compliance retention, 12+ hour retrieval OK |

**Gotchas:** Objects <128KB NOT auto-tiered in IT. Minimum storage durations: S3-IA 30 days, Glacier IR 90 days, Deep Archive 180 days — early deletion incurs prorated charge. Always add `NoncurrentVersionExpiration` — old versions accumulate silently.

## Lambda: Memory and Architecture

| Strategy | Savings | Effort |
|----------|---------|--------|
| Switch to arm64 (Graviton) | ~20% cost | Low — config change |
| Right-size memory | 10-50% | Medium — use Power Tuning |
| SnapStart (Java/Python/.NET) | Eliminates provisioned concurrency cost | Low |

**Gotchas:** Reserved concurrency (free) ≠ Provisioned concurrency (paid). 1,769 MB = 1 full vCPU — more memory = more CPU = potentially lower total cost.

## NAT Gateway: VPC Endpoints

NAT Gateway: ~$0.045/hr (~$32/month) + ~$0.045/GB. Often the #1 surprise cost.

**Always create free gateway endpoints for S3 and DynamoDB:**

```bash
aws ec2 create-vpc-endpoint --vpc-id vpc-123abc \
  --service-name com.amazonaws.<REGION>.s3 --route-table-ids rtb-123abc
```

Interface endpoints cost ~$0.01/hr/AZ + ~$0.01/GB — cheaper than NAT only for high-traffic services. Do the math before adding many interface endpoints.

## CloudWatch: Log Retention

Default retention is "Never expire" — logs accumulate at ~$0.03/GB/month.

```bash
# Find log groups without retention
aws logs describe-log-groups \
  --query "logGroups[?!retentionInDays].{Name:logGroupName,StoredBytes:storedBytes}" --output table
```

**Gotchas:** Log class cannot be changed after creation. Infrequent Access class does NOT support metric filters, subscription filters, or live tail. Custom metrics: each unique dimension combination is a separate metric (~$0.30/metric/month in us-east-1).

## DynamoDB: Capacity Mode

On-demand is ~6x more expensive per request than provisioned at steady state. Start on-demand for new tables, switch to provisioned once traffic patterns are known. Can switch modes once per 24 hours. Database Savings Plans (up to 35%) now apply to DynamoDB on-demand.

## ECS/EKS: Fargate Spot

Fargate Spot: up to 70% discount, 2-minute interruption warning. Always have Fargate fallback with `base=1`. EKS control plane costs $0.10/hr ($73/month) regardless of node count — not covered by any SP.
