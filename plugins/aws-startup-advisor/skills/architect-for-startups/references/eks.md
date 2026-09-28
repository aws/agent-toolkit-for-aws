# EKS — Startup-Specific Guidance

## The Hard Truth: Most Startups Shouldn't Use EKS

**EKS is a Series B+ decision.** The Kubernetes tax is real:

- EKS control plane: $73/month (before any workload runs)
- Minimum viable production cluster: ~$300-500/month (control plane + 2-3 nodes + ALB + NAT)
- Platform engineering time: 20-40% of one engineer's bandwidth for maintenance, upgrades, RBAC, networking
- Time to first deploy: days/weeks vs hours for ECS Fargate

**Choose EKS only when:**

- Team > 10-15 engineers with multiple teams needing namespace isolation
- You're hiring primarily from a Kubernetes-experienced talent pool
- You need advanced scheduling (GPU sharing, bin-packing, multi-tenancy)
- Your compute spend exceeds $20K/month and Karpenter's optimization justifies the platform cost
- You're already running K8s and migrating to AWS (don't re-learn ECS just for AWS)

## Startup Cost Traps

1. **The $73/month control plane for dev/staging**: Many startups create 3 clusters (dev/staging/prod) = $219/month in control planes alone before a single pod runs. At pre-Series A, use namespaces on a single cluster for isolation. Add dedicated clusters at Series B.

2. **Managed node groups with oversized instances**: Default tutorials use `m5.large` nodes. A startup running 3-5 microservices needs maybe 2-4 vCPUs total. Use `t3.medium` nodes or Karpenter with tight resource limits.

3. **Add-on sprawl**: Each add-on (cert-manager, external-dns, ArgoCD, Datadog, Istio) runs pods that consume node resources. A "production-ready" cluster with common add-ons needs 2-4 vCPUs just for platform components. Budget this separately.

4. **Karpenter consolidation disabled**: Karpenter defaults to not consolidating nodes. Enable `consolidationPolicy: WhenEmptyOrUnderutilized` immediately — it's the primary mechanism for right-sizing your fleet and avoiding paying for idle capacity.

5. **Load Balancer per service**: Each Kubernetes `Service type: LoadBalancer` creates an NLB (~$16/month). Use an Ingress controller (ALB Controller or nginx) to share one load balancer across services.

## Stage-Specific Recommendations (If You're Committed to EKS)

### Early (1 cluster, <$5K/month compute)

- Single cluster, namespaces for env separation (dev/staging/prod namespaces)
- Karpenter from day one — never use Cluster Autoscaler for new clusters
- Fargate profiles for low-traffic namespaces (dev) to avoid idle node costs
- Skip service mesh (Istio/Linkerd) — use simple K8s Services and Network Policies
- ArgoCD for GitOps from the start — it's free and prevents `kubectl apply` drift

### Growth ($5K-50K/month compute)

- Separate prod cluster from non-prod
- Karpenter with Spot for stateless workloads (70% savings)
- Pod Identity for IAM (not IRSA) — simpler, fewer moving parts
- Enable control plane logging for security/audit
- Implement PodDisruptionBudgets for all production workloads

### Scale ($50K+/month compute)

- Dedicated node groups for isolation (GPU, high-memory, batch)
- Multi-cluster with fleet management (if multi-region needed)
- Full observability stack (Prometheus/Grafana or Datadog)
- Consider EKS Anywhere for hybrid if needed

## Counterintuitive Startup Advice

- **ECS to EKS migration is easier than EKS to ECS.** If unsure, start with ECS. If you later need K8s, your containers and Dockerfiles transfer unchanged — only the orchestration layer changes. The reverse (EKS → ECS) requires removing all K8s-specific config (Helm charts, CRDs, operators).

- **A well-run ECS setup is operationally simpler AND cheaper than EKS until $20K/month compute.** The K8s ecosystem flexibility only pays off when you have enough services and team size to leverage it.

- **Don't use Helm for everything.** Early startups over-invest in templating 3-5 services with complex Helm charts. Plain Kubernetes manifests + Kustomize overlays are more readable and debuggable for small teams. Switch to Helm when you have 10+ services with shared patterns.

- **Fargate on EKS is worse than Fargate on ECS.** EKS Fargate has more limitations (no DaemonSets, no persistent volumes, no GPUs, higher per-pod overhead, slower scheduling). If you want Fargate simplicity, use ECS. If you want EKS, use managed node groups with Karpenter.

## When to Graduate TO EKS

| Signal                                                | Why Now                                 |
| ----------------------------------------------------- | --------------------------------------- |
| >15 engineers, multiple teams deploying independently | Namespace isolation, RBAC per team      |
| Monthly compute > $20K, need optimization             | Karpenter's bin-packing saves 30-40%    |
| Need GPU sharing across workloads                     | K8s device plugin + time-slicing        |
| Hiring pipeline is primarily K8s-experienced          | Developer experience matters            |
| Need advanced traffic management                      | K8s ecosystem (Istio, Cilium) is richer |

## Credits-Specific Guidance

- EKS control plane ($73/month) is covered by credits but is a fixed cost — don't create clusters you won't use.
- During credits: experiment with EKS to validate if your team can operate it. This is the time to learn without cost pressure.
- If your team struggles with EKS during the credits period, that's your answer — switch to ECS before credits expire and you're paying $500+/month for a platform you can't operate well.
