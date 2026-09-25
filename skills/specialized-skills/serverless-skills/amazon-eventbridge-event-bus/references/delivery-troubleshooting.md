# Delivery troubleshooting: published but never arrived

Nearly every delivery problem presents identically. The publish call returned success and the target
is empty. This file is the ordered procedure for finding out why.

You SHOULD work down the list in order. It is ordered by how often each cause turns out to be the
answer, so
stopping early is normal.

**If the failure is a rejected `CreateSubscriber` rather than a missing delivery, you are in the wrong
file.** The message names the member, and [target-contract.md](target-contract.md) §1 to §3 explains
which layer rejected it and why. Come here only once the subscriber exists.

---

## 0. Before you start: two facts that invalidate most conclusions

**A publish response does not mean delivery.** `SuccessCode: PUBLISHED` means the service accepted and
stored the event. Delivery happens afterwards and can fail with no effect on that response.

**`SuccessCode: DEDUPLICATED` is also a success.** The event was accepted and suppressed as a
duplicate. If your test harness treats every success as a new event, deduplication looks exactly like
a delivery failure.

---

## 1. Did you wait long enough?

The single most common false alarm.

| Situation | Minimum wait before concluding "nothing arrived" |
|---|---|
| Live delivery, default retry policy | the full default retry window (`MaxEventAgeInSeconds`) |
| Live delivery, custom `MaxEventAgeInSeconds` | more than that value |
| Replay (`POINT_IN_TIME` subscriber) | the replay startup delay, before you even expect the first event |

**A healthy delivery reaches the target quickly, so an event that has not arrived promptly is probably
failing rather than in flight.** That does not make a
negative conclusion safe yet: the retry policy keeps retrying a failing delivery until `MaxRetryAttempts`
or `MaxEventAgeInSeconds` is exhausted. So you SHOULD use the fast-delivery expectation to decide
something is wrong,
and the table above to decide nothing is coming.

**There is no exception for a permanent fault.** An input-evaluation failure, a local conversion failure,
and a 4xx from the target are each retried on the same budget as a 5xx, so none of them produces a
dead-letter record any sooner. Retrying cannot fix them, so the whole window is spent for nothing. **Set
`MaxRetryAttempts: 0` while you are diagnosing** and the record arrives as soon as the first attempt
fails. The one class that behaves differently is a service fault, which retries indefinitely and never
dead-letters at all.

Two delays are not delivery latency and are often mistaken for it. A newly created subscriber needs a
short activation delay before it reliably picks up events, which is a one-time cost per subscriber, not
per event. And a replaying subscriber has its own startup delay before its first event, after which it
runs at live speed.

---

## 2. Did the publish actually reach the bus?

A quick check that splits the problem in half, and it needs nothing configured in advance.

Metrics land in the **`AWS/EventsV2`** namespace, on the tuple **`{EventBus}`**. The dimension value is the
bus name and the generated id from its ARN, joined by a slash, and **not** the ARN itself:

```
aws cloudwatch get-metric-statistics --namespace AWS/EventsV2 \
  --metric-name PublishEventsEntryCount \
  --dimensions Name=EventBus,Value=my-bus/exampleid0123456789abcdef \
  --start-time <t0> --end-time <t1> --period 300 --statistics Sum
```

Passing the full ARN returns no datapoints, which looks exactly like no traffic. You SHOULD check
the dimension
value before you believe an empty result.

Read three metrics together:

| Metric | If it is zero |
|---|---|
| `PublishEventsEntryCount` | your producer never reached this bus. Stop here; the problem is upstream, in the endpoint, credentials, or bus ARN |
| `PublishEventsApproximateSuccessCallCount` | every call either threw or was throttled. `PublishEventsApproximateThrottledCallCount` against `PublishEventsApproximateFailedCallCount` says which |
| `PublishEventsFailedEntriesCount` | non-zero means entries were rejected individually, inside calls your client may have treated as successful |

