# Code samples: first calls against a new custom event bus

Load this when writing the first CLI or SDK call: creating a bus and a subscriber, publishing with either
API, replaying from history, granting cross-account access, or checking per-entry results. Each sample
uses only fields the service requires plus the ones the skill body tells you to always set. The
CloudFormation form of the same setup is in [infrastructure-as-code.md](infrastructure-as-code.md).

## Create a bus and a subscriber (CLI)

A bus, the waiter (chapter 15), and one SQS-targeted subscriber with a filter and a dead-letter queue
(chapters 7, 9, and 12):

```bash
BUS_ARN=$(aws eventbridgev2 create-event-bus --name my-bus --query EventBusArn --output text)
aws eventbridgev2 wait event-bus-active --event-bus-arn "$BUS_ARN"

aws eventbridgev2 create-subscriber --name orders-to-queue \
  --event-bus-arn "$BUS_ARN" \
  --filter-configuration '{"Filters":[{"Scope":"DATA","Pattern":"{\"detail\":{\"orderId\":[{\"exists\":true}]}}"}]}' \
  --invoke-configuration '{"TargetArn":"arn:aws:sqs:us-east-1:111122223333:my-queue","RoleArn":"arn:aws:iam::111122223333:role/my-delivery-role"}' \
  --on-failure-configuration '{"Arn":"arn:aws:sqs:us-east-1:111122223333:my-dlq"}'
```

You SHOULD allow a short delay after the subscriber is created before publishing, because otherwise
the first
event can be missed (see [provisioning-and-state.md](provisioning-and-state.md)). The delivery role needs
`sqs:SendMessage` on both the queue and the dead-letter queue (chapter 13). No `SqsParameters` block
appears above because a standard queue needs none of its members; only a universal target requires a
parameter block of its own (chapter 9).

## Create a subscriber that reads history (CLI)

`StartingPosition` is a plain enum, `LATEST` or `POINT_IN_TIME`; the point itself goes in the separate
`PointInTimeConfiguration` member (chapter 17). So `--starting-position` takes the bare enum value, with
no JSON wrapper:

```bash
aws eventbridgev2 create-subscriber --name orders-replay \
  --event-bus-arn "$BUS_ARN" \
  --starting-position POINT_IN_TIME \
  --point-in-time-configuration '{"PointType":"HORIZON"}' \
  --invoke-configuration '{"TargetArn":"arn:aws:sqs:us-east-1:111122223333:my-queue","RoleArn":"arn:aws:iam::111122223333:role/my-delivery-role"}'
```

`{"PointType":"TIMESTAMP","StartingPoint":1756605600}` starts from a timestamp instead; `StartingPoint`
is epoch seconds (chapter 17). No `--filter-configuration` appears above because it is optional on
create; an unfiltered subscriber receives every event on the bus (see
[filters-and-expressions.md](filters-and-expressions.md)).

## Point a subscriber at each target type (CLI)

Each shape below is the `--invoke-configuration` for one target type, with the delivery-role action it
needs (chapter 13). At most one parameter block, and only a universal target requires its own
(chapter 9). Per-target delivery behaviour and traps are in
[target-configuration.md](target-configuration.md).

SNS topic. The role needs `sns:Publish`; no parameter block; a `RAW` transformer delivers the payload
alone to the topic's subscribers:

```
'{"TargetArn":"arn:aws:sns:us-east-1:111122223333:my-topic","RoleArn":"'"$ROLE_ARN"'"}'
```

Lambda function. The role needs `lambda:InvokeFunction`. **The function receives a JSON array of
events, a batch, not a single event object**, so you MUST write the handler for a list:

```
'{"TargetArn":"arn:aws:lambda:us-east-1:111122223333:function:my-fn","RoleArn":"'"$ROLE_ARN"'"}'
```

Kinesis stream. The role needs `kinesis:PutRecords`; `KinesisParameters` may be omitted, and
`PartitionKey` accepts a JSONata expression, which it should, being per-message (chapter 9, rule 2):

```
'{"TargetArn":"arn:aws:kinesis:us-east-1:111122223333:stream/my-stream","RoleArn":"'"$ROLE_ARN"'","KinesisParameters":{"PartitionKey":"{% $events.Data.detail.orderId %}"}}'
```

Step Functions state machine. The role needs `states:StartExecution`:

```
'{"TargetArn":"arn:aws:states:us-east-1:111122223333:stateMachine:my-machine","RoleArn":"'"$ROLE_ARN"'"}'
```

Another new custom event bus. The role needs **both** `events:PutEvents` and `events:PutRawEvents`,
because the action is chosen per forwarded event (see [authorization.md](authorization.md)):

