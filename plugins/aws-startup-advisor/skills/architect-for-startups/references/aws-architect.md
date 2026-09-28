# AWS Architect — Startup-Specific Guidance

## Startup-Stage Service Selection

### Compute — Default by Stage

| Stage                     | Default Compute                   | Why                                                                                                                                                                          |
| ------------------------- | --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Pre-seed / MVP            | Lambda + API Gateway              | $0 at zero traffic. Ship in hours, not days.                                                                                                                                 |
| Seed / Early traction     | Lambda OR ECS Fargate             | Fargate if you need WebSockets or >15min processing. ALB setup cost is worth avoiding a forced re-platform later. Lambda function URLs + response streaming cover some gaps. |
| Series A / Steady traffic | ECS Fargate                       | Predictable costs at steady-state; Savings Plans eligible                                                                                                                    |
| Series B+ / Team has K8s  | EKS only if team already knows it | Never adopt K8s as a startup unless you're hiring K8s engineers                                                                                                              |

**Counterintuitive**: ECS Fargate at seed stage feels heavy, but the ALB + target group + task definition setup is a one-time cost (~1 day). You avoid a forced re-platform when you outgrow Lambda's 15-minute timeout or need persistent connections. For simpler cases, Lambda function URLs with response streaming can bridge the gap without a full container deploy.

### Database — The Startup Trap

| Stage                               | Default Database               | Why NOT the "proper" choice                                                                                       |
| ----------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| MVP validation                      | RDS PostgreSQL t4g.micro       | $12/mo. SQL gives you joins, ad-hoc queries, and flexibility to iterate on your data model without re-engineering |
| MVP with auto-scaling needs         | Aurora Serverless v2           | Scales to zero ACU... but minimum is 0.5 ACU ($43/mo). Worth it only if traffic is spiky and unpredictable        |
| Confirmed key-value access patterns | DynamoDB on-demand             | $0 at zero traffic. Only choose this if you've confirmed you don't need relational queries                        |
| Need PostgreSQL but cost-sensitive  | RDS PostgreSQL t4g.micro/small | $12-25/mo. Single-AZ is FINE until you have paying customers with uptime commitments                              |

**DynamoDB single-table design**: Every blog post says do it. DON'T at a startup. It's a premature optimization that makes your data model rigid before you know your access patterns. Use multiple simple tables. Refactor to single-table design when you have proven query patterns AND DynamoDB costs justify the optimization.

## Startup-Specific Gotchas

| Gotcha                                | Impact                                       | What to Do Instead                                                                                                                                                                                                                  |
| ------------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| NAT Gateway as default                | $32/mo + $0.045/GB — often your #2 line item | VPC endpoints for S3/DynamoDB. Public subnets + SGs for Lambda. Only add NAT if you actually need private subnet egress                                                                                                             |
| Aurora Serverless v2 "scales to zero" | Minimum 0.5 ACU = $43/mo even idle           | RDS t4g.micro at $12/mo is cheaper until you need auto-scaling                                                                                                                                                                      |
| Multi-AZ everything                   | 2x cost on RDS, ElastiCache                  | Single-AZ until you have paying customers with uptime commitments (SLA or contractual). If credits cover it and you're past MVP, enabling early is fine as insurance — but don't let it become a hard dependency before you need it |
| CloudFront for API                    | $0 minimum but adds debugging complexity     | Skip until you need geographic distribution or WAF                                                                                                                                                                                  |
| Secrets Manager per secret            | $0.40/secret/mo adds up                      | SSM Parameter Store SecureString is free. Use Secrets Manager only for rotation                                                                                                                                                     |
| Cross-AZ data transfer                | $0.01/GB between AZs                         | Chatty microservices in different AZs = hidden cost. Colocate or go single-AZ                                                                                                                                                       |

## Credits-Aware Architecture Decisions

| Decision                           | With Credits                                                                                                                                                                         | Without Credits                                           |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------- |
| RDS instance size                  | Right-size to actual need (credits don't change this)                                                                                                                                | Same — don't over-provision just because credits cover it |
| Multi-AZ                           | Enable if credits cover it AND you're past MVP — fine as early insurance                                                                                                             | Defer until paying customers with uptime commitments      |
| Reserved Instances / Savings Plans | Do NOT buy while on credits — wait until credits expire to see real spend patterns                                                                                                   | Buy after 3 months of stable, post-credits usage          |
| Managed services vs DIY            | Always prefer managed services. EKS is the exception — only adopt it if your team already has Kubernetes expertise, and understand you're taking on significant operational overhead | Same                                                      |
| Graviton instances                 | Prefer Graviton unless you have native x86 dependencies. 20% cheaper AND credits last longer. Test your container on ARM before committing                                           | Same                                                      |

**Critical**: Never commit to Savings Plans or Reserved Instances while on credits. You can't see your real usage patterns. Wait until 3 months AFTER credits are exhausted.

## The "10x Cost" Test

Before finalizing any architecture, ask: "If traffic 10x's, what happens to my bill?"

| Service            | 10x Behavior                                  | Startup Risk                                                                                                           |
| ------------------ | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Lambda             | 10x invocations = ~10x cost                   | Low risk — linear and predictable                                                                                      |
| DynamoDB on-demand | 10x reads/writes = ~10x cost                  | Medium risk — costs scale linearly with reads/writes. Design access patterns early to avoid surprise bills at traction |
| RDS                | Doesn't auto-scale (unless Aurora Serverless) | Low cost risk, HIGH availability risk                                                                                  |
| NAT Gateway        | 10x data = 10x data processing charges        | High risk — this is where surprise bills come from                                                                     |
| S3                 | 10x storage = linear. 10x requests = linear   | Low risk                                                                                                               |
| CloudFront         | 10x requests = ~8x cost (volume discounts)    | Low risk                                                                                                               |
| ECS Fargate        | 10x tasks = 10x cost. No volume discounts     | Medium risk — but you control the scaling                                                                              |

## When Architecture Recommendations DIFFER from AWS Best Practices

| AWS Best Practice                         | Startup Reality                               | Do This Instead                                                                                                                                                      |
| ----------------------------------------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Multi-AZ for all stateful services        | Costs 2x, you have 50 users                   | Single-AZ until paying customers with uptime commitments                                                                                                             |
| Separate microservices from day 1         | You have 2 engineers and 1 service            | Monolith or modular monolith. Split at pain points. If on Lambda, a well-organized single-repo with shared layers achieves the same cohesion as a container monolith |
| Use CloudTrail + GuardDuty + Security Hub | $20-50+/mo for security tooling               | CloudTrail only until Series A. Add GuardDuty at first enterprise deal                                                                                               |
| VPC with private subnets + NAT            | NAT costs $32+/mo minimum                     | Public subnets + security groups until you have compliance requirements                                                                                              |
| Custom KMS keys for encryption            | $1/key/mo + API costs                         | AWS-managed keys (free) until compliance requires CMK                                                                                                                |
| Detailed CloudWatch dashboards            | You're iterating weekly, dashboards are stale | 3 alarms (error rate, p99 latency, cost threshold). Add dashboards when you have an SRE                                                                              |
