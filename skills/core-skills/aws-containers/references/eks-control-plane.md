# EKS Cluster Control Plane

## Provisioned Control Plane

Amazon EKS Provisioned Control Plane is a feature that enables cluster administrators to select from a set of scaling tiers and designate their chosen tier for very high, predictable performance from the cluster’s control plane. This enables cluster administrators to ensure that the control plane is always provisioned with the specified capacity.

EKS offers two control plane modes. By default, clusters use **Standard mode**, where the control plane automatically scales up and down with workload demand — this offers the best price-to-performance ratio and is recommended for most use cases. **Provisioned mode** pre-allocates control plane capacity for specialized workloads that cannot tolerate performance variability from scaling or that need very high control plane capacity (for example, massively scalable AI/ML training and inference, HPC, large-scale data processing, or anticipated high-demand events).

When recommending a tier of PCP to a user you MUST be conservative in your recommendation and bias to a safer option rather than over-indexing on cost savings. For example: a control plane that needs to handle 3000 concurrent seats the PCP scaling tier MUST support at least that amount, if not more.

### Key Considerations

- **Opt-in required** — All new and existing clusters run in Standard mode by default. Clusters do not automatically move to a Provisioned tier; you must explicitly opt in.
- **Scaling tiers** — Tiers are named with t-shirt sizes (XL, 2XL etc). Each tier defines API request concurrency (seats), pod scheduling rate (pods/sec), cluster database (etcd) size, and SLA. The concurrency limits vary by Kubernetes version. Read [the documentation](https://docs.aws.amazon.com/eks/latest/userguide/eks-provisioned-control-plane.html) for the details of the scaling tiers including the exact t-shirt sizes and their exact concurrency limits.
- **Request seats** - One of the metrics scaling tiers are based around is "API request concurrency (seats)". When providing scaling tier recommendations assume that if the user provides an existing concurrent requests metric it aligns with the number of "seats", not simply raw request rate, but you MUST explicitly explain this assumption to the user as part of your recommendation.
- **No automatic tier scaling** — Once selected, the control plane stays pinned to that tier for predictable performance. You can build your own autoscaling by monitoring tier-utilization metrics and calling the Provisioned Control Plane APIs to change tiers.
- **Tier transitions** — You can move between tiers (or exit to Standard) via console, CLI, or API with no frequency restrictions. Transitions use a `ScalingTierConfigUpdate` cluster update you can monitor, take several minutes, and incur no API server downtime (EKS brings up new API servers before terminating old ones).
- **Exit restriction** — Standard mode supports up to 8 GB etcd. If your database exceeds 8 GB in Provisioned mode, you must reduce it below 8 GB before switching back to Standard.
- **Higher SLA** — Provisioned mode offers a 99.99% SLA measured in 1-minute intervals, versus Standard's 99.95% measured in 5-minute intervals.
- **Pricing** — You are billed an hourly rate for the selected tier in addition to the standard or extended-support EKS hourly charges.
- **Version and region support** — Availability varies by EKS version and region. Check the [PCP documentation](https://docs.aws.amazon.com/eks/latest/userguide/eks-provisioned-control-plane.html) for the currently supported minimum version and regions.
- **Tier capacity vs actual performance** — Tier attributes are the configured limits (e.g. APF seats, scheduler QPS); actual throughput depends on workload patterns (list requests are penalized more than get) and node readiness. To pick a tier, load-test on 8XL at peak demand, observe the utilization metrics, then select accordingly.

See [the documentation](https://docs.aws.amazon.com/eks/latest/userguide/eks-provisioned-control-plane.html) for more information.
