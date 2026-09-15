# Amazon EFS

This reference captures information addressing common gotchas and frequently asked questions for Amazon EFS to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon EFS User Guide](https://docs.aws.amazon.com/efs/latest/ug/whatisefs.html), [Amazon EFS API Reference](https://docs.aws.amazon.com/efs/latest/ug/api-reference.html), [Amazon EFS product page](https://aws.amazon.com/efs/), and [Amazon EFS FAQs](https://aws.amazon.com/efs/faq/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon EFS is a serverless, fully elastic NFS file system for Linux that grows and shrinks automatically with no capacity planning, built for shared file access with high aggregate throughput across many concurrent clients. It is Regional (Multi-AZ) by default, with a lower-cost One Zone option, and is mountable by Lambda, Fargate, EC2, ECS, and EKS.

**Well-suited for:** shared Linux file workloads, such as containers, cloud-native Linux applications, serverless persistent storage, analytics and ML training data (including SageMaker), big data, media processing, web and content management, shared home directories, dev/test, and infrequently accessed file data.

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | NFS on Linux; mounting from Lambda, Fargate, EC2, ECS, EKS; access points; cross-account and cross-VPC mounting; on-premises mount | [Mounting EFS file systems](https://docs.aws.amazon.com/efs/latest/ug/mounting-fs.html) |
| Deployment and availability | Regional (Multi-AZ); One Zone | [Availability and durability (EFS file system types)](https://docs.aws.amazon.com/efs/latest/ug/features.html) |
| Storage classes | Standard; Infrequent Access; Archive; One Zone; One Zone-IA; Lifecycle Management | [Managing storage lifecycle](https://docs.aws.amazon.com/efs/latest/ug/lifecycle-management-efs.html) |
| Data protection and management | cross-Region and cross-account replication; AWS Backup | [Replicating EFS file systems](https://docs.aws.amazon.com/efs/latest/ug/efs-replication.html) |
| Performance | Elastic, Provisioned, and Bursting throughput modes; General Purpose performance mode; per-client throughput ceiling | [Amazon EFS performance specifications](https://docs.aws.amazon.com/efs/latest/ug/performance.html) |
| Security | IAM and POSIX authorization; resource-policy condition keys; KMS at rest; TLS in transit | [Securing your data in Amazon EFS](https://docs.aws.amazon.com/efs/latest/ug/security-considerations.html) |
| Health and monitoring | CloudWatch metrics; alarms; CloudTrail | [Monitoring metrics with Amazon CloudWatch](https://docs.aws.amazon.com/efs/latest/ug/monitoring-cloudwatch.html) |
| Pricing | per-GB-month by storage class; IA and Archive access charges; Elastic vs Provisioned throughput; replication transfer (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon EFS pricing](https://aws.amazon.com/efs/pricing/) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Performance | per-client throughput capped | spread load across clients; use the higher-ceiling client or CSI driver on Elastic | [Amazon EFS quotas](https://docs.aws.amazon.com/efs/latest/ug/limits.html) |
| Connectivity and networking | mount timeout; cross-account or cross-VPC DNS resolution fails | verify the security group, a mount target in the client AZ, and cross-VPC DNS | [Troubleshooting mount issues](https://docs.aws.amazon.com/efs/latest/ug/troubleshooting-efs-mounting.html), [Mount from a different VPC](https://docs.aws.amazon.com/efs/latest/ug/efs-different-vpc.html) |
| Access and permissions | root write denied under IAM authorization | grant the required client actions in either the resource or the identity policy (one ALLOW suffices, no DENY) | [Using IAM to control access to file systems](https://docs.aws.amazon.com/efs/latest/ug/iam-access-control-nfs-efs.html) |
