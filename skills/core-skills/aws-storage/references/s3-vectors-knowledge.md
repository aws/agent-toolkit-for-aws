# Amazon S3 Vectors

This reference captures information addressing common gotchas and frequently asked questions for Amazon S3 Vectors to support accurate model responses. It is not a complete specification. The authoritative source for current specifications, limits, quotas, and API behavior is the [Amazon S3 User Guide (S3 Vectors)](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors.html), [Amazon S3 Vectors API Reference](https://docs.aws.amazon.com/AmazonS3/latest/API/API_Operations_Amazon_S3_Vectors.html), [Amazon S3 Vectors feature page](https://aws.amazon.com/s3/features/vectors/), and [Amazon S3 FAQs](https://aws.amazon.com/s3/faqs/). Retrieve current specifications, limits, and quotas from those pages before citing specifics; cite figures only from those pages.

## 1. Overview

**What it is:** Amazon S3 Vectors is object storage with native support for storing and querying vector embeddings. It delivers the elasticity, durability, and availability of Amazon S3, and is cost-optimized for infrequent to moderately frequent similarity queries.

**Well-suited for:** cost-sensitive retrieval augmented generation (RAG) pipelines, semantic search, recommendation systems, vector deduplication and matching, anomaly and fraud detection, AI agent memory, and cost-effective storage of large vector datasets.

Choose Amazon OpenSearch Service or another dedicated vector database when the workload needs very low latency, very high sustained query throughput, or capabilities beyond what S3 Vectors supports; see [Vector database options](https://docs.aws.amazon.com/prescriptive-guidance/latest/choosing-an-aws-vector-database-for-rag-use-cases/vector-db-options.html).

## 2. Service Information

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related topic.

| Topic | Example service characteristics, features, and actions | Documentation |
| --- | --- | --- |
| Access and protocols | s3vectors namespace and API | [Identity and Access management in S3 Vectors](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-access-management.html) |
| Deployment and availability | supported Regions and endpoints | [AWS Regions, endpoints, and quotas for S3 Vectors](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-regions-quotas.html) |
| Data protection and management | 11 9's durability inherited from Amazon S3 | [Working with S3 Vectors and vector buckets](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors.html) |
| Performance | latency for cold vs. warm queries; queries per second throughput; batching; index sharding | [S3 Vectors best practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-best-practices.html) |
| Security | SSE-S3 and SSE-KMS; S3 Block Public Access; AWS PrivateLink; condition keys | [Security in S3 Vectors](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-security.html) |
| Health and monitoring | CloudTrail management and data events (including QueryVectors) | [Logging with AWS CloudTrail for S3 Vectors](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-logging.html) |
| Pricing | storage; PUT; queries; data processed and returned; index partitioning (not exhaustive, review pricing page for the full list of pricing dimensions) | [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/) |

### Related services and integrations

You MUST retrieve information from the linked documentation in the below table before answering any user question on the related service.

| Example service | Example characteristics and common workloads | Documentation |
| --- | --- | --- |
| Amazon Bedrock Knowledge Bases | integration provides S3 Vectors as managed vector store for RAG with characteristics such as metadata filtering; storing large text chunks via non-filterable metadata keys, etc. | [Using S3 Vectors with Amazon Bedrock Knowledge Bases](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-bedrock-kb.html), [Metadata filtering](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-metadata-filtering.html) |
| Amazon OpenSearch Service | Integration with S3 Vectors provides two distinct architectural paths: a low-cost vector storage engine for managed OpenSearch Service clusters, and an automated export pipeline to OpenSearch Serverless for high-performance search workloads. | [Using S3 Vectors with OpenSearch Service](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-opensearch.html) |

## 3. Troubleshooting

You MUST retrieve information from the linked documentation in the below table before providing the user with any guidance on the related area.

| Example area | Example errors | Example fixes | Documentation |
| --- | --- | --- | --- |
| Access and permissions | AccessDenied on s3vectors query or get actions | use s3vectors actions; grant query and get actions | [Identity and Access management in S3 Vectors](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-access-management.html), [QueryVectors](https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_QueryVectors.html), [GetVectors](https://docs.aws.amazon.com/AmazonS3/latest/API/API_S3VectorBuckets_GetVectors.html) |
| Capacity and scaling | TooManyRequestsException under high request rates | S3 Vectors is fully serverless and scales automatically; use client-side backoff and rate limiting, and batch writes | [Limitations and restrictions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html), [S3 Vectors best practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-best-practices.html) |
