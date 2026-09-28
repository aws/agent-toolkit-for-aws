# Stage Frameworks

## Pre-Revenue (1-2 founders, no users)

**Principle**: Ship something users can touch this week. Nothing else matters.

**Hard constraints**:

- Zero server management — Lambda or ECS Express Mode only
- Match compute to how the team develops locally: if they're already containerized, deploy containers. If not, Lambda is simpler.
- No custom VPC (Lambda, DynamoDB, S3 don't need one)
- No Multi-AZ (you have zero users)
- IaC is optional — Console or `cdk deploy` from laptop is fine
- CI/CD = `git push` → auto-deploy. Nothing more.
- Cost target: $0-50/month

**Explicitly banned** (money pits at this stage):

- EKS ($73/mo for nothing), NAT Gateway ($32/mo for nothing)
- Multi-AZ RDS, ElastiCache, AWS Config
- Custom CloudWatch metrics ($0.30/metric/month adds up)
- Service mesh, multi-region, dedicated CI/CD pipeline

**You don't need this yet**: observability beyond basic alarms, load testing, DR plan, staging environment.

---

## Seed (2-5 people, <1K users, $500K-$2M raised)

**Principle**: Every dollar on infra is a dollar not spent on product. Prove PMF first.

**Key constraints**:

- On-demand pricing only — don't commit to provisioned anything
- One pipeline, one environment (prod). Staging is optional luxury.
- Single AWS account is still fine (use tags)
- No Savings Plans — you don't know your baseline yet
- Cost target: $100-500/month, credits should cover 12-18 months

**Now add** (but keep simple):

- SQS for async work (decouple heavy processing from API)
- EventBridge for internal event routing
- IaC (CDK or Terraform) — one stack, not microstack per service
- CloudWatch alarms on: 5xx rate, latency p99, DynamoDB throttles

**Still avoid**: EKS, Redshift, Step Functions Standard ($0.025/1K transitions), multiple AWS accounts, Security Hub.

**Trigger to graduate**: >1K active users, raising Series A, team >5, first incident that costs you users.

---

## Series A (5-15 engineers, 1K-100K users, $5M-$20M raised)

**Principle**: Harden what works. Add reliability and observability — don't re-architect.

**Key changes**:

- Multi-AZ for all production workloads
- Separate AWS accounts (prod vs non-prod)
- No console changes to production — everything in IaC
- On-call rotation (minimum 4 people for sustainability)
- Weekly 5-minute cost review
- Cost target: $1K-10K/month

**Now appropriate**:

- Savings Plans after 3+ months stable data (1-year Compute SP, No Upfront, cover 50-70% baseline)
- ECS with EC2 for steady-state workloads where Fargate cost exceeds EC2 + SP
- RDS Proxy for Lambda → RDS connection pooling
- WAF if handling sensitive data or seeing abuse
- SOC2 prep (GuardDuty + Security Hub + Config)
- Blue/green or canary deploys

**Trigger to graduate**: 100K+ users, >15 engineers, need dedicated platform team, multi-region requirements.

---

## Series B+ (15+ engineers, 100K+ users, dedicated platform team)

At this stage, standard AWS best practices apply. Startup-specific filtering dissolves.

**What persists from startup thinking**:

- Speed still matters — platform team enables, doesn't gate
- Track cost per customer (investors care about unit economics)
- Still prefer managed services — your moat is product, not your K8s cluster
- Credits may still apply through Series B — check expiration dates

---

## Stage Transition Checklist

### Pre-Revenue → Seed

- [ ] Real users (not just friends testing)
- [ ] Hit a real limitation of pre-revenue architecture (not just "feels hacky")
- [ ] Credits/funding for 12+ months of infra

### Seed → Series A

- [ ] PMF evidence (retention, revenue, growth rate)
- [ ] At least one user-impacting incident
- [ ] Can afford $1K+/month in infra without stress
- [ ] Team growing and needs shared standards

### Series A → Series B+

- [ ] Need dedicated platform/SRE team (not just one person part-time)
- [ ] Multi-region is a real requirement, not nice-to-have
- [ ] Compliance demands formal controls
