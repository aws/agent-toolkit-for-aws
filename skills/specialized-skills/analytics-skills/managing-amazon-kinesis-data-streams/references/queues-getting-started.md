# Queues in Kinesis Data Streams: getting started

A queue adds queue-based consumption to a Kinesis data stream. Instead of the shard, lease, and checkpoint machinery of the Kinesis Client Library (KCL), a consumer polls, receives, processes, and acknowledges records.

## How it works

- Queue operations are part of the standard Kinesis SDK client and the `aws kinesis` CLI, in the latest versions (see [SKILL.md Prerequisites](../SKILL.md#prerequisites)).
- `ReceiveQueueRecords` returns up to 10 records per call, each with a `ReceiptHandle`. Each record is delivered to one consumer at a time.
- `AcknowledgeQueueRecords` tells the queue a record is processed, so the queue does not deliver it again. It changes only the queue's delivery state: the record stays in the stream for its retention period, where stream consumers and other queues can still read it.
- A queue can deliver a record only while the stream still retains it. A record that is never acknowledged, including a dead-letter record, expires when the stream's retention period ends for that record (24 hours by default, up to 365 days).
- An unacknowledged record becomes visible again after the visibility timeout, so a later receive can deliver it again. Other records keep being delivered meanwhile, so an unacknowledged record does not hold up the ones behind it.
- The queue tracks delivery state, so there is no lease table, shard assignment, or checkpointing to manage, and the number of consumer instances is independent of the stream's shard count.
- Existing stream consumers (KCL, Lambda, and others) keep working unchanged. A queue reads alongside them.
- Each queue keeps its own delivery state, separate from every other queue on the stream. Instances of one application share one queue; two applications that each need every record need a queue each.
- Producers (`PutRecord`, `PutRecords`) do not change.

### Record lifecycle

- **Visible** - ready to be received.
- **In flight** - received by a consumer and hidden for the visibility timeout.
- **Acknowledged** - processing confirmed; the queue does not deliver it again.
- **Dead-letter** - dead-letter handling is on by default. Once the record has been received `MaxReceiveCount` times (6 by default) without being acknowledged, the next receive moves it to the dead-letter state instead of delivering it. `ReceiveQueueRecords` no longer returns it; receive, acknowledge, or restore it with the dead-letter operations or in the Kinesis console. See [queues-dead-letter-records.md](queues-dead-letter-records.md).

If the visibility timeout expires before acknowledgment, an in-flight record returns to visible. The next receive delivers it again and increases its `ReceiveCount`.

## When to use a queue

Kinesis Data Streams has two kinds of consumer:

- **Stream consumers** read the stream directly. Within one application, each shard is read by one consumer instance at a time, in the order its records were written. This fits stateful processing, where handling a record depends on the records before it, such as live analytics, personalization, or anomaly and pattern detection. KCL coordinates the instances and tracks checkpoints and processing state. A stream consumer reads with throughput shared across the stream's consumers, or with enhanced fan-out's dedicated throughput.
- **Queue consumers** fit stateless processing, where each record is handled on its own, such as microservice integration, order processing and fulfillment, notifications, background jobs, and per-record inference. They need no client library and no shard handling, checkpointing, or instance coordination. Unacknowledged records are redelivered without holding up the records behind them, and once a record has been received `MaxReceiveCount` times without being acknowledged, the next receive moves it to the dead-letter state, so it stops using consumer capacity on redeliveries. Instances are not tied to shards, so you add instances to process more records in parallel, and queue-level CloudWatch metrics show the backlog.

Judge fit with the [queue checks in SKILL.md](../SKILL.md#queues) and the checks below, or ask about the user's requirements. Ask about every check: users given a partial list tend to check only what's on it.

### No server-side filtering

A queue delivers every record in the stream. Content-based filtering happens in the consumer.

- Filter right after `ReceiveQueueRecords`. Acknowledge non-matching records only if no other consumer reads this queue; an acknowledged record is not delivered from this queue again. Consumers that need different records should each use their own queue.
- If filtering matters at scale, the producer can route event types to separate streams, each with its own queue. This is a producer change.

### No partition-key or shard affinity

Any consumer can receive any record. Records with the same partition key are not guaranteed to reach the same consumer or arrive in order.

- If the workload groups records by partition key (for example, in-memory aggregation per entity), queues are not a fit. Keep it on a stream consumer.
- If partition keys only spread load across shards, there is no impact.

### No ordering guarantee

A queue doesn't necessarily deliver records in the order producers wrote them. Records are distributed across consumers independently of shards, and a slow record does not block the ones after it.

- Keep ordering-sensitive processing on stream consumers and move only order-insensitive work to a queue (a hybrid).
- Standard SQS and SNS do not guarantee ordering either. Only SQS FIFO and SNS FIFO do. Do not suggest SQS or SNS as ordered alternatives unless naming the FIFO variants.

### At-least-once delivery

A record can be delivered more than once: again after its visibility timeout expires, and rarely even after it has been acknowledged. Make the consumer idempotent. If the producer writes a unique ID into each record's data, deduplicate on it: it also catches duplicates from producer retries, which are separate stream records with their own `RecordId`. Otherwise, deduplicate on `RecordId`, which stays the same across every delivery of one record but catches only redeliveries. For more on where duplicates come from, see [Handling duplicate records](https://docs.aws.amazon.com/streams/latest/dev/kinesis-record-processor-duplicates.html).

KCL consumers have the same requirement, because KCL replays records from the last checkpoint after a failover. A consumer that already handles KCL replays handles queue redeliveries too.

### No record de-aggregation

KPL aggregation packs several user records into one Kinesis Data Streams record. A queue delivers that record as-is and does not de-aggregate it. Do not use a queue with a producer that aggregates: turn KPL aggregation off first. Check how the producer writes before creating a queue. A producer that uses `PutRecord`/`PutRecords`, or KPL with aggregation turned off, is unaffected.

## Add a queue consumer to a stream

First ask: **"Do you already have a stream with a producer writing to it, or does one need to be created? The stream must be in on-demand mode (On-demand Standard or On-demand Advantage)."**

- **Existing stream:** confirm its ARN, then check it with `DescribeStreamSummary`:
  - It must be on-demand. If it isn't, switch it with `UpdateStreamMode`, or change it in the IaC if IaC manages the stream (see [Create the queue with infrastructure as code](#create-the-queue-with-infrastructure-as-code)). Switching modes doesn't disrupt producers or consumers. The stream is `UPDATING` until it returns to `ACTIVE`, and each stream can switch modes at most twice in 24 hours. See [Switch between modes](https://docs.aws.amazon.com/streams/latest/dev/how-do-i-size-a-stream.html#switchingmodes).
  - It should be encrypted at rest (`EncryptionType: KMS`). If it isn't, recommend turning on encryption with `StartStreamEncryption` before creating the queue, and ask before changing the stream.
- **No stream yet:** `CreateStream` with `StreamModeDetails={StreamMode: ON_DEMAND}`, wait until `DescribeStreamSummary` shows `StreamStatus` `ACTIVE`, then encrypt it at rest with `StartStreamEncryption` (`EncryptionType=KMS`, with a customer managed key or `alias/aws/kinesis`). Data in transit already uses TLS. A new stream has no records, so the queue has nothing to deliver until records are written to the stream.

Confirm fit with the [queue checks in SKILL.md](../SKILL.md#queues) before writing code. Strict ordering or partition-key grouping rules queues out for that workload. Before using a queue, make the processing idempotent if the workload needs exactly-once processing, and turn off KPL aggregation if the producer uses it.

Confirm IAM in the conversation before generating code that calls these APIs. This is a question for the user, not a code comment:

- **Setup calls** (`CreateStream`, `DescribeStreamSummary`, `UpdateStreamMode`, `StartStreamEncryption`, `CreateQueue`) need the setup/operator policy in [queues-operations-and-iam.md](queues-operations-and-iam.md). It includes `kinesis:AssociateStreamsWithQueue` on the **stream** ARN, which is often missed, and allows `CreateQueue` only with an owner tag, so pass that tag in `CreateQueue`'s `Tags`.
- **The receive/process/acknowledge loop** needs only the consumer policy.

Before creating the queue, settle three settings:

1. **Starting position.** Ask: **"Where should the queue start reading? TRIM_HORIZON (all existing and new records), LATEST (new records only), or AT_TIMESTAMP (from a specific time)?"** It defaults to `LATEST`, which skips everything already in the stream, and cannot be changed after creation. `StartingPosition` goes inside the `StreamConfigurationList` entry, next to `StreamARN`.
2. **Visibility timeout.** How long a received record stays hidden before it becomes visible again and can be redelivered. Set it with `VisibilityTimeoutSeconds` in `QueueAttributes`, from 0 to 43,200 seconds (12 hours); it defaults to 30 seconds. Keep the queue's default visibility timeout above 0. At 0, a received record is immediately available for other consumers to receive while it is still being processed. A timeout of 0 can be used when you want a record available again right away, for example one the consumer decides not to process: set it with `UpdateQueueRecordsVisibility`. The timeout starts when `ReceiveQueueRecords` returns and covers every record in that response, so size it for processing and acknowledging a whole batch. If processing time varies, set a timeout that covers the common case and extend individual records that need longer with `UpdateQueueRecordsVisibility`, rather than setting one very high value, which delays redelivery when a consumer fails.
3. **Dead-letter configuration.** Ask whether the default threshold fits, or whether the user wants dead-letter handling off. If the consumer often fails on transient errors, such as timeouts from a downstream service, suggest a higher `MaxReceiveCount` so those records aren't set aside before a retry succeeds. Defaults and sizing are in [queues-dead-letter-records.md](queues-dead-letter-records.md).

`UpdateQueue` changes the visibility timeout or dead-letter configuration later. A new visibility timeout applies to future receives, not records already in flight.

Creating or updating a queue is asynchronous. Wait until `DescribeQueue` shows `QueueStatus` `ACTIVE`. Before starting consumers, check that the `DescribeQueue` response matches what you asked for: the visibility timeout and dead-letter configuration, including `MaxReceiveCount`, and after `CreateQueue`, the `StartingPosition`.

### Create the queue with infrastructure as code

If IaC (CloudFormation, CDK, Terraform) manages the stream:

- CloudFormation, CDK, and Terraform have no queue resource for Kinesis Data Streams, so create the queue with the CLI or SDK. If the IaC tool's documentation lists one, use it instead and follow that documentation.
- Keep the rest in the IaC. The queue ARN is generated by `CreateQueue`, so create the queue first, then pass the `QueueARN` from its response into the IaC as a parameter. Use it to scope the consumer's IAM policy, and pass it to the consumer as configuration, such as an environment variable.
- If the stream is provisioned, change its mode to on-demand in its IaC definition, not with `UpdateStreamMode`, or a later deploy tries to switch it back. Preview the change (`terraform plan`, `cdk diff`, or a CloudFormation change set) and check that the stream is updated in place, not replaced.

### Consumer loop

`ReceiveQueueRecords` -> process each record -> `AcknowledgeQueueRecords` for the records processed successfully, with the `ReceiptHandle` from that receive. Check the `Failed` list in every acknowledge response. If processing may approach the visibility timeout, call `UpdateQueueRecordsVisibility` to extend it. Take the request and response names from the installed SDK.

### Consume with Lambda

Lambda event source mappings don't support queues in Kinesis Data Streams, so a Lambda function can't consume a queue directly. Use the consumer loop above. If the Lambda documentation lists these queues as an event source, follow it instead.

## Troubleshooting

- **Records are redelivered** - three causes:
  1. **At-least-once delivery (expected).** A record can be redelivered, rarely even after a successful acknowledgment. See [At-least-once delivery](#at-least-once-delivery).
  2. **Visibility timeout too short.** The record becomes visible again while the consumer is still working on it. Each early redelivery counts toward `MaxReceiveCount`, so a timeout that is too short can also put records that were only slow into the dead-letter state. See the sizing guidance above.
  3. **Acknowledged with an older handle.** Each receive issues a new `ReceiptHandle`. An acknowledgment with an older one can succeed without removing the record. Always use the handle from the most recent receive.
- **`UnknownOperationException`, or the client has no `receive_queue_records` (or equivalent) method** - the SDK or CLI version predates queues, so update it (see [SKILL.md Prerequisites](../SKILL.md#prerequisites)). If it is current, queues may not be available in that Region yet.
- **`CreateQueue` fails:**
  - `ValidationException` - a request value isn't valid, for example the stream is in provisioned mode or a parameter is out of range. The error message says which.
  - `ResourceInUseException` - the queue name is already used in the account and Region, or the stream isn't `ACTIVE` or `UPDATING`. The error message says which.
  - `LimitExceededException` - either the stream reached its registered consumer limit, which enhanced fan-out consumers and queues share, or too many queues are being created or deleted at once. See the quotas in [queues-operations-and-iam.md](queues-operations-and-iam.md#quotas).
  - `AccessDeniedException` even though the queue permissions look right - usually `kinesis:AssociateStreamsWithQueue` is missing or scoped to the queue instead of the stream ARN. The error message does not name the action.
- **First receives on a new queue come back empty** - normal. A new queue can take over a minute after it becomes `ACTIVE` to start delivering, so several receives can be empty even with records in the stream.
- **Some records never arrive, or stop arriving after a few receives** - dead-letter handling is on by default, so once a record has been received `MaxReceiveCount` times (6 by default) without being acknowledged, the next receive puts it into the dead-letter state, and `ReceiveQueueRecords` no longer returns it. Check the `VisibleDeadLetterQueueRecords` CloudWatch metric, or read the records with `ReceiveDeadLetterQueueRecords`. Fix the cause, then return the records to the queue with `RestoreDeadLetterQueueRecords`; see [queues-dead-letter-records.md](queues-dead-letter-records.md). Turning dead-letter handling off instead has trade-offs; see [Turning dead-letter handling off](queues-dead-letter-records.md#turning-dead-letter-handling-off).
- **How many records does my queue still have to deliver** - no Kinesis API returns it, and `DescribeQueue` has no record count. Add up the CloudWatch metrics in [queues-operations-and-iam.md](queues-operations-and-iam.md#cloudwatch-metrics), for example with `GetMetricData`: `VisibleQueueRecords` (waiting to be received) and `InFlightQueueRecords` (received, not yet acknowledged), plus `VisibleDeadLetterQueueRecords` and `InFlightDeadLetterQueueRecords` for dead-letter records. The two `Visible` metrics stop at 1,000,000, even when more records are visible. Not every record in the stream is waiting to be delivered by this queue: the stream also keeps records this queue's consumers have acknowledged, and records from before the queue's starting position. An empty receive doesn't mean the queue is empty either; see the entries on empty receives below.
- **Are consumers keeping up, or will records expire?** Check two things:
  - **Backlog:** watch how `VisibleQueueRecords` and `InFlightQueueRecords` change over time. If they keep growing, consumers are processing more slowly than producers write: add consumer instances, or speed up processing. A large backlog isn't a problem by itself if consumers clear it in time, so set any alarm threshold from the queue's usual levels. Once `VisibleQueueRecords` stays at 1,000,000, it no longer shows the trend: compare the stream's `IncomingRecords` with the queue's `AcknowledgedQueueRecords` (`Sum`) instead. If dead-letter records keep growing, records are failing, and adding queue consumer instances won't clear them; see [Handling dead-letter records](queues-dead-letter-records.md#handling-dead-letter-records).
  - **Record age:** records can expire even when the backlog is steady or shrinking slowly, and no queue metric shows how old they are. Each record returned by `ReceiveQueueRecords` or `ReceiveDeadLetterQueueRecords` includes `ApproximateArrivalTimestamp`, so the existing receive code can compare each record's age (the current time minus that timestamp) with the stream's `RetentionPeriodHours` from `DescribeStreamSummary`, and log a warning when the age passes the delay the workload tolerates. Records aren't delivered in order, so this shows the age of the records being received, not of the oldest record waiting. If the user wants an alarm instead of a log warning, the receive code can publish the oldest age from each receive as a custom CloudWatch metric; custom metrics and `PutMetricData` calls are billed, so ask the user first. The consumer may need additional IAM permissions to call `DescribeStreamSummary` and `PutMetricData`. If records get close to the retention period, add consumer instances or speed up processing. To give consumers more time, raise the stream's retention period with `IncreaseStreamRetentionPeriod`; retention above 24 hours costs extra, so ask the user first. To raise it, the principal that changes the stream, such as the setup/operator role, needs `kinesis:IncreaseStreamRetentionPeriod` on the stream ARN.
- **Receives come back empty while `VisibleQueueRecords` is above 0** - check `InFlightQueueRecords`. If it holds steady at a maximum, the queue has reached its in-flight limit. Acknowledge records as soon as they are processed, and avoid visibility timeouts much longer than processing needs.
- **`AccessDeniedException` on a queue operation** - policies that list stream actions explicitly do not include queue actions. Wildcards do: `kinesis:*` covers every queue action, and `kinesis:Describe*` or `kinesis:List*` cover `DescribeQueue` and `ListQueues`. Grant the specific action; see [queues-operations-and-iam.md](queues-operations-and-iam.md).
