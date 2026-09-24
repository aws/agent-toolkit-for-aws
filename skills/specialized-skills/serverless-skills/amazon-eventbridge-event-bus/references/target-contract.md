# The subscriber target contract

Load this before writing any `CreateSubscriber` or `UpdateSubscriber` call. It answers four
questions: which fields you must supply, which fields the target service requires at delivery,
when a literal is checked and when it is not, and how a delivery failure is reported.

`target-configuration.md` is the shorter companion: it gives the per-target parameter block and the
five rules. This file gives the contract those rules come from, with one working example per target
type.

---

## 1. Who validates what, and when

Three layers check a subscriber, in this order. Knowing which layer owns a check tells you where a
mistake will surface.

**Layer 1, the model.** Shapes, lengths, patterns, and `@required` members. It runs before any
service code. It is deliberately narrow about targets: `TargetArn` is typed as a
service-neutral ARN (`^arn:aws(-[a-z0-9]+)*:[^\s]+$`, 1 to 1600 characters), because the supported
target services use different resource separators. So the model never rejects a target for being the
wrong kind of resource.

**Layer 2, the service, before the subscriber is stored.** This is where the service checks the
invariants **it** owns. It resolves a target type from the ARN, then applies the rules it needs in
order to route, to build a request at all, and to protect itself. Every failure here is an
`InvalidInputException` naming the member, and nothing is persisted.

**Layer 3, the target service, at delivery.** Existence, reachability, authorization, value ranges,
identifier grammars and lengths, sizes, and required fields of the target's own API.

The line between layer 2 and layer 3 is one rule, and it is narrower than it looks:

> **Layer 2 checks only what the service itself needs, plus generous anti-abuse ceilings. It does not
> hold a second copy of the target API's parameter grammar.** Anything belonging to the target — its
> ranges, its identifier rules, its vocabularies — is checked by the target, when it is invoked.

That boundary is deliberate. A rule the service copies from a target is enforced twice, and the two
copies drift: when the target widens a rule, the copy rejects a value the target would have accepted,
and the customer gets an error for a request that was fine. So the copy is not made.

Three consequences follow, and all three are common surprises.

1. **A target ARN is checked for shape, type, region, partition and account, never for existence.** A
   well-formed ARN naming a queue that does not exist is accepted, and becomes a delivery-time
   failure. A wrong region or partition is a different matter and is rejected at create:
   `TargetArn must be in region us-east-1`, `TargetArn must be in partition aws`. Only a new-custom-bus and a
   universal target are exempt from the region check.
2. **A JSONata expression is checked for syntax, not for its result.** Create-time acceptance of an
   expression is no evidence it is correct; it is not evaluated until an event arrives.
3. **A value the target will reject is accepted in either form.** A `DelaySeconds` of `999999` and of
   `{% 999999 %}` are both stored, and SQS rejects both at delivery with a 400
   `InvalidParameterValue`. The accepted range is SQS's, so the service does not carry it. The same
   holds for a member the target *requires* and you omitted, and for one the target does not accept
   on the resource you named: as long as the SDK can serialize what you sent, the service forwards
   it and the target decides.

### What layer 2 actually checks

Resolved from the ARN's service and resource type, so this list is also the set of supported targets:

| Target ARN | Type | Parameter block |
|---|---|---|
| `arn:{p}:sqs:{r}:{a}:{queueName}` | SQS | `SqsParameters` |
| `arn:{p}:sns:{r}:{a}:{topicName}` | SNS | `SnsParameters` |
| `arn:{p}:lambda:{r}:{a}:function:{name}[:{qualifier}]` | Lambda | `LambdaParameters` |
| `arn:{p}:kinesis:{r}:{a}:stream/{name}` | Kinesis | `KinesisParameters` |
| `arn:{p}:states:{r}:{a}:stateMachine:{name}[:{version}]` | Step Functions | `StepFunctionsParameters` |
| `arn:{p}:firehose:{r}:{a}:deliverystream/{name}` | Firehose | none permitted |
| `arn:{p}:execute-api:{r}:{a}:{apiId}/{stage}/{method}[/{path}]` | API Gateway | `HttpParameters` |
| `arn:{p}:events:{r}:{a}:api-destination/{name}/{id}` | API destination | `HttpParameters` |
| `arn:{p}:events:{r}:{a}:event-busv2/{name}/{id}` | new custom bus | `EventBusV2Parameters` |
| `arn:{p}:events:{r}:{a}:event-bus/{name}` | classic bus | none permitted |

An ARN whose service is not in that table is rejected with
`InvokeConfiguration.TargetArn: TargetArn is not a supported subscriber target`. A recognised service
whose resource part has the wrong shape names the shape it wanted instead, for example
`InvokeConfiguration.TargetArn: TargetArn resource must be of the form stream/{name}`. Each form's
delimiter is pinned, so `deliverystream:name` is rejected where `deliverystream/{name}` is required, and
a form written without `[:{qualifier}]` rejects a trailing element.

**Those shape rules are structural only, and no character is reserved.** A queue named `queue?name` or
`queue*name` is accepted, because the resource part carries neither `/` nor `:` and so parses as a bare
queue name. The `*` in an `execute-api` ARN is a non-blank path segment like any other, not a wildcard.
Neither is a useful thing to do; the point is that a create call will not stop you.

