# Foundation Operations: Quotas, Service Selection, and Architecture

## Overview

Cross-cutting operational knowledge: MSF service quotas, ENI capacity planning for VPC apps, MSF vs EMR Flink decision, and source/sink selection. Use when planning capacity, choosing the right streaming service, or designing a new pipeline.

## CLI and CloudWatch Identifiers

| Item | Value | Common wrong values |
|------|-------|---------------------|
| AWS CLI service / SDK client | `kinesisanalyticsv2` | ❌ `flink`, `msf`, `kinesisanalytics` (v1, deprecated SQL apps only) |
| Service Quotas service-code | `kinesisanalytics` (no `v2`) | ❌ `kinesisanalyticsv2`, `flink`, `msf` |
| IAM action prefix | `kinesisanalytics:` (no `v2`) | ❌ `kinesisanalyticsv2:` |
| CloudWatch namespace | `AWS/KinesisAnalytics` | ❌ `AWS/Flink`, `AWS/ManagedFlink` |
| Trust policy principal | `kinesisanalytics.amazonaws.com` | ❌ `kinesisanalyticsv2.amazonaws.com` |

The CLI/SDK is the *only* identifier that uses the `v2` suffix. Service Quotas, IAM actions, the CloudWatch namespace, and the trust principal all use the legacy `kinesisanalytics` name. Treating the v2 form as the "default" and applying it everywhere is the single most common source of permission failures, empty metric results, missing service-quota lookups, and trust policy errors.

## What Goes In the Execution Role (and What Does NOT)

The MSF execution role is assumed by the **MSF service** to access **your data plane resources** on behalf of the application. It is not used by the application code itself, and it does not call MSF's own control plane. The principle of least privilege follows from that:

| Permission | Required in execution role? | Why |
|------------|------------------------------|-----|
| Source/sink data plane (e.g. `kinesis:GetRecords`, `s3:PutObject`, `kafka:DescribeCluster`) | Yes — scoped to specific stream/bucket/cluster ARNs | The service uses this role to read sources and write sinks |
| `logs:CreateLogStream`, `logs:PutLogEvents`, `logs:DescribeLogStreams` on the configured log group | Yes | The service writes application logs to the configured CloudWatch Logs group |
| EC2 ENI permissions (`ec2:CreateNetworkInterface`, `ec2:DescribeNetworkInterfaces`, `ec2:DeleteNetworkInterface`, `ec2:CreateNetworkInterfacePermission`, `ec2:DescribeVpcs`, `ec2:DescribeSubnets`, `ec2:DescribeSecurityGroups`) | Yes — only for VPC-enabled apps | The service creates ENIs on your behalf when VPC is configured |
| `kinesisanalytics:*` actions | **No** | These are MSF control-plane actions consumed by humans/CI calling the MSF API, not by the service when it runs your application |
| `cloudwatch:PutMetricData` | **No** | MSF publishes the standard metrics (cpuUtilization, downtime, numRecordsIn*, etc.) to the `AWS/KinesisAnalytics` namespace from the service plane, not via the execution role. Adding it does no harm if scoped to the namespace, but it's noise — leave it out for a clean least-privilege role. The exception: if your **application code** explicitly calls `CloudWatchAsyncClient.putMetricData()` to emit custom application metrics, then you do need to grant it (still scope to the custom namespace) |
| `secretsmanager:GetSecretValue` | Only if you use Secrets Manager for connector credentials | Scope to the specific secret ARN |
| `kms:Decrypt` | Only when reading from a KMS-encrypted source/sink or KMS-encrypted secret | Scope to the specific key ARN |

When generating an execution role, default to omitting `kinesisanalytics:*` and `cloudwatch:PutMetricData` unless the user explicitly says they emit custom metrics. The CloudWatch metrics you see in the AWS console come from the service, not from this role.

## Service Quotas

| Quota | Default | Adjustable |
|-------|---------|------------|
| Applications per region | 50 | Yes |
| KPUs per application | 64 (configurable to 250) | Yes |
| Application snapshots per application | 1000 | Yes |
| Parallelism per application | 256 | Yes |

Check current values:

```bash
aws service-quotas list-aws-default-service-quotas \
  --service-code kinesisanalytics --region "$REGION"
```

The Service Quotas service-code is `kinesisanalytics` (legacy name), not `kinesisanalyticsv2`. The KPUs-per-application quota code is `L-3A88E041` (`Apache Flink Kinesis Processing Units (KPUs)`).

