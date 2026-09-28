# Observability: metrics and logs

Load this when setting up monitoring or alarms, or when reading delivery logs to diagnose a failure.

Two surfaces tell you what the service is doing: CloudWatch metrics, which are on by default, and
subscriber logs, which are off by default and which you turn on per subscriber.

## Publish metrics

Metrics are published to the customer-vended **`AWS/EventsV2`** namespace.

| Metric | Counts | Per |
|---|---|---|
| `PublishEventsApproximateCallCount` | publish calls, whatever their outcome | call |
| `PublishEventsApproximateSuccessCallCount` | calls that returned a response | call |
| `PublishEventsApproximateFailedCallCount` | calls that threw anything other than `ThrottlingException` | call |
| `PublishEventsApproximateThrottledCallCount` | calls that threw `ThrottlingException` | call |
| `PublishEventsEntryCount` | entries submitted | entry |
| `PublishEventsFailedEntriesCount` | entries rejected | entry |
| `PublishEventsIngressBytes` | bytes stored | byte |

**The three outcome metrics describe the request, not the events in it.** Exactly one of them fires per
call. A call that returned a response counts as a success even when every entry inside it was rejected, and
that case reads as `PublishEventsFailedEntriesCount` equal to `PublishEventsEntryCount`. So a healthy
`PublishEventsApproximateSuccessCallCount` does not mean events landed; compare the two entry counts for
that.

A per-entry throttle lands in `PublishEventsFailedEntriesCount`, because only a whole-request
`ThrottlingException` counts as a throttled call.

**A whole-request failure or throttle still reports every entry.** `PublishEventsEntryCount` carries the
submitted total on all three outcomes, and `PublishEventsFailedEntriesCount` carries that whole total on a
failure or a throttle, so entry-level ratios stay meaningful through an outage.

### `PublishEventsIngressBytes`

This is the stored size rather than the size you sent. The measurement is taken after the service builds
and encrypts the stored message, so system metadata and framing are inside it, and the two publish APIs
store different shapes: `PutEvents` stores a composed envelope, and `PutRawEvents` stores your bytes with
their content type. So a 1 KB event is not 1 KB of ingress.

It trends your ingress bill without equalling it, because billing rounds each entry up to a whole KB before
summing while this metric sums the raw stored sizes. Entries of 0.6, 1.5, and 2.2 KB bill as 6 KB and
report here as 4.3 KB.

A deduplicated entry stores nothing, so it contributes no bytes while still counting as a successful entry.
So `PublishEventsEntryCount` does not decompose into bytes plus failures.

It is absent rather than zero when a call stored nothing, so an interval with no datapoint means nothing was
stored rather than data missing. `PublishEventsApproximateCallCount` is the companion that separates an idle
interval from calls that stored nothing.

### Dimensions

Metrics carry dimension tuples rather than independent dimensions:

| Tuple | Carries | Emitted when |
|---|---|---|
| `{EventBus}` | every metric above | always |
| `{EventBus, EventSource}` | the count metrics, and not the bytes | the call is attributed to a registered event source |
| `{EventBus, PublisherAccount}` | `PublishEventsIngressBytes` alone | in the bus owner's account, when bytes were stored |

**Only managed forwarding from classic EventBridge is attributed.** That path carries a signed header
naming the classic forwarding rule, which identifies the event source behind it. A do-it-yourself
forwarder, a bus-to-bus forward, and a direct `PutEvents` or `PutRawEvents` all emit `{EventBus}` alone.

**The `{EventBus, EventSource}` tuple is emitted in addition to `{EventBus}`, not instead of it.** So
summing one metric across both tuples counts attributed traffic twice.

Both dimension values are compound, and neither is an ARN:

| Dimension | Value | Example |
|---|---|---|
| `EventBus` | the bus name and the generated id from its ARN, joined by a slash | `my-bus/exampleid0123456789abcdef` |
| `EventSource` | the discriminator, the name, and the generated id, joined by slashes | `aws.service/my-source/exampleid0123456789abcdef` |

Querying `EventBus` with the full bus ARN returns no data and looks identical to no traffic.

Every one of these lands in the bus owner's account, and in the publishing account too when the two
differ. The publisher's copy omits the `{EventBus, PublisherAccount}` bytes, which stay with the bus
owner. So a bus owner can attribute stored bytes to a publishing account with no cross-account setup, and
a publisher reads its own traffic from its own account.

A call whose event bus cannot be resolved emits no publish metrics at all, and neither does a call that
throws before the service records its step.

`PublishEventsApproximateCallCount` against `PublishEventsApproximateSuccessCallCount` is the cheapest check
that your producer is reaching the bus at all, and `PublishEventsFailedEntriesCount` is how you notice
per-entry rejections that a caller ignoring individual entry results would otherwise miss (chapter 21).