Given the resolved type, the service checks two groups, and nothing outside them.

**1. Routing — can the service reach this target at all.**

* **Every parameter block you supply must match the resolved target.** Each target type accepts exactly
  one block, so this one rule also covers supplying two: one of the two cannot match. The message names
  the offending block and the expected one, for example `SnsParameters is not supported for target
  arn:aws:sqs:us-east-1:111122223333:orders. Expected SqsParameters`. A target that takes no block at
  all — a classic bus, or Firehose — reads `Expected no target parameters`. The block must match because
  the invoker is chosen from the ARN, so a mismatched block would be stored and never read.
* **The target is in the caller's account.** `Target resource account (X) must match the subscriber
  account (Y)`. Unlike the ARN messages above, this one carries no field-name prefix.
* **The target is in the endpoint's region and partition**, except for a new-custom-bus or universal target,
  which are exempt from the region check.
* **The target is not the subscriber's own bus.**
  `InvokeConfiguration.TargetArn must not reference the subscriber's own event bus`, because delivering
  to the source bus re-publishes and re-matches forever. The check is exact string equality, so it
  catches only the identical ARN and not some other bus that forwards back.

**2. Rules that protect the service itself.**

* **Every JSONata expression must parse**, because the service evaluates it once per delivered event.
  An expression that fails only at delivery is invisible to the caller.
* **An API Gateway header name must be a literal, and must not be one the service signs.**
  `Authorization`, `Host`, and any header prefixed `X-Amz` are rejected, case-insensitively, because
  the request is signed with SigV4 and overriding a signed header invalidates the signature. **This is
  not API Gateway's reserved-header list**, which API Gateway owns and enforces itself. **The rule is
  scoped to API Gateway.** An API destination also takes `HttpParameters`, and its header names are not
  checked at all — neither for being literal nor for being signing-sensitive.
* **A `BinaryValue` must not contain `{%` or `%}`**, because it is forwarded unevaluated and an
  expression would arrive at the target as its own literal text. The test is for either delimiter
  anywhere in the value, so a literal that merely contains one is rejected too.
* **1 MiB of UTF-8 per message-attribute map**, counting each entry's name, `DataType`, `StringValue`
  and `BinaryValue` text. `MessageAttributes` and `MessageSystemAttributes` are measured separately
  rather than summed, and a `BinaryValue` counts its Base64 text rather than its decoded bytes. This is
  an anti-abuse ceiling well above any target's own budget, so the target is still what rejects an
  oversized set.
* **A message-attribute map must not hold a null attribute object.** A null there is not a value the
  SDK can serialize; it is a hole the service would dereference while building the request.

Not checked here, because they belong to the target: whether a member the target's API requires is
present, whether a member applies to the standard or FIFO resource you named, SQS's delay range and
its refusal of a per-message delay on a FIFO queue, SNS's `MessageStructure` vocabulary, Lambda's
durable-execution-name and tenant-id grammars, whether a Lambda qualifier names a version or an alias
that exists, FIFO group-id and deduplication-id requiredness, emptiness, length and character rules,
Kinesis's partition-key requiredness and length, message-attribute names against SQS's and SNS's own
naming rules, `DataType` requiredness, attribute counts and data-type vocabularies, the Base64
contract, and reserved system-attribute names.

`RoleArn` is not checked for account here. `CreateSubscriber` authorization enforces `iam:PassRole`
on it first, which rejects a role you cannot pass with `AccessDeniedException` before validation
runs.

---

## 2. Required request fields

Unconditionally required by the model on `CreateSubscriber`:

| Member | Notes |
|---|---|
| `Name` | 1 to 256 chars, first character alphanumeric, then `[.\-_A-Za-z0-9]` |
| `EventBusArn` | full ARN including the 25-character generated id |
| `InvokeConfiguration.TargetArn` | see the table above |
| `InvokeConfiguration.RoleArn` | must be passable by the caller |

Required conditionally, by the service:

| Condition | Then required |
|---|---|
| `FilterConfiguration` supplied on create | at least one filter in `Filters` with a non-empty `Pattern`, so `{}` is rejected. Each `Filter` needs both `Pattern` and `Scope`. Omitting the block is allowed and receives every event |
| `Transformer.Type: JSONATA` | `Transformer.JsonataConfiguration.Expression` |
| `StartingPosition: POINT_IN_TIME` | `PointInTimeConfiguration.PointType` |

Everything else is optional, and three optional members are worth treating as mandatory in practice:
`OnFailureConfiguration`, `LogConfiguration`, and `RetryPolicy`. The first two are why a failure is
visible at all, and every example below sets them.

## Target-required runtime fields

These are the target API's own required fields. The service does not check them at create. The target
service checks them at delivery — **including a FIFO `MessageGroupId`, which the service no longer
requires at create.** A `.fifo` queue or topic with no group id is stored, and SQS or SNS rejects
every delivery.

| Target API | Required by the target |
|---|---|
| SQS `SendMessageBatch` | queue URL, message body; `MessageGroupId` on a FIFO queue; a `DataType` on every message attribute |
| SNS `PublishBatch` | `TopicArn`, `Message`; `MessageGroupId` on a FIFO topic; a `DataType` on every message attribute |
| Lambda `Invoke` | function identifier, payload |
| Kinesis `PutRecords` | `PartitionKey` per record, stream name |
| Step Functions `StartExecution` | state machine ARN, input |
| Firehose `PutRecordBatch` | delivery stream name. There is no parameter block, so there is nothing else to supply |

