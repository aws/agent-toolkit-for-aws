# Managing ECS Compute

Amazon ECS runs your containers as _tasks_, and each task needs compute capacity to run on. ECS gives you three ways to provide that capacity: AWS Fargate (serverless), the EC2 launch type backed by Auto Scaling group capacity providers (you manage the EC2 instances), and Amazon ECS Managed Instances (AWS manages the EC2 instances for you). You select capacity per task or service using either a launch type (`FARGATE` or `EC2`) or a capacity provider strategy.

## ECS Managed Instances

Amazon ECS Managed Instances is a fully managed compute option for Amazon ECS that enables you to run containerized workloads on the full range of Amazon EC2 instance types while offloading infrastructure management to AWS. With Amazon ECS Managed Instances, you can access specific compute capabilities such as GPU acceleration, particular CPU architectures, high network performance, and specialized instance types, while AWS handles provisioning, scaling, patching, and maintenance of the underlying infrastructure.

You package your application in containers and specify your compute requirements. AWS automatically selects the most cost-optimized general-purpose EC2 instance types that meet your workload needs, or you can specify desired instance attributes (instance types, CPU manufacturers, accelerators, and so on). By default, ECS Managed Instances optimizes utilization by placing multiple smaller tasks on a single larger instance, unlike Fargate which runs each task in its own isolated environment.

Important considerations:

1. ECS Managed Instances is used through **capacity providers**, not a launch type. You enable ECS Managed Instances in your account, create a capacity provider (default instance selection or custom `instanceRequirements`), associate it with a cluster, and reference it in a capacity provider strategy. A capacity provider strategy can only contain one type of capacity provider — ECS Managed Instances, Auto Scaling group, or Fargate/Fargate_SPOT — not a mix.
1. To make a task definition eligible, set the `requiresCompatibilities` parameter to include `MANAGED_INSTANCES`. A task definition can declare both `FARGATE` and `MANAGED_INSTANCES` for deployment flexibility, and existing Fargate task definitions using platform version `1.4.0` are compatible.
1. The instances run an AWS-managed, security-hardened **Bottlerocket** AMI. Custom AMIs are not supported. There is no SSH access — use ECS Exec for debugging.
1. Instances have a **maximum lifetime of 14 days**; ECS drains and replaces them automatically to keep them patched. Long-running tasks that must exceed 14 days are not suitable for ECS Managed Instances.
1. Two IAM roles are required: an _infrastructure role_ that lets ECS manage instances on your behalf, and an _instance profile_ for the workloads running on the instances.
1. Supported CPU architectures are `X86_64` and `ARM64`. Supported network modes are `awsvpc` and `host`.
1. The capacity provider can launch On-Demand or Spot Instances (and EC2 Capacity Reservations) via the `capacityOptionType` parameter on the instance launch template — valid values are `ON_DEMAND`, `SPOT`, and `RESERVED`, defaulting to `ON_DEMAND`. Spot uses spare EC2 capacity at reduced cost but can be interrupted with a two-minute notification.
1. By default ECS packs multiple tasks onto a single instance for utilization. If you require strong isolation, you can configure ECS Managed Instances to run a single task per instance, giving each task VM-level security isolation boundaries.
1. To prevent overly aggressive scale-in of underutilized instances, set the `scaleInAfter` parameter on the capacity provider's `infrastructureOptimization` configuration. It defines how many seconds (0–3600) ECS waits before optimizing idle or underutilized instances — a longer delay increases the chance of placing new tasks on existing instances and reduces startup time, while a shorter delay reduces cost. Use `null` for the default behavior or `-1` to disable automatic optimization entirely.
1. See [the supported instance types documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/managed-instances-instance-types.html) to check which EC2 instance types are supported.

See [the documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ManagedInstances.html) for more information.

## AWS Fargate

AWS Fargate is a technology that you can use with Amazon ECS to run containers without having to manage servers or clusters of Amazon EC2 instances. With AWS Fargate, you no longer have to provision, configure, or scale clusters of virtual machines to run containers. This removes the need to choose server types, decide when to scale your clusters, or optimize cluster packing. To use it, set the `requiresCompatibilities` task definition parameter to include `FARGATE` (or launch with the `FARGATE`/`FARGATE_SPOT` capacity providers).

### Key Considerations

