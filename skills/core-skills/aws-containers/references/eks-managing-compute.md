# Managing EKS Compute

A Kubernetes node is a machine that runs containerized applications. Your Amazon EKS cluster can schedule Pods on any combination of EKS Auto Mode managed nodes, self-managed nodes, Amazon EKS managed node groups, AWS Fargate, and Amazon EKS Hybrid Nodes.

## EKS Managed Node Groups

Amazon EKS managed node groups automate the provisioning and lifecycle management of nodes (Amazon EC2 instances) for Amazon EKS Kubernetes clusters.

### Warm Pools

Amazon EKS managed node groups support Amazon EC2 Auto Scaling warm pools. A warm pool maintains pre-initialized EC2 instances alongside your Auto Scaling group that can quickly join your cluster during scale-out events. Instances in the warm pool have already completed the bootup initialization process and can be kept in a Stopped, Running, or Hibernated state. This is most useful for applications with long initialization or boot times, where waiting for a cold node to boot and join the cluster would delay pod scheduling.

Key considerations:

- Always configure warm pools through the EKS API (`create-nodegroup` or `update-nodegroup-config`), not the EC2 Auto Scaling API directly — manual changes conflict with EKS management. EKS manages the pool via the `AWSServiceRoleForAmazonEKSNodegroup` service-linked role.
- Configuration parameters: `enabled`, `maxGroupPreparedCapacity` (max combined instances across the warm pool and ASG), `minSize` (default `0`), `poolState` (default `Stopped`), and `reuseOnScaleIn` (return instances to the pool on scale-in instead of terminating them; default `false`).
- Custom AMIs are not supported — you must use EKS-optimized AMIs.
- With Bottlerocket AMIs, the `Hibernated` pool state and `reuseOnScaleIn` are not supported; use `Stopped` or `Running` only.
- The `Hibernated` pool state is only supported on specific instance types (see the EC2 hibernation prerequisites).
- Updating warm pool settings doesn't affect instances already in the pool; new settings apply only to instances entering the pool afterward. Set `enabled=false` to disable the pool.
- Cost: a warm pool that isn't needed adds unnecessary cost. Size it to your scaling patterns — a starting point is 10–20% of expected peak capacity.
- Ensure your VPC has enough IP addresses for both the ASG and warm pool instances.
- Not all instance types, AMIs, or configurations are supported; review the EC2 Auto Scaling warm pool prerequisites and limitations first.

Create a managed node group with a warm pool:

```bash
aws eks create-nodegroup \
  --cluster-name my-cluster \
  --nodegroup-name my-nodegroup \
  --node-role arn:aws:iam::111122223333:role/AmazonEKSNodeRole \
  --subnets subnet-12345678 subnet-87654321 \
  --region us-east-1 \
  --scaling-config minSize=2,maxSize=10,desiredSize=3 \
  --warm-pool-config enabled=true,maxGroupPreparedCapacity=8,minSize=2,poolState=Stopped,reuseOnScaleIn=true
```

Add a warm pool to (or update one on) an existing node group:

```bash
aws eks update-nodegroup-config \
  --cluster-name my-cluster \
  --nodegroup-name my-nodegroup \
  --region us-east-1 \
  --warm-pool-config enabled=true,maxGroupPreparedCapacity=10,minSize=3,poolState=Running,reuseOnScaleIn=true
```

Disable the warm pool attached to a node group:

```bash
aws eks update-nodegroup-config \
  --cluster-name my-cluster \
  --nodegroup-name my-nodegroup \
  --region us-east-1 \
  --warm-pool-config enabled=false
```