A non-zero `PublishEventsFailedEntriesCount` SHOULD be checked even when everything else looks healthy,
because a caller that only inspects the HTTP status will not have noticed those rejections. The outcome
metrics count calls rather than events, so a call that returned a response counts as a success even when
every entry in it was rejected: `PublishEventsFailedEntriesCount` equal to `PublishEventsEntryCount` is
that case.

If entries were accepted, the publish side is fine and the fault is in routing or delivery. Continue.

---

## 3. Is the subscriber running, and has it been revoked?

One `DescribeSubscriber` call answers both, and they are different failures.

```
DescribeSubscriber { "SubscriberArn": "..." }
```

Check `State`:

* `RUNNING`: continue to the revocation check below, then to step 4.
* `STOPPED`: the subscriber is accruing a backlog, not failing. Resume it with
  `UpdateSubscriber { State: RUNNING }`. `ResumePosition: LAST_PROCESSED` (the default) delivers the
  backlog; `LATEST` discards it.
* `CREATING`: not ready yet. A subscriber created and published to immediately can miss the first
  event. You SHOULD allow a short delay before publishing.
* `CREATE_FAILED`: read `StateReason`. It names the cause.

Then check `Revoked`. This is the answer whenever a working subscriber stops receiving events suddenly
and nothing about your own configuration changed.

The bus owner can revoke any subscriber attached to their bus. **A revoked subscriber stops delivering
regardless of its `State`**, so `State: RUNNING` with `Revoked: true` is a subscriber that looks healthy
and delivers nothing. Anything checking only `State` will call it fine.

The field is present only when true, so an absent `Revoked` means not revoked.

Revocation is terminal. No operation clears it, and mutating the subscriber now fails with
`InvalidStateException`. Deleting it still works. So the remedy is not on your side: talk to the bus
owner, and if they agree, create a new subscriber. You SHOULD NOT spend time re-checking filters,
permissions, or
expressions, because none of them are the cause.

The same applies to an event source that stops delivering into a bus. Call `DescribeEventSource` and check
its `Revoked` field, which behaves identically.

---

## 4. Is the starting position what you think it is?

This cause has no error message, which is why it survives a search of the logs.

A subscriber created with `StartingPosition: LATEST`, which is the value you get by saying nothing,
**never sees an event published before the subscriber existed.** If your test publishes first and
subscribes second, `LATEST` correctly delivers nothing.

On a bus holding 5 events all published before any subscriber existed, each starting position
delivers:

| Subscriber | Delivers |
|---|---|
| `LATEST` | none |
| `POINT_IN_TIME` / `HORIZON` | all 5, once each |
| `POINT_IN_TIME` / `TIMESTAMP` at a midpoint | only those after the midpoint |

Fix: either publish after the subscriber is `RUNNING`, or create the subscriber with
`POINT_IN_TIME` / `HORIZON`.

---

## 5. Does the filter actually match?

You SHOULD narrow it down by simplifying rather than deleting. Start from the broadest pattern that
should still match
your test event, confirm events flow, then add your conditions back one at a time until they stop. The
condition you added last is the cause, and it is almost always an addressing mistake rather than a
pattern mistake.

For an event `{"orderId":"123","region":"eu"}` published with `PutEvents`, that sequence looks like:

```
{"detail":{"orderId":[{"exists":true}]}}      does the field resolve at all?
{"detail":{"orderId":["123"]}}                does the value match?
{"detail":{"orderId":["123"],"region":["eu"]}} does the full condition match?
```

If the first step already matches nothing, the problem is the addressing rather than any value, so go
straight to the four checks below. You MAY work on a copy of the subscriber if you would rather not
change the
live one: create a second subscriber with the simplified filter, pointed at a queue you own, and leave
the original alone.

You SHOULD check these four in order:

1. **Which API published the traffic?** The asymmetry is the same for patterns as for expressions:

   | | `PutRawEvents` | `PutEvents` |
   |---|---|---|
   | JSONata | `$events.Data.myfield` | `$events.Data.detail.myfield` |
   | `DATA` pattern | `{"myfield":["v"]}` | `{"detail":{"myfield":["v"]}}` |

   A pattern or expression written for the wrong API does not error. It matches nothing.