There is no delivery-side metric to alarm on. Every metric above is publish-side, so a subscriber that
fails every delivery moves none of them. Delivery health has to come from the logs and the dead-letter
queue, which is why both are worth configuring before you need them rather than after.

## Audit with CloudTrail

**You SHOULD enable a CloudTrail trail covering this service before you run a bus in production.** Both
planes are recorded, and they are recorded differently, so a trail answers questions the metrics above
cannot.

Control-plane calls arrive as management events: who created or deleted a bus, who attached or revoked a
subscriber, who changed a resource policy, and every KMS operation the service ran against your key under
the key policy in [security-and-sharing.md](security-and-sharing.md). The metrics tell you a subscriber
stopped delivering. The trail tells you which principal changed it.

Publishes arrive as data events, recorded per entry rather than per call. One batch publish produces a
record for the call and a record for each entry in it. An entry's record carries that entry's own outcome,
its assigned event id and success code where it succeeded and its error code where it did not, so a
partly failed batch is attributable to the entries that failed. Two fields join the records: a parent
request id links an entry record to its call record, and an entry index gives the entry's position in the
batch.

That index is the only way to tell which entry a record describes, because **no event payload reaches the
trail.** A `PutEvents` entry contributes its `Source` and `DetailType`, and its `Detail` is dropped. A
`PutRawEvents` entry contributes nothing, because both `Data` and `Metadata` are dropped. So the trail
tells you who published what kind of event and with what outcome, and never what the event said.

Entry records exist only where the publish reached the point of having per-entry outcomes. A call rejected
before that, an authorization denial for example, leaves the call-level record alone. So no entry records
is not evidence that nothing was published, and the call record is what settles it.

EventSource events are audited against the event source rather than as a publish you made: each record
describes an event arriving through your event source, and names the event source as the resource it
happened to. Forwarding through non-managed rules and targets is recorded as an ordinary publish instead,
because that is what it is. Both attribute the record to the producing account.

For the wider control set, see the AWS security best practices guidance at
https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html

## Subscriber logs

Delivery detail comes from per-subscriber logging, set with `LogConfiguration`:

| Field | Values | Default |
|---|---|---|
| `Level` | `OFF`, `ERROR`, `INFO` | `OFF` |
| `IncludePayload` | `FULL`, `ON_ERROR_ONLY` | `ON_ERROR_ONLY` |

`Level: OFF` is the default, so **a new subscriber emits no logs until you ask for them.** Set `ERROR` to
record failures only, or `INFO` to record every delivery attempt including the successes.
`IncludePayload: FULL` embeds the event payload in every record, which is what you want while debugging and
which you SHOULD reconsider afterwards, both for log volume and because the payload is your own data.

**`IncludePayload: FULL` copies your event bodies out of the bus and into the log group, so the bus's own
encryption stops protecting them there.** The log group is encrypted under its own key, and a reader with
`logs:GetLogEvents` on that group reads every payload. So three things follow. You SHOULD encrypt the
destination log group with a customer managed key (`aws logs associate-kms-key`). You SHOULD scope read
access to that group as tightly as access to the bus. And you SHOULD set `ON_ERROR_ONLY`, or
`Level: ERROR`, once a diagnosis is finished.

A dead-letter queue does not create the same exposure, because a dead-letter record references the failed
events instead of containing them; [target-contract.md](target-contract.md) has the record's fields. Scope
the queue for the identifiers it does hold, since the event group id and the deduplication id are values
you chose and can carry meaning of their own.

You MAY set `LogConfiguration` at create time or with `UpdateSubscriber`, and it takes effect without
recreating the subscriber. The Create and Update responses do not echo the field back, so you SHOULD
confirm it with
`DescribeSubscriber`, which does return it. This is the same read-back discipline chapter 16 asks for.

### Setting up the log delivery

Records reach a log group through the CloudWatch Logs vended-log delivery mechanism, and until you
wire it up, no log group appears on its own: turning `Level` up produces nothing you can read. The
wiring is three CloudWatch Logs calls that pair the subscriber with a destination:

```bash
aws logs create-log-group --log-group-name /aws/vendedlogs/my-subscriber-logs

aws logs put-delivery-source --name my-sub-source \
  --resource-arn "$SUBSCRIBER_ARN" \
  --log-type TRACE_LOGS

aws logs put-delivery-destination --name my-sub-dest \
  --delivery-destination-configuration destinationResourceArn=arn:aws:logs:us-east-1:111122223333:log-group:/aws/vendedlogs/my-subscriber-logs

aws logs create-delivery \
  --delivery-source-name my-sub-source \
  --delivery-destination-arn <the DeliveryDestination ARN returned by put-delivery-destination>
```