The target also decides **applicability**: whether a member is accepted on the resource you named.
`MessageDeduplicationId` on a standard queue, an SNS group or deduplication id on a standard topic,
and a per-message `DelaySeconds` on a FIFO queue are all stored and dealt with when the target is
called.

For the typed target blocks the service builds the request, so you only supply the parts the block
exposes.

---

## 3. Literal versus JSONata

Most scalar target parameters are modelled as strings so they can carry either a literal or a JSONata
expression in `{% ... %}` form. The expression is evaluated once per delivered event, with the event
available as `$events` (addressing is in `filters-and-expressions.md`).

**Both forms are checked the same way, and it is a short check.** A literal is checked only against
the rules the service owns; an expression is additionally required to parse. Neither is checked
against the target's own range or grammar, and neither is checked for being required or for applying
to the resource you named. So for most members the create call tells you nothing about whether the
value is acceptable — the target decides that at delivery.

| Member | What the service checks | What the target checks at delivery |
|---|---|---|
| `SqsParameters.DelaySeconds` | expression syntax only | the accepted range, 0 to 900, and that a FIFO queue takes no per-message delay |
| `SqsParameters.MessageGroupId` | expression syntax only | requiredness on a FIFO queue, emptiness, length and character rules |
| `SqsParameters.MessageDeduplicationId` | expression syntax only | that it applies to a FIFO queue at all, plus length and character rules |
| `SnsParameters.MessageStructure` | expression syntax only | the accepted vocabulary, `json` |
| `SnsParameters.Subject` | expression syntax only | length and character rules |
| `SnsParameters.MessageGroupId` | expression syntax only | requiredness on a FIFO topic, that it applies to the topic at all, emptiness, length and character rules |
| `SnsParameters.MessageDeduplicationId` | expression syntax only | that it applies to a FIFO topic at all, plus length and character rules |
| `LambdaParameters.InvocationType` | the whole value: only `EVENT` and `REQUEST_RESPONSE` are accepted, and an expression is rejected | nothing; the service converts the value to Lambda's own vocabulary at delivery |
| `LambdaParameters.Qualifier` | expression syntax only | the qualifier grammar, and that the version or alias exists |
| `LambdaParameters.DurableExecutionName` | expression syntax only | the name grammar and length |
| `LambdaParameters.TenantId` | expression syntax only | the tenant-id grammar and length |
| `StepFunctionsParameters.InvocationType` | the whole value: only `EVENT` and `REQUEST_RESPONSE` are accepted, and an expression is rejected | nothing; the value selects `StartExecution` or `StartSyncExecution` |
| `StepFunctionsParameters.Name` | expression syntax only | the name grammar, and uniqueness |
| `KinesisParameters.PartitionKey` | expression syntax only | requiredness, key length, and character rules |
| `KinesisParameters.ExplicitHashKey` | expression syntax only | decimal format and range |
| `MessageAttributes.*` name (the map key) | expression syntax, but **only when the value is fully delimited** | the name against its own naming rules. A name that resolves to nothing, or two names that resolve to the same string, fail the delivery |
| `MessageAttributes.*.DataType` | nothing | requiredness, and the data-type vocabulary |
| `MessageAttributes.*.StringValue` | expression syntax only | value rules for the data type. An expression resolving to nothing is forwarded as a null value rather than failing |
| `MessageAttributes.*` (whole map) | 1 MiB of UTF-8 per map, and that no entry is a null object | the count limit and the real size budget |
| `InvocationTimeoutSeconds` | accepted on `HttpParameters` for API Gateway, and on the Lambda, Step Functions and universal-target blocks; **a literal is range-checked and rejected out of range, never clamped**. The universal-target block takes a literal only, and rejects an expression at create | an expression's resolved value is range-checked **and clamped** here; a universal target never sees one |

`InvocationTimeoutSeconds` is the one range the service does hold, because the service is what makes
the call and holds the connection open. It is a service-owned limit, not a copy of a target's. Three
details do not follow from that: on `HttpParameters` it is valid for an API Gateway target and rejected
for an API destination; a universal target refuses an expression outright and requires an integer; and
on any other block an expression skips the create-time range check entirely and is clamped at delivery.
The upper bound is resolved from service configuration at runtime rather than compiled in, so treat 30
as the documented default rather than a fixed ceiling.

Beyond the two `InvocationType` members and the universal target's `InvocationTimeoutSeconds` above, two
more members must be literals and reject an expression outright:

* **`HttpParameters.HeaderParameters` keys, on an API Gateway target.** A header name **MUST** be a
  literal so it can be inspected at all, and an expression is rejected on that ground. A name that is
  `Authorization`, `Host`, or `X-Amz`-prefixed is rejected because the request is signed with SigV4 and
  those are the headers the signature covers. API Gateway's own reserved-header list is longer and is
  enforced by API Gateway, at delivery. Neither check runs for an API destination, which takes the same
  block: there a header name may be an expression and may be one of the signing headers.
* **`MessageAttributes.*.BinaryValue`.** It is forwarded unevaluated, so an expression would reach the
  target as its own literal text. The rejection triggers on `{%` or `%}` appearing anywhere in the
  value, not only on a well-formed expression.