```
'{"TargetArn":"arn:aws:events:us-east-1:111122223333:event-busv2/dest-bus/exampleid0123456789abcdef","RoleArn":"'"$ROLE_ARN"'"}'
```

Universal target, here Step Functions' `startExecution` called directly. The parameter block and
`BatchConfiguration` are required, and the field names inside `Input` are PascalCase Smithy member
names, `StateMachineArn` not `stateMachineArn` (chapter 10):

```
'{"TargetArn":"arn:aws:events:::aws-sdk:sfn:startExecution","RoleArn":"'"$ROLE_ARN"'","UniversalTargetParameters":{"Input":"{\"StateMachineArn\":\"arn:aws:states:us-east-1:111122223333:stateMachine:my-machine\",\"Input\":\"{}\"}"},"BatchConfiguration":{"MaxBatchSize":1,"MaxBatchWindowInSeconds":0}}'
```

A worked universal `dynamodb:putItem` with a JSONata `Input` is in
[target-configuration.md](target-configuration.md). HTTP targets take either an API Gateway
`execute-api` ARN or an EventBridge API destination ARN, with `HttpParameters`; see
[target-configuration.md](target-configuration.md).

## Grant another account access (CLI)

Share the bus through AWS RAM where possible; the managed permission names are in
[security-and-sharing.md](security-and-sharing.md). For a hand-written grant, the operation is
`put-resource-policy`, and the request names the bus through `--resource-arn` and the policy through
`--policy-document`:

```bash
aws eventbridgev2 put-resource-policy \
  --resource-arn "$BUS_ARN" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Sid": "AllowConsumerSubscribe",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::444455556666:root"},
      "Action": ["events:CreateSubscriber", "events:DescribeEventBus"],
      "Resource": "'"$BUS_ARN"'"
    }]
  }'
```

Omitting `--policy-name` writes the customer-managed `default` policy; the `AWS_RAM` policy is written
only by RAM. The principal must be a real account, and the actions use the `events:` namespace, never
`eventbridgev2:` (see [authorization.md](authorization.md)).

## Publish with either API (CLI)

The `DATA` filter above matches `PutEvents` traffic, whose payload sits under `detail` (chapter 6). The
raw publish carries its payload at the top of `Data`, so it does not match that filter. The samples below
leave that mismatch in place, so both payload shapes stay visible. `Data` is base64, and the
base64 below decodes to `{"orderId":"123"}`:

```bash
aws eventbridgev2 put-events --event-bus-arn "$BUS_ARN" --entries '[{
  "Source": "com.example.orders",
  "DetailType": "OrderPlaced",
  "Detail": "{\"orderId\":\"123\"}"
}]'

aws eventbridgev2 put-raw-events --event-bus-arn "$BUS_ARN" --entries '[{
  "Data": "eyJvcmRlcklkIjoiMTIzIn0=",
  "SystemMetadata": { "ContentType": "application/json" }
}]'
```

## Publish from an SDK, checking per-entry results

The client name is `eventbridgev2` in every language, and the class name is `EventBridgeV2Client`. The
publish call can succeed while individual entries fail,
so you MUST check every entry (chapter 21). Results align with the request entries by index, and
`FailedEntryCount` can be absent on a fully successful publish, so you SHOULD null-check it rather than
assume zero. `SuccessCode: DEDUPLICATED` is a success, not an error (chapter 5), so you MUST NOT count
successes as new events, because a deduplicated entry was not newly ingested.

Python:

```python
import boto3, json

events = boto3.client("eventbridgev2")
response = events.put_events(
    EventBusArn=bus_arn,
    Entries=[{
        "Source": "com.example.orders",
        "DetailType": "OrderPlaced",
        "Detail": json.dumps({"orderId": "123"}),
    }],
)
failed = [entry for entry in response["Entries"] if entry.get("ErrorCode")]
```

Java (AWS SDK for Java v2; the client is `EventBridgeV2Client` in
`software.amazon.awssdk.services.eventbridgev2`):

```java
import java.util.List;

import software.amazon.awssdk.services.eventbridgev2.EventBridgeV2Client;
import software.amazon.awssdk.services.eventbridgev2.model.PutEventsRequest;
import software.amazon.awssdk.services.eventbridgev2.model.PutEventsRequestEntry;
import software.amazon.awssdk.services.eventbridgev2.model.PutEventsResponse;
import software.amazon.awssdk.services.eventbridgev2.model.PutEventsResultEntry;

EventBridgeV2Client events = EventBridgeV2Client.create();
PutEventsResponse response = events.putEvents(PutEventsRequest.builder()
        .eventBusArn(busArn)
        .entries(PutEventsRequestEntry.builder()
                .source("com.example.orders")
                .detailType("OrderPlaced")
                .detail("{\"orderId\":\"123\"}")
                .build())
        .build());
List<PutEventsResultEntry> failed = response.entries().stream()
        .filter(entry -> entry.errorCode() != null)
        .toList();
```

