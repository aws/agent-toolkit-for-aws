# Amazon FSx for NetApp ONTAP

This reference captures information addressing common gotchas and frequently asked questions for Amazon FSx for NetApp ONTAP to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon FSx for NetApp ONTAP User Guide](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/what-is-fsx-ontap.html), [Amazon FSx API Reference](https://docs.aws.amazon.com/fsx/latest/APIReference/), [Amazon FSx for NetApp ONTAP product page](https://aws.amazon.com/fsx/netapp-ontap/), and [Amazon FSx for NetApp ONTAP FAQs](https://aws.amazon.com/fsx/netapp-ontap/faqs/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon FSx for NetApp ONTAP provides fully managed shared storage built on NetApp's popular ONTAP file system, bringing the familiar features, performance, and APIs of on-premises NetApp to AWS as a fully managed service. It offers multi-protocol access (NFS, SMB, iSCSI, NVMe-over-TCP, and the Amazon S3 API via S3 Access Points), and is designed to deliver sub-millisecond latencies and tens of GB/s of throughput along with ONTAP's rich data management capabilities (like snapshots, data cloning, SnapMirror replication, deduplication, compression, and automatic tiering).

**Well-suited for:** enterprise NAS migrations, especially from NetApp, and any workload that needs more than one access protocol or the broadest set of enterprise data-management, security, and resiliency features from a single system, such as general-purpose file shares and home directories, multi-protocol shares, business-critical databases (such as SAP HANA, Oracle, and SQL Server), VMware datastores, line-of-business applications (such as medical imaging and product lifecycle management), and hybrid or disaster-recovery workloads.

See [When to choose Amazon FSx](https://aws.amazon.com/fsx/when-to-choose-fsx/) and [How Amazon FSx for NetApp ONTAP works](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/how-it-works-fsx-ontap.html).

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | NFS; SMB; iSCSI and NVMe-over-TCP (block protocols, limited by HA-pair count); S3 Access Points; concurrent NFS and SMB; Storage Virtual Machines; volume security style; Active Directory and LDAP identity | [Accessing your FSx for ONTAP data](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/supported-fsx-clients.html) |
| Deployment and availability | Single-AZ HA; Multi-AZ | [Availability, durability, and deployment options](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/high-availability-AZ.html) |
| Storage classes | SSD; capacity pool | [Managing storage capacity (storage tiers)](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-storage-capacity.html) |
| Data protection and management | tiering policies; snapshots; SnapMirror (ONTAP-to-ONTAP data replication); FlexClone (clones); FlexCache (caching); deduplication; compression; compaction; thin provisioning; SnapLock WORM; backups | [Protecting your data](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/protecting-data.html) |
| Performance | SSD IOPS baseline and limits; throughput capacity; scale-out with HA pairs; utilization-gated tiering | [Amazon FSx for NetApp ONTAP performance](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html) |
| Security | AWS KMS at rest; in-transit via Nitro, Kerberos, IPsec; vscan; SnapLock; file-access auditing; QoS; administrative credentials | [Security in Amazon FSx for NetApp ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/security.html) |
| Health and monitoring | CloudWatch metrics; alarms; ONTAP EMS events; AWS CloudTrail | [Monitoring Amazon FSx for NetApp ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/monitoring_overview.html) |
| Pricing | SSD storage; SSD IOPS; throughput capacity; capacity pool storage and requests; backup storage; S3 Access Points requests; Multi-AZ premium (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon FSx for NetApp ONTAP pricing](https://aws.amazon.com/fsx/netapp-ontap/pricing/) |

### Related services and integrations

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related service.

| Example service | Example characteristics and common workloads | Documentation |
| --- | --- | --- |
| S3 Access Points for FSx | S3 API access to file data; per-access-point IAM and POSIX; concurrent NFS and S3 | [Accessing your data via Amazon S3 access points](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/accessing-data-via-s3-access-points.html) |
| Non-NetApp NAS migration | Dell PowerScale/Isilon, Qumulo, VAST, Pure; rsync, Robocopy, NetApp CloudSync | [Migrating to Amazon FSx for NetApp ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/migrating-fsx-ontap.html) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Access and permissions | NFS identities unresolved; SMB fails without AD | join the SVM to Active Directory and configure LDAP | [Enabling multiprotocol workloads](https://aws.amazon.com/blogs/storage/enabling-multiprotocol-workloads-with-amazon-fsx-for-netapp-ontap/), [Active Directory in FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/ad-integration-ontap.html) |
| Migration | SnapMirror from a non-NetApp source | use AWS DataSync (AWS-native, recommended), rsync, Robocopy, or NetApp CloudSync | [Amazon FSx for NetApp ONTAP FAQs](https://aws.amazon.com/fsx/netapp-ontap/faqs/) |
| Capacity and scaling | tuning not aligned with SSD utilization; per-volume tiering-policy fine-tuning | keep SSD utilization in range; fine-tune the tiering policy per volume for the workload | [Volume storage capacity](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/volume-storage-capacity.html) |
| Connectivity and networking | access issues for Multi-AZ file systems from a peered or on-premises network; iSCSI or NVMe LUN unavailable | for Multi-AZ file systems, NFS, SMB, and ONTAP management endpoints use floating IP addresses, so access from a peered VPC or on-premises requires AWS Transit Gateway (VPC Peering, Direct Connect, and Site-to-Site VPN cannot route to floating IPs); Single-AZ endpoints are secondary IPs in the VPC CIDR and do not require Transit Gateway; iSCSI, NVMe, and inter-cluster (SnapMirror) endpoints use VPC-CIDR IPs and work over VPC Peering; for LUNs verify igroup and mapping | [Routing to Multi-AZ file systems](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-routing-using-AWSTG.html), [Creating an iSCSI LUN](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/create-iscsi-lun.html) |