One member is neither evaluated nor guarded: **`MessageAttributes.*.DataType` is forwarded exactly as
written and is not validated at all.** An expression there is not rejected; it arrives at the target as
its own text and the target rejects the data type.

**Message-attribute names are evaluated per event.** For SQS and SNS, both an attribute's name and its
`StringValue` may be expressions. The failure modes differ: a name that resolves to nothing fails the
whole delivery, as do two names that resolve to the same string, while a `StringValue` that resolves to
nothing is delivered as a null value. Create-time syntax checking
of a name is conditional — a malformed expression is caught only if its `{%` and `%}` delimiters are
both intact. `{% $events.Data` fails the delimiter test, is treated as a literal name, and reaches SQS
or SNS as that text.

**Per-message fields belong in an expression.** A message group id, a deduplication id, a partition
key, and an execution name are per-message by nature. A literal deduplication id is accepted and
makes the target treat every message after the first as a duplicate; the symptom is exactly one
message arriving and then nothing. The canonical forms derive them from the event's own ordering
fields:

```
"MessageGroupId":        "{% $events.SystemMetadata.EventGroupId %}"
"MessageDeduplicationId": "{% $events.SystemMetadata.DeduplicationId %}"
```

Limits: `Transformer.JsonataConfiguration.Expression` is 1 to 8192 characters and must match
`{% ... %}` with nothing after the closing delimiter.

---

### A create rejected on `invocationType` is the enum's casing

The `InvocationType` rows above produce the one create-time rejection people copy into tickets.
Verbatim:

```
InvalidInputException: 1 validation error detected: Value at
'invokeConfiguration.stepFunctionsParameters.invocationType' failed to satisfy constraint: Member must
satisfy enum value set: [REQUEST_RESPONSE, EVENT]
```

The value is an enum, upper case: `EVENT` or `REQUEST_RESPONSE`. The rejected value is usually `Event`,
the casing Lambda's own `Invoke` API uses, or a JSONata expression, which this member does not accept.
The Lambda member path form is identical with `lambdaParameters` in the path.

## 4. Working examples

Nine target types. Each is a complete `CreateSubscriber` request body, and each sets an SQS
dead-letter queue, subscriber logging, and lists the delivery-role actions. Substitute your own
partition, region, and account. Read the subscriber back with `DescribeSubscriber` afterwards:
`CreateSubscriber` returns identity and state only, never the stored configuration.

Every example carries this pair, so it is elided from the bodies below to keep them readable:

```json
"OnFailureConfiguration": { "Arn": "arn:aws:sqs:us-east-1:111122223333:my-dlq" },
"LogConfiguration":       { "Level": "INFO", "IncludePayload": "FULL" }
```

`LogConfiguration.Level` defaults to `OFF`, so set it before you need it. The dead-letter queue ARN
is shape-checked at create, and its queue-name grammar is SQS's own: 1 to 80 characters of
`[A-Za-z0-9_-]`, where a `.fifo` suffix counts toward the 80.

**Every role below also needs `sqs:SendMessage` on the dead-letter queue.** Granting the target but
not the dead-letter queue loses the failure entirely: deliveries fail, the failure record cannot be
written, and no surface records it.

### Standard SQS queue

```json
{
  "Name": "orders-to-queue",
  "EventBusArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/exampleid0123456789abcdef",
  "InvokeConfiguration": {
    "TargetArn": "arn:aws:sqs:us-east-1:111122223333:orders",
    "RoleArn": "arn:aws:iam::111122223333:role/my-delivery-role",
    "SqsParameters": {
      "DelaySeconds": "0",
      "MessageAttributes": {
        "orderId": { "DataType": "String", "StringValue": "{% $events.Data.detail.orderId %}" }
      }
    }
  },
  "FilterConfiguration": { "Filters": [ { "Scope": "DATA", "Pattern": "{\"detail\":{\"orderId\":[{\"exists\":true}]}}" } ] },
  "RetryPolicy": { "MaxRetryAttempts": 5, "MaxEventAgeInSeconds": 300 }
}
```

Role: `sqs:SendMessage` on the queue. Delivery is `SendMessageBatch`.
`SqsParameters` is optional on a standard queue; omitting it delivers the payload with no attributes.
`MessageDeduplicationId` is FIFO-only, and SQS is what says so: setting it here is accepted at create
and fails at delivery.
The attribute count limit, the requiredness of each attribute's `DataType`, the accepted data types,
and the real size budget are SQS's and are enforced when the queue is called; the service applies only
a generous aggregate byte ceiling and a rejection of a null attribute object. The accepted
`MessageSystemAttributes` names are SQS's too — `AWSTraceHeader` is the one it takes.

### FIFO SQS queue

```json
{
  "Name": "orders-to-fifo",
  "EventBusArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/exampleid0123456789abcdef",
  "Type": "FIFO",
  "InvokeConfiguration": {
    "TargetArn": "arn:aws:sqs:us-east-1:111122223333:orders.fifo",
    "RoleArn": "arn:aws:iam::111122223333:role/my-delivery-role",
    "SqsParameters": {
      "MessageGroupId": "{% $events.SystemMetadata.EventGroupId %}",
      "MessageDeduplicationId": "{% $events.SystemMetadata.DeduplicationId %}"
    }
  },
  "FilterConfiguration": { "Filters": [ { "Scope": "DATA", "Pattern": "{\"detail\":{\"orderId\":[{\"exists\":true}]}}" } ] }
}
```

