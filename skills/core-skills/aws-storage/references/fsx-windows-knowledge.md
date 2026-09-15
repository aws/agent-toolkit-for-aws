# Amazon FSx for Windows File Server

This reference captures information addressing common gotchas and frequently asked questions for Amazon FSx for Windows File Server to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon FSx for Windows File Server User Guide](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/what-is.html), [Amazon FSx API Reference](https://docs.aws.amazon.com/fsx/latest/APIReference/), [Amazon FSx for Windows File Server product page](https://aws.amazon.com/fsx/windows/), and [Amazon FSx for Windows File Server FAQs](https://aws.amazon.com/fsx/windows/faqs/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon FSx for Windows File Server provides fully managed, highly reliable file storage built on Windows Server and can be accessed via the industry-standard Server Message Block (SMB) protocol. It integrates natively with Microsoft Active Directory and is designed to deliver sub-millisecond latencies along with a rich set of Windows-native data management capabilities (like data deduplication, shadow copies, DFS namespaces, and user quotas). Shares are accessible from Windows, Linux (via cifs-utils), and macOS clients.

**Well-suited for:** workloads where applications and users depend on native Windows and SMB behavior and Active Directory identity, such as Windows file and home or department shares, .NET applications, highly available Microsoft SQL Server, and Windows Server migrations.

See [When to choose Amazon FSx](https://aws.amazon.com/fsx/when-to-choose-fsx/) and [Amazon FSx for Windows File Server Features](https://aws.amazon.com/fsx/windows/features/).

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | SMB; Windows; Active Directory; DFS Namespaces | [Accessing data using file shares](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/using-file-shares.html) |
| Deployment and availability | Multi-AZ (recommended for production workloads); Single-AZ 2 and Single-AZ 1 (cost-efficient for dev/test); failover timing; Continuously Available shares | [Availability and durability: Single-AZ and Multi-AZ file systems](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/high-availability-multiAZ.html) |
| Storage classes | SSD; HDD with in-memory cache; in-place HDD-to-SSD; increase-only capacity | [Managing storage (optimizing storage costs)](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/managing-storage-configuration.html) |
| Data protection and management | incremental backups; cross-Region backup copy; shadow copies; dedup and compression; DFS Replication (Single-AZ 1); FSRM quotas | [Protecting your data with backups](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/using-backups.html) |
| Performance | throughput capacity; baseline and burst network speeds | [FSx for Windows File Server performance](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/performance.html) |
| Security | KMS at rest; SMB 3.0+ encryption in transit; Active Directory and Kerberos; IAM and NTFS ACLs; file-access auditing; File Classification (PII tagging); File Screening | [Security in Amazon FSx](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/security.html) |
| Health and monitoring | CloudWatch metrics; alarms; CloudTrail | [Monitoring FSx for Windows File Server file systems](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/monitoring_overview.html) |
| Pricing | storage capacity; throughput capacity; backup storage; Multi-AZ premium; dedup and compression; DataSync to S3 (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon FSx for Windows File Server pricing](https://aws.amazon.com/fsx/windows/pricing/) |

### Related services and integrations

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related service.

| Example service | Example characteristics and common workloads | Documentation |
| --- | --- | --- |
| AWS DataSync | migrate files preserving NTFS ACLs and SACLs | [Migrating files with DataSync](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/migrate-files-to-fsx-datasync.html) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Data protection and recovery | Robocopy dedup corruption; no native cross-Region replication; shadow copies consume capacity | verify after copy and prefer DataSync; copy backups cross-Region; monitor shadow-copy usage | [Managing storage on FSx for Windows File Server](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/managing-storage-configuration.html), [Protecting your data with backups](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/using-backups.html) |
| Connectivity and networking | Multi-AZ failover on throughput change; Linux client mount loss | schedule changes in maintenance windows; remount Linux clients after failover | [Availability and durability: Single-AZ and Multi-AZ file systems](https://docs.aws.amazon.com/fsx/latest/WindowsGuide/high-availability-multiAZ.html) |