Request increases via `request-service-quota-increase` with the quota code from the list output. Increases for KPU and snapshot quotas typically approve within a business day.

## ENI Capacity Planning (VPC Apps)

MSF creates one ENI per allocated KPU, in each subnet, for VPC-enabled applications. Subnet sizing and the regional ENI quota both matter.

```
ENIs_per_subnet = KPUs
required_subnet_IPs = ENIs_per_subnet + 20% headroom for scaling and rolling restarts
```

Example: 16 KPU app 16 ENIs per subnet. Allow 20 available IPs per subnet to account for 20% buffer. A `/28` subnet (11 usable IPs) is too small; use `/27` (27 usable) or larger.

**Regional ENI quota** (`vpc` service code, `Network interfaces per region`) defaults to 5,000. Each VPC-enabled MSF KPU consumes one. Multiple large MSF apps in the same region can pressure this quota — check before deploying. Other services in the VPC (Lambda, ECS, RDS) also consume ENIs from the same quota.

Subnets should span at least 2 AZs for fault tolerance.

## When VPC Is Required

| Source/Sink | VPC Required |
|-------------|--------------|
| Kinesis Data Streams | No (public endpoint) |
| Amazon S3 | No (public endpoint, S3 gateway endpoint optional) |
| DynamoDB | No (public endpoint) |
| Firehose | No |
| Amazon MSK (Kafka) | **Yes** |
| RDS / Aurora | **Yes** |
| ElastiCache | **Yes** |
| OpenSearch in VPC | **Yes** |
| Self-hosted Kafka | **Yes** if private |
| Public Kafka / external API | No, but needs NAT gateway in VPC subnets |

VPC apps without a NAT gateway lose access to public AWS endpoints (CloudWatch, S3 if not using gateway endpoint, Kinesis). Symptoms: silent failure of metric publishing, S3 checkpoint failures, deserialization errors trying to call schema registry.

## MSF vs EMR Flink

| Factor | MSF | EMR Flink |
|--------|-----|-----------|
| Operations | Fully managed, no clusters | Self-managed EC2/EKS clusters |
| Scaling | KPU autoscaling (CPU-only) | Manual cluster scaling |
| Billing | Per KPU-hour | Per EC2-hour (+ EMR surcharge) |
| Flink version | AWS-managed (1.15, 1.18, 1.19, 1.20, 2.2) | Any Flink version, including custom builds |
| Custom connectors | Limited to bundled JARs / fat-JAR upload | Full Flink ecosystem |
| Job isolation | One job per application | Multiple jobs per cluster |
| Startup time | 1–3 min | 5–15 min cluster boot |
| Max parallelism | 256 (quota-adjustable) | Unlimited (cluster size) |
| State backend | Managed RocksDB | Self-managed RocksDB / heap |

**Choose MSF when:** zero infrastructure management, single-job-per-app is acceptable, parallelism fits within KPU limits, fast iteration matters.

**Choose EMR Flink when:** custom Flink connectors not in MSF, multiple Flink jobs sharing infrastructure, specific Flink version or patch control, parallelism exceeds 256, fine-grained CPU/memory ratios needed.

**Cost crossover:** EMR is typically cheaper at large scale (10+ KPU equivalent, 24/7) due to EC2 commitment savings, but the operational overhead (cluster patching, scaling, monitoring) typically erases the savings unless EMR expertise already exists.

## Source Selection: KDS vs MSK vs S3

| Source | Best For | Throughput | VPC | Ordering | Retention |
|--------|---------|-----------|-----|----------|-----------|
| Kinesis Data Streams (KDS) | AWS-native ingestion, < 1 GB/s, Lambda integration | Per-shard (1 MB/s in, 2 MB/s out) | No | Per-shard | 1–365 days |
| Amazon MSK | Kafka ecosystem, complex routing, > 1 GB/s | Per-broker (hundreds MB/s) | Yes | Per-partition | Unlimited (storage-based) |
| Amazon S3 | Batch-to-stream replay, reprocessing | Bulk file scan | No | File ordering | Indefinite |

**KDS pitfalls:** shard count drives parallelism; shard count is hard to change post-creation. Cost scales linearly with shard count, not throughput.

**MSK pitfalls:** broker provisioning takes hours; cross-AZ replication doubles network cost; SASL/IAM auth requires careful security group setup.

