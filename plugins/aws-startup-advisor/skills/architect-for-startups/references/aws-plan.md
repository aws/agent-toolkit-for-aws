# AWS Planning — Startup-Specific Guidance

## Stage-Gated Planning

### Pre-Seed / MVP (< $1K/mo AWS spend)

- Skip Phase 3 (Security Review) depth — basic guardrails only. Don't let security theater block shipping.
- Phase 4 (Cost Estimate) matters more than Phase 2 (Design) at this stage. A $500/mo surprise kills a pre-seed startup.
- Deliver the simplest architecture that validates the hypothesis. If it's a single Lambda + DynamoDB, that IS the plan.

### Seed / Product-Market Fit ($1K–$10K/mo)

- Full workflow applies but bias toward speed over perfection
- Security Review: focus only on data exposure risk (public S3, no auth) — skip compliance depth until Series A
- Cost Estimate: model the "what if we 10x" scenario — will your architecture bankrupt you at success?

### Series A+ ($10K+/mo)

- Full workflow with no shortcuts
- Add: cost allocation tags from day 1 (you'll need them for board reporting)
- Add: multi-account strategy planning (separate prod/dev NOW, not later)

## Anti-Patterns — Startup Edition

- **Over-engineering for hypothetical scale**: You have 50 users. Lambda + DynamoDB. Not EKS. Not multi-region. Not event sourcing. The startup that builds for 10M users at 50 users usually dies at 50 users.
- **Skipping cost modeling because "we have credits"**: Credits expire. Model what happens when they run out. If your architecture costs $15K/mo and credits cover $5K, you have 3 months of runway buffer, not infinite time.
- **Proposing services the team cannot operate**: A 3-person startup cannot operate Kubernetes, Kafka, and a data lake simultaneously. Each managed service you skip saves 20% of one engineer's time.
- **Building the "enterprise-ready" version first**: SOC2, multi-tenant isolation, audit logging — all matter, but not before you have 10 paying customers. Build the path TO compliance, don't implement it day 1.

## Startup-Specific Cost Traps in Planning

| Trap                                   | Why It Hits Startups Hard                                                                    |
| -------------------------------------- | -------------------------------------------------------------------------------------------- |
| NAT Gateway ($32/mo + data)            | Often unnecessary pre-PMF. Use VPC endpoints or public subnets with security groups          |
| Multi-AZ RDS ($200+/mo minimum)        | Single-AZ is fine until you have SLA commitments to paying customers                         |
| Secrets Manager ($0.40/secret/mo)      | Use SSM Parameter Store SecureString (free) until you need rotation                          |
| CloudWatch Logs (never-expire default) | Set 30-day retention. You won't look at 6-month-old dev logs                                 |
| ECS + ALB baseline                     | $50/mo minimum even at zero traffic. Consider Lambda until steady-state traffic justifies it |

## "When to Graduate" Triggers

| Current Choice           | Graduate When                                          | Graduate To                                              |
| ------------------------ | ------------------------------------------------------ | -------------------------------------------------------- |
| Single Lambda + DynamoDB | p99 latency matters AND traffic is steady (not spiky)  | ECS Fargate + Aurora                                     |
| Single-AZ RDS            | First paying customer with uptime SLA                  | Multi-AZ RDS                                             |
| No IaC (console clicks)  | Second engineer joins OR you need a second environment | CDK or Terraform                                         |
| Single AWS account       | First production customer                              | Prod + Dev accounts minimum                              |
| No monitoring            | First production customer                              | CloudWatch dashboards + 3 alarms (errors, latency, cost) |
