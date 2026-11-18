---
name: managing-amazon-kinesis-data-streams
description: >
  Operates data delivery and queues in Amazon Kinesis Data Streams (KDS).
  Covers delivering a stream to Iceberg tables on S3 Tables or to S3
  buckets, and queue-based consumption: receive, acknowledge, visibility
  timeout, and migrating KCL, GetRecords, or Lambda consumers. Applies when
  records can be processed independently, without shard ordering: to consume a
  stream without managing shards, leases, or checkpoints, run more consumers
  than shards, or stop one bad record blocking a shard, whether or not they
  mention Kinesis queues.

  Triggers: Kinesis Data Streams, KDS, streaming tables, stream to S3, stream to
  Iceberg, stream to S3 Tables, KDS delivery, KDS channel, CreateChannel, data
  channel, data freshness, dead-letter queue, KDS lakehouse, serverless Kinesis
  delivery, Firehose alternative for KDS, zero-ops Kinesis to S3,
  ReceiveQueueRecords, Kinesis dead-letter records.
  Not for Kinesis Data Firehose, Kinesis Video Streams, Managed Service for
  Apache Flink, SQS dead-letter queues, or tuning a KCL app.
version: 2
---

# Amazon Kinesis Data Streams

## Overview

Domain expertise for two Amazon Kinesis Data Streams features:

- **Streaming tables and Amazon S3 delivery** (data delivery) - serverless, fully managed delivery from a KDS stream to Apache Iceberg tables on S3 Tables or to general-purpose S3 buckets. No consumers, Firehose, or Flink required for append-only delivery. Delivery is configured as a **channel** on a stream with `CreateChannel`. Channels consume no shard capacity and no enhanced fan-out slots.
- **Queues** - a queue delivers records from an on-demand stream to a queue consumer and tracks the delivery state of each record. Consumer instances receive records, process them, and acknowledge them, with no shards, leases, or checkpoints to manage. A queue has no retention period of its own: a record that is never acknowledged, including a dead-letter record, expires when the stream's retention period ends for that record.

The two features are independent. A stream can have channels and queues at the same time, alongside existing stream consumers.

The AWS MCP server is recommended for sandboxed execution and audit logging of AWS operations. Without it, run the same operations with the AWS CLI or an AWS SDK.

## Which Workflow Do You Need?

If a Kinesis request is ambiguous, ask: **"Are you delivering stream data to S3 or Iceberg, or consuming records in your own application?"**

Ask the same when a user mentions a **dead-letter queue**. The two features handle failed records in unrelated ways: a channel's dead-letter queue is an S3 bucket, while a queue marks a record that keeps failing as a dead-letter record and stops returning it from `ReceiveQueueRecords`.

### Data delivery: streaming tables and S3

| Customer Intent | Reference |
|---|---|
| Deliver stream data to Apache Iceberg tables on S3 Tables - setup, IAM, Glue schema, type mapping, partitioning, channel lifecycle | [references/data-delivery-streaming-tables.md](references/data-delivery-streaming-tables.md) |
| Deliver stream data to a general-purpose S3 bucket as objects - setup, IAM, compression, storage class, output key templates, channel lifecycle | [references/data-delivery-general-purpose-delivery-to-s3.md](references/data-delivery-general-purpose-delivery-to-s3.md) |
| Build a lakehouse / data lake from Kinesis; make streaming data queryable in Athena | [references/data-delivery-streaming-tables.md](references/data-delivery-streaming-tables.md) |
| Zero-ops, serverless alternative to Firehose or Kinesis consumers for KDS to S3 delivery | [references/data-delivery-general-purpose-delivery-to-s3.md](references/data-delivery-general-purpose-delivery-to-s3.md) |
| CloudWatch metrics and alarms, delivery logging, CloudTrail, encryption, channel states, quotas, naming rules, what can be updated | [references/data-delivery-monitoring-security-and-limits.md](references/data-delivery-monitoring-security-and-limits.md) |
| Channel is ACTIVE but no data arrives; records landing in the channel's DLQ; rising data freshness | Start with [references/data-delivery-monitoring-security-and-limits.md](references/data-delivery-monitoring-security-and-limits.md), then the destination-specific troubleshooting table |
| Deliver to both S3 and S3 Tables from one stream | Supported - create one channel per destination |

### Queues in Kinesis Data Streams

| Customer Intent | Reference |
|---|---|
| What queues are; whether a workload fits (ordering, filtering, partition keys, delivery guarantees); create a queue, including on a stream that IaC manages; build a queue consumer; visibility timeout; redelivery and other troubleshooting | [references/queues-getting-started.md](references/queues-getting-started.md) |
| Migrate a KCL, `GetRecords`, or Lambda consumer to a queue consumer | [references/queues-migration.md](references/queues-migration.md) (plan template: [assets/queues-migration-plan-template.md](assets/queues-migration-plan-template.md)) |
| Dead-letter records; `MaxReceiveCount`; inspect, restore, or acknowledge them | [references/queues-dead-letter-records.md](references/queues-dead-letter-records.md) |
| IAM policies for queue consumers and operators; security considerations; operation behavior; quotas; queue CloudWatch metrics | [references/queues-operations-and-iam.md](references/queues-operations-and-iam.md) |

