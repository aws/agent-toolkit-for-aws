# Target configuration

The short version: which parameter block goes with which target, and the five rules that prevent most
delivery failures.

**For anything more than that, load [target-contract.md](target-contract.md).** It carries the
validation ownership model, the required-field lists, a complete working example per target type,
literal-versus-JSONata rules, the runtime error taxonomy, and a troubleshooting flow.

`InvokeConfiguration` carries three things: the `TargetArn`, the `RoleArn` the service assumes to
invoke it, and at most one parameter block matching the target type. A universal target requires its
block. Every typed block may be omitted, including Kinesis's: an absent or empty `KinesisParameters` is
stored, and Kinesis reports the missing `PartitionKey` when it is called.

The delivery role **MUST** belong to the account creating the subscriber, and its trust policy
**MUST** allow the `events.amazonaws.com` service principal to call `sts:AssumeRole`.

**That trust policy SHOULD also condition on `aws:SourceAccount` and `aws:SourceArn`**, so the role can be
assumed only on behalf of your own subscribers rather than by the service acting for anyone:

```json
"Condition": {
  "StringEquals": { "aws:SourceAccount": "111122223333" },
  "ArnLike": { "aws:SourceArn": "arn:aws:events:us-east-1:111122223333:subscriber/*" }
}
```

The service sets `aws:SourceArn` to the **subscriber** ARN and `aws:SourceAccount` to that subscriber's
account, so a pattern ending `subscriber/*` matches every subscriber you own and nothing else. Narrow it to
one subscriber by name if you want the role usable by only that one.

---

## The parameter blocks

| Block | Target |
|---|---|
| `SqsParameters` | SQS queue, standard or FIFO |
| `SnsParameters` | SNS topic, standard or FIFO |
| `LambdaParameters` | Lambda function |
| `KinesisParameters` | Kinesis stream |
| `StepFunctionsParameters` | Step Functions state machine |
| `HttpParameters` | API Gateway route or API destination |
| `EventBusV2Parameters` | another new custom event bus |
| `UniversalTargetParameters` | any supported AWS API |
| none permitted | classic `event-bus` target, Firehose delivery stream |

Firehose **is** a supported target, and it takes no parameter block. Its `InvokeConfiguration` is exactly
`TargetArn` plus `RoleArn`, the ARN's resource part **MUST** be `deliverystream/{name}`, and delivery calls
`PutRecordBatch`, so the role **MUST** hold `firehose:PutRecordBatch`. Records are written as the raw
payload bytes with no separator or envelope added, so a consumer expecting newline-delimited JSON receives
them concatenated. This target has less operational mileage than the others, so you **SHOULD** verify a
delivery end to end before depending on it.

Supplying a block that does not match the resolved target type is rejected at create, naming both the
block you sent and the one expected, for example `SnsParameters is not supported for target
arn:aws:sqs:us-east-1:111122223333:orders. Expected SqsParameters`. Each target type accepts exactly one
block, so supplying two trips the same rule rather than a separate count check. A target that takes no
block reads `Expected no target parameters`.

Two per-target facts:

* **A Lambda target receives a JSON array of events, a batch, not a single event object.** A handler
  written to read fields off one event reads nothing; you **MUST** write the handler for a list.
* **`HttpParameters` serves two target kinds**: an API Gateway `execute-api` ARN and an EventBridge
  API destination ARN. Within this block `InvocationTimeoutSeconds` is accepted only for the API Gateway
  kind, though the member also exists on the Lambda, Step Functions and universal-target blocks. The
  header rules below are likewise API Gateway only.

---

## The five rules

These apply to every target type. They prevent the same failure mode in every case: a configuration
accepted at create time that the target service rejects at delivery time, where the publish response
cannot tell you.

### 1. Supply the block your target requires

An omitted or empty typed block is accepted at create. `KinesisParameters: {}` is stored, and Kinesis
reports the missing `PartitionKey` during delivery. A FIFO SQS queue or SNS topic likewise needs a
`MessageGroupId` to deliver, but that is the target's requirement, so omitting its block is accepted
at create and fails on every delivery.

### 2. Distinguish per-message fields from constants

A deduplication id, a message group id, a partition key, and an execution name are per-message by
nature. A literal constant for any of them is accepted at create and is almost never right.

The consequence for a deduplication id: the target treats every message after the first as a
duplicate and discards it. The symptom is exactly one message arriving and then nothing.

You **MUST** use a JSONata expression for anything per-message, where the member supports expressions.
Most scalar target parameters accept one in `{% %}` form, evaluated per event. The canonical FIFO pair:

