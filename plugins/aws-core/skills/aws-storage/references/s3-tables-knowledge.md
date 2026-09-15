# Amazon S3 Tables

This reference captures information addressing common gotchas and frequently asked questions for Amazon S3 Tables to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon S3 User Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables.html), [Amazon S3 Tables API Reference](https://docs.aws.amazon.com/AmazonS3/latest/API/API_Operations_Amazon_S3_Tables.html), [Amazon S3 Tables feature page](https://aws.amazon.com/s3/features/tables/), and [Amazon S3 FAQs](https://aws.amazon.com/s3/faqs/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon S3 Tables delivers fully managed Apache Iceberg tables in purpose-built table buckets, with S3 running compaction, snapshot management, and unreferenced-file removal automatically. It reduces operational overhead and can deliver higher transactions per second and better query throughput than self-managing Iceberg on general purpose buckets, plus table-native features, like defining tables as resources with Amazon Resource Names (ARNs), Tables replication, and S3 Intelligent-Tiering for tabular datasets. Tables are exposed through the Iceberg REST Catalog API, so any Iceberg-compatible engine (Amazon Athena, Amazon Redshift, Amazon EMR, AWS Glue ETL, Apache Spark, and others) can read and write to S3 Tables.

**Well-suited for:** new Iceberg analytics projects, data lake tables and structured analytics data, ETL pipeline outputs, streaming into tables for SQL analysis, and migrating open table format data outside of S3 or self-managed Iceberg on S3.

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | Iceberg REST Catalog API; concurrent writers; Apache Iceberg supported versions | [Accessing table data](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-access.html) |
| Iceberg support | Apache Iceberg table format and spec versions, including Apache Iceberg v3 | [Working with Apache Iceberg V3 tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/working-with-apache-iceberg-v3.html) |
| Deployment and availability | supported Regions; table buckets; per-Region quotas | [Getting started with S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-getting-started.html), [S3 Tables AWS Regions, endpoints, and service quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-regions-quotas.html) |
| Data protection and management | automatic maintenance; no manual object overwrite or delete; MaximumSnapshotAge and MinimumSnapshots; cross-Region and cross-account replication; noncurrent-version retention | [S3 Tables maintenance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-maintenance-overview.html); [Replicating S3 tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-replication-tables.html) |
| Performance | Auto; Binpack; Sort; Z-order compaction | [S3 Tables maintenance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-maintenance-overview.html) |
| Security | s3tables namespace; table-bucket, namespace, and table access control; Block Public Access; SSE-S3 and SSE-KMS; maintenance-principal key permissions; condition keys; VPC endpoints | [Security for S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-security-overview.html) |
| Health and monitoring | CloudWatch metrics; alarms; CloudTrail | [Logging and monitoring for S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-monitoring-overview.html) |
| Pricing | table storage; per-object monitoring; API requests; automated compaction; cross-Region replication; Intelligent-Tiering (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/), [Cost optimization for tables with Intelligent-Tiering](https://docs.aws.amazon.com/AmazonS3/latest/userguide/tables-intelligent-tiering.html) |

### Related services and integrations

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related service.

| Example services | Example characteristics and common workloads | Documentation |
| --- | --- | --- |
| Amazon Athena, Amazon Redshift, Amazon EMR, AWS Glue ETL, Apache Spark, and other Iceberg-compatible engines | query and process S3 Tables, with AWS Glue Data Catalog integration for AWS analytics services, or access tables directly using the Amazon S3 Tables Iceberg REST endpoint or the Amazon S3 Tables Catalog for Apache Iceberg | [Accessing table data](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-access.html), [Integrating with AWS analytics services](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-aws.html) |
| AWS Glue Data Catalog | catalog federation; IAM authentication | [Integrating with Amazon S3 Tables](https://docs.aws.amazon.com/glue/latest/dg/glue-federation-s3tables.html) |
| AWS Lake Formation | optional fine-grained access control (IAM is the default access model) | [Creating an S3 Tables catalog in Lake Formation](https://docs.aws.amazon.com/lake-formation/latest/dg/create-s3-tables-catalog.html) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Access and permissions | AccessDenied despite broad S3 permissions; IAM vs Lake Formation confusion | grant s3tables actions specifically | [Security for S3 Tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-security-overview.html), [Integrating with Amazon S3 Tables](https://docs.aws.amazon.com/glue/latest/dg/glue-federation-s3tables.html), [Integrating Amazon S3 Tables with AWS analytics services](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-aws.html) |
| Capacity and scaling | quota reached; throttling during ingestion | request a quota increase through Support; back off and spread writes | [S3 Tables AWS Regions, endpoints, and service quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-regions-quotas.html) |
| Data protection and recovery | replicas reject writes; deleted noncurrent objects unrecoverable | write to the source; enable noncurrent-version retention | [Replicating S3 tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-replication-tables.html) |
| Maintenance | table name rejected; Sort or Z-order not applied; manual overwrite blocked | define a sort order; rely on automatic maintenance | [Maintenance for tables](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-maintenance.html), [Naming rules](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-buckets-naming.html) |