## Prerequisites

Data delivery and queues both require an **ON_DEMAND stream**. Provisioned-mode streams are not supported. Use `UpdateStreamMode` to switch an existing stream; [switching modes](https://docs.aws.amazon.com/streams/latest/dev/how-do-i-size-a-stream.html#switchingmodes) doesn't disrupt producers or consumers. Don't recreate the stream, which would lose the records already in it.

- **Data delivery** also needs an IAM service execution role trusted by `kinesis.amazonaws.com`, and a destination in the **same Region** as the stream.
- **Queues** need an AWS CLI or AWS SDK version that has the queue operations, so check before running or generating any queue calls. For the CLI, run `aws kinesis receive-queue-records help`. If the command isn't found, ask the user before updating, then follow [AWS CLI update instructions](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html#cli-update). For an SDK, update the Kinesis client to its latest release with the language's package manager. Queues also need their own IAM actions. A policy that lists only stream actions does not grant them. `CreateQueue` also requires `kinesis:AssociateStreamsWithQueue` on the stream ARN.

## Hard Limits to Check First

### Data delivery

These rule out delivery entirely, so confirm them before designing a solution:

- **Append-only** - no CDC, upserts, or deletes
- **No schema evolution** - a schema change means deleting and recreating the channel
- **No backfill** - only records produced after the channel is `ACTIVE` are delivered
- **No transformations** - records are delivered as-is
- **New table per channel** - cannot deliver into an existing Iceberg table
- **Data freshness is 300-900 seconds** - not sub-minute
- **Same Region only** - cross-account is supported, cross-Region is not

If any of these block the customer, recommend **Managed Service for Apache Flink** instead.

### Queues

Queues fit stateless processing, where each record can be processed on its own, without reference to other records, for example microservice integration, order processing and fulfillment, notifications, background jobs, and per-record inference. Before building or migrating a queue consumer, ask whether the workload needs any of these:

- **Strict ordering** per partition key or shard. A queue doesn't necessarily deliver records in the order producers wrote them.
- **Partition-key grouping** - the same consumer handling all records for a key. A queue distributes records across consumers independently of shards.
- **Exactly-once processing** - processing a record more than once would cause a problem, such as a duplicate write. A queue delivers each record at least once, so processing must be idempotent.

If the whole workload needs strict ordering or partition-key grouping (stateful processing, such as live analytics, personalization, or anomaly and pattern detection), read the stream directly with shared throughput or enhanced fan-out, for example with KCL. If only part does, offer a hybrid. If duplicates are the only problem, the processing must be made idempotent first.

Also check the producer: a queue does not de-aggregate records written with **KPL aggregation**. See [references/queues-getting-started.md](references/queues-getting-started.md).

## Guardrail - where this skill's own files live (MCP vs local install)

This skill can be loaded two ways, and they resolve the skill's own bundled
files from different places. Determine how the skill was loaded before reading
a reference or asset:

- **Loaded through the AWS MCP `retrieve_skill` tool:** The skill is not
  installed on the local filesystem. You MUST fetch each reference or asset
  via `retrieve_skill` with the `file` parameter (e.g.
  `file="references/queues-getting-started.md"` or
  `file="assets/queues-migration-plan-template.md"`). Do NOT `file_read` these
  paths from the local or working directory, and do NOT search the filesystem
  for them - they are not there, and any local file that happens to match the
  name is unrelated to this skill.
- **Installed locally** (e.g. `.kiro/skills/managing-amazon-kinesis-data-streams/` or
  `~/.claude/skills/managing-amazon-kinesis-data-streams/`): Read files from the
  local skill directory using relative paths.

This distinction applies only to the skill's own packaged files. User data and
session artifacts are always read from and written to the user's working
directory. Never fetch or write customer data through `retrieve_skill`.

## Additional Resources

- [KDS Developer Guide](https://docs.aws.amazon.com/streams/latest/dev/introduction.html)
- [Kinesis Data Streams terminology and concepts](https://docs.aws.amazon.com/streams/latest/dev/key-concepts.html)
- [KDS API Reference](https://docs.aws.amazon.com/kinesis/latest/APIReference/)
- [Kinesis Data Streams pricing](https://aws.amazon.com/kinesis/data-streams/pricing/)
- [Consume records from a stream with queues](https://docs.aws.amazon.com/streams/latest/dev/consuming-with-queues.html)
- [Handle dead-letter records in a queue](https://docs.aws.amazon.com/streams/latest/dev/queues-dead-letter-records.html)
- [Monitor a queue](https://docs.aws.amazon.com/streams/latest/dev/queues-monitoring.html)
- [IAM permissions for queues](https://docs.aws.amazon.com/streams/latest/dev/queues-iam.html)
- [Quotas and limits for queues](https://docs.aws.amazon.com/streams/latest/dev/queues-quotas.html)
- [S3 Tables Developer Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables.html)
- [Glue Schema Registry](https://docs.aws.amazon.com/glue/latest/dg/schema-registry.html)
