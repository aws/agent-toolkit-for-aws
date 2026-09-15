# Amazon S3 Files

This reference captures information addressing common gotchas and frequently asked questions for Amazon S3 Files to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon S3 User Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files.html), [Amazon S3 Files API Reference](https://docs.aws.amazon.com/AmazonS3/latest/API/API_Operations_Amazon_S3_Files.html), [Amazon S3 Files feature page](https://aws.amazon.com/s3/features/files/), and [Amazon S3 FAQs](https://aws.amazon.com/s3/faqs/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon S3 Files is a fully managed shared file system, built on Amazon EFS infrastructure, that provides NFS access to data in an S3 general purpose bucket while the bucket remains the authoritative system of record. Applications read, write, lock, and delete files over NFS while the same data stays reachable through the S3 API, with automatic bidirectional synchronization between the two. It serves small, actively used files from a high-performance layer at low latency while large reads stream directly from S3.

**Well-suited for:** cases where data already lives in an S3 general purpose bucket and file-based applications need NFS read and write access, or where both API and file access to the same data are required without copying.

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | NFS v4.2 and v4.1; s3files mount type; mounting from EC2, ECS, EKS, Lambda, Fargate; bucket prerequisites; file system role | [Mounting your S3 buckets on compute resources](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-attach-compute.html) |
| Deployment and availability | per-AZ mount target; Multi-AZ durability | [Creating and managing S3 Files resources](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-resources.html) |
| Data protection and management | bidirectional synchronization; bucket as system of record; lost-and-found; consistency model | [Understanding how synchronization works](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-synchronization.html) |
| Performance | small-file high-performance layer; large-read streaming from S3 | [Performance specifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-performance.html) |
| Security | API and client access controls; scoped IAM policies; encryption in transit enforced on the mount; encryption at rest on the file system, SSE-S3 (Amazon S3-managed keys) by default or optional customer-managed SSE-KMS; file system policy | [Security for S3 Files](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-security.html) |
| Health and monitoring | CloudWatch sync and activity metrics; alarms; CloudTrail | [Monitoring and auditing S3 Files](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-monitoring-logging.html) |
| Pricing | standard S3 storage and requests; high-performance storage; file system access operations (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/), [How S3 Files is metered](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-metering.html) |

### Related services and integrations

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related service.

| Example service | Example characteristics and common workloads | Documentation |
| --- | --- | --- |
| Backing S3 general purpose bucket | system of record; concurrent S3 API access | [Getting started with Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/GetStartedWithS3.html) |
| Mountpoint for Amazon S3 | read-heavy FUSE client; read-only or append-only vs full read-write | [Mountpoint](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mountpoint.html) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Connectivity and networking | mount fails; command-not-found | install the S3 Files client and use the s3files mount type | [Troubleshooting S3 Files](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-troubleshooting.html) |
| Rename and move | slow or costly file or directory rename; creation error on a large prefix | expect rename to rewrite objects; pass the bucket-warning flag on large prefixes | [Understanding how synchronization works](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-synchronization.html) |
| Data protection and recovery | file not visible as an object; lost-and-found; archived-object I/O error | allow export and import to complete; restore archived objects first | [Understanding how synchronization works](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-synchronization.html), [Monitoring S3 Files with Amazon CloudWatch](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-monitoring-cloudwatch.html) |
| Performance | large reads slower than a direct GET | add the inline S3 read policy; confirm export | [Performance specifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-performance.html) |
