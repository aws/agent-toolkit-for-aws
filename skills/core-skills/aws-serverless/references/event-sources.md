# Lambda Event Sources Reference

Event source mapping (ESM) config parameters, scaling numbers, and filtering gotchas. Assumes you know the basics (SNS pushes asynchronously and is a direct trigger not an ESM; `ReportBatchItemFailures` returns `{batchItemFailures: [{itemIdentifier}]}`; unmatched SQS filter messages are permanently deleted; SQS visibility timeout ≥ 6× function timeout) — this file focuses on the exact values and edge cases.

## Contents

- [SQS event source mapping](#sqs-event-source-mapping)
- [DynamoDB Streams triggers](#dynamodb-streams-triggers)
- [Event filtering](#event-filtering)
- [Partial batch failure reporting](#partial-batch-failure-reporting)
- [Error handling and concurrency](#error-handling-and-concurrency)

---

## SQS event source mapping

Lambda long-polls SQS and invokes your function **synchronously** with a batch.

| Parameter | Default | Range / Notes |
|-----------|---------|---------------|
| `BatchSize` | 10 | Standard: max 10,000. FIFO: max 10 |
| `MaximumBatchingWindowInSeconds` | 0 | 0–300. Not for FIFO. Requires ≥ 1s when BatchSize > 10 |
| `MaximumConcurrency` | — | 2–1,000. Per-ESM cap |
| `ProvisionedPollerConfig.MinimumPollers` | 2 | 2–200 |
| `ProvisionedPollerConfig.MaximumPollers` | 200 | 1–2,000 |
| `FilterCriteria` | — | Filters on `body` key only |
| `FunctionResponseTypes` | — | Set to `ReportBatchItemFailures` |

> **MaximumConcurrency and Provisioned Mode are mutually exclusive** on the same ESM.

Lambda invokes when **any** of: batching window expires, batch size reached, or payload hits 6 MB.

### Scaling

**Standard queues:** concurrency **starts at 5** concurrent invocations and scales up by **~300 per minute** to a **default maximum of 1,250** — so a sudden burst (e.g. a backlog of 10,000 messages) is not absorbed immediately; it takes several minutes to ramp. For high scale-out or high-throughput workloads, use **Provisioned Mode**, which starts higher, ramps significantly faster, and reaches a much larger ceiling. The 1,250 default is also bounded by account concurrency; confirm current account limits with `aws service-quotas get-service-quota --service-code lambda`.

**FIFO queues:** concurrency capped by the **lower** of (number of message group IDs, `MaximumConcurrency`); order preserved per group ID.

```yaml
# SAM
Events:
  SQSEvent:
    Type: SQS
    Properties:
      Queue: !GetAtt MyQueue.Arn
      BatchSize: 10
      MaximumBatchingWindowInSeconds: 5
      FunctionResponseTypes: [ReportBatchItemFailures]
      ScalingConfig:
        MaximumConcurrency: 50
      FilterCriteria:
        Filters:
          - Pattern: '{"body": {"status": ["PENDING"]}}'
```

CDK: `fn.addEventSource(new SqsEventSource(queue, { batchSize, maxBatchingWindow, reportBatchItemFailures: true, maxConcurrency }))`. Harden the queue: `new sqs.Queue(this, 'MyQueue', { encryption: sqs.QueueEncryption.SQS_MANAGED, enforceSSL: true, ... })` (set the same on the DLQ).

---

## DynamoDB Streams triggers

Lambda polls stream shards **4×/second**; invokes synchronously, in-order per partition key.

| Parameter | Default | Range / Notes |
|-----------|---------|---------------|
| `BatchSize` | 100 | Max 10,000 |
| `StartingPosition` | — | `TRIM_HORIZON` (recommended) or `LATEST` |
| `ParallelizationFactor` | 1 | 1–10. Concurrent batches per shard |
| `BisectBatchOnFunctionError` | false | Split failed batch in half; does NOT consume retry quota |
| `MaximumRetryAttempts` | -1 (infinite) | 0–10,000 |
| `MaximumRecordAgeInSeconds` | -1 (infinite) | -1 (infinite), or 60–604,800 (7 days); 0–59 rejected |
| `DestinationConfig.OnFailure` | — | SQS, SNS, S3, or Kafka topic |
| `TumblingWindowInSeconds` | — | 0–900, for stateful aggregation |

### Key behaviors

- **Max 2 Lambda readers per shard** (single-region tables). Global tables: limit to **1**.
- **TRIM_HORIZON** recommended — `LATEST` may miss events during ESM creation.
- 100 shards × ParallelizationFactor 10 = up to **1,000 concurrent invocations** (order maintained at partition-key level).
- **Stream retention is 24 hours** — a poison record can block a shard for that entire window if retries aren't bounded. Set `MaximumRetryAttempts` / `MaximumRecordAgeInSeconds` / `BisectBatchOnFunctionError`.

```yaml
# SAM
Events:
  DynamoDBStream:
    Type: DynamoDB
    Properties:
      Stream: !GetAtt MyTable.StreamArn
      StartingPosition: TRIM_HORIZON
      ParallelizationFactor: 5
      BisectBatchOnFunctionError: true
      MaximumRetryAttempts: 3
      FunctionResponseTypes: [ReportBatchItemFailures]
      DestinationConfig:
        OnFailure:
          Destination: !GetAtt FailureQueue.Arn
```

Encrypt the source table at rest — CDK `new dynamodb.Table(this, 'MyTable', { encryption: dynamodb.TableEncryption.AWS_MANAGED, ... })`, or a customer managed KMS key when compliance requires key control.

SNS filter policies (not Lambda `FilterCriteria`) are SNS-managed; set `FilterPolicyScope` to `MessageAttributes` (default) or `MessageBody`.

---

## Event filtering

`FilterCriteria` applies to ESMs only (not SNS/push triggers).

| Source | Filter key | Notes |
|--------|-----------|-------|
| SQS | `body` | Unmatched messages **automatically (permanently) deleted** |
| DynamoDB Streams | `dynamodb` + metadata (e.g. `eventName`) | **Does NOT support numeric operators** |
| Kinesis | `data` | Base64-decoded before filtering |
| MSK / Kafka | `value` | — |

- Up to **5 filters** per ESM (request increase to 10). Multiple filters are **OR**'d; fields within one filter are **AND**'d.
- **DynamoDB numeric filtering is unsupported** — numbers are stored as strings in the DynamoDB stream JSON. Use `{"S": [...]}`/`{"N": ["123"]}` string matches, not `{"numeric": [...]}`.
- Format mismatch drops the record: if the incoming body is plain string but the filter is JSON (or vice versa), Lambda drops the message.

Operators: `["value"]`, `{"equals-ignore-case"}`, `[null]`, `[""]`, `{"anything-but"}`, `{"numeric": [">", 10, "<=", 20]}`, `{"exists": true}`, `{"prefix"}`, `{"suffix"}`, `"$or": [...]`.

```yaml
# DynamoDB — INSERT events only / by NewImage attribute (string match, not numeric)
FilterCriteria:
  Filters:
    - Pattern: '{"eventName": ["INSERT"]}'
    - Pattern: '{"dynamodb": {"NewImage": {"status": {"S": ["ACTIVE"]}}}}'
```

---

## Partial batch failure reporting

Set `FunctionResponseTypes: [ReportBatchItemFailures]` and return the failed identifiers.

- **SQS:** return failed `messageId` values in `batchItemFailures`.
- **Streams (DynamoDB/Kinesis):** return the failed `SequenceNumber`; Lambda checkpoints at the **lowest** returned sequence number and retries everything from that point.
- **FIFO:** stop after the first failure; return that message plus all unprocessed ones (preserves ordering).

Response edge cases that cause a **complete batch retry**: `itemIdentifier` empty/null, a bad key name, or any unhandled exception. An empty/null `batchItemFailures` = complete success.

Streams interaction: an unhandled **exception** triggers `BisectBatchOnFunctionError` (no response returned, so `ReportBatchItemFailures` has no effect); a **success with `batchItemFailures`** checkpoints at the lowest failed sequence number.

The Powertools Batch Processor (`process_partial_response`) handles all of this — prefer it over hand-rolled loops. See [assets/powertools-handler.py](../assets/powertools-handler.py).

---

## Error handling and concurrency

| Source | Key strategies |
|--------|---------------|
| SQS | Redrive policy / DLQ (`maxReceiveCount`) always; `ReportBatchItemFailures`; visibility ≥ 6× timeout; `MaximumConcurrency` to protect downstream |
| DynamoDB/Kinesis | `BisectBatchOnFunctionError`; `ReportBatchItemFailures`; `MaximumRetryAttempts` + `MaximumRecordAgeInSeconds` (prevent shard blocking); `OnFailure` destination; `ParallelizationFactor` to reduce blast radius |

### Concurrency formulas

```
SQS (default):     min(1250, MaximumConcurrency, ReservedConcurrency)
SQS (provisioned):  MaximumPollers × 10
DynamoDB/Kinesis:   number_of_shards × ParallelizationFactor
```

### Idempotency

All event sources deliver at-least-once — duplicates happen. Make handlers idempotent (Powertools Idempotency utility, keyed e.g. on SQS `messageId`). See [production.md](production.md#idempotency).