Role: `sqs:SendMessage` on the queue.
The service accepts any subscriber `Type` for this target. SQS still requires `MessageGroupId` and refuses
per-message `DelaySeconds` on a FIFO queue, so an incompatible configuration fails during delivery.
The group id above is not optional in practice; SQS is what enforces it.

### SNS topic

```json
{
  "Name": "orders-to-topic",
  "EventBusArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/exampleid0123456789abcdef",
  "InvokeConfiguration": {
    "TargetArn": "arn:aws:sns:us-east-1:111122223333:orders",
    "RoleArn": "arn:aws:iam::111122223333:role/my-delivery-role",
    "SnsParameters": {
      "Subject": "New order",
      "MessageAttributes": {
        "orderId": { "DataType": "String", "StringValue": "{% $events.Data.detail.orderId %}" }
      }
    }
  },
  "FilterConfiguration": { "Filters": [ { "Scope": "DATA", "Pattern": "{\"detail\":{\"orderId\":[{\"exists\":true}]}}" } ] }
}
```

Role: `sns:Publish` on the topic. Delivery is `PublishBatch`.
Nothing about the FIFO pairing is checked at create. On a standard topic a `MessageGroupId` or a
`MessageDeduplicationId` is accepted and SNS rejects the publish; on a `.fifo` topic an absent
`MessageGroupId` is accepted and SNS rejects the publish. The accepted attribute data types, each
attribute's `DataType` requiredness, and the total size budget are SNS's own, so `MessageStructure`
and an attribute type are both create-time no-ops here.

**Size is the binding constraint here, and it fails silently.** SNS caps the enveloped message at
256 KB, so a payload at or above roughly 250 KB is accepted by the publish call and never arrives.
Around 200 KB delivers normally.

### Lambda function

```json
{
  "Name": "orders-to-lambda",
  "EventBusArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/exampleid0123456789abcdef",
  "InvokeConfiguration": {
    "TargetArn": "arn:aws:lambda:us-east-1:111122223333:function:process-order",
    "RoleArn": "arn:aws:iam::111122223333:role/my-delivery-role",
    "LambdaParameters": { "InvocationType": "EVENT", "Qualifier": "$LATEST" }
  },
  "FilterConfiguration": { "Filters": [ { "Scope": "DATA", "Pattern": "{\"detail\":{\"orderId\":[{\"exists\":true}]}}" } ] },
  "BatchConfiguration": { "MaxBatchSize": 10, "MaxBatchWindowInSeconds": 5 }
}
```

Role: `lambda:InvokeFunction` on the function.
Lambda owns the ARN resource subtype, region, partition, qualifier, `DurableExecutionName`, and
`TenantId`. The service accepts their literal values after shape and expression syntax checks; Lambda
rejects unsupported combinations during delivery. `InvocationType` is the exception: the service accepts
only `EVENT` or `REQUEST_RESPONSE` at create, and delivers the value in Lambda's own vocabulary.

A Lambda returning `batchItemFailures` in a 200 response retries only the reported entries (§5).

### Kinesis data stream

```json
{
  "Name": "orders-to-stream",
  "EventBusArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/exampleid0123456789abcdef",
  "InvokeConfiguration": {
    "TargetArn": "arn:aws:kinesis:us-east-1:111122223333:stream/orders",
    "RoleArn": "arn:aws:iam::111122223333:role/my-delivery-role",
    "KinesisParameters": { "PartitionKey": "{% $events.Data.detail.customerId %}" }
  },
  "FilterConfiguration": { "Filters": [ { "Scope": "DATA", "Pattern": "{\"detail\":{\"customerId\":[{\"exists\":true}]}}" } ] }
}
```

Role: `kinesis:PutRecords` on the stream.
`KinesisParameters` may be omitted or empty. The invoker still constructs `PutRecords`, and Kinesis
owns `PartitionKey` requiredness plus both members' formats and ranges. Missing or invalid values are
reported through retries, the DLQ, and, when enabled, subscriber logs.

### Step Functions state machine

```json
{
  "Name": "orders-to-sfn",
  "EventBusArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/exampleid0123456789abcdef",
  "InvokeConfiguration": {
    "TargetArn": "arn:aws:states:us-east-1:111122223333:stateMachine:order-workflow",
    "RoleArn": "arn:aws:iam::111122223333:role/my-delivery-role",
    "StepFunctionsParameters": {
      "InvocationType": "EVENT",
      "Name": "{% 'order-' & $events.Data.detail.orderId %}"
    }
  },
  "FilterConfiguration": { "Filters": [ { "Scope": "DATA", "Pattern": "{\"detail\":{\"orderId\":[{\"exists\":true}]}}" } ] }
}
```

Role: `states:StartExecution`, plus `states:StartSyncExecution` if you set
`InvocationType: REQUEST_RESPONSE`.
`Name` must be unique per account, region, and state machine, so derive it from the event. A literal
`Name` causes every execution after the first to be rejected by Step Functions as a duplicate.

### HTTP: API destination and API Gateway

