# Lambda Event Sources Reference

Quick reference for Lambda event source mappings (ESMs), direct triggers, filtering, and error handling.

## Contents

- [SQS event source mapping](#sqs-event-source-mapping)
- [DynamoDB Streams triggers](#dynamodb-streams-triggers)
- [SNS subscriptions](#sns-subscriptions)
- [Event filtering](#event-filtering)
- [Partial batch failure reporting](#partial-batch-failure-reporting)
- [Error handling strategies](#error-handling-strategies)

---

## SQS event source mapping

Lambda polls SQS using long polling and invokes your function **synchronously** with a batch of messages.

### Configuration parameters

| Parameter | Default | Range / Notes |
|-----------|---------|---------------|
| `BatchSize` | 10 | Standard: max 10,000. FIFO: max 10 |
| `MaximumBatchingWindowInSeconds` | 0 | 0–300. Not supported for FIFO. Requires ≥ 1s when BatchSize > 10 |
| `MaximumConcurrency` | — | 2–1,000. Per-ESM concurrency cap |
| `ProvisionedPollerConfig.MinimumPollers` | 2 | 2–200 |
| `ProvisionedPollerConfig.MaximumPollers` | 200 | 2–2,000 |
| `FilterCriteria` | — | Filters on `body` key only |
| `FunctionResponseTypes` | — | Set to `ReportBatchItemFailures` |

> **MaximumConcurrency and Provisioned Mode are mutually exclusive.** You cannot set both on the same ESM.

### Batching behavior

Lambda invokes when **any** condition is met:

1. Batching window expires
2. Batch size reached
3. Payload reaches 6 MB

### Scaling behavior

**Standard queues:**

- Starts with **5** concurrent invocations
- Scales up by **300/min**
- Default maximum: **1,250** concurrent invocations
- Provisioned mode: up to **20,000** (scales 3× faster at 1,000/min)

**FIFO queues:**

- Concurrency capped by the **lower** of: number of message group IDs or `MaximumConcurrency`
- Messages delivered in order per message group ID

### Error handling

- Use the **SQS redrive policy** (native dead-letter queue (DLQ) on the queue) — not an ESM-level DLQ
- Set visibility timeout to **≥ 6× function timeout** to prevent premature retry
- On function error, entire batch becomes visible again after visibility timeout
- On throttle, Lambda backs off; messages reappear after visibility timeout

### SAM template

```yaml
MyFunction:
  Type: AWS::Serverless::Function
  Properties:
    Handler: index.handler
    Runtime: nodejs22.x
    Events:
      SQSEvent:
        Type: SQS
        Properties:
          Queue: !GetAtt MyQueue.Arn
          BatchSize: 10
          MaximumBatchingWindowInSeconds: 5
          FunctionResponseTypes:
            - ReportBatchItemFailures
          ScalingConfig:
            MaximumConcurrency: 50
          FilterCriteria:
            Filters:
              - Pattern: '{"body": {"status": ["PENDING"]}}'
```

### CDK example

```typescript
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import * as sqs from 'aws-cdk-lib/aws-sqs';

const dlq = new sqs.Queue(this, 'DLQ');
const queue = new sqs.Queue(this, 'MyQueue', {
  visibilityTimeout: Duration.seconds(300), // 6× function timeout
  deadLetterQueue: { queue: dlq, maxReceiveCount: 3 },
});

fn.addEventSource(new SqsEventSource(queue, {
  batchSize: 10,
  maxBatchingWindow: Duration.seconds(5),
  reportBatchItemFailures: true,
  maxConcurrency: 50,
}));
```

---

## DynamoDB Streams triggers

Lambda polls DynamoDB stream shards at **4 times per second**. Invokes synchronously with in-order processing at the partition-key level.

### Configuration parameters

| Parameter | Default | Range / Notes |
|-----------|---------|---------------|
| `BatchSize` | 100 | Max 10,000 |
| `MaximumBatchingWindowInSeconds` | 0 | 0–300 |
| `StartingPosition` | — | `TRIM_HORIZON` (recommended) or `LATEST` |
| `ParallelizationFactor` | 1 | 1–10. Concurrent batches per shard |
| `BisectBatchOnFunctionError` | false | Split failed batch in half |
| `MaximumRetryAttempts` | -1 (infinite) | 0–10,000 |
| `MaximumRecordAgeInSeconds` | -1 (infinite) | -1 to 604,800 (7 days) |
| `DestinationConfig.OnFailure` | — | SQS, SNS, S3, or Kafka topic |
| `FilterCriteria` | — | Filters on `dynamodb` key and metadata fields (e.g., `eventName`) |
| `FunctionResponseTypes` | — | `ReportBatchItemFailures` |
| `TumblingWindowInSeconds` | — | 0–900 for stateful aggregation |

### Key behaviors

- **TRIM_HORIZON** recommended — `LATEST` may miss events during ESM creation
- **Max 2 Lambda readers per shard** (single-region tables). Global tables: limit to 1
- **ParallelizationFactor**: 100 shards × factor 10 = up to 1,000 concurrent invocations. Order maintained at partition-key level
- **BisectBatchOnFunctionError** does NOT consume retry quota
- DynamoDB stream retention is **24 hours** — a poison record can block a shard for that entire window without retry limits

### SAM template

```yaml
MyFunction:
  Type: AWS::Serverless::Function
  Properties:
    Handler: index.handler
    Runtime: nodejs22.x
    Events:
      DDBStream:
        Type: DynamoDB
        Properties:
          Stream: !GetAtt MyTable.StreamArn
          StartingPosition: TRIM_HORIZON
          BatchSize: 100
          MaximumBatchingWindowInSeconds: 5
          ParallelizationFactor: 5
          BisectBatchOnFunctionError: true
          MaximumRetryAttempts: 3
          MaximumRecordAgeInSeconds: 3600
          FunctionResponseTypes:
            - ReportBatchItemFailures
          DestinationConfig:
            OnFailure:
              Destination: !GetAtt FailureQueue.Arn
          FilterCriteria:
            Filters:
              - Pattern: '{"eventName": ["INSERT"]}'
```

### CDK example

```typescript
import { DynamoEventSource, SqsDlq } from 'aws-cdk-lib/aws-lambda-event-sources';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';

const table = new dynamodb.Table(this, 'MyTable', {
  partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
  stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
});

fn.addEventSource(new DynamoEventSource(table, {
  startingPosition: lambda.StartingPosition.TRIM_HORIZON,
  batchSize: 100,
  maxBatchingWindow: Duration.seconds(5),
  parallelizationFactor: 5,
  bisectBatchOnError: true,
  retryAttempts: 3,
  maxRecordAge: Duration.hours(1),
  reportBatchItemFailures: true,
  onFailure: new SqsDlq(dlq),
}));
```

---

## SNS subscriptions

SNS invokes Lambda **asynchronously** — it is a **direct trigger, NOT an event source mapping**. No polling involved; SNS pushes events to Lambda.

### Key characteristics

- **Standard topics only** (not FIFO)
- At-least-once delivery — make functions idempotent
- SNS retries at increasing intervals over several hours if Lambda is unreachable
- Cross-account subscriptions supported

### Filter policies

Filter policies are managed by **SNS** (not Lambda `FilterCriteria`). Set `FilterPolicyScope` to control what is filtered:

| Scope | Filters on |
|-------|-----------|
| `MessageAttributes` (default) | SNS message attributes |
| `MessageBody` | JSON body content |

```json
{
  "event_type": ["order_placed"],
  "price_usd": [{"numeric": [">=", 100]}],
  "store": [{"anything-but": "test_store"}]
}
```

### SAM template

```yaml
ProcessorFunction:
  Type: AWS::Serverless::Function
  Properties:
    Handler: processor.handler
    Runtime: nodejs22.x
    Events:
      SNSEvent:
        Type: SNS
        Properties:
          Topic: !Ref MyTopic
          FilterPolicy:
            event_type:
              - order_placed
          FilterPolicyScope: MessageAttributes
```

### CDK example

```typescript
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';

topic.addSubscription(new subscriptions.LambdaSubscription(fn, {
  filterPolicy: {
    event_type: sns.SubscriptionFilter.stringFilter({
      allowlist: ['order_placed'],
    }),
    price: sns.SubscriptionFilter.numericFilter({
      greaterThanOrEqualTo: 100,
    }),
  },
}));
```

---

## Event filtering

Lambda `FilterCriteria` applies to event source mappings only (not SNS or other push triggers).

### Supported sources and filter keys

| Source | Filter key | Notes |
|--------|-----------|-------|
| SQS | `body` | Unmatched messages **automatically deleted** |
| DynamoDB Streams | `dynamodb` and metadata fields | Does **NOT** support numeric operators |
| Kinesis | `data` | Base64-decoded before filtering |
| MSK / Kafka | `value` | — |
| Amazon MQ | `data` | — |

### Filter rules

- Up to **5 filters** per ESM (can request increase to 10)
- Multiple filters are **ORed** — record matches if any filter matches
- Fields within a single filter are **ANDed**

### Filter rule operators

| Operator | Syntax | Example |
|----------|--------|---------|
| Equals | `["value"]` | `"City": ["Seattle"]` |
| Equals (ignore case) | `[{"equals-ignore-case": "value"}]` | `"City": [{"equals-ignore-case": "seattle"}]` |
| Null | `[null]` | `"UserID": [null]` |
| Empty | `[""]` | `"Name": [""]` |
| Not | `[{"anything-but": ["value"]}]` | `"Weather": [{"anything-but": ["Raining"]}]` |
| Numeric equals | `[{"numeric": ["=", 100]}]` | `"Price": [{"numeric": ["=", 100]}]` |
| Numeric range | `[{"numeric": [">", 10, "<=", 20]}]` | `"Price": [{"numeric": [">", 10, "<=", 20]}]` |
| Exists | `[{"exists": true}]` | `"Field": [{"exists": true}]` |
| Prefix | `[{"prefix": "us-"}]` | `"Region": [{"prefix": "us-"}]` |
| Suffix | `[{"suffix": ".png"}]` | `"FileName": [{"suffix": ".png"}]` |
| Or (fields) | `"$or": [{...}, {...}]` | `"$or": [{"City": ["NY"]}, {"Day": ["Mon"]}]` |

> **DynamoDB filtering does NOT support numeric operators.** Numbers are stored as strings in the DynamoDB JSON record.

### Body/data format matching

| Incoming format | Filter format | Result |
|----------------|---------------|--------|
| Plain string | Plain string | Filters normally |
| Plain string | Valid JSON | Lambda drops the message |
| Valid JSON | Plain string | Lambda drops the message |
| Valid JSON | Valid JSON | Filters normally |

### Filter examples

```yaml
# SQS — filter on body field
FilterCriteria:
  Filters:
    - Pattern: '{"body": {"RequestCode": ["BBBB"]}}'

# DynamoDB — INSERT events only
FilterCriteria:
  Filters:
    - Pattern: '{"eventName": ["INSERT"]}'

# DynamoDB — filter by NewImage attribute
FilterCriteria:
  Filters:
    - Pattern: '{"dynamodb": {"NewImage": {"status": {"S": ["ACTIVE"]}}}}'

# Kinesis — filter decoded data
FilterCriteria:
  Filters:
    - Pattern: '{"data": {"status": ["ACTIVE"]}}'
```

---

## Partial batch failure reporting

Enable by setting `FunctionResponseTypes` to `["ReportBatchItemFailures"]`.

### SQS — return failed messageId values

```javascript
export const handler = async (event) => {
  const batchItemFailures = [];
  for (const record of event.Records) {
    try {
      await processMessage(record);
    } catch (error) {
      batchItemFailures.push({ itemIdentifier: record.messageId });
    }
  }
  return { batchItemFailures };
};
```

### Streams — return failed SequenceNumber values

For DynamoDB Streams and Kinesis, Lambda uses the **lowest sequence number** as the checkpoint and retries everything from that point.

```javascript
export const handler = async (event) => {
  for (const record of event.Records) {
    try {
      await processRecord(record);
    } catch (e) {
      return {
        batchItemFailures: [
          { itemIdentifier: record.dynamodb.SequenceNumber },
          // Kinesis: { itemIdentifier: record.kinesis.sequenceNumber }
        ],
      };
    }
  }
  return { batchItemFailures: [] };
};
```

### Python with Powertools Batch Processor

```python
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor, EventType, process_partial_response,
)

processor = BatchProcessor(event_type=EventType.SQS)

def record_handler(record):
    payload = record.body
    # process payload...

def lambda_handler(event, context):
    return process_partial_response(
        event=event, record_handler=record_handler,
        processor=processor, context=context,
    )
```

### FIFO queue behavior

- **Stop processing after the first failure**
- Return all failed and unprocessed messages in `batchItemFailures`
- This preserves message ordering within the group

### Success/failure conditions

| Response | Interpretation |
|----------|---------------|
| Empty `batchItemFailures` list | Complete success |
| Null `batchItemFailures` or empty `EventResponse` | Complete success |
| `itemIdentifier` is empty string or null | **Complete failure** (entire batch retried) |
| Bad key name in `itemIdentifier` | **Complete failure** |
| Unhandled exception | **Complete failure** |

### Interaction with BisectBatchOnFunctionError (streams)

- Function **errors** (unhandled exception): `BisectBatchOnFunctionError` splits the batch in half for retry. `ReportBatchItemFailures` has no effect since no response was returned.
- Function **succeeds** with `batchItemFailures`: Lambda checkpoints at the lowest failed sequence number and retries from that point. If `BisectBatchOnFunctionError` is also enabled, the batch is bisected at the returned sequence number.

---

## Error handling strategies

### SQS

| Strategy | Configuration | When to use |
|----------|--------------|-------------|
| SQS redrive policy (DLQ) | `maxReceiveCount` on the queue | Always — catches poison messages |
| Partial batch failures | `ReportBatchItemFailures` | Batches with mix of good/bad messages |
| Visibility timeout | Set to ≥ 6× function timeout | Always — prevents premature retry |
| MaximumConcurrency | `ScalingConfig` on ESM | Protect downstream resources |

### DynamoDB Streams / Kinesis

| Strategy | Configuration | When to use |
|----------|--------------|-------------|
| BisectBatchOnFunctionError | `true` | Isolate bad records in large batches |
| Partial batch failures | `ReportBatchItemFailures` | Avoid reprocessing successful records |
| Maximum retry attempts | `MaximumRetryAttempts` | Limit retries to prevent shard blocking |
| Maximum record age | `MaximumRecordAgeInSeconds` | Skip stale records |
| On-failure destination | `DestinationConfig.OnFailure` | Capture failed records for analysis |
| Parallelization factor | `ParallelizationFactor` | Reduce blast radius per shard |

### ESM (polling) vs direct trigger (push)

| Aspect | ESM (SQS, DDB, Kinesis) | Async push (SNS, S3) | Sync push (API Gateway) |
|--------|--------------------------|----------------------|-------------------------|
| Invocation | Synchronous (Lambda polls) | Asynchronous (service pushes) | Synchronous (service pushes) |
| Batching | Yes (configurable) | No (single event) | No (single event) |
| Event filtering | Lambda `FilterCriteria` | SNS filter policies (SNS-managed) | N/A |
| Error handling | Partial batch, bisect, retry config | 2 automatic retries, DLQ/destination | Error returned directly to caller, no automatic retry |
| Ordering | Supported (streams, FIFO) | Not guaranteed | N/A (request/response) |

### Concurrency formulas

```
SQS (default):     min(1250, MaximumConcurrency, ReservedConcurrency)
SQS (provisioned):  MaximumPollers × 10
DDB/Kinesis:        number_of_shards × ParallelizationFactor
```

### Idempotency

All event sources deliver at least once — duplicates can occur. Use Powertools idempotency utility:

```python
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor, EventType, process_partial_response,
)
from aws_lambda_powertools.utilities.idempotency import (
    IdempotencyConfig, DynamoDBPersistenceLayer, idempotent_function,
)

processor = BatchProcessor(event_type=EventType.SQS)
persistence_layer = DynamoDBPersistenceLayer(table_name="IdempotencyTable")
config = IdempotencyConfig(event_key_jmespath="messageId")

@idempotent_function(config=config, persistence_store=persistence_layer, data_keyword_argument="record")
def record_handler(record):
    # process record...
    pass

def lambda_handler(event, context):
    return process_partial_response(
        event=event, record_handler=record_handler,
        processor=processor, context=context,
    )
```
