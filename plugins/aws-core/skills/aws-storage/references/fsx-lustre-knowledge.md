# Amazon FSx for Lustre

This reference captures information addressing common gotchas and frequently asked questions for Amazon FSx for Lustre to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon FSx for Lustre User Guide](https://docs.aws.amazon.com/fsx/latest/LustreGuide/what-is.html), [Amazon FSx API Reference](https://docs.aws.amazon.com/fsx/latest/APIReference/), [Amazon FSx for Lustre product page](https://aws.amazon.com/fsx/lustre/), and [Amazon FSx for Lustre FAQs](https://aws.amazon.com/fsx/lustre/faqs/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon FSx for Lustre is a fully managed service that provides high-performance, cost-effective, and scalable storage powered by Lustre, the world's most popular high-performance file system. FSx for Lustre provides the fastest storage performance for GPU instances in the cloud, with up to terabytes per second of throughput, millions of IOPS, sub-millisecond latencies, and virtually unlimited storage capacity.

**Well-suited for:** compute-intensive workloads where storage must keep pace with large fleets of GPU or CPU compute, such as ML training and inference, HPC, genomics, seismic and financial modeling, media rendering, and back-end EDA, with native Amazon S3 integration that makes datasets in S3 transparently accessible as files.

See [When to choose Amazon FSx](https://aws.amazon.com/fsx/when-to-choose-fsx/) and [Amazon FSx for Lustre Features](https://aws.amazon.com/fsx/lustre/features/).

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | Lustre parallel client on Linux; cross-AZ client access; Elastic Fabric Adapter for high-throughput, low-latency inter-node networking | [Accessing file systems](https://docs.aws.amazon.com/fsx/latest/LustreGuide/accessing-fs.html) |
| Deployment and availability | Persistent 1 and 2; Scratch 2 | [Deployment and storage class options](https://docs.aws.amazon.com/fsx/latest/LustreGuide/using-fsx-lustre.html) |
| Storage classes | SSD; Intelligent-Tiering | [Lustre storage classes](https://docs.aws.amazon.com/fsx/latest/LustreGuide/using-fsx-lustre.html) |
| Data protection and management | S3 data repository association; auto-import and auto-export; writes from multiple locations; file release to free local space; capacity increase; backups | [Using data repositories with Amazon FSx for Lustre](https://docs.aws.amazon.com/fsx/latest/LustreGuide/fsx-data-repositories.html) |
| Performance | aggregate throughput; sub-millisecond latency; high IOPS; metadata IOPS; NVIDIA GPUDirect Storage (GDS); working-set sizing | [Amazon FSx for Lustre performance](https://docs.aws.amazon.com/fsx/latest/LustreGuide/performance.html) |
| Security | KMS at rest; in-transit automatic from EC2 instances that support it (Nitro-based) and between file-system hosts; instances that do not support it and on-premises clients do not receive in-transit encryption; POSIX permissions; VPC and security groups | [Security in Amazon FSx for Lustre](https://docs.aws.amazon.com/fsx/latest/LustreGuide/security.html) |
| Health and monitoring | CloudWatch metrics; alarms; CloudTrail | [Monitoring Amazon FSx for Lustre file systems](https://docs.aws.amazon.com/fsx/latest/LustreGuide/monitoring_overview.html) |
| Pricing | storage capacity; throughput capacity; metadata IOPS; backup storage; cross-AZ transfer; Intelligent-Tiering (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon FSx for Lustre pricing](https://aws.amazon.com/fsx/lustre/pricing/) |

### Related services and integrations

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related service.

| Example service | Example characteristics and common workloads | Documentation |
| --- | --- | --- |
| Amazon EKS (FSx for Lustre CSI driver) | dynamic and static Kubernetes volume provisioning; pod access to shared Lustre | [Amazon FSx for Lustre CSI driver](https://docs.aws.amazon.com/eks/latest/userguide/fsx-csi.html) |
| Amazon SageMaker | high-throughput training-data input; file-system mount for training jobs | [Setting up training jobs to access datasets](https://docs.aws.amazon.com/sagemaker/latest/dg/model-access-training-data.html) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Connectivity and networking | mount fails; Lustre client missing | install the client matching the OS and kernel | [Installing the Lustre client](https://docs.aws.amazon.com/fsx/latest/LustreGuide/install-lustre-client.html) |
| Connectivity and networking | mount hangs or times out; security group misconfigured | allow the required Lustre ports between the file-system and client security groups (restrict to the specific client security group IDs); verify VPC routing | [File system access control with Amazon VPC](https://docs.aws.amazon.com/fsx/latest/LustreGuide/limit-access-security-groups.html) |
| Data protection and recovery | data repository misconfigured; slow first read; conflicting writes; backups only on Persistent non-S3-linked | restore IAM access; pre-stage hot files; write from a single source; use Persistent (not S3-linked) for backups | [Data repository association lifecycle state](https://docs.aws.amazon.com/fsx/latest/LustreGuide/dra-lifecycles.html), [Linking to an S3 bucket](https://docs.aws.amazon.com/fsx/latest/LustreGuide/create-dra-linked-data-repo.html), [Protecting your data with backups](https://docs.aws.amazon.com/fsx/latest/LustreGuide/using-backups-fsx.html) |
| Capacity and scaling | out of space with a large S3 dataset | release infrequently-accessed files; size to the working set | [Releasing files](https://docs.aws.amazon.com/fsx/latest/LustreGuide/file-release.html), [Increasing storage capacity](https://docs.aws.amazon.com/fsx/latest/LustreGuide/increase-storage-capacity.html) |
