# EKS Networking

Your Amazon EKS cluster is created in a VPC. Pod networking is provided by the Amazon VPC Container Network Interface (CNI) plugin for nodes that run on AWS infrastructure.

## Amazon VPC CNI

The Amazon VPC CNI plugin for Kubernetes add-on is deployed on each Amazon EC2 node in your Amazon EKS cluster. The add-on creates elastic network interfaces and attaches them to your Amazon EC2 nodes. The add-on also assigns a private IPv4 or IPv6 address from your VPC to each Pod.

### Network policies

By default, there are no restrictions in Kubernetes for IP addresses, ports, or connections between any Pods in your cluster or between your Pods and resources in any other network. You can use Kubernetes network policy to restrict network traffic to and from your Pods.

EKS supports different types of network policies.

#### Layer 3 and 4 isolation

Standard Kubernetes network policies operate at layers 3 and 4 of the OSI network model and allow you to control traffic flow at the IP address or port level within your Amazon EKS cluster.

Use cases:

- Segment network traffic between workloads to ensure that only related applications can talk to each other.
- Isolate tenants at the namespace level using policies to enforce network separation.

This is available through the Amazon VPC CNI and EKS Auto Mode (see [eks-auto-mode.md](eks-auto-mode.md)).

See [the documentation](https://docs.aws.amazon.com/eks/latest/userguide/cni-network-policy.html).

#### DNS-based enforcement

Domain Name System (DNS) based policies allow you to strengthen your security posture by adopting a more stable and predictable approach for preventing unauthorized access from pods to cluster-external resources or endpoints. This mechanism eliminates the need to manually track and allow list specific IP addresses.

Use cases:

- Standardize on a DNS-based approach for filtering access from a Kubernetes environment to cluster-external endpoints.
- Secure access to AWS services in a multi-tenant environment.
- Manage network access from pods to on-prem workloads in your Hybrid cloud environments.

DNS-based enforcement is only available on EKS Auto Mode (see [eks-auto-mode.md](eks-auto-mode.md)).

#### Admin (or cluster-scoped) rules

In some cases, like multi-tenant scenarios, customers may have the requirement to enforce a network security standard that applies to the whole cluster. Instead of repetitively defining and maintaining a distinct policy for each namespace, you can use a single policy to centrally manage network access controls for different workloads in the cluster, irrespective of their namespace.

Use cases:

- Centrally manage network access controls for all (or a subset of) workloads in your EKS cluster.
- Define a default network security posture across the cluster.
- Extend organizational security standards to the scope of the cluster in a more operationally efficient way.

Admin policies are only available on EKS Auto Mode (see [eks-auto-mode.md](eks-auto-mode.md)).