```
"MessageGroupId":         "{% $events.SystemMetadata.EventGroupId %}"
"MessageDeduplicationId": "{% $events.SystemMetadata.DeduplicationId %}"
```

Neither form is checked against the target's own range, requiredness, or applicability. A `DelaySeconds`
of `999999` and of `{% 999999 %}` are both accepted at create and both rejected by SQS at delivery,
because the accepted range belongs to SQS and the service does not keep a copy of it. The same holds for
a `MessageGroupId` you omitted on a FIFO target and a `MessageDeduplicationId` you set on a standard one.
An expression additionally **MUST** parse, and that is the only extra check it gets. So create-time
acceptance of either form is not evidence the value is correct.

### 3. Check the target service's own rules

The service checks the request. The target checks its own resource, and it does so at delivery.

Everything below is the target's, not this service's: whether the resource exists, whether the role
may reach it, the payload size after enveloping, the value ranges, and the required fields of the API
being called. See [target-contract.md](target-contract.md) §5 for how each failure class is reported.

Three that catch people:

* **Effective size limit is the target's, after enveloping.** Through SNS a payload near 200 KB is
  delivered, while payloads at 250 KB and above are accepted by the publish call and never arrive,
  because SNS caps the enveloped message at 256 KB. The binding number is the target's, and the
  envelope counts against it.
* **A FIFO target owns its ordering and identifier rules.** The service accepts any subscriber `Type`
  for a `.fifo` queue, and accepts a missing or malformed group or deduplication id. SQS or SNS
  enforces the target behaviour during delivery, so you **SHOULD** check that target's length and
  character limits rather than assuming a value the bus accepted will be accepted there.
* **HTTP 200 is not success for a batch target.** SQS, SNS, Kinesis, and Firehose are delivered through
  batch APIs that can return 200 with a list of individually failed entries. Only the failed entries are
  retried.

### 4. Confirm at the target

You **SHOULD** read the queue, scan the table, list the executions, check the function's invocation
count. A `PUBLISHED` response is not delivery, and neither is an HTTP 200 from a batch API. See
`delivery-troubleshooting.md` for a rig that counts correctly.

### 5. Attach a dead-letter queue before you test, and grant it

`OnFailureConfiguration: { "Arn": "arn:aws:sqs:..." }`. The ARN's shape is checked at create, so a
malformed value is rejected. You **MUST** read the subscriber back and confirm the field is populated,
because other nestings of it are accepted and stored empty.

The delivery role **MUST** have `sqs:SendMessage` on that queue **in addition** to the target's own
action. A denied dead-letter queue turns every delivery failure into total silent loss, which is
strictly worse than having no dead-letter queue at all, because you believe you have one.

Set `LogConfiguration: { "Level": "INFO", "IncludePayload": "FULL" }` at the same time. It defaults to
`OFF`, and it is faster than the dead-letter queue: a log record appears on the first failed attempt,
while a dead-letter record waits for the retry window to close.

---

## What the service checks before storing a subscriber

This list decides where you look when something is wrong. The service resolves the
target type from the ARN and then rejects, with `InvalidInputException` and nothing persisted:

* a target ARN that names an unsupported service or resource type
* a target ARN whose resource part has the wrong shape for its service
* a target ARN in a different region, or a different partition, except for a new-custom-bus or universal target,
  which are exempt from the region check
* a target in a different account
* a target that is verbatim the subscriber's own bus
* a parameter block that does not match the resolved target, which also covers supplying two blocks,
  since each target type accepts exactly one
* a `MessageAttributes` entry whose value is a null object
* a JSONata expression anywhere that does not parse
* a `BinaryValue` containing `{%` or `%}`, since it is forwarded unevaluated
* on an **API Gateway** target only, a non-literal header name or a header name the service signs
  (`Authorization`, `Host`, `X-Amz*`). An API destination takes the same block and gets neither check
* `InvocationTimeoutSeconds` inside `HttpParameters` for an API destination rather than API Gateway, or
  a literal out of range. The member is also valid on the Lambda, Step Functions and universal-target
  blocks
* a message-attribute map over 1 MiB of UTF-8, measured per map rather than summed across the two maps,
  which is an anti-abuse limit set well above any target's real budget
* a `LogConfiguration.Level` or `IncludePayload` outside its enum

