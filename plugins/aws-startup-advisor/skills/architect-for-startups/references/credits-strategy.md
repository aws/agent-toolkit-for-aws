# Credits Strategy

## Key Facts for Architecture Decisions

- Credits apply AFTER free tier (free tier is consumed first)
- Credits do NOT cover: Route53 domain registration, Marketplace purchases, Support plan upgrades, third-party billed services
- Credits expire (typically 1-2 years from activation) — check Billing Console → Credits

---

## High-Burn Traps (avoid at early stages)

These eat credits even at zero traffic:

| Service               | Hidden Fixed Cost            | Alternative                                 |
| --------------------- | ---------------------------- | ------------------------------------------- |
| NAT Gateway           | $32/mo + $0.045/GB processed | VPC endpoints or no VPC                     |
| EKS Control Plane     | $73/mo per cluster           | Lambda, ECS Express Mode, or ECS Fargate    |
| Multi-AZ RDS          | 2x single-AZ cost            | Aurora Serverless v2 or DynamoDB            |
| OpenSearch Serverless | ~$700/mo minimum             | Bedrock Knowledge Base managed vector store |
| VPN Connection        | $36/mo                       | SSM Session Manager                         |

## Burn Rate Red Flags

- **NAT Gateway data processing**: Chatty services behind NAT can burn $100+/mo in processing alone
- **CloudWatch Logs default retention**: "Never expire" = costs accumulate forever. Set 7d dev / 30d prod.
- **Stopped EC2 still pays for EBS**, unattached volumes, idle ALBs
- **Over-provisioned RDS** at 5% CPU — use Aurora Serverless v2 instead
- **Dev environments running 24/7** — schedule stop outside business hours

---

## Credits Runway by Stage

| Stage       | Monthly Spend Target | $25K Credits Lasts | $100K Credits Lasts |
| ----------- | -------------------- | ------------------ | ------------------- |
| Pre-Revenue | $0-50                | Years              | Years               |
| Seed        | $100-500             | 50+ months         | Years               |
| Series A    | $1K-10K              | 2.5-25 months      | 10-100 months       |

---

## Stage-Specific Optimization

### Pre-Revenue: $0-50/month target

- Stay within free tier entirely — Lambda + DynamoDB + S3 all scale to zero
- **No custom VPC** — Lambda, DynamoDB, S3 work without one
- No NAT Gateway under any circumstances

### Seed: $100-500/month target

- Replace NAT Gateway with VPC endpoints for S3/DynamoDB (free)
- DynamoDB on-demand only — you don't know access patterns yet
- Use Graviton (ARM) for Lambda and Fargate — 20% cheaper for free
- Audit monthly with `aws ce get-cost-and-usage`

### Series A: When to start commitments

- Savings Plans ONLY after 3+ months of stable usage data
- Start with 1-year Compute Savings Plan, No Upfront
- Cover only 50-70% of baseline — leave room for variability
- Enable Cost Anomaly Detection (catches unexpected spikes)

---

## Credits Expiration: Don't Lose Them

If credits expire in <3 months with significant balance remaining, spend on things you'll need anyway:

- Staging/DR environments you were going to build
- Load tests and performance benchmarks
- Bedrock model experimentation
- Observability buildout (dashboards, alarms, tracing)

**Don't** spin up resources just to burn credits — that's worse than letting some expire.
