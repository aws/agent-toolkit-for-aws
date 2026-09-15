# Amazon S3 General Purpose

This reference captures information addressing common gotchas and frequently asked questions for Amazon S3 general purpose buckets to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon S3 User Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html), [Amazon S3 API Reference](https://docs.aws.amazon.com/AmazonS3/latest/API/API_Operations_Amazon_Simple_Storage_Service.html), [Amazon S3 product page](https://aws.amazon.com/s3/), and [Amazon S3 FAQs](https://aws.amazon.com/s3/faqs/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon S3 General Purpose is virtually unlimited object storage accessed over a REST and HTTP API, storing objects redundantly across a minimum of three Availability Zones in a Region for high durability and availability by default. It offers multiple storage classes and Lifecycle Management that optimize cost across access frequencies without application changes.

**Well-suited for:** the default starting point and system of record for unstructured data, such as data lakes and analytics, backups and archive targets, ML training data, media storage and content distribution, log and event data, static website and application assets, and regulatory and compliance archives.

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | REST and HTTP API; strong read-after-write consistency | [Access control in Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-management.html); [Accessing an Amazon S3 general purpose bucket](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-bucket-intro.html) |
| Deployment and availability | Multi-AZ redundancy; durability vs backup | [Data protection in Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/DataDurability.html) |
| Storage classes | S3 Standard; S3 Standard-Infrequent Access (S3 Standard-IA); S3 One Zone-IA; S3 Intelligent-Tiering; S3 Express One Zone; S3 Glacier storage classes (S3 Glacier Instant Retrieval, S3 Glacier Flexible Retrieval, S3 Glacier Deep Archive); Lifecycle transitions | [Understanding and managing Amazon S3 storage classes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html) |
| Data protection and management | Versioning; Object Lock; Replication; Batch Replication; Replication Time Control; Batch Operations | [Data protection in Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/data-protection.html); [Working with objects in Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/uploading-downloading-objects.html); [Retaining multiple versions of objects with S3 Versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html) |
| Performance | prefix partitioning; 503 SlowDown; request-rate pre-warming | [Best practices design patterns: optimizing Amazon S3 performance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html) |
| Security | SSE-S3; SSE-KMS; IAM and bucket policies; Block Public Access; ACLs disabled / bucket-owner-enforced; condition keys; explicit deny; checksums; account regional namespace; bucket owner condition; encryption in transit | [Security in Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security.html); [S3 Security Best Practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/security-best-practices.html) |
| Health and monitoring | CloudWatch metrics; alarms; CloudTrail; Storage Lens | [Logging and monitoring in Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/monitoring-overview.html) |
| Pricing | storage by class; requests; retrieval; data transfer; Intelligent-Tiering monitoring; lifecycle transitions; Inventory and Analytics; replication (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/) |
| Mountpoint for Amazon S3 | local file-system mount; read-heavy sequential workloads | [Mountpoint](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mountpoint.html) |
| S3 Metadata | queryable object-metadata tables; discovery and governance | [Discovering your data with S3 Metadata tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/metadata-tables-overview.html) |
| S3 Tables | managed Apache Iceberg tables; automatic compaction, snapshot management, and unreferenced-file removal | [Working with Amazon S3 Tables and table buckets](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables.html) |
| S3 Vectors | storing and querying vector embeddings | [Working with S3 Vectors and vector buckets](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors.html) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Cost and billing | bill spikes; incomplete multipart uploads; lifecycle transition costs | isolate with Storage Lens and Cost Explorer; abort incomplete uploads | [Understanding your S3 bill](https://docs.aws.amazon.com/AmazonS3/latest/userguide/aws-usage-report-understand.html), [S3 Storage Lens](https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage_lens.html), [Aborting incomplete multipart uploads](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpu-abort-incomplete-mpu-lifecycle-config.html) |
| Data protection and recovery | delete markers on versioned buckets; archive restore expiry; replication gaps | use versioning or Object Lock and Batch Replication; budget minimum durations | [Locking objects with Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html), [Replicating existing objects with Batch Replication](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-batch-replication-batch.html), [Restoring an archived object](https://docs.aws.amazon.com/AmazonS3/latest/userguide/restoring-objects.html), [Troubleshooting replication](https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication-troubleshoot.html), [Troubleshooting versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/troubleshooting-versioning.html) |
| Access and permissions | cross-account AccessDenied; KMS key mismatch | evaluate the full policy chain; explicit deny overrides allows | [Access denied (403)](https://docs.aws.amazon.com/AmazonS3/latest/userguide/troubleshoot-403-errors.html), [Bucket policy examples using condition keys](https://docs.aws.amazon.com/AmazonS3/latest/userguide/amazon-s3-policy-keys.html) |
| Performance | 503 SlowDown on hot prefixes | spread across prefixes; back off with jitter | [Performance design patterns for Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance-design-patterns.html) |