TypeScript (AWS SDK for JavaScript v3; the package name follows the service id, so the client ships as
`@aws-sdk/client-eventbridgev2`):

```typescript
import { EventBridgeV2Client, PutEventsCommand } from "@aws-sdk/client-eventbridgev2";

const events = new EventBridgeV2Client({ region: "us-east-1" });
const response = await events.send(new PutEventsCommand({
  EventBusArn: busArn,
  Entries: [{
    Source: "com.example.orders",
    DetailType: "OrderPlaced",
    Detail: JSON.stringify({ orderId: "123" }),
  }],
}));
const failed = (response.Entries ?? []).filter((entry) => entry.ErrorCode);
```

## Publish binary with an SDK: raw bytes, not base64

`Data` is a blob. **An SDK takes the raw bytes and does the wire encoding itself; base64 is only the
CLI's text form of a blob.** You MUST NOT base64-encode bytes before handing them to an SDK, because they
are then delivered as base64 text rather than your payload, with no error anywhere. An Avro publish also
carries the schema-registry configuration at the request level (see
[schema-registries.md](schema-registries.md)).

Python:

```python
response = events.put_raw_events(
    EventBusArn=bus_arn,
    Entries=[{
        "Data": avro_bytes,  # raw bytes; boto3 encodes the wire form
        "SystemMetadata": {"ContentType": "application/avro"},
    }],
    SchemaRegistryConfiguration={"RegistryUri": glue_registry_arn},
)
```

Java, where the raw-bytes form is `SdkBytes.fromByteArray`:

```java
import software.amazon.awssdk.core.SdkBytes;
import software.amazon.awssdk.services.eventbridgev2.model.PutRawEventsRequest;
import software.amazon.awssdk.services.eventbridgev2.model.PutRawEventsRequestEntry;
import software.amazon.awssdk.services.eventbridgev2.model.PutRawEventsSystemMetadata;
import software.amazon.awssdk.services.eventbridgev2.model.SchemaRegistryConfiguration;

events.putRawEvents(PutRawEventsRequest.builder()
        .eventBusArn(busArn)
        .entries(PutRawEventsRequestEntry.builder()
                .data(SdkBytes.fromByteArray(avroBytes))
                .systemMetadata(PutRawEventsSystemMetadata.builder()
                        .contentType("application/avro")
                        .build())
                .build())
        .schemaRegistryConfiguration(SchemaRegistryConfiguration.builder()
                .registryUri(glueRegistryArn)
                .build())
        .build());
```

## Create a subscriber and wait from an SDK

The same create as the CLI form above, plus the waiter. `EventBusActive` and `EventBusDeleted` are
modelled waiters, so every SDK generates them (chapter 15). In Python:

```python
bus_arn = events.create_event_bus(Name="my-bus")["EventBusArn"]
events.get_waiter("event_bus_active").wait(EventBusArn=bus_arn)

subscriber_arn = events.create_subscriber(
    Name="orders-to-queue",
    EventBusArn=bus_arn,
    FilterConfiguration={"Filters": [{
        "Scope": "DATA",
        "Pattern": '{"detail":{"orderId":[{"exists":true}]}}',
    }]},
    InvokeConfiguration={"TargetArn": queue_arn, "RoleArn": role_arn},
    OnFailureConfiguration={"Arn": dlq_arn},
)["SubscriberArn"]
```

You SHOULD read the subscriber back with `describe_subscriber` to confirm `OnFailureConfiguration` and
`LogConfiguration` stored what you sent, because the create response does not prove it (chapter 16).

## Back off on ThrottlingException

Publishing is throttled per account across both publish APIs (chapter 23), and `ThrottlingException`
is retryable (chapter 21). The SDK's built-in retries absorb short bursts; when they are exhausted, you
SHOULD retry with exponential backoff and jitter rather than immediately, because retrying immediately
keeps hitting the same limit:

```python
import random, time
from botocore.exceptions import ClientError

def publish_with_backoff(entries, attempts=5):
    delay = 0.2
    for attempt in range(attempts):
        try:
            return events.put_events(EventBusArn=bus_arn, Entries=entries)
        except ClientError as error:
            if error.response["Error"]["Code"] != "ThrottlingException" or attempt == attempts - 1:
                raise
            time.sleep(delay + random.uniform(0, delay))
            delay *= 2
```

If you are steadily at the ceiling, raise the account quota instead of retrying harder
(see [cost-and-quotas.md](cost-and-quotas.md)).

## Verify the delivery

You SHOULD read the queue and delete what you read, because otherwise counts lie to you. The full
test-rig sequence is in [delivery-troubleshooting.md](delivery-troubleshooting.md).