```json
{
  "Name": "orders-to-api",
  "EventBusArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/exampleid0123456789abcdef",
  "InvokeConfiguration": {
    "TargetArn": "arn:aws:events:us-east-1:111122223333:api-destination/partner-api/exampleid0123456789abcdef",
    "RoleArn": "arn:aws:iam::111122223333:role/my-delivery-role",
    "HttpParameters": {
      "HeaderParameters": { "x-partner-tenant": "{% $events.Data.detail.tenantId %}" },
      "QueryStringParameters": { "source": "eventbridge" },
      "PathParameterValues": [ "{% $events.Data.detail.orderId %}" ]
    }
  },
  "FilterConfiguration": { "Filters": [ { "Scope": "DATA", "Pattern": "{\"detail\":{\"tenantId\":[{\"exists\":true}]}}" } ] }
}
```

Role: `events:InvokeApiDestination` on the API destination ARN.
`PathParameterValues` are substituted in order into the endpoint path's placeholders. Header names and
values may both be expressions here, because the header rules below are enforced for API Gateway only.

For **API Gateway**, change `TargetArn` to
`arn:aws:execute-api:us-east-1:111122223333:{apiId}/{stage}/POST/orders`, grant
`execute-api:Invoke`, and you may add `"InvocationTimeoutSeconds": "20"`. Two differences bite here:

* **Within `HttpParameters`, `InvocationTimeoutSeconds` is valid for API Gateway and rejected for an
  API destination**: `InvocationTimeoutSeconds is only supported for API Gateway HTTP targets`. The
  member also exists on the Lambda, Step Functions and universal-target blocks, so that message is
  about this block rather than about the service as a whole. A literal is range-checked and rejected
  out of range rather than clamped, because the service holds the connection and so owns the range.
* **The service rejects only the headers it signs**, case-insensitively: `Authorization`, `Host`, and
  any header prefixed `X-Amz`, and it also requires the name to be a literal so it can check it. It
  signs the API Gateway request with SigV4, and a customer override of a signed header invalidates that
  signature. **API Gateway's own reserved-header list is longer, and API Gateway enforces it** — a name
  like `Connection`, `Content-Length`, `TE`, or `X-Forwarded-For` is accepted at create and dealt with
  by API Gateway at delivery. Neither check applies to an API destination.

### Firehose delivery stream

```json
{
  "Name": "orders-to-firehose",
  "EventBusArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/exampleid0123456789abcdef",
  "InvokeConfiguration": {
    "TargetArn": "arn:aws:firehose:us-east-1:111122223333:deliverystream/orders",
    "RoleArn": "arn:aws:iam::111122223333:role/my-delivery-role"
  },
  "FilterConfiguration": { "Filters": [ { "Scope": "DATA", "Pattern": "{\"detail\":{\"orderId\":[{\"exists\":true}]}}" } ] }
}
```

Role: `firehose:PutRecordBatch` on the delivery stream. Delivery is `PutRecordBatch`.
**Firehose takes no parameter block**, so `InvokeConfiguration` is exactly `TargetArn` and `RoleArn`.
Supplying any block is rejected: `SqsParameters is not supported for target arn:aws:firehose:... Expected
no target parameters`. Everything outside `InvokeConfiguration` still applies — filter, transformer,
`BatchConfiguration`, dead-letter queue, logging, ordering `Type`, `StartingPosition`, `RetryPolicy`.
The ARN's resource part must be exactly `deliverystream/{name}`: the colon form is rejected, as is a
trailing qualifier. Batches are capped at 500 records and about 4 MiB.

Two cautions specific to this target. Records are written as the raw payload bytes with **no separator,
newline, or envelope added**, so a downstream consumer that expects newline-delimited JSON will see
concatenated records unless the payload itself ends in a newline. And this target has less operational
mileage than the others here, so verify a delivery end to end before depending on it.

### Another new custom event bus

```json
{
  "Name": "orders-to-bus",
  "EventBusArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/exampleid0123456789abcdef",
  "InvokeConfiguration": {
    "TargetArn": "arn:aws:events:us-east-1:111122223333:event-busv2/downstream/exampleid0123456789abcdef",
    "RoleArn": "arn:aws:iam::111122223333:role/my-delivery-role",
    "EventBusV2Parameters": {
      "Metadata": { "forwardedBy": "orders-to-bus" },
      "SystemMetadata": { "EventGroupId": "{% $events.SystemMetadata.EventGroupId %}" },
      "DeduplicationConfiguration": { "DeduplicationType": "CONTENT_BASED" }
    }
  },
  "FilterConfiguration": { "Filters": [ { "Scope": "DATA", "Pattern": "{\"detail\":{\"orderId\":[{\"exists\":true}]}}" } ] }
}
```

Role: `events:PutEvents` **and** `events:PutRawEvents` on the destination bus.
Forwarding is authorized per event at ingestion against the destination bus's resource policy, and
the action is chosen from the event's own system metadata: a genuine AWS or partner event needs
`events:PutEvents`, and anything you originated needs `events:PutRawEvents`. A forwarder carrying
both kinds and granted only one silently loses half the stream. See `authorization.md`.

`Metadata` holds at most 100 keys. A target that is verbatim the subscriber's own bus is rejected at
create, because it would loop; a *different* bus that forwards back to this one is not detected, so
you own avoiding that cycle.

---

## 5. Target and runtime error taxonomy

Delivery failures fall into classes, and the class decides whether the event is retried, dead-lettered,
or dropped. Working through the classes in order is faster than reading a message cold.