- Each Fargate task runs in its own isolated compute environment (a dedicated microVM) and does not share its underlying kernel, CPU, memory, or network interface with another task.
- Fargate tasks always use the `awsvpc` network mode and receive their own elastic network interface. The `host` network mode, `hostPort` host bindings, and `disableNetworking` are not supported.
- Both Application Load Balancers (ALB) and Network Load Balancers (NLB) are supported for ECS services on Fargate. When you create the target group, you must choose the `ip` target type (not `instance`) because tasks have their own network interface.
- Privileged containers (`privileged`) are not supported. For `linuxParameters` capabilities, the only Linux capability you can add is `CAP_SYS_PTRACE`.
- GPU workloads are not supported on Fargate (the `gpu` resource requirement is not valid).
- Several task definition parameters are not valid on Fargate, including `placementConstraints`, `links`, `ipcMode`, `dnsServers`, `extraHosts`, `maxSwap`, and `swappiness`.
- Persistent storage is supported through both Amazon EFS volumes and Amazon EBS volumes; bind mounts provide ephemeral storage. (Unlike EKS Fargate, EBS volumes _are_ supported on ECS Fargate.)
- Fargate tasks ephemeral storage on Linux platform version `1.4.0` or later (and Windows `1.0.0` or later), configurable via the `ephemeralStorage` parameter. The ephemeral storage is encrypted.
- Linux containers can run on `X86_64` or `ARM64`; Windows containers require `X86_64`.
- Supported log drivers are `awslogs`, `splunk`, and `awsfirelens`.

### Fargate Task Sizing

Fargate task definitions require you to specify CPU and memory at the **task level** (most workloads only need task-level values; you can optionally also set container-level limits). Fargate allocates resources to match the configuration you request — there is no rounding or implicit default, so you must pick a valid combination. CPU can be expressed in CPU units or vCPUs (for example `1024` or `1 vCPU`) and memory in MiB or GB (for example `3072` or `3 GB`).

If your task needs more resources than provided, use the EC2 launch type or ECS Managed Instances.

See [the documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-tasks-services.html) for more information, including valid combinations for CPU and memory.

## EC2 launch type and capacity providers

When you use the EC2 launch type, you provide and manage the Amazon EC2 instances (container instances) that your tasks run on. The recommended way to manage this capacity is with **Auto Scaling group (ASG) capacity providers**, which connect an ECS cluster to an Auto Scaling group so capacity scales with your task demand.

### Cluster auto scaling and managed scaling

With **managed scaling** enabled, ECS manages the scale-out and scale-in actions of the Auto Scaling group on your behalf, using a target-tracking scaling policy driven by the `CapacityProviderReservation` metric. When managed scaling is on, the Auto Scaling group's desired count can start at `0` and ECS scales it as tasks are placed. If the group can't scale out to fit the tasks you run, those tasks stay in the `PROVISIONING` state until capacity is available.

### Managed instance draining

We recommend using **managed instance draining**, which is on by default, so that EC2 instances are gracefully drained (tasks stopped and rescheduled) before the instance is terminated during scale-in or instance replacement. This avoids disrupting your workloads.

### Warm pools

ECS supports Amazon EC2 Auto Scaling warm pools. A warm pool maintains pre-initialized EC2 instances alongside your Auto Scaling group that can quickly join your cluster during scale-out events. Instances in the warm pool have already completed the bootup initialization process and can be kept in a Stopped, Running, or Hibernated state. See [the documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/using-warm-pool.html) for limitations.

A cluster can contain a mix of Auto Scaling group and Fargate capacity providers, but a single capacity provider strategy can only use one type. You can specify a maximum of 20 capacity providers in a strategy.

See [the documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/asg-capacity-providers.html) for more information.

## Pre-built optimized AMIs

When you use the EC2 launch type, your container instances run from an AMI that includes the **Amazon ECS container agent** (which registers the instance with your cluster and manages task lifecycle) and a container runtime. AWS publishes Amazon ECS-optimized AMIs preconfigured for this, and you can also build your own custom AMI. Variants are available for Amazon Linux 2023 and Amazon Linux 2, including arm64 (Graviton), GPU, and Neuron (Inferentia/Trainium) flavors. You can retrieve the latest AMI IDs from the Systems Manager Parameter Store.

We recommend the **Amazon ECS-optimized Amazon Linux 2023 AMI** for new instances, as it receives current security updates and the latest container agent version.

### Amazon Linux 2 deprecation

The Amazon ECS-optimized Amazon Linux 2 AMI is being retired, mirroring the EOL of the upstream Amazon Linux 2 operating system. AWS recommends upgrading to Amazon Linux 2023. Check the migration documentation below for the current end-of-life date.

See [the migration documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/al2-to-al2023-ami-transition.html) and the [Amazon ECS-optimized Linux AMIs documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-optimized_AMI.html) for more information.
