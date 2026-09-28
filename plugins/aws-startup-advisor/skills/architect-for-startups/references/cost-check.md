# Cost Check — Startup-Specific Guidance

## The Startup Cost Model (Different from Enterprise)

Enterprise optimizes for: lowest per-unit cost at scale.
Startups optimize for: lowest BASELINE cost with LINEAR scaling (no cliffs).

### The Three Cost Questions for Startups

1. **What's my cost at zero/minimal traffic?** (This is your monthly burn before you have customers)
2. **What's my cost at 10x current traffic?** (Is it linear or does it cliff?)
3. **What's my cost when credits expire?** (The real number)

## Hidden Cost Killers — Startup-Specific

These rarely appear in enterprise cost reviews but destroy startup budgets:

| Service                           | Hidden Cost                           | Why Startups Get Hit                                                      |
| --------------------------------- | ------------------------------------- | ------------------------------------------------------------------------- |
| NAT Gateway                       | $32/mo + $0.045/GB processed          | Added by default in "best practice" VPC templates                         |
| ALB                               | $16/mo + LCU charges                  | Required for ECS/EKS even at 1 request/minute                             |
| Elastic IP (unattached)           | $3.60/mo (post Feb 2024)              | Forgotten after shutting down EC2 dev instances                           |
| CloudWatch Logs                   | $0.50/GB ingestion + storage          | Default log retention = never expire. Grows forever                       |
| Secrets Manager                   | $0.40/secret/mo + $0.05/10K API calls | Often 10+ secrets for a simple app. SSM is free                           |
| S3 Intelligent-Tiering monitoring | $0.0025/1K objects/mo                 | Not worth it for <1M objects — just use S3 Standard                       |
| VPC endpoints                     | $7.20/endpoint/mo per AZ              | "Best practice" adds 3-5 endpoints = $20-36/mo for nothing at low traffic |
| KMS customer-managed keys         | $1/key/mo + API charges               | AWS-managed keys are free and sufficient pre-compliance                   |
| Config rules                      | $0.003/evaluation                     | 20 rules × 50 resources × daily = $90/mo for dev accounts                 |

## Credits Strategy

### How to Model Costs with Credits

```
Real monthly cost = AWS bill - credits applied
Runway (months) = Remaining credits / Real monthly cost
Post-credits monthly cost = AWS bill (this is what you need revenue to cover)
```

### Credits Optimization Rules

1. **Never buy Reserved Instances or Savings Plans while on credits** — you can't see real usage patterns
2. **Credits cover everything except Marketplace** — use native AWS services, not Marketplace alternatives
3. **Track credits burn rate monthly** — if burning faster than expected, investigate NOW not at expiry
4. **Plan architecture for post-credits reality** — if your arch costs $15K/mo and revenue is $5K/mo, you have a problem BEFORE credits expire
5. **Credits don't carry over after expiry date** — use-it-or-lose-it. Don't under-utilize to "save" them

## Cost Scaling Patterns — Choose Wisely

| Pattern                               | Cost at 0 traffic            | Cost at 1K req/day | Cost at 100K req/day | Startup Fit                          |
| ------------------------------------- | ---------------------------- | ------------------ | -------------------- | ------------------------------------ |
| Lambda + DynamoDB (on-demand)         | ~$0                          | ~$1                | ~$30                 | ✅ Best for pre-seed                 |
| ECS Express Mode (1 task)             | ~$7                          | ~$7                | ~$30                 | ✅ Good for seed                     |
| ECS Fargate (1 task) + ALB            | ~$50                         | ~$50               | ~$100                | ⚠️ Only if traffic justifies baseline |
| ECS Fargate (2 tasks, multi-AZ) + ALB | ~$85                         | ~$85               | ~$150                | ❌ Skip until SLA requirements       |
| EKS + Fargate                         | ~$80 (control plane) + tasks | ~$130              | ~$250                | ❌ Skip until team has K8s skills    |

## The "$100/mo Baseline" Rule

If your architecture costs >$100/mo at zero customers, justify every dollar:

- $16/mo ALB: Do you need it, or can Lambda + API Gateway work?
- $32/mo NAT Gateway: Do you actually need private subnet egress?
- $43/mo Aurora Serverless v2 minimum: Is RDS t4g.micro ($12/mo) sufficient?
- $7/mo per VPC endpoint: Can you use public endpoints with IAM auth instead?

## When to Invest in Cost Optimization

| Monthly Spend | Optimization ROI             | Action                                                                      |
| ------------- | ---------------------------- | --------------------------------------------------------------------------- |
| < $500        | Not worth engineering time   | Set a budget alarm. Move on. Ship features.                                 |
| $500–$2K      | Quick wins only (30 min max) | Delete unused resources, set log retention, right-size one big instance     |
| $2K–$10K      | Dedicated half-day           | Review top 5 line items, consider Savings Plans for stable workloads        |
| > $10K        | Dedicated effort             | Full cost review, Savings Plans, architecture changes, cost allocation tags |

## Quick Wins Checklist

- [ ] Unused EBS volumes and unattached Elastic IPs
- [ ] CloudWatch log retention set to "Never expire" — change to 7d dev / 30d prod
- [ ] NAT Gateway traffic that could use VPC endpoints
- [ ] Over-provisioned RDS instances (check CPU utilization)
- [ ] Lambda functions with excessive memory allocation
- [ ] Dev environments running 24/7 — schedule stop outside business hours
- [ ] Old EBS snapshots and unused AMIs
- [ ] S3 buckets without lifecycle policies

## Gotchas

- Data transfer costs are the silent killer — especially cross-AZ and cross-region
- DynamoDB on-demand vs provisioned: on-demand is cheaper below ~20% utilization of provisioned capacity
- S3 Intelligent-Tiering monitoring fee per object — not worth it for millions of tiny objects
- CloudFront can be cheaper than S3 direct for high-traffic reads (no S3 request fees)
- Graviton instances are ~20% cheaper and often faster — use them unless you need x86