See [the documentation](https://docs.aws.amazon.com/eks/latest/userguide/warm-pools-managed-node-groups.html) for more information.

## AWS Fargate

AWS Fargate is a serverless compute engine for containers that removes the need to provision and manage servers. With Fargate, you no longer have to select EC2 instance types, manage node scaling, or optimize cluster packing. Instead, you define Fargate profiles for your EKS cluster that specify which Pods should run on Fargate.

> **Note:** For new clusters, we recommend [EKS Auto Mode](eks-auto-mode.md) as the preferred approach to serverless compute. EKS Auto Mode provides a fully automated node management experience with broader feature support, including GPU workloads, EBS volumes, and a wider range of compute configurations. Consider Fargate for existing workloads that already use Fargate profiles or when your use case specifically requires the per-Pod microVM isolation model.

### Fargate Profiles

A Fargate profile defines which Pods run on Fargate infrastructure. Each profile specifies:

- One or more subnets (only private subnets are supported; Fargate Pods are not assigned public IP addresses)
- One or more selectors, each containing a namespace and optional labels used to match Pods

When a Pod matches a selector in a Fargate profile, it is scheduled onto Fargate. A cluster can have multiple Fargate profiles. If a Pod matches multiple profiles, the first matching profile is used.

### Key Considerations

- Each Fargate Pod runs in its own isolated compute environment (a dedicated microVM) and does not share its underlying kernel, CPU, memory, or network interface with another Pod.
- DaemonSets are not supported on Fargate. If your application requires a DaemonSet, consider using a sidecar container pattern instead.
- Privileged containers and `hostNetwork`/`hostPort` are not supported on Fargate.
- GPU workloads are not supported on Fargate.
- If your Pod requires more resources than supported by Fargate, use Karpenter or Managed Node Groups.
- Persistent storage is supported through Amazon EFS (via CSI driver). Amazon EBS volumes are not supported on Fargate.
- The EKS node monitoring agent and automatic node repair are not available for Fargate Pods since AWS manages the underlying infrastructure.
- Vertical Pod Autoscaler can be used to right-size Fargate Pod resource requests.

### Fargate Pod Sizing

Fargate allocates compute resources based on the Pod's resource requests. It rounds up to the nearest Fargate-supported configuration. If no requests are specified, a default of 0.25 vCPU and 0.5 GB memory is applied. You should always set explicit resource requests to ensure Pods receive appropriate compute capacity and to avoid overpaying for unused resources.

When provisioned, each Pod running on Fargate receives ephemeral storage. This type of storage is deleted after a Pod stops.

See [the documentation](https://docs.aws.amazon.com/eks/latest/userguide/fargate-pod-configuration.html) for more information on both pod sizing and ephemeral storage.

## Pre-build optimized AMIs

You can deploy nodes with pre-built Amazon EKS optimized Amazon Machine Images (AMIs) or your own custom AMIs when you use managed node groups or self-managed nodes.

### Amazon Linux 2 deprecation

AWS is ending support for EKS AL2-optimized and AL2-accelerated AMIs. After the end-of-support (EOS) date, EKS will no longer release any new Kubernetes versions or updates to AL2 AMIs, including minor releases, patches, and bug fixes, though existing AMIs remain usable. We recommend upgrading to Amazon Linux 2023 (AL2023) or Bottlerocket AMIs. Check the documentation below for the current EOS date.

See [the documentation](https://docs.aws.amazon.com/eks/latest/userguide/eks-ami-deprecation-faqs.html) for more information.

## Node health and repair

To help with maintaining healthy nodes in EKS clusters, EKS offers the node monitoring agent and automatic node repair. These features are automatically enabled with EKS Auto Mode compute. You can also use automatic node repair with EKS managed node groups and Karpenter, and can use the EKS node monitoring agent with any EKS compute types except for AWS Fargate. The EKS node monitoring agent and automatic node repair are most effective when used together, but they can also be used individually in EKS clusters.

If the user has expresses a specific type of node issue they wish help monitoring and remediating then you MUST consult the associated documentation below to confirm it is in scope for the corresponding feature.

### Node monitoring agent

The EKS node monitoring agent reads node logs to detect health issues. It parses logs to detect failures and surfaces status information about the health status of the nodes. For each category of issues detected, the agent applies a dedicated NodeCondition to the worker nodes. For detailed information on the node health issues detected by the EKS node monitoring agent, see [Detect node health issues with the EKS node monitoring agent](https://docs.aws.amazon.com/eks/latest/userguide/node-health-nma.html).

Considerations:

- EKS Auto Mode compute automatically includes the node monitoring agent.
- For other EKS compute types, you can add the node monitoring agent as an EKS add-on or you can manage it with Kubernetes tooling such as Helm.

### Automatic node repair

EKS automatic node repair continuously monitors node health, reacts to detected problems, and replaces or reboots nodes when possible. This improves cluster reliability with minimal manual intervention and helps reduce application downtime.

Considerations:

- Automatic node repair is enabled by default in EKS Auto Mode and can also be used with EKS managed node groups and Karpenter. It relies on the NodeConditions surfaced by the node monitoring agent, so the two are most effective together.
- It cannot be configured for EKS Auto Mode (always on with the same defaults as Karpenter). For Karpenter, enable the `NodeRepair=true` feature gate. For managed node groups, enable it at creation or update (for example `--node-repair-config enabled=true`, the console checkbox, or `nodeRepairConfig.enabled: true` in eksctl).
- Repair only happens after the unhealthy condition persists for a wait period. Most conditions (`Ready`, `KernelReady`, `NetworkingReady`, `StorageReady`, `ContainerRuntimeReady`) wait 30 minutes and are repaired by replacing the node; `AcceleratedHardwareReady` (GPU/Neuron) waits 10 minutes. Standard `DiskPressure` and `MemoryPressure` conditions trigger no repair action.
- `Reboot` as a repair action is only supported by EKS managed node groups. For EKS Auto Mode and Karpenter, all `AcceleratedHardwareReady` repairs are `Replace`.
- Repair is paused automatically to avoid mass disruption: for managed node groups when the group has more than five nodes and more than 20% are unhealthy (or when an ARC zonal shift triggers); for Auto Mode and Karpenter when more than 20% of nodes in the NodePool (or cluster, for standalone NodeClaims) are unhealthy. In-progress repairs continue.
- For managed node groups you can tune this behavior: set an unhealthy-node stop threshold (`maxUnhealthyNodeThresholdCount` or `maxUnhealthyNodeThresholdPercentage`), control concurrency (`maxParallelNodesRepairedCount` or `maxParallelNodesRepairedPercentage`), and override per-condition behavior with `nodeRepairConfigOverrides` (setting `minRepairWaitTimeMins` and a `repairAction` of `Replace`, `Reboot`, or `NoAction` for a specific `nodeMonitoringCondition`/`nodeUnhealthyReason`).

For more information on EKS automatic node repair, see [Automatically repair nodes in EKS clusters](https://docs.aws.amazon.com/eks/latest/userguide/node-repair.html).