Three details that break this when missed:

* The log group name MUST start with `/aws/vendedlogs/`, because CloudWatch Logs auto-manages the
  delivery resource policy only for that prefix. A log group elsewhere needs its policy managed by
  hand.
* The delivery source's `resource-arn` is the subscriber ARN, and the `log-type` for subscriber
  delivery logs is `TRACE_LOGS`.
* One delivery pairs exactly one source with one destination. To send one subscriber's logs to a
  second destination, you MUST create a second delivery.

## Reading a delivery record

Each delivery attempt produces one `EVENT_DELIVERY_ATTEMPT` record per event in the batch. A record carries
a fixed set of top-level fields, plus a `details` object holding the delivery state and an `error` object
present only on failure:

| Field | Contents |
|---|---|
| `eventId` | the event this record is about |
| `messageType` | `EVENT_DELIVERY_ATTEMPT` |
| `error` | omitted on success. On failure, `error_code` and `error_message` |
| `details.outcome` | `SUCCESS` or `FAILURE` |
| `details.attempt_count` | which attempt this was, so retries are countable |
| `details.target_arn` | the target invoked |
| `details.http_status`, `details.target_request_id` | the target's own response, for correlating in the target service |
| `details.ingestion_to_start_latency_ms`, `details.ingestion_to_complete_latency_ms` | end-to-end latency from ingestion |
| `details.target_input` | what was actually sent to the target, when payloads are included |
| `details.event_detail`, `details.event_metadata`, `details.event_system_metadata` | the event as the service held it |

`details.target_input` is the field to reach for when a transformer or a target parameter is suspected,
because it shows what the target actually received rather than what you intended to send.

Three fields read together tell you where the failure happened, which is faster than reading the message
cold:

| Reading | Where it failed |
|---|---|
| no record at all for a published event | the event never reached the subscriber: filter, starting position, or addressing |
| `outcome: FAILURE`, `target_request_id` empty | before the wire call: the JSONata expression threw or produced nothing, or the resolved request could not be converted or exceeded the target's payload cap |
| `outcome: FAILURE`, `http_status` 4xx | the target rejected the call. Your request, so retrying will not help — but note it **is** retried, so `attempt_count` still climbs |
| `outcome: FAILURE`, `http_status` 5xx or 429 | the target is unhealthy or throttling. `attempt_count` climbs |
| `outcome: SUCCESS` but the target is empty | a batch API returned HTTP 200 with individually failed entries. Count at the target, not from the status |

**Do not use `attempt_count` to decide whether a fault is permanent.** Every class is retried on the same
budget, so a 4xx and a 5xx look alike in that field. `error_code` and `error_message` are what separate
them. [target-contract.md](target-contract.md) §5 has the full class table and what each class does about
retries and dead-lettering.

**The error field names differ by surface, and both are correct for their own surface.** A log record
carries snake_case fields nested under `error`: `error.error_code` and `error.error_message`. A
dead-letter record carries the same information as top-level camelCase fields: `errorCode` and
`errorMessage`. A parser written for one surface reads nothing from the other. The content matches, so
a failure is diagnosable from the log without waiting for retries to exhaust and write the dead-letter
record.

## Observability across accounts

Logs are per subscriber, so a topology spanning accounts spreads them across those accounts. Publish
metrics already reach more than one account: they land in the bus owner's account, and in the publishing
account too when the two differ. Three questions come up.

**Aggregating subscriber logs centrally.** The vended-log delivery destination can live in a different
account than the subscriber. Each subscriber's delivery source is created in the account that owns the
subscriber, the delivery destination names a log group in the central account, and the central account
MUST allow the delivery with `PutDeliveryDestinationPolicy` on that destination, naming each source
account. So a platform team can collect every consumer's delivery logs into one log group without
owning the subscribers.

**Aggregating metrics centrally.** A publish already appears in both the bus owner's account and the
publisher's, and the bus owner additionally gets ingress bytes broken out by `PublisherAccount`. Nothing
aggregates across buses in different accounts, though. For that, use CloudWatch
cross-account observability: link the bus and subscriber accounts as source accounts to a monitoring
account, and query the `AWS/EventsV2` metrics from there. The `EventBus` dimension still names one bus
per account, so a fleet-wide view is a query across linked accounts rather than a single metric.

**Correlating one event across bus hops.** There is no service-assigned identifier that follows an
event from one bus to another. `aws:EventId` identifies the event on the bus that ingested it, a
bus-to-bus forward is a new ingestion at the destination, and the publish request and delivered
envelope define no trace field. So you SHOULD put your own correlation identifier inside the
payload, or in a
`Metadata` key on `PutRawEvents`, at the original producer, and have every consumer log it. That
identifier plus the per-hop subscriber logs is the cross-account trace.
