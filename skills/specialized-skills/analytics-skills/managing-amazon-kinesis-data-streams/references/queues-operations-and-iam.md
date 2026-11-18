# Queues in Kinesis Data Streams: operations and IAM

This file covers which operation to use, behavior that is easy to get wrong, and IAM policies. It does not list every request and response field.

For full request and response shapes, read them from the installed CLI or SDK, which must be the latest version (see [SKILL.md Prerequisites](../SKILL.md#prerequisites)). This works without documentation access:

- **CLI:** `aws kinesis <operation> help` lists every parameter and the output fields, and `aws kinesis <operation> --generate-cli-skeleton` prints a request template (for example `aws kinesis create-queue --generate-cli-skeleton`). For a full CLI walkthrough, see [Get started with queues using the AWS CLI](https://docs.aws.amazon.com/streams/latest/dev/queues-getting-started.html).
- **SDK:** read the request and response classes, or the service model, of the installed Kinesis client.

API reference: [KDS API Reference](https://docs.aws.amazon.com/kinesis/latest/APIReference/).

## Operations

| Operation | Use |
|---|---|
| `CreateQueue` | Create a queue on one on-demand stream. `StreamConfigurationList` takes exactly one entry, with `StreamARN` and an optional `StartingPosition`. |
| `UpdateQueue` | Change `VisibilityTimeoutSeconds` or `DeadLetterConfiguration`. Attributes you leave out stay unchanged. The queue must be `ACTIVE`. |
| `DescribeQueue`, `ListQueues`, `DeleteQueue` | Inspect, list (optionally filtered by stream), and delete queues. `ListQueues` returns results in pages: call it again with `NextToken` until a response has none, even when a page has fewer results than `MaxResults`. |
| `ReceiveQueueRecords` | Receive up to 10 records. `WaitTimeSeconds` (1-20 seconds, default 9) sets how long the call waits for records to arrive. `VisibilityTimeoutSeconds` overrides the queue's timeout for this call. |
| `AcknowledgeQueueRecords` | Acknowledge processed records so the queue does not deliver them again, 1-10 per call. |
| `UpdateQueueRecordsVisibility` | Extend or shorten an in-flight record's visibility, 1-10 per call. `0` makes the record visible again immediately, for example to hand back records a consumer cannot finish before it shuts down. |
| `ReceiveDeadLetterQueueRecords`, `AcknowledgeDeadLetterQueueRecords`, `RestoreDeadLetterQueueRecords`, `UpdateDeadLetterQueueRecordsVisibility` | Work with records in the dead-letter state, using the queue's ARN. See [queues-dead-letter-records.md](queues-dead-letter-records.md). |

Each received record carries `RecordId`, `ReceiptHandle`, `Data`, `ApproximateArrivalTimestamp`, `FirstReceiveTimestamp`, and `ReceiveCount`, and optionally `PartitionKey`. It has no `SequenceNumber`, because a queue does not expose shards; use `RecordId` to identify a record. SDKs return `Data` as raw bytes; the CLI shows it base64-encoded.

In typed SDKs, generated class names are not predictable from the operation name. Read them from the installed SDK rather than deriving them.

## Behavior that is easy to get wrong

- **Never construct a queue ARN.** The ARN contains a generated ID, not the queue name. Use the `QueueARN` returned by `CreateQueue` or `ListQueues`.
- **`ReceiptHandle` identifies one receive, not the record.** A redelivered record arrives with a new handle. Always use the handle from the most recent receive. A call with an older handle can succeed without acting on the record, so a `Successful` result for an old handle does not confirm the record was removed.
- **`RecordId` identifies the record.** It stays the same across every delivery, and it is the same in every queue on the stream that delivers the record. Use it to detect a redelivery of the same record; it does not catch a duplicate written by a producer retry. Don't deduplicate on `ReceiptHandle`: each delivery gets a new one.
- **Batch entries are identified by `ReceiptHandle`.** Entries for `AcknowledgeQueueRecords`, `UpdateQueueRecordsVisibility`, `AcknowledgeDeadLetterQueueRecords`, `UpdateDeadLetterQueueRecordsVisibility` and `RestoreDeadLetterQueueRecords` take a `ReceiptHandle`, and `Successful` and `Failed` results are keyed by it. Batch calls can partially fail; always check `Failed`.
- **A visibility change replaces the remaining time; it does not add to it.** Pass the total time the record still needs from now. A value smaller than the time left shortens visibility.
- **Visibility has a 12-hour ceiling per receive.** It is counted from when the record was received, and extending does not reset it. A value past the ceiling fails for that entry. A redelivered record starts a new 12-hour ceiling.
- **Every receive is billed.** Receives are billed by data size, including redeliveries and dead-letter receives, with a 1 KB minimum per record. Empty receives are free. Rates are on the [Kinesis Data Streams pricing page](https://aws.amazon.com/kinesis/data-streams/pricing/).
- **Starting position is fixed at creation.** `Timestamp` is required for `AT_TIMESTAMP` and rejected with `ValidationException` for any other type. An `AT_TIMESTAMP` earlier than the oldest record the stream still retains starts at that oldest record, the same as `TRIM_HORIZON`. Once the queue is `ACTIVE`, `DescribeQueue` reports the effective start time for every type.
- **Queue state:** `CREATING`, `ACTIVE`, `UPDATING` (returns to `ACTIVE`), `DELETING`. Calls made while the queue is `CREATING` can return `ResourceNotFoundException`; wait for `ACTIVE`. Receives and acknowledgments keep working while the queue is `UPDATING`. Deleting a queue drops its delivery state: its in-flight records are not delivered again and its receipt handles stop working, while the records stay in the stream. Before calling `DeleteQueue`, check `VisibleQueueRecords`, `InFlightQueueRecords`, `VisibleDeadLetterQueueRecords` and `InFlightDeadLetterQueueRecords`. If any is above 0, tell the user those records will not be delivered by this queue again and ask them to confirm the delete.
- **Stream mode and deletion.** A stream with queues cannot be switched to provisioned mode or deleted: `DeleteStream` fails with `ResourceInUseException`, and `EnforceConsumerDeletion` has no effect on queues. Delete its queues first.
- **VPC endpoints.** Queue operations use their own interface VPC endpoint service, `com.amazonaws.REGION.kinesis-queues` (`com.amazonaws.REGION.kinesis-queues-fips` for FIPS), separate from the stream's. To call queue operations from a VPC through AWS PrivateLink, create an interface VPC endpoint for that service. See [Use interface VPC endpoints for Kinesis Data Streams](https://docs.aws.amazon.com/streams/latest/dev/vpc.html#using-interface-vpc-endpoints).
- **Finding a queue's stream.** Each `QueueSummary` from `ListQueues` includes `Streams`. `DescribeStreamSummary` returns `QueueCount`, the number of queues on the stream (0 if none). Its `ConsumerCount` does not include queues (see [Quotas](#quotas)).
- **Tags.** `TagResource`, `UntagResource`, and `ListTagsForResource` accept a queue ARN.

## Quotas

Confirm current values at [Quotas and limits for queues](https://docs.aws.amazon.com/streams/latest/dev/queues-quotas.html).

- **Queues per stream:** queues share the stream's registered consumer limit with enhanced fan-out consumers. `CreateQueue` returns `LimitExceededException` once enhanced fan-out consumers plus queues reach it. Look up the current limit in the quotas page above. Check the current counts with `DescribeStreamSummary` and add `ConsumerCount` (enhanced fan-out consumers only) and `QueueCount`.
- **Queues being created or deleted:** each account has a limit on how many queues can be in `CREATING` or `DELETING` at the same time. Past that limit, `CreateQueue` returns `LimitExceededException`. Create queues one at a time and wait for each to become `ACTIVE`.
- **Maximum record size:** a queue delivers any record the stream accepts, up to 10 MiB. A stream accepts records up to its `MaxRecordSizeInKiB` (1 MiB by default, up to 10 MiB).
- **Account and Region:** a queue is in the same account and Region as its stream. To share queue access with a principal in another account, see [Cross-account consumers](#cross-account-consumers).

## Errors

- `InvalidArgumentException` and `ValidationException` are request errors. Fix the request rather than retrying.
- `ThrottlingException` and `InternalFailureException` are transient. Retry with backoff, which the AWS SDKs do by default. Only the data plane operations (receive, acknowledge, visibility, and the dead-letter operations) return `ThrottlingException`.
- The control plane operations (`CreateQueue`, `UpdateQueue`, `DeleteQueue`, `DescribeQueue`, `ListQueues`) return `LimitExceededException` instead. It can mean a request-rate limit or a quota, such as too many queues in `CREATING` or `DELETING`, so read the message.
- On a KMS-encrypted stream, receives can also fail with `KMS*` exceptions (for example `KMSAccessDeniedException` or `KMSDisabledException`). Apart from `KMSThrottlingException`, retrying does not help until the key or its permissions are fixed.

## Security considerations

- **Record data.** `Data` holds whatever the producer wrote, which can include sensitive values. Do not write record `Data` to logs, metrics or consumer output. Log the `RecordId` and error details instead.
- **Encryption at rest.** Encrypt the stream with KMS (`StartStreamEncryption`) before creating a queue. Receives decrypt records with the stream's key, so with a customer managed key, consumers and dead-letter handlers also need the `kms:Decrypt` statement in [IAM permissions](#iam-permissions).
- **Least privilege.** Give consumers only the consumer policy, scoped to the `QueueARN` reference, and keep the dead-letter handler and setup policies on separate roles.
- **Auditing.** CloudTrail records queue management calls, such as `CreateQueue`, `UpdateQueue` and `DeleteQueue`, as management events. Record operations, such as `ReceiveQueueRecords`, are data events, which a trail records only when data events are turned on.

## IAM permissions

Use separate policies by role. A **consumer** needs far less than the **setup/operator** principal that creates the stream and queue, and dead-letter actions go only to a **dead-letter handler**.

Only `ListQueues` and `ListStreams` need `Resource: "*"`. Every other action scopes to a queue or stream ARN, or to `queue/*` limited by an owner tag (see [Setup / operator](#setup--operator)).

If the stream is encrypted with a customer-managed KMS key, add this statement to the consumer and dead-letter handler policies. The `kms:ViaService` condition limits the key to calls made through Kinesis. The default key `alias/aws/kinesis` needs no KMS permissions. To manage encryption with a customer-managed key, the setup principal also needs `kms:List*` and `kms:DescribeKey*` on it.

```json
{
  "Sid": "DecryptStreamRecords",
  "Effect": "Allow",
  "Action": "kms:Decrypt",
  "Resource": "arn:aws:kms:REGION:ACCOUNT_ID:key/KEY_ID",
  "Condition": {"StringEquals": {"kms:ViaService": "kinesis.REGION.amazonaws.com"}}
}
```

### Consumer (least privilege)

Scope the policy to the queue's ARN: the `QueueARN` returned by `CreateQueue`. Pass the same ARN to the consumer as configuration.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "QueueConsumer",
      "Effect": "Allow",
      "Action": [
        "kinesis:ReceiveQueueRecords",
        "kinesis:AcknowledgeQueueRecords",
        "kinesis:UpdateQueueRecordsVisibility",
        "kinesis:DescribeQueue"
      ],
      "Resource": "arn:aws:kinesis:REGION:ACCOUNT_ID:queue/QUEUE_ID"
    }
  ]
}
```

### Dead-letter handler

Use this policy for the principal or tool that inspects, restores, or acknowledges dead-letter records. If it should only restore records, remove `AcknowledgeDeadLetterQueueRecords`. If it should only acknowledge them, remove `RestoreDeadLetterQueueRecords`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DeadLetterHandler",
      "Effect": "Allow",
      "Action": [
        "kinesis:ReceiveDeadLetterQueueRecords",
        "kinesis:AcknowledgeDeadLetterQueueRecords",
        "kinesis:UpdateDeadLetterQueueRecordsVisibility",
        "kinesis:RestoreDeadLetterQueueRecords",
        "kinesis:DescribeQueue"
      ],
      "Resource": "arn:aws:kinesis:REGION:ACCOUNT_ID:queue/QUEUE_ID"
    }
  ]
}
```

### Setup / operator

A queue's ARN is generated by `CreateQueue`, so it cannot be named before the queue exists. This policy uses `queue/*` and limits it with an owner tag: `CreateQueue` is allowed only with the tag, `TagResource` only on queues that already carry it, and the other queue actions only on queues that carry it. Replace `OWNER` with a value for the team or application, and pass `Tags={"owner": "OWNER"}` to `CreateQueue`. `CreateQueue` also requires `kinesis:AssociateStreamsWithQueue` on the **stream** ARN, so a policy scoped only to `queue/*` cannot create a queue. Add `kinesis:PutRecord` and `kinesis:PutRecords` on the stream only if the same principal produces.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CreateTaggedQueue",
      "Effect": "Allow",
      "Action": "kinesis:CreateQueue",
      "Resource": "arn:aws:kinesis:REGION:ACCOUNT_ID:queue/*",
      "Condition": {"StringEquals": {"aws:RequestTag/owner": "OWNER"}}
    },
    {
      "Sid": "AssociateStreamForCreateQueue",
      "Effect": "Allow",
      "Action": "kinesis:AssociateStreamsWithQueue",
      "Resource": "arn:aws:kinesis:REGION:ACCOUNT_ID:stream/STREAM_NAME"
    },
    {
      "Sid": "TagOwnQueues",
      "Effect": "Allow",
      "Action": "kinesis:TagResource",
      "Resource": "arn:aws:kinesis:REGION:ACCOUNT_ID:queue/*",
      "Condition": {"StringEquals": {"aws:RequestTag/owner": "OWNER", "aws:ResourceTag/owner": "OWNER"}}
    },
    {
      "Sid": "ManageOwnQueues",
      "Effect": "Allow",
      "Action": [
        "kinesis:DescribeQueue",
        "kinesis:UpdateQueue",
        "kinesis:ListTagsForResource"
      ],
      "Resource": "arn:aws:kinesis:REGION:ACCOUNT_ID:queue/*",
      "Condition": {"StringEquals": {"aws:ResourceTag/owner": "OWNER"}}
    },
    {
      "Sid": "StreamSetup",
      "Effect": "Allow",
      "Action": [
        "kinesis:CreateStream",
        "kinesis:DescribeStreamSummary",
        "kinesis:UpdateStreamMode",
        "kinesis:StartStreamEncryption"
      ],
      "Resource": "arn:aws:kinesis:REGION:ACCOUNT_ID:stream/STREAM_NAME"
    },
    {
      "Sid": "ListOperations",
      "Effect": "Allow",
      "Action": [
        "kinesis:ListQueues",
        "kinesis:ListStreams"
      ],
      "Resource": "*"
    }
  ]
}
```

### Cross-account consumers

To share a queue with a principal in another account, attach a resource-based policy to the queue with `PutResourcePolicy`. Name the specific role or account as the principal: queue policies don't accept wildcard principals or service principals. A stream's resource-based policy does not cover its queues. For the actions a queue policy can allow and the identity-based and KMS permissions the other account needs, see [IAM permissions for queues](https://docs.aws.amazon.com/streams/latest/dev/queues-iam.html). If the stream is encrypted with the AWS managed key (`alias/aws/kinesis`), switch it to a customer managed key before sharing the queue with another account.

### Teardown

Grant `DeleteQueue` only to the principal that deletes queues, with the same owner tag condition:

```json
{
  "Sid": "DeleteOwnQueues",
  "Effect": "Allow",
  "Action": "kinesis:DeleteQueue",
  "Resource": "arn:aws:kinesis:REGION:ACCOUNT_ID:queue/*",
  "Condition": {"StringEquals": {"aws:ResourceTag/owner": "OWNER"}}
}
```

## CloudWatch metrics

Namespace `AWS/Kinesis`, dimensions `QueueId` and `QueueName`. `QueueId` is the ID at the end of the `QueueARN` (`queue/QUEUE_ID`). Metrics are published with both dimensions together, so specify both `QueueId` and `QueueName` to alarm on or query a specific queue. Use the `Sum` statistic for the counts (received, acknowledged, empty receives) and `Average` for the `Visible` and `InFlight` metrics. Kinesis Data Streams can stop publishing a queue's metrics after about six hours with no visible records, so an idle queue can have gaps in its metrics.

| Metric | Description |
|---|---|
| `VisibleQueueRecords` | Records available to receive. The metric stops at 1,000,000, even when more are visible. |
| `InFlightQueueRecords` | Records received and still within their visibility timeout: not yet acknowledged or visible again |
| `ReceivedQueueRecords` | Records returned by `ReceiveQueueRecords` |
| `EmptyReceives` | `ReceiveQueueRecords` calls that returned no records |
| `AcknowledgedQueueRecords` | Records successfully acknowledged |

Dead-letter metrics are listed in [queues-dead-letter-records.md](queues-dead-letter-records.md#metrics).