**What it does not check is longer than the list above.** It does not check that the target exists, is
reachable, or is writable by the role — those are delivery-time facts, so a well-formed ARN naming
nothing is accepted. And **it does not hold a copy of the target API's parameter grammar**: value
ranges, required members, whether a member applies to the standard or FIFO resource you named,
identifier lengths and character sets, non-empty identifiers, message-attribute names against the
target's own naming rules, data-type vocabularies and the requiredness of a `DataType`, attribute
counts, the Base64 contract, and reserved system-attribute names all stay with the target and are
enforced when it is invoked. The ARN shape rules are structural too, so no character is reserved: a
queue named `queue?name` is accepted. A create call that succeeds tells you the service can route and
build the request, not that the target will accept it.

---

## Universal targets

A universal target invokes an AWS API directly, with no function in between.

```
arn:{partition}:events:::aws-sdk:{service}:{apiAction}
```

Four requirements, each with the verbatim rejection you get for breaking it:

| Requirement | Get it wrong |
|---|---|
| `apiAction` is camelCase, lowercase first letter | `PutItem` → `The api PutItem is not valid for the service dynamodb`; `put_item` → `apiAction component must be alphanumeric camelCase` |
| `service` is the SDK service id, not always the obvious word | Step Functions is `sfn`, not `states` |
| `UniversalTargetParameters.Input` is required | omitted → `UniversalTargetParameters is required when TargetArn is a USI target`; supplied on a non-universal target → `only supported when TargetArn is a USI target`. The validation text abbreviates universal target as "USI target" |
| `BatchConfiguration` with valid `MaxBatchSize` and `MaxBatchWindowInSeconds` is required | create fails |

A malformed service namespace is rejected with `not a supported subscriber target`.

**`Input` is validated at create time against the target API's required fields.** This is stricter
than most of the surface and it is useful: the message names the exact fields the API expects.
The field names inside `Input` are the target API's Smithy member names in PascalCase
(`TableName`, `Item`, `StateMachineArn`), and the validator names missing fields in that casing, even
where the target API's own wire format is camelCase.

```
DynamoDB putItem with empty input
  -> UniversalTargetParameters.Input is missing required field(s): Item, TableName
SNS publish with empty input
  -> UniversalTargetParameters.Input is missing required field(s): Message
```

Worked example, one DynamoDB row per event, key taken from the payload:

```
TargetArn: arn:aws:events:::aws-sdk:dynamodb:putItem
BatchConfiguration: { MaxBatchSize: 1, MaxBatchWindowInSeconds: 0 }
RoleArn: arn:aws:iam::111122223333:role/my-delivery-role
UniversalTargetParameters.Input:
  {% { "TableName": "my-table", "Item": { "pk": { "S": $events.Data.detail.m } } } %}
```

The addressing matters more here than anywhere else, because the expression builds the whole API
request. That example publishes with `PutEvents`, so the payload is at `Data.detail`. The same
expression written as `$events.Data.m` yields an empty attribute, and the delivery fails with a
dead-letter record reading `errorCode: CUSTOMER_VALIDATION`, `errorMessage: "Supplied AttributeValue is
empty, must contain exactly one of the supported datatypes"`. In that case the target and the role are
both correct and only the expression is wrong.

---

## Delivery permissions

`InvokeConfiguration.RoleArn` **MUST** be a role the caller can pass. `CreateSubscriber` enforces
`iam:PassRole` on it during authorization, so a role you cannot pass fails with `AccessDeniedException`
before target validation runs.

Minimum policy contents:

* the action the target requires: `sqs:SendMessage`, `sns:Publish`, `lambda:InvokeFunction`,
  `kinesis:PutRecord`, `states:StartExecution`, or the API your universal target calls
* `sqs:SendMessage` on the dead-letter queue

Corrections to that first bullet. Kinesis delivery calls `PutRecords`, so the action is
`kinesis:PutRecords`. Step Functions needs `states:StartSyncExecution` as well when you set
`InvocationType: REQUEST_RESPONSE`. Firehose delivery calls `PutRecordBatch`, so the action is
`firehose:PutRecordBatch`. And the HTTP and bus targets are missing from it: an API Gateway
target needs `execute-api:Invoke`, an API destination needs `events:InvokeApiDestination`, and
another new custom bus needs `events:PutEvents` **and** `events:PutRawEvents`.

The target ARN is checked at create for shape, target type, region, partition, and account, but **not
for resource subtype existence or reachability**. So a Lambda ARN in another region or partition is
rejected at create, and one whose resource is not `function:{name}` fails the shape rule at create,
while a well-formed ARN naming a function that does not exist is stored and becomes a delivery-time
failure. A qualifier is accepted without checking that the version or alias exists.