**S3 source pitfalls:** no event-time ordering across files unless designed in; file enumeration is the bottleneck for large prefix counts.

For source-side EFO and Kinesis polling tradeoffs, see [kinesis-efo-guide.md](kinesis-efo-guide.md). For MSK setup, see the [iac-and-deployment.md](iac-and-deployment.md) deployment patterns.

## Sink Selection

| Sink | Best For | VPC | Ordering Preserved |
|------|---------|-----|--------------------|
| S3 (Parquet/ORC) | Data lake, batch analytics, Athena | No | File-level only |
| Iceberg | Transactional data lake, schema evolution, time travel | No (catalog-dependent) | Yes (commit-order) |
| Kinesis Data Streams | Real-time downstream consumers | No | Per-shard |
| MSK | Kafka ecosystem | Yes | Per-partition |
| OpenSearch | Search, log analytics, dashboards | Yes (VPC mode) or No (public) | No (eventually consistent) |
| DynamoDB | Low-latency key-value lookups | No | No (last-write-wins per key) |
| RDS / Aurora | Relational writes, joins on results | Yes | Yes (transaction order) |
| Firehose | Managed delivery to S3/Redshift/OpenSearch with batching | No | Within batch |

**S3 small files anti-pattern:** Streaming writers commit on every checkpoint, creating one file per checkpoint per partition. With 60s checkpoints and 8 partitions, a job writes 11,520 files/day. Use Iceberg with compaction, or batch via Firehose, or increase checkpoint interval. See [iceberg-tuning-and-operations.md](iceberg-tuning-and-operations.md).

**RDS/Aurora sink anti-pattern:** Per-record JDBC writes are 10–100× slower than batched writes. Use the JDBC sink with batching enabled. RDS connection pool limits (typically 5,000) cap effective parallelism.

## Architecture Patterns

| Pattern | Use Case | VPC |
|---------|---------|-----|
| KDS → MSF → S3/Iceberg | Data lake ingestion | No |
| MSK → MSF → MSK | Stream-to-stream enrichment | Yes |
| KDS → MSF → DynamoDB | Real-time aggregation serving | No |
| KDS → MSF → OpenSearch | Real-time search index | Optional |
| CDC source → MSF → Iceberg | Database replication to lake | Yes (DB side) |
| MSK → MSF → S3 + KDS | Fan-out to lake and downstream consumers | Yes (MSK side) |

## Co-location and Cross-AZ Cost

For private connections (MSK, RDS, OpenSearch in VPC), MSF KPUs must be in the same VPC or peered VPC as the source/sink. Cross-AZ data transfer between MSF and MSK is **always billed** at $0.01/GB each direction — at 100 MB/s sustained that is $26K/year. Place MSF subnets in the same AZs as MSK brokers and use rack-aware producers/consumers where supported.

## Common Mistakes

| Mistake | Impact |
|---------|--------|
| Using `kinesisanalytics` for the CLI / SDK control plane | Returns v1 SQL apps only, not Flink — use `kinesisanalyticsv2` for the CLI/SDK |
| `kinesisanalyticsv2` for the Service Quotas service-code | `NoSuchResourceException` — Service Quotas uses the legacy `kinesisanalytics` code |
| `kinesisanalyticsv2:` IAM actions | All API calls denied — IAM uses `kinesisanalytics:` prefix |
| `AWS/Flink` namespace in CloudWatch | Empty metric results |
| `kinesisanalyticsv2.amazonaws.com` trust principal | MSF cannot AssumeRole — trust principal is `kinesisanalytics.amazonaws.com` |
| Hardcoding region lists for cross-region discovery | Disabled regions cause `AccessDeniedException` — use `describe-regions` |
| Sizing subnets without ENI headroom | Application stuck STARTING; ENIs cannot be created |
| Choosing EMR for a single-job pipeline | Operational overhead exceeds infrastructure savings |
| Mismatched MSF and source AZs | Persistent cross-AZ data transfer cost |

## References

- [MSF Quotas](https://docs.aws.amazon.com/managed-flink/latest/java/limits.html)
- [MSF VPC Configuration](https://docs.aws.amazon.com/managed-flink/latest/java/vpc.html)
- [MSF Pricing](https://aws.amazon.com/managed-service-apache-flink/pricing/)
- [Cross-AZ Data Transfer Pricing](https://aws.amazon.com/ec2/pricing/on-demand/)
