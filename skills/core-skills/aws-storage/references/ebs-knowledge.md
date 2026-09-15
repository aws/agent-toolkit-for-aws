# Amazon Elastic Block Store (EBS)

This reference captures information addressing common gotchas and frequently asked questions for Amazon EBS to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon EBS User Guide](https://docs.aws.amazon.com/ebs/latest/userguide/what-is-ebs.html), [Amazon EC2 API Reference](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/Welcome.html), [Amazon EBS product page](https://aws.amazon.com/ebs/), and [Amazon EBS FAQs](https://aws.amazon.com/ebs/faqs/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon EBS is high-performance, durable block storage for Amazon EC2: network-attached volumes that persist independently of the instance and are replicated within an Availability Zone, with a range of SSD and HDD volume types to match performance and cost to the workload.

**Well-suited for:** workloads that need durable, low-latency block storage attached to a single EC2 instance, such as boot volumes, databases, transactional applications and file systems, dev/test environments, sequential batch processing, and log and data warehouse scans.

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | single-instance attachment; Availability Zone scope; Multi-Attach; cross-AZ and cross-Region portability | [Amazon EBS volumes](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-volumes.html) |
| Deployment and availability | Availability Zone scope; in-AZ replication; snapshot portability | [Amazon EBS overview](https://docs.aws.amazon.com/ebs/latest/userguide/what-is-ebs.html) |
| Volume types | gp3; io2 Block Express; st1; sc1; boot volume requirements | [Amazon EBS volume types](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-volume-types.html) |
| Data protection and management | snapshots; Volume Clones; Elastic Volumes; Fast Snapshot Restore; Provisioned Rate for Volume Initialization; time-based snapshot copy; snapshot archive; Amazon Data Lifecycle Manager; Recycle Bin | [Amazon EBS snapshots](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-snapshots.html), [Copy an Amazon EBS volume](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-copying-volume.html), [EBS direct APIs](https://docs.aws.amazon.com/ebs/latest/APIReference/API_Operations.html) |
| Performance | instance EBS bandwidth ceiling; gp3 provisioned performance; lazy-load on first read | [Amazon EBS volume performance](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-performance.html) |
| Security | encryption by default; encrypted snapshot sharing; least-privilege IAM on destructive actions; tags and descriptions | [Security in Amazon EBS](https://docs.aws.amazon.com/ebs/latest/userguide/security.html) |
| Health and monitoring | CloudWatch metrics; alarms; CloudTrail | [Monitoring Amazon EBS](https://docs.aws.amazon.com/ebs/latest/userguide/monitoring-overview.html) |
| Pricing | provisioned capacity; provisioned performance; snapshot storage; snapshot archive; Fast Snapshot Restore; detached-volume charges; gp2-to-gp3 migration (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon EBS pricing](https://aws.amazon.com/ebs/pricing/) |

### Related services and integrations

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related service.

| Example service | Example characteristics and common workloads | Documentation |
| --- | --- | --- |
| EC2 instance store | ephemeral local block storage; SSD and HDD variants; data loss on stop, terminate, hibernate, or hardware failure | [Instance store temporary block storage for EC2 instances](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/InstanceStorage.html), [Amazon EC2 FAQs](https://aws.amazon.com/ec2/faqs/) |
| Amazon EKS (EBS CSI driver) | Kubernetes persistent and ephemeral volumes on EBS | [Use Kubernetes volume storage with Amazon EBS](https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Capacity and scaling | resize not reflected in OS; modification limits | extend the OS file system after the volume optimizes | [Extend the file system after resizing](https://docs.aws.amazon.com/ebs/latest/userguide/recognize-expanded-volume-linux.html), [Modify a volume](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-modify-volume.html) |
| Performance | high latency; slow first reads on restored volumes | check the instance bandwidth ceiling; pre-hydrate restored volumes | [Amazon EBS-optimized instance types](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ebs-optimized.html), [Amazon EBS fast snapshot restore](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-fast-snapshot-restore.html) |
| Data protection and recovery | root volume deleted on terminate; encrypted snapshot fails to attach | review DeleteOnTermination and KMS permissions | [Preserve data when an instance is terminated](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/preserving-volumes-on-termination.html), [Amazon EBS encryption](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-encryption.html) |
| Access and permissions | volume will not attach across AZ | snapshot and restore to move across AZs | [Attach a volume](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-attaching-volume.html) |
| Cost and billing | unexpected charges; billed size vs restore size | delete or snapshot unused volumes | [View Amazon EBS snapshot information](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-describing-snapshots.html), [Amazon EBS pricing](https://aws.amazon.com/ebs/pricing/) |