2. **Are you filtering on `aws:Source` or `aws:DetailType`?** Those fields exist only on `PutEvents`
   events. A `SYSTEM_METADATA` filter on `aws:Source` never matches raw-published traffic, because
   the field is absent, not empty.
3. **Are you filtering on `ContentType`?** `PutEvents` events carry
   `application/eventbridge+json`, not `application/json`. A filter for `application/json` will not
   match them.
4. **Do you have more than one filter?** All filters must match. They are ANDed. Two filters that are
   each individually correct can still combine to match nothing.

---

## 6. Read the failure: subscriber logs, then the dead-letter record

Two surfaces name the cause. Logs are faster, because a dead-letter record only
appears after retries are exhausted, which takes the full retry window.

**Subscriber logs are off by default.** `LogConfiguration.Level` defaults to `OFF`, so a subscriber
you did not configure for logging has emitted nothing. Turn it on:

```
UpdateSubscriber {
  "SubscriberArn": "...",
  "LogConfiguration": { "Level": "INFO", "IncludePayload": "FULL" }
}
```

`INFO` records every attempt including successes, which is what you want while diagnosing. `ERROR`
records failures only. The Create and Update responses do not echo the field, so you SHOULD confirm with
`DescribeSubscriber`. Records reach a destination through a CloudWatch Logs delivery, so you MUST
create one for
the subscriber if you have not, because raising `Level` with no delivery configured produces nothing
readable.
The three-call delivery setup is in [observability.md](observability.md).

Then reproduce and read the `EVENT_DELIVERY_ATTEMPT` records. The fields that answer this question
fastest:

| Field | Tells you |
|---|---|
| `details.outcome` | `SUCCESS` or `FAILURE`, per event per attempt |
| `error.error_code`, `error.error_message` | the cause, in the target service's own words |
| `details.target_input` | what was actually sent to the target, which settles any transformer or parameter question |
| `details.http_status`, `details.target_request_id` | the target's own response, for correlating inside the target service |
| `details.attempt_count` | whether retries are happening at all |

Two readings settle where the failure happened:

* No records at all means the event never reached the subscriber, so the fault is upstream of delivery:
  go back to steps 4 and 5.
* An empty `details.target_request_id` on a failed attempt means the call never left this service. That
  is an input-evaluation or local SDK conversion failure, so the expression or the resolved request is
  wrong rather than the target.

Read `details.target_input` when an expression is suspected, because it shows what
the target received rather than what you meant to send.

**The dead-letter record** is the other surface. If a dead-letter queue is configured, read it; the
record names the cause and you are done.

If no dead-letter queue is configured, you **SHOULD configure one and reproduce**, because with neither
logs nor a dead-letter queue a delivery failure leaves no readable trace anywhere.

```
UpdateSubscriber {
  "SubscriberArn": "...",
  "OnFailureConfiguration": { "Arn": "arn:aws:sqs:...:my-dlq" }
}
```

The ARN's shape is checked, so a malformed value is rejected outright. Then you **SHOULD** read the
subscriber back and confirm `OnFailureConfiguration` is populated: other nestings of that field are
accepted and stored empty, so a read-back is the only confirmation that a dead-letter queue exists.

Record shape, from a real access-denied failure:

```json
{
 "version": "1.0",
 "busArn": "arn:aws:events:us-east-1:111122223333:event-busv2/my-bus/...",
 "subscriberArn": "arn:aws:events:us-east-1:111122223333:subscriber/my-sub/...",
 "targetArn": "arn:aws:sqs:us-east-1:111122223333:my-queue",
 "errorCode": "ACCESS_DENIED",
 "errorMessage": "User: ... is not authorized to perform: sqs:sendmessage on resource: ...",
 "exhaustedRetryCondition": "MaximumRetryAttempts",
 "retryAttempts": 5,
 "failedMessages": [
  { "eventId": "...", "eventGroupId": "g9", "deduplicationId": "order-1234",
    "timestamp": "2026-09-07T01:43:53.768Z", "targetRequestId": "..." }
 ]
}
```

How to read it:

