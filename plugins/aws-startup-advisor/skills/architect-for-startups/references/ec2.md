# EC2 — Startup-Specific Guidance

## When Startups Should Use EC2 Directly

**Almost never as your first choice.** Start with Lambda or ECS Fargate. EC2 makes sense for startups only when:

- You need GPUs (ML training/inference) — no Fargate GPU support
- You're running software that requires full OS control (custom kernels, specific drivers, Docker-in-Docker)
- You're running a stateful workload that doesn't fit managed services (self-managed databases, Redis clusters, Kafka)
- Your sustained compute spend exceeds $10K/month and you can commit to instance management

**The hidden cost**: EC2 requires patching, AMI management, monitoring agents, and capacity planning. At a 3-person startup, that's 10-20% of an engineer's time — your scarcest resource.

## Startup Cost Traps

1. **Running instances 24/7 in dev/staging**: A `t3.medium` costs ~$30/month. Three dev environments left running = $90/month doing nothing nights/weekends. Use Auto Scaling scheduled actions or Lambda-triggered stop/start. Savings: 65% on non-prod instances.

2. **Elastic IPs not attached to instances**: $3.60/month per unused EIP. Teams allocate them "for later" and forget. Check monthly.

3. **gp2 volumes still in use**: gp2 costs more than gp3 and performs worse at small sizes (gp2 scales IOPS with size; gp3 gives 3000 IOPS baseline regardless). Convert all gp2 → gp3 immediately, it's free and non-disruptive.

4. **Savings Plans purchased too early**: Don't buy Compute Savings Plans until you have 3+ months of stable EC2 usage data. Startups pivot — a 1-year commitment on instance types you abandon in 3 months is wasted money.

5. **Data transfer between AZs**: $0.01/GB each way. A chatty microservices architecture across AZs can accumulate $100s/month in cross-AZ transfer that doesn't show up obviously in Cost Explorer. Keep tightly-coupled services in the same AZ or use ECS/EKS service mesh for efficient routing.

## Stage-Specific Recommendations

### If You Must Use EC2 (Pre-Series A)

- **Single instance, single AZ** is acceptable for non-critical workloads
- Use `t3.small` or `t3a.small` ($15/month) — burstable is fine for dev/staging
- Use Spot for batch/ML training from day one — 70-90% savings and you learn the interruption model early
- **SSM Session Manager, not SSH keys** — zero additional infrastructure cost and IAM-controlled

### Growth Stage (Series A-B, steady EC2 usage)

- Buy 1-year No Upfront Compute Savings Plans for baseline (30% savings, flexible across instance types)
- Graviton (ARM64): migrate workloads for 20-30% cost reduction — most Docker containers work unchanged
- Mixed instance ASGs: 3+ instance types, Spot for workers, On-Demand for stateful

### Scale ($50K+/month EC2)

- 3-year Partial Upfront Savings Plans for steady-state base (up to 60% savings)
- Reserved Instances for specific GPU instances that don't change
- Spot fleet with `capacity-optimized` for batch/ML — diversify across 10+ instance types

## Counterintuitive Startup Advice

- **A single EC2 instance is a valid architecture.** For internal tools, admin panels, or low-traffic services that don't justify container orchestration — one `t3.small` with a Docker Compose setup and an AMI-based backup strategy works fine. It's not "production best practice" but it's pragmatic until revenue justifies HA.

- **Don't build for multi-AZ until you have paying customers who'd notice.** Multi-AZ doubles your compute baseline cost. If your SLA is informal and your recovery plan is "redeploy from AMI in 10 minutes," that's fine at pre-PMF.

- **Spot instances for production stateless workloads is fine.** The standard advice is "never use Spot in production." For startups: if your service handles graceful shutdown and you have On-Demand fallback in your ASG, the 70% savings funds an extra engineer-month every few months.

## When to Graduate TO EC2 (from Fargate)

| Signal                                             | Why EC2                                 |
| -------------------------------------------------- | --------------------------------------- |
| Monthly Fargate spend > $10K with >80% utilization | EC2 + Savings Plans is 30-50% cheaper   |
| Need GPU instances                                 | No Fargate GPU support                  |
| Need instance store NVMe for caching               | Fargate has no local storage option     |
| Running workloads requiring privileged containers  | Fargate doesn't support privileged mode |

## Credits-Specific Guidance

- EC2 On-Demand is covered by AWS Activate credits. During credits: don't buy Savings Plans or Reserved Instances — they can't be applied against credits and you lose flexibility.
- When credits expire: you'll hit full on-demand pricing immediately. Plan 1 month ahead: identify steady-state instances, purchase Savings Plans, and right-size or terminate anything over-provisioned.
- GPU instances (P/G family) burn credits extremely fast. A single `p3.2xlarge` costs ~$2,200/month. Use Spot for training and be deliberate about GPU hours.
