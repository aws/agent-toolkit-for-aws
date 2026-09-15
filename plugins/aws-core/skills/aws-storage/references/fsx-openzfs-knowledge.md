# Amazon FSx for OpenZFS

This reference captures information addressing common gotchas and frequently asked questions for Amazon FSx for OpenZFS to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon FSx for OpenZFS User Guide](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/what-is-fsx.html), [Amazon FSx API Reference](https://docs.aws.amazon.com/fsx/latest/APIReference/), [Amazon FSx for OpenZFS product page](https://aws.amazon.com/fsx/openzfs/), and [Amazon FSx for OpenZFS FAQs](https://aws.amazon.com/fsx/openzfs/faqs/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon FSx for OpenZFS provides fully managed, cost-effective, shared file storage powered by the popular OpenZFS file system, and is designed to deliver latencies as low as a few hundred microseconds and multi-GB/s throughput along with rich ZFS-powered data management capabilities (like snapshots, data cloning, and compression). It is accessible from Linux, Windows, and macOS NFS clients.

**Well-suited for:** Linux and NFS workloads that want the lowest latency and a simple, high-performance NAS, including migrations from ZFS or other Linux file servers, dev/test that benefits from instant writable clones, front-end EDA, financial modeling, media processing, and latency-sensitive line-of-business apps and databases.

See [When to choose Amazon FSx](https://aws.amazon.com/fsx/when-to-choose-fsx/) and [Amazon FSx for OpenZFS features](https://aws.amazon.com/fsx/openzfs/features/).

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | NFS (v3, v4.x); S3 Access Points; POSIX identity | [Accessing your data](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/accessing-your-data.html) |
| Deployment and availability | Multi-AZ (HA); Single-AZ (HA); Single-AZ (non-HA); max file-system size | [Availability and durability for Amazon FSx for OpenZFS](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/availability-durability.html) |
| Storage classes | Intelligent-Tiering; SSD | [Choosing a storage class](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/performance.html) |
| Data protection and management | snapshots; writable clones; LZ4 and Zstandard compression; on-demand replication; backups; child-volume quotas | [Protecting your Amazon FSx for OpenZFS data](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/protecting-data.html) |
| Performance | latencies as low as a few hundred microseconds for cached data; provisioned throughput and IOPS; record size | [Performance for Amazon FSx for OpenZFS](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/performance.html) |
| Security | KMS at rest; in-transit automatic on supported EC2 (Nitro-based) instances; VPC, IAM, POSIX | [Security in Amazon FSx for OpenZFS](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/security.html) |
| Health and monitoring | CloudWatch metrics; alarms; CloudTrail | [Monitoring Amazon FSx for OpenZFS file systems](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/monitoring_overview.html) |
| Pricing | storage by class and deployment; throughput capacity; SSD IOPS; read cache; backup storage; compression and clones (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon FSx for OpenZFS pricing](https://aws.amazon.com/fsx/openzfs/pricing/) |

### Related services and integrations

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related service.

| Example service | Example characteristics and common workloads | Documentation |
| --- | --- | --- |
| S3 Access Points for FSx | S3 API access to file data; per-access-point IAM and POSIX; concurrent NFS and S3 | [Accessing your data using Amazon S3 access points](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/s3accesspoints-for-FSx.html) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Data protection and recovery | snapshot delete blocked by a clone; space not freed; compression not retroactive | delete dependent clones; copy data to apply new settings | [Protecting your data with snapshots](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/snapshots-openzfs.html), [Updating an Amazon FSx for OpenZFS volume](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/updating-volumes.html), [DeleteSnapshot](https://docs.aws.amazon.com/fsx/latest/APIReference/API_DeleteSnapshot.html) |
| Connectivity and networking | file-system creation fails on security group | allow inbound TCP 2049 from the security group itself or the subnet CIDR so the file-system hosts can reach each other | [Troubleshooting Amazon FSx for OpenZFS issues](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/troubleshooting.html) |
| Connectivity and networking | mount hangs or times out | allow inbound TCP 2049 from the client (restrict to the specific client security group or narrowest applicable CIDR); verify subnet routing and the volume path | [Troubleshooting Amazon FSx for OpenZFS issues](https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/troubleshooting.html) |