| Field | Use |
|---|---|
| `errorCode` | the class of failure, for example `ACCESS_DENIED`, `CUSTOMER_VALIDATION`. `CUSTOMER_VALIDATION` collapses every customer fault, so it does not by itself say which |
| `errorMessage` | the target service's own message, usually the exact answer. Truncated at 1024 characters |
| `exhaustedRetryCondition` | `MaximumRetryAttempts` or `MaximumEventAgeInSeconds`, tells you which limit ended it |
| `retryAttempts` | how many retries happened. **`0` means the retry budget was zero, or the age limit ended it at the first attempt — not that the fault was permanent**, since permanent faults are retried too |
| `failedMessages[].eventId` | which events failed, for correlating against the publish response and the log record |
| `failedMessages[].targetRequestId` | the target's own request id. Empty when the call never left this service |

Three limits. `failedMessages` **does not carry the payload**, so the record alone is not enough to
reconstruct the event; you need the event still inside the retention window. `deduplicationId` is
present whenever the event carried one, including for an `UNORDERED` subscriber, so its presence tells
you nothing about the subscriber's `Type`. And treat the `errorCode` set as open: match on the string
rather than an enum.

**Once you have `error_code` and `error_message`, classify the failure.**
[target-contract.md](target-contract.md) §5 has the full table: which classes are permanent, which are
retried, and which entries a partially failed batch retries. Every class is retried on the same budget,
so the class tells you whether retrying can help, not whether a retry happens.

---

## 7. Can the delivery role write both the target and the dead-letter queue?

The role in `InvokeConfiguration.RoleArn` MUST have the target's own action **and** `sqs:SendMessage` on
the dead-letter queue.

Granting the target but not the dead-letter queue means deliveries fail, the failure record cannot be
written, and nothing is observable anywhere. A denied dead-letter
queue produces total silent loss.

You SHOULD check with the target's action for your target type: `sqs:SendMessage`, `sns:Publish`,
`lambda:InvokeFunction`, `kinesis:PutRecord`, `states:StartExecution`, or the API your universal
target calls.

Corrections to that list. Kinesis delivery calls `PutRecords`, so the action is `kinesis:PutRecords`,
and Firehose calls `PutRecordBatch`, so its action is `firehose:PutRecordBatch`. An API Gateway target
needs `execute-api:Invoke`, an API destination needs `events:InvokeApiDestination`, and another new
custom bus needs `events:PutEvents` **and** `events:PutRawEvents`. Full table in
[target-configuration.md](target-configuration.md).

Create checked the ARN's shape, target type, region, partition and account, so a wrong-region,
wrong-partition, cross-account or wrong-shape target was rejected outright and never reached this point.
Create did **not** check existence or reachability, so a well-formed ARN naming a target that does not
exist is the case that arrives here and fails at delivery.

---

## 8. Does the target service accept what you are sending?

The target enforces its own rules at delivery time, and for most targets this service cannot tell you
about them at create time.

* **Size.** The binding limit is the target's, after enveloping, not the publish limit. Through SNS a
  payload around 200 KB is delivered, while payloads at 250 KB and above are accepted by the publish
  call and never arrive, because SNS caps the enveloped message at 256 KB.
* **Value ranges.** The target owns these, and the service does not keep a copy, so **neither a
  literal nor an expression is range-checked at create.** A `DelaySeconds` of `999999` and of
  `{% 999999 %}` are both stored and both rejected by SQS with a 400 `InvalidParameterValue`. A create
  call that succeeded says nothing about the value.
* **Required and applicable members.** The target also owns whether a member had to be there and
  whether it applies to the resource you named. An absent `MessageGroupId` on a `.fifo` queue or topic,
  a `MessageDeduplicationId` on a standard queue, a per-message `DelaySeconds` on a FIFO queue, and a
  message attribute with no `DataType`, and an `UNORDERED` subscriber targeting a FIFO queue are each
  accepted at create. The target decides whether delivery succeeds.
* **Name and identifier formats.** Execution names, message group ids, and deduplication ids are
  checked by the target for character set, emptiness, and length, so a blank or too-long group id
  surfaces as a delivery failure rather than a create-time rejection.