### Where the failure happens

The fault column says who can act on the failure. The retry column says what the delivery path does,
and the important part is that **it is almost the same for every row**: failures are retried by
default, and being permanent does not exempt one.

| Class | Trigger | Fault | Retried? |
|---|---|---|---|
| **Transformation** | a `JSONATA` transformer's expression throws: syntax, runtime, or a resource limit | customer | yes, on the budget |
| **Transformation** | the expression evaluates cleanly and produces **nothing** | customer | yes, on the budget |
| **Transformation** | the event body will not parse as JSON, so `$events` cannot be built | customer | yes, on the budget |
| **Input evaluation** | a target-parameter expression throws against the event | customer | yes, on the budget |
| **Input evaluation** | a message-attribute **name** expression resolves to nothing, or two names resolve to the same string | customer | yes, on the budget |
| **Input evaluation** | the resolved request omits a field the target API requires | customer | yes, on the budget |
| **Local SDK conversion** | the resolved request cannot be converted into an SDK request, or exceeds the target's payload cap before any call is made | customer | yes, on the budget |
| **Target 4xx** | the target rejects the call: value out of range, resource not found, access denied, malformed request | customer | yes, on the budget |
| **Target 429 or throttling** | the target is rate-limiting | neither | yes |
| **Target 5xx** | the target service failed | target | yes |
| **Network fault** | connection, TLS, or timeout | neither | yes |
| **Service fault** | the failure is internal to this service | service | **indefinitely**, never exhausts |
| **HTTP 200 with per-entry failures** | a batch API returns success with a failed-entry list | per entry | only the failed entries |

Four of these are worth spelling out.

**A permanent fault is retried anyway.** There is no class that dead-letters on the first attempt on
its own. A 4xx, an expression that throws, and a request that cannot be converted are each retried
until `MaxRetryAttempts` or `MaxEventAgeInSeconds` is reached, and only then dead-lettered. Retrying
cannot fix any of them, so the retries buy nothing and cost the whole window. **If you want a
first-attempt dead-letter — when testing a failure path, or for a target whose 4xx you know is
final — set `MaxRetryAttempts: 0`.**

**A service fault is the one class that never exhausts.** It retries indefinitely rather than
dead-lettering, on the reasoning that the customer cannot act on it and the event should not be
discarded for a defect on this side.

**HTTP 200 is not success for a batch target.** Delivery to SQS, SNS, Kinesis, and Firehose uses the
batch APIs — `SendMessageBatch`, `PublishBatch`, `PutRecords`, `PutRecordBatch` — and each can return
HTTP 200 carrying a list of individually failed entries. The invoker reads that list and retries the
failed entries alone, so a partially failing batch neither succeeds nor fails as a unit. The same shape
exists for Lambda: a function returning `batchItemFailures` in its 200 response has only those items
retried. When you are counting deliveries, count at the target, never from an HTTP status.

**A transformation or conversion failure never reaches the target.** It is classified before the wire
call, so there is no `http_status` and no target request id in the log record. An empty
`details.target_request_id` on a failed attempt is the signal that the failure was local. A
transformation failure is reported as its own `EVENT_TRANSFORMATION_FAILURE` record rather than a
delivery attempt.

### Retries and dead-lettering

`RetryPolicy` has three members, and delivery stops at whichever limit is reached first:

| Member | Range | Default |
|---|---|---|
| `MaxRetryAttempts` | 0 to 185 | 5 |
| `MaxEventAgeInSeconds` | 60 to 86400 | 300 |
| `RetryStrategy` | `ALL` | `ALL` |

With the defaults, a failing delivery is attempted `MaxRetryAttempts + 1` times and stops at whichever
limit is reached first, so **"nothing arrived" is only a sound conclusion once `MaxEventAgeInSeconds` has
elapsed** — for a permanent fault as much as a retriable one. The attempts cap is evaluated before the age
cap, so when both are hit the record reports `MaximumRetryAttempts`.

`OnFailureConfiguration.Arn` names the SQS queue that receives the failure record, and SQS is the
only supported destination. Read the subscriber back and confirm the field is populated; other
nestings of it are accepted and stored empty.

### The dead-letter record

One record per failed batch, carrying a reference per event:

```json
{
  "version": "1.0",
  "busArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/...",
  "subscriberArn": "arn:aws:events:us-east-1:111122223333:subscriber/orders-to-queue/...",
  "targetArn": "arn:aws:sqs:us-east-1:111122223333:orders",
  "errorCode": "ACCESS_DENIED",
  "errorMessage": "User: ... is not authorized to perform: sqs:sendmessage on resource: ...",
  "exhaustedRetryCondition": "MaximumRetryAttempts",
  "retryAttempts": 5,
  "failedMessages": [
    {
      "eventId": "...",
      "eventGroupId": "g9",
      "deduplicationId": "order-1234",
      "timestamp": "2026-09-07T01:43:53.768Z",
      "targetRequestId": "..."
    }
  ]
}
```

How to read it:

