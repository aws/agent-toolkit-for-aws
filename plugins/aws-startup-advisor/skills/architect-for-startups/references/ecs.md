# ECS — Startup-Specific Guidance

## When to Choose ECS (vs Lambda or EKS)

**Choose ECS when**: You've outgrown Lambda ($300-500+/month Lambda bill with steady traffic), need long-running processes, WebSockets, or >6MB responses, but don't have a platform team to run Kubernetes.

**The startup sweet spot**: ECS Fargate is the "right-sized" container platform for teams of 1-15 engineers. It gives you containers without the Kubernetes learning curve, tax, or operational burden.

**Do NOT start with ECS if**: Your traffic is spiky/unpredictable and you can fit in Lambda's constraints. Lambda's scale-to-zero beats Fargate's minimum-task cost for low-traffic services.

## Startup Cost Traps

1. **Fargate Spot in production services**: 70% savings sounds great, but Spot tasks get terminated with 30s warning. Use ONLY for: batch jobs, queue workers, background processing. Never for user-facing APIs unless you have graceful failover to on-demand.

2. **Over-provisioned task definitions**: Startups copy-paste `2 vCPU / 4GB` task defs without measuring. A typical Node.js/Python API serves 200+ req/s on `0.25 vCPU / 0.5GB` (~$9/month). Start at the minimum and scale up based on Container Insights metrics.

3. **ALB cost baseline**: An ALB costs ~$22/month minimum (fixed hourly) + LCU charges. For a startup with 2-3 services, that's fine. But don't create one ALB per service — use path-based routing on a shared ALB until you need isolation.

4. **NAT Gateway double-tax**: Fargate tasks in private subnets need NAT for internet access. NAT costs $32/month + $0.045/GB processed. For early startups with one service, consider running in public subnets with security groups locked down (heresy, but saves $32/month). Graduate to private subnets when you have compliance requirements or >3 services.

5. **Container Insights**: Costs ~$7-15/month in CloudWatch charges per cluster. Worth it for production, not needed for dev/staging.

## Stage-Specific Recommendations

### Pre-PMF (1-5 engineers, <$1K/month infra)

- **Single Fargate service**, single ALB, public subnet (with locked-down SG)
- `0.25 vCPU / 0.5GB` task, `minCount=1`, `maxCount=3`
- Use `ECS Exec` for debugging (replaces SSH)
- Total cost: ~$35-50/month (1 task + ALB)

### Post-PMF / Series A (5-15 engineers, $1K-10K/month)

- Move to private subnets + NAT Gateway
- Add a second service (worker/background jobs)
- Enable Container Insights on production cluster
- Use Fargate Spot for workers, on-demand for APIs
- Consider Graviton (`ARM64`) — 20% cheaper on Fargate too

### Scaling (Series B+, >$10K/month compute)

- Evaluate ECS on EC2 with Savings Plans if >80% utilization sustained
- Fargate's ~20-30% premium over EC2 matters at $50K+/month
- At this stage, also evaluate if EKS makes sense for your hiring pipeline (more K8s engineers available than ECS-specific)

## Counterintuitive Startup Advice

- **One cluster, one service is fine.** The "one cluster per environment" guidance assumes you have environments. At pre-PMF, run one cluster with one production service. Add dev/staging clusters when you have a team that needs them.

- **Skip blue/green deployments initially.** Rolling updates with circuit breaker give you auto-rollback without CodeDeploy complexity. Blue/green adds value at scale (instant rollback) but adds operational surface area early.

- **`:latest` tag is acceptable in dev/staging.** Yes, it's an anti-pattern in production. But for a 2-person team iterating daily, the overhead of tagging every dev build with a SHA isn't worth it until you have a CI/CD pipeline.

- **Don't multi-region until revenue demands it.** ECS services in 2 regions = 2x base cost + cross-region complexity. Stay single-region until you have customers requiring <50ms latency in another continent or contractual uptime SLAs.

## When to Graduate from ECS

| Signal                                                      | Direction                                                |
| ----------------------------------------------------------- | -------------------------------------------------------- |
| Team > 15 engineers, multiple teams deploying independently | Evaluate EKS — better multi-tenancy, namespace isolation |
| Monthly compute bill > $50K with Fargate                    | Evaluate ECS on EC2 with Spot + Savings Plans            |
| Need service mesh, custom autoscaling, GitOps               | EKS ecosystem is richer for these                        |
| Hiring pipeline returns mostly K8s-experienced candidates   | Switching cost is worth it for velocity                  |

## Credits-Specific Guidance

- Fargate compute is covered by AWS Activate credits. During credits: use on-demand everywhere, don't bother with Spot, and provision for peak.
- When credits expire: the "always on" baseline of Fargate tasks hits immediately. Budget the transition: right-size tasks, add Spot for workers, configure scale-to-zero for non-prod.
- Fargate costs are predictable — easy to model post-credits burn rate: `tasks × hours × (vCPU_price + memory_price)`.
