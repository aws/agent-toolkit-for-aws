# Team Scaling

## Ops Capacity Limits by Team Size

### Solo Founder (1 person)

- **Zero ops tolerance**. If it requires SSH, patching, monitoring, or on-call — you can't use it.
- If it breaks at 3am, it waits until morning.
- One AWS account. No staging environment.
- Cannot operate anything with "cluster" in the name or anything requiring capacity planning.

### Small Team (2-5 engineers)

- ~20% of one engineer's time on infra (not a dedicated role)
- Alerts go to Slack, not PagerDuty — not enough people for on-call
- Can now operate: ECS Fargate, Aurora Serverless v2, basic IaC
- Cannot operate: EKS, multi-account, Transit Gateway, SOC2 program

### Growth Team (5-15 engineers)

- Infrastructure lead at 50% time (not full-time dedicated)
- On-call rotation possible (minimum 4 people for sustainable rotation)
- Can now operate: ECS with EC2, ElastiCache, multi-account, VPC with subnets, Security Hub
- Cannot operate: EKS (unless deep K8s experience exists), multi-region active-active, service mesh

### Platform Team (15+ engineers)

- 2-4 dedicated platform/SRE engineers justified
- Generic AWS service references apply without team-size filtering
- Platform team enables product teams — doesn't gate them

---

## When to Hire for Infrastructure

| Signal                                  | Hire                                             | Typical Stage  |
| --------------------------------------- | ------------------------------------------------ | -------------- |
| Deploys breaking, nobody knows why      | First infra-aware engineer (not full-time infra) | Seed           |
| On-call burning out product engineers   | Infra lead (50/50 split)                         | Early Series A |
| Teams blocked waiting for infra changes | First dedicated platform engineer                | Mid Series A   |
| AWS bill > $50K/month                   | FinOps-focused engineer                          | Series B       |

### Counterintuitive Advice

**Don't hire a "DevOps engineer" at seed stage:**

- Not enough infra to justify full-time role
- They will over-engineer because that's their job
- You'll end up with Kubernetes for a 3-service app
- Instead: hire product engineers comfortable with AWS + use managed services

**Don't wait until Series B for infra thinking:**

- Years of accumulated tech debt by then
- Nobody understands the system holistically
- Hiring becomes harder (intimidating codebase)
- Right time for dedicated infra person: when incidents start costing users or revenue

---

## Managed Services Cost Justification

**Rule of thumb**: At startup salaries ($150-250K/year = $75-125/hour), a managed service costing $500/month is cheaper than 7 hours of engineering time per month.

| Self-Managed              | Managed          | Monthly Ops Hours Saved |
| ------------------------- | ---------------- | ----------------------- |
| PostgreSQL on EC2         | Aurora/RDS       | 10-20 hours             |
| Kubernetes (self-managed) | EKS with Fargate | 20-40 hours             |
| Jenkins on EC2            | GitHub Actions   | 10-15 hours             |
| Prometheus/Grafana        | CloudWatch       | 10-20 hours             |
| Keycloak                  | Cognito          | 5-10 hours              |

The smaller your team, the more managed services function as headcount replacement.