* **Batch APIs can fail per entry inside an HTTP 200.** SQS, SNS, and Kinesis deliveries use
  `SendMessageBatch`, `PublishBatch`, and `PutRecords`. A 200 carrying a failed-entry list retries
  only those entries, so a partly failing batch shows as neither a clean success nor a clean failure.
* **Required fields.** For universal targets, the target API's required fields are checked at create
  time and the message names them, for example
  `UniversalTargetParameters.Input is missing required field(s): Item, TableName`.

---

## 9. Is a per-message field pinned to a constant?

A deduplication id is per-message by nature. A constant value is accepted at create time and is
almost never correct: the target treats every message after the first as a duplicate of the first and
discards it. The symptom is exactly one message arriving and then nothing.

Same reasoning applies to any field the target uses for identity or ordering, including a Step Functions
execution `Name`, which **MUST** be unique per account, region, and state machine. You **SHOULD** derive
them with a JSONata expression rather than a literal.

---

## 10. Did a transformer or target parameter resolve to nothing?

An expression that resolves to nothing produces an empty value, not an error. The delivery then either
carries an empty field or is rejected by the target for an empty required field.

Diagnostic: create a second subscriber with `Transformer: { Type: WITH_METADATA }` and no filter,
pointed at a queue you own. That delivers the event exactly as the service sees it, three-part
envelope and all, which tells you the true addressing for your traffic and settles any expression
question.

Worked example of this failure. A universal target writing DynamoDB with
`{% { "TableName": "t", "Item": { "pk": { "S": $events.Data.m } } } %}` against `PutEvents` traffic
fails with a dead-letter record reading:

```
errorCode: CUSTOMER_VALIDATION
errorMessage: Supplied AttributeValue is empty, must contain exactly one of the supported datatypes
```

The expression should be `$events.Data.detail.m`. The target and the permissions are not at fault.

A related failure has a different message and the same cause: an expression that **throws** rather than
resolving to nothing, for example `$number()` applied to a non-numeric field. That fails inside the
invoker before any target call, so the dead-letter record carries no `targetRequestId`.

---

## 11. Is one bad event blocking a group?

With the subscriber's `Type: FIFO`, events are ordered within an `EventGroupId`. An undeliverable event can
hold up others in its group.

Test by publishing with a distinct `SystemMetadata.EventGroupId`. If the new group flows and the old
one does not, you have a stuck group, not a broken subscriber.

---

## Building a test rig that does not lie to you

Two measurement mistakes produce wrong counts.

**Reading an SQS queue without deleting the messages re-reads them.** A receive with
`--visibility-timeout 0` returns the same messages on the next call, so raw counts overstate
deliveries. You SHOULD either consume as you read (receive, then delete by receipt handle), or
deduplicate on a
marker you put in the payload.

**A shared target accumulates messages from earlier runs.** You SHOULD use a fresh target per
experiment, or a
marker unique to the run.

Reliable sequence:

1. Create the bus and wait with `aws eventsv2 wait event-bus-active`.
2. Create the subscriber with `OnFailureConfiguration` and `LogConfiguration.Level: INFO` set from the
   start, so a failure is readable without a second attempt. Then allow a short delay before publishing.
3. Publish with a unique marker inside the payload, and make the subscriber's filter match that marker,
   so a shared bus delivers only this run's events.
4. Read the target. Live delivery is fast, so a poll loop with a short
   interval and a generous overall timeout tells you more than one long sleep.
5. Consume the target and match on the marker.

Two refinements belong in the rig. You **SHOULD** publish repeatedly rather than once, on a short
interval, while polling: a subscriber's routing takes a moment to converge after activation, so a single
up-front publish can be missed by a subscriber that is otherwise correct. And you **SHOULD** set
`MaxRetryAttempts: 0` when testing a failure path, because otherwise a fault that retrying cannot fix is
retried for the whole window and the dead-letter record is delayed by every attempt.

If you are measuring latency rather than correctness, a per-call `aws` CLI invocation adds its
own process startup time, which can dominate the delivery time you are trying to measure. You SHOULD
use an SDK in a
single process for that.
