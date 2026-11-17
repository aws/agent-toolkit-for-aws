# Queues in Kinesis Data Streams: dead-letter records

Dead-letter handling is built into every queue. When it is on, once a record has been received `MaxReceiveCount` times without being acknowledged, the next receive puts it into a **dead-letter state** instead of delivering it: `ReceiveQueueRecords` no longer returns it, and you work with it through a separate set of dead-letter operations. There is no second queue to create, point a consumer at, or manage, and no separate ARN: the dead-letter operations use the queue's own ARN.

## Configuration

Set `DeadLetterConfiguration` in `QueueAttributes` on `CreateQueue`, or change it with `UpdateQueue`. It can also be set in the Kinesis console when creating or editing a queue.

| Field | Values |
|---|---|
| `TargetType` (required) | `BUILT_IN` - dead-letter handling on. `NONE` - dead-letter handling off. |
| `MaxReceiveCount` (required when `TargetType` is `BUILT_IN`) | 1-1000. How many times a record can be received without being acknowledged before it is put into the dead-letter state. |

The default, `BUILT_IN` with `MaxReceiveCount` 6, applies only when `DeadLetterConfiguration` is omitted entirely at creation. A `DeadLetterConfiguration` with `TargetType` `BUILT_IN` must also set `MaxReceiveCount`. `DescribeQueue` returns the current configuration in `QueueAttributes`.

Choose `MaxReceiveCount` together with the visibility timeout. A record enters the dead-letter state after roughly `MaxReceiveCount` x visibility timeout without being acknowledged, so a short timeout with a low count can put records that were only slow, not broken, into the dead-letter state.

## How a record enters the dead-letter state

- **Dead-letter handling on:** once a record has been received `MaxReceiveCount` times without being acknowledged, the next receive attempt puts it into the dead-letter state instead of delivering it. With `MaxReceiveCount` 6, a record is delivered 6 times.
- **Dead-letter handling off:** an unacknowledged record becomes visible again each time its visibility timeout expires, so it can be received again. See [Turning dead-letter handling off](#turning-dead-letter-handling-off).

A dead-letter record stays until it is acknowledged with `AcknowledgeDeadLetterQueueRecords`, restored, or expires at the end of the stream's retention period, so handle dead-letter records well before then.

## Turning dead-letter handling off

Setting `TargetType` to `NONE` turns dead-letter handling off, with these effects:

- **Records your consumer cannot process are never set aside.** A record that is never acknowledged becomes visible again after every visibility timeout, and can be received again until it is acknowledged or its retention period ends (24 hours by default, up to 365 days). Each redelivery is another billed receive and another processing attempt.
- **Records already in the dead-letter state stay there.** Handle them with the dead-letter operations.
- **Turning it back on uses each record's existing receive count.** A record received `MaxReceiveCount` times or more while dead-letter handling was off becomes a dead-letter record on its next receive.

## Operations

All take the queue's ARN.

| Operation | Effect |
|---|---|
| `ReceiveDeadLetterQueueRecords` | Reads records in the dead-letter state. Same request and response syntax as `ReceiveQueueRecords`. `WaitTimeSeconds` (1-20 seconds, default 9) sets how long the call waits for records to arrive. A record keeps its `RecordId`, `ApproximateArrivalTimestamp`, and `FirstReceiveTimestamp`, and its `ReceiveCount` includes the receives before it entered the dead-letter state. |
| `AcknowledgeDeadLetterQueueRecords` | Acknowledges dead-letter records you are finished with, so the queue never delivers them again. |
| `UpdateDeadLetterQueueRecordsVisibility` | Extends or shortens how long a received dead-letter record stays hidden. |
| `RestoreDeadLetterQueueRecords` | Takes records out of the dead-letter state, so `ReceiveQueueRecords` returns them again. |

The batch operations take 1-10 `Entries`, each a `ReceiptHandle` returned by `ReceiveDeadLetterQueueRecords` (plus `VisibilityTimeoutSeconds` for the visibility update). They report each entry as `Successful` or `Failed`; check `Failed` even when the call succeeds. Use the handle from the most recent receive, and restore or acknowledge before its visibility timeout expires, or extend it first. After that, a call with the handle can succeed without acting on the record.

## Restored records

- A restored record can be received from the same queue immediately. Existing consumers receive it through their usual `ReceiveQueueRecords` calls, with no code or configuration changes. It mixes with new traffic in no particular order.
- Its receive count restarts, so it gets the full `MaxReceiveCount` attempts again.
- Design consumers to be idempotent. Restore is at-least-once.
- Restoring before the cause is fixed sends the record through the same failures again: after `MaxReceiveCount` more unacknowledged deliveries, the next receive puts it back into the dead-letter state.

## Handling dead-letter records

Queue consumers do not process dead-letter records. Reading them takes code that calls `ReceiveDeadLetterQueueRecords`, so handle them outside the main consumer:

1. Alarm on the number of records in the dead-letter state: `VisibleDeadLetterQueueRecords`. A threshold of 0 alerts on every record set aside; ask the user whether a higher threshold fits.
2. Receive them with `ReceiveDeadLetterQueueRecords` and inspect them.
3. Fix the consumer or data issue.
4. Restore the records you want processed again. A restored record is no longer returned by `ReceiveDeadLetterQueueRecords`; if a later dead-letter receive still returns it, restore it again. Acknowledge only the records you want to discard from the queue, such as ones that can never be processed. An acknowledged record is not delivered again; it stays in the stream until its retention period ends.

The Kinesis console can also receive dead-letter records, restore the ones you want processed again, and acknowledge the ones you want to discard. There is no bulk restore operation. To restore many dead-letter records, loop receive and restore calls, restoring each batch with the receipt handles from the receive that returned it. An empty receive does not mean every record is restored: records from earlier receives stay hidden until their visibility timeout ends. Stop when `VisibleDeadLetterQueueRecords` and `InFlightDeadLetterQueueRecords` are both 0.

## Permissions

Each dead-letter operation has its own IAM action, granted separately from the queue's other actions. A consumer that only processes the queue needs none of them. Use the dead-letter handler policy in [queues-operations-and-iam.md](queues-operations-and-iam.md#dead-letter-handler).

## Metrics

Same namespace, dimensions, and statistics as the [queue metrics](queues-operations-and-iam.md#cloudwatch-metrics).

| Metric | Description |
|---|---|
| `VisibleDeadLetterQueueRecords` | Dead-letter records available to receive. The metric stops at 1,000,000, even when more are visible. |
| `InFlightDeadLetterQueueRecords` | Dead-letter records received and still within their visibility timeout: not yet acknowledged, restored, or visible again |
| `ReceivedDeadLetterQueueRecords` | Records returned by `ReceiveDeadLetterQueueRecords` |
| `EmptyDeadLetterReceives` | `ReceiveDeadLetterQueueRecords` calls that returned no records |
| `AcknowledgedDeadLetterQueueRecords` | Dead-letter records acknowledged |
| `RestoredDeadLetterQueueRecords` | Dead-letter records restored to the queue |
