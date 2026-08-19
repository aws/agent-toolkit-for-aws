# AWS Data Movement & Protection Services

This reference captures information addressing common gotchas and frequently asked questions for the AWS data movement and protection services (AWS DataSync, AWS Storage Gateway, AWS Transfer Family, and AWS Backup) to support accurate model responses. It is not a complete specification. The authoritative source for latest specifications, limits, quotas, and API behavior is each service's User Guide and API Reference:

| Service | User Guide | API Reference | Product page | FAQs |
| --- | --- | --- | --- | --- |
| AWS DataSync | [User Guide](https://docs.aws.amazon.com/datasync/latest/userguide/what-is-datasync.html) | [API Reference](https://docs.aws.amazon.com/datasync/latest/apireference/API_Operations.html) | [Product page](https://aws.amazon.com/datasync/) | [FAQs](https://aws.amazon.com/datasync/faqs/) |
| AWS Storage Gateway | [User Guide](https://docs.aws.amazon.com/filegateway/latest/files3/what-is-file-s3.html) | [API Reference](https://docs.aws.amazon.com/storagegateway/latest/APIReference/API_Operations.html) | [Product page](https://aws.amazon.com/storagegateway/), [Features](https://aws.amazon.com/storagegateway/features/) | [FAQs](https://aws.amazon.com/storagegateway/faqs/) |
| AWS Transfer Family | [User Guide](https://docs.aws.amazon.com/transfer/latest/userguide/what-is-aws-transfer-family.html) | [API Reference](https://docs.aws.amazon.com/transfer/latest/APIReference/Welcome.html) | [Product page](https://aws.amazon.com/aws-transfer-family/) | [FAQs](https://aws.amazon.com/aws-transfer-family/faqs/) |
| AWS Backup | [User Guide](https://docs.aws.amazon.com/aws-backup/latest/devguide/whatisbackup.html) | [API Reference](https://docs.aws.amazon.com/aws-backup/latest/APIReference/Welcome.html) | [Product page](https://aws.amazon.com/backup/) | [FAQs](https://aws.amazon.com/backup/faqs/) |

Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** AWS DataSync, AWS Storage Gateway, AWS Transfer Family, and AWS Backup are the cross-service storage operations layer: they move data between storage systems, bridge on-premises applications to cloud storage, exchange files with external partners over managed protocols, and centralize backup and retention across AWS services. All four support AWS CloudTrail logging and Amazon CloudWatch metrics and alarms to detect unauthorized transfers or anomalous activity.

**Well-suited for:** moving, bridging, exchanging, or protecting data rather than choosing a primary storage target.

Note: AWS Snow Family and Amazon FSx File Gateway are not actively supported for new workloads; for supported data transfer and hybrid storage alternatives, see [Cloud Data Migration](https://aws.amazon.com/cloud-data-migration/).

## 2. Services

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

### AWS DataSync

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| What it does | online transfers and migrations; connects all FSx variants; EFS; S3; non-AWS clouds; agent vs agentless; Enhanced vs Basic mode; continuous replication | [What is AWS DataSync?](https://docs.aws.amazon.com/datasync/latest/userguide/what-is-datasync.html) |
| Security | scoped IAM roles; TLS in transit | [Security in AWS DataSync](https://docs.aws.amazon.com/datasync/latest/userguide/security.html) |
| Pricing | per GB transferred (not exhaustive, review pricing page for the full list of pricing dimensions) | [AWS DataSync pricing](https://aws.amazon.com/datasync/pricing/) |

### AWS Storage Gateway

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| What it does | on-premises access via local cache; Amazon S3 File Gateway; Volume Gateway (Cached or Stored); Tape Gateway; bucket-to-file-share mapping; file size limit; no symlink or hard-link | [What is Amazon S3 File Gateway?](https://docs.aws.amazon.com/filegateway/latest/files3/what-is-file-s3.html) |
| Security | SSL in transit; SSE-S3 or SSE-KMS on the S3 backend; VPC endpoints; IAM roles for activation | [Security in AWS Storage Gateway](https://docs.aws.amazon.com/filegateway/latest/files3/security.html) |
| Pricing | per GB stored; request charges (not exhaustive, review pricing page for the full list of pricing dimensions) | [AWS Storage Gateway pricing](https://aws.amazon.com/storagegateway/pricing/) |

### AWS Transfer Family

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| What it does | provides managed SFTP; FTPS; FTP; AS2 endpoints on S3 or EFS; public and VPC endpoint types; managed workflows; AS2 MDN; Transfer Family Web Apps | [What is AWS Transfer Family?](https://docs.aws.amazon.com/transfer/latest/userguide/what-is-aws-transfer-family.html) |
| Security | SFTP and FTPS encrypt in transit; FTP is unencrypted and not for production workloads; FTP and FTPS require a VPC endpoint; ACM certificate for FTPS; managed identity providers; Secrets Manager for keys | [Security in AWS Transfer Family](https://docs.aws.amazon.com/transfer/latest/userguide/security.html) |
| Pricing | per protocol endpoint provisioned; per GB transferred (not exhaustive, review pricing page for the full list of pricing dimensions) | [AWS Transfer Family pricing](https://aws.amazon.com/aws-transfer-family/pricing/) |

### AWS Backup

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| What it does | policy-based backup across many AWS services; S3 Versioning prerequisite; continuous backup and point-in-time restore; Vault Lock Compliance vs Governance | [What is AWS Backup?](https://docs.aws.amazon.com/aws-backup/latest/devguide/whatisbackup.html) |
| Security | AWS KMS keys in the vault; Vault Lock WORM immutability | [Security in AWS Backup](https://docs.aws.amazon.com/aws-backup/latest/devguide/security-considerations.html) |
| Pricing | backup storage; restore; cross-Region and cross-account copy; service-specific tiering (not exhaustive, review pricing page for the full list of pricing dimensions) | [AWS Backup pricing](https://aws.amazon.com/backup/pricing/) |
