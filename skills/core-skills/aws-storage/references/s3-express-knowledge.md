# Amazon S3 Express One Zone

This reference captures information addressing common gotchas and frequently asked questions for Amazon S3 Express One Zone to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon S3 User Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/directory-bucket-high-performance.html), [Amazon S3 API Reference](https://docs.aws.amazon.com/AmazonS3/latest/API/API_Operations_Amazon_Simple_Storage_Service.html), [Amazon S3 Express One Zone storage class page](https://aws.amazon.com/s3/storage-classes/express-one-zone/), and [Amazon S3 FAQs](https://aws.amazon.com/s3/faqs/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon S3 Express One Zone is an S3 storage class for latency-sensitive, high-request-rate workloads, storing data in directory buckets within a single Availability Zone. It delivers consistent single-digit-millisecond latency at high request rates; offers faster data access with lower request cost than S3 Standard.

**Well-suited for:** latency-sensitive hot data, such as Spark and EMR shuffle, ETL intermediate data, Kafka tiered storage, observability and log analytics (hot tier), interactive analytics on hot partitions, media and video editing, ML training checkpoints, scratch, and model loading, large-scale ML training and inference (including as a primary data tier, not only checkpoints), high-frequency transactional access, and caching for machine learning inference; it especially helps small objects where request latency dominates.

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | Zonal endpoint; s3express namespace; CreateSession session authorization; bucket-name form; zone-ID co-location; gateway VPC endpoint; S3A MagicV2 committer for Spark and EMR | [Networking for directory buckets](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-express-networking.html) |
| Deployment and availability | Single-AZ directory buckets; Dedicated vs other Local Zones | [S3 Express One Zone Availability Zones and Regions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-express-Endpoints.html) |
| Data protection and management | limited lifecycle actions; backup or replication to a general purpose bucket | [Differences for directory buckets](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-express-differences.html) |
| Performance | single-digit-millisecond latency; per-second request limits; optional co-location | [Optimizing S3 Express One Zone performance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-express-performance.html) |
| Security | explicit CreateSession grant; scoped s3express policies; condition keys; SSE-S3 and SSE-KMS; Block Public Access; CloudTrail data events | [Security for directory buckets](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-express-security.html) |
| Health and monitoring | CloudWatch metrics; alarms; CloudTrail | [Monitoring metrics with Amazon CloudWatch for directory buckets](https://docs.aws.amazon.com/AmazonS3/latest/userguide/cloudwatch-monitoring-directory-buckets.html) |
| Pricing | storage and requests; per-GB upload and retrieval; expiration lifecycle; small-object aggregation (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Access and permissions | data-plane request rejected without a session; CLI sync failures | use a session-aware SDK or CLI; use recursive copy | [CreateSession](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CreateSession.html) |
| Connectivity and networking | 503 Slow Down under rising request rate; throughput capped on a private subnet | retry with exponential backoff while S3 scales; add an s3express gateway VPC endpoint | [Configure a gateway VPC endpoint](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-express-tutorial-endpoints.html) |
| Data protection and recovery | objects not expiring under a lifecycle rule | grant CreateSession and remove any deny-delete bucket policy; check CloudTrail for AccessDenied | [Troubleshooting S3 Lifecycle issues for directory buckets](https://docs.aws.amazon.com/AmazonS3/latest/userguide/directory-buckets-lifecycle-troubleshooting.html) |
| Performance | higher cross-zone latency | co-locate compute with the bucket zone ID | [Optimizing S3 Express One Zone performance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-express-performance.html) |
| Data writes | Spark or Hive write failures on directory buckets; S3 Select and object change-detection incompatibilities with the S3A connector | use the S3A MagicV2 committer rather than the default file output committer; disable S3 Select and object change-detection in the S3A connector | [Upload data to Amazon S3 Express One Zone](https://docs.aws.amazon.com/emr/latest/ManagementGuide/emr-express-one-zone.html), [S3A MagicV2 Committer](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/s3a-magicv2-committer.html), [Requirements for the EMRFS S3-optimized committer](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-spark-committer-reqs.html) |
