# EKS Auto Mode

EKS Auto Mode extends AWS management of Kubernetes clusters beyond the cluster itself, to allow AWS to also set up and manage the infrastructure that enables the smooth operation of your workloads. You can delegate key infrastructure decisions and leverage the expertise of AWS for day-to-day operations. Cluster infrastructure managed by AWS includes many Kubernetes capabilities as core components, as opposed to add-ons, such as compute autoscaling, pod and service networking, application load balancing, cluster DNS, block storage, and GPU support.

In general it is critical to avoid making assumptions about EKS Auto Mode clusters, their capabilities and how to configure them relative to traditional EKS clusters. The EKS Auto Mode documentation should be referred to as much as needed to make informed decisions.

## Compute

EKS Auto Mode relies on Karpenter autoscaling to provision and manage cluster compute, and nodes are designed to be treated like appliances. EKS Auto Mode does the following:

- Chooses an appropriate AMI that’s configured with many services needed to run your workloads without intervention.
- Locks down access to files on the AMI using SELinux enforcing mode and a read-only root file system.
- Prevents direct access to the nodes by disallowing SSH or SSM access.
- Includes GPU support, with separate kernel drivers and plugins for NVIDIA and Neuron GPUs, enabling high-performance workloads.
- Automatically handles EC2 Spot Instance interruption notices and EC2 Instance health events

### Node Classes

Amazon EKS Node Classes are templates that offer granular control over the configuration of your EKS Auto Mode managed nodes. A Node Class defines infrastructure-level settings that apply to groups of nodes in your EKS cluster, including network configuration, storage settings, and resource tagging.

EKS Auto Mode uses a node class CRD that is different from standard Karpenter. You must refer to the relevant EKS Auto Mode [documentation](https://docs.aws.amazon.com/eks/latest/userguide/create-node-class.html) when answering questions or authoring configurations related to Auto Mode node classes.

### Node Pools

Amazon EKS node pools offer a flexible way to manage compute resources in your Kubernetes cluster. This topic demonstrates how to create and configure node pools by using Karpenter, a node provisioning tool that helps optimize cluster scaling and resource utilization. With Karpenter’s NodePool resource, you can define specific requirements for your compute resources, including instance types, availability zones, architectures, and capacity types.

EKS Auto Mode uses different labels than Karpenter. Labels related to EC2 managed instances start with `eks.amazonaws.com`.

See the relevant [documentation](https://docs.aws.amazon.com/eks/latest/userguide/create-node-pool.html) for more information on EKS Auto Mode node pools.

## Networking

EKS Auto Mode has some networking capabilities that differ from standard EKS clusters.

### Ingress

EKS Auto Mode creates and configures Application Load Balancers (ALBs). For example, EKS Auto Mode creates a load balancer when you create an Ingress Kubernetes object and configures it to route traffic to your cluster workload.

This works much the same way as the AWS Load Balancer Controller but is a different implementation. Key differences include:

- Certain Ingress annotations are not supported, see the documentation for details before recommending certain annotations.
- You cannot use Annotations on an IngressClass to configure load balancers with EKS Auto Mode. IngressClass configuration should be done through IngressClassParams.
- `TargetGroupBinding` and `IngressClassParams` CRDs have different signatures, see the documentation for details.

See [the documentation](https://docs.aws.amazon.com/eks/latest/userguide/auto-configure-alb.html) for more information.

### Network policies

EKS Auto Mode supports the following through network policies:

- L3/L4 isolation
- DNS-based environment
- Admin (or cluster-scoped) rules

See [the documentation](https://docs.aws.amazon.com/eks/latest/userguide/auto-net-pol.html) for more information.