| Field | Use |
|---|---|
| `errorCode` | the class. `CUSTOMER_VALIDATION` collapses every customer fault, so the class alone does not tell you which |
| `errorMessage` | the target service's own words, usually the answer. Truncated at 1024 characters |
| `exhaustedRetryCondition` | `MaximumRetryAttempts` or `MaximumEventAgeInSeconds`, so you know which limit ended it |
| `retryAttempts` | how many retries happened. **`0` means the budget was `MaxRetryAttempts: 0`, or the age limit ended it at the first attempt — it does not mean the fault was permanent**, because permanent faults are retried too |
| `failedMessages[].eventId` | which event, for correlating against the log record and the publish response |
| `failedMessages[].targetRequestId` | the target's own request id. Empty when the failure was local |

Two limits. **`failedMessages` carries no payload**, so the record alone cannot reconstruct the
event; you need the event still inside the bus's retention window. And `deduplicationId` is
populated whenever the event carried one, including for an `UNORDERED` subscriber — ordering mode and
publish-time deduplication are independent, so its presence says nothing about `Type`.

### Vended logs

Set `LogConfiguration.Level` to `INFO` and reproduce, rather than waiting out the retry window. Each
attempt produces one `EVENT_DELIVERY_ATTEMPT` record per event; `details.target_input` shows what the
target actually received, and `error.error_code` with `error.error_message` is the same pair the
dead-letter record carries. Full field list in `observability.md`.

---

## 6. Troubleshooting flow

Work down. Each step either explains the failure or eliminates a class.

1. **Did `CreateSubscriber` succeed?** If the failure is an `InvalidInputException`, the message
   names the member. Fix that member; nothing was stored.
2. **Wait past the retry window.** More than 5 minutes on the defaults, or past
   `MaxEventAgeInSeconds`. Before that, a failing delivery is still being retried.
3. **Confirm events reached the bus.** `PublishEventsEntryCount` in `AWS/EventsV2`. Zero means the
   problem is upstream and nothing below matters. The `EventBus` dimension value is
   `{name}/{generatedId}`, not the ARN.
4. **`DescribeSubscriber`.** Check `State` is `RUNNING`, and check `Revoked`. A revoked subscriber
   delivers nothing while still reading `RUNNING`, and revocation is terminal.
5. **Is anything failing at all?** Turn on logs at `INFO` with `IncludePayload: FULL`, reproduce, and
   read `details.outcome`.
   * **No records at all** — the event is not reaching the subscriber. The cause is the filter, the
     starting position, or the addressing asymmetry between the two publish APIs. Go to
     `delivery-troubleshooting.md` steps 4 and 5.
   * **Records with `outcome: FAILURE`** — continue.
6. **Read `error.error_code` and `error.error_message`, then classify with §5.** Do not use the
   attempt count to tell a permanent fault from a retriable one: both are retried on the same budget.
   The message distinguishes them.
   * A 5xx or a throttle: the target is unhealthy or rate-limited. Raise `MaxRetryAttempts`, or fix
     the target.
   * `CUSTOMER_VALIDATION`: your request or expression. Read the message; retries will not help, so
     `MaxRetryAttempts: 0` gets you the record faster while you iterate.
7. **Read `details.target_input`.** This settles every expression question, because it is what the
   target received rather than what you meant to send. An empty or missing field there is an
   addressing mistake in your expression, not a target problem.
8. **Empty `details.target_request_id` on a failure** means the call never left: an input-evaluation
   or local-conversion fault. The expression or the resolved request is wrong.
9. **`AccessDenied` in the message** means the delivery role is missing the target's action — or, if
   nothing is observable anywhere, missing `sqs:SendMessage` on the dead-letter queue.
10. **Still nothing.** Add a second subscriber with `Transformer: { Type: WITH_METADATA }`, no
    filter, and an SQS queue you own. That delivers the event exactly as the service holds it and
    settles the addressing question outright.

---

## 7. Authoritative AWS references

Limits and quotas change, so read them at the source rather than from a copy. Each target's own API
reference is where the required fields and value ranges live, and each service's quota page is where
the numbers live.

### Target APIs the service calls

* SQS `SendMessageBatch` — https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_SendMessageBatch.html
* SNS `PublishBatch` — https://docs.aws.amazon.com/sns/latest/api/API_PublishBatch.html
* Lambda `Invoke` — https://docs.aws.amazon.com/lambda/latest/api/API_Invoke.html
* Kinesis `PutRecords` — https://docs.aws.amazon.com/kinesis/latest/APIReference/API_PutRecords.html
* Firehose `PutRecordBatch` — https://docs.aws.amazon.com/firehose/latest/APIReference/API_PutRecordBatch.html
* Step Functions `StartExecution` — https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html
* Step Functions `StartSyncExecution` — https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartSyncExecution.html

### Quotas and limits

* SQS — https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-quotas.html
* SNS — https://docs.aws.amazon.com/sns/latest/dg/sns-quotas.html
* Lambda — https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html
* Kinesis — https://docs.aws.amazon.com/streams/latest/dev/service-sizes-and-limits.html
* Firehose — https://docs.aws.amazon.com/firehose/latest/dev/limits.html
* Step Functions — https://docs.aws.amazon.com/step-functions/latest/dg/limits-overview.html
* API Gateway — https://docs.aws.amazon.com/apigateway/latest/developerguide/limits.html

### Reference material for the surrounding concepts

* FIFO queue message grouping and deduplication — https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/FIFO-queues.html
* SNS FIFO topics — https://docs.aws.amazon.com/sns/latest/dg/fifo-topic-code-examples.html
* Lambda partial batch responses — https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html
* `iam:PassRole` — https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html
