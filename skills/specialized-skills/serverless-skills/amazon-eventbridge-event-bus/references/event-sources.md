# AWS service and partner event sources

Load this when you want AWS service events or partner (SaaS) events on a new custom event bus, or when
forwarded events are not arriving or not matching a filter you expected them to match.

An **event source** is a managed feed. You create one, naming a destination bus and one origin, and the
service stands up the forwarding on the classic EventBridge side for you: a rule and a target, plus a
dedicated event bus for a partner origin. You supply no role and no delivery code.

This file covers managed forwarding. Forwarding through non-managed rules and targets is a separate
mechanism and is not covered here.

---

## Creating one

`CreateEventSource` names the destination bus and one origin. **The bus MUST be past creation**: the
permitted states are `ACTIVE`, `UPDATING`, and `UPDATE_FAILED`. A bus still `CREATING` refuses the call
with `InvalidStateException` reading `EventBus is in invalid state for CreateEventSource. Must be in one
of [ACTIVE, UPDATING, UPDATE_FAILED]`, so create the bus, wait on the `event-bus-active` waiter, and then
create the event source.

## The two origins

`Configuration` is discriminated and **exactly one variant MUST be set**:

| Variant | Origin | Required member |
|---|---|---|
| `AwsServiceEventsConfiguration` | events one AWS service emits into your account | `AwsService` |
| `PartnerEventsConfiguration` | events a partner emits through a classic partner event source | `PartnerEventSourceArn` |

Both variants also take an optional `Pattern` and an optional `OnFailureConfiguration`. The partner
variant additionally takes `PartnerBusKmsKeyIdentifier`.

`AwsService` names **one** service, as `aws.s3` or `aws.ec2`. The model pattern is `aws\.[a-z0-9\-]+`, so
a list, a wildcard, or a bare service name is rejected at the SDK.

`PartnerEventSourceArn` names a classic partner event source, which the partner owns rather than you.
**Pass the ARN that classic's own `DescribeEventSource` returns to you** for that source name, in your
account. The model leaves the account segment optional, because a partner-owned ARN can carry an empty
one, so both forms pass validation and only the value classic gave you resolves to a source you were
offered.

The service derives a type from the variant you set, and reports it as `Type` on a list row:
`AWS_SERVICE_EVENTS` or `PARTNER_EVENTS`.

## Name and ARN

`Name` is flat: it starts with an alphanumeric character, may then carry `.`, `-`, and `_`, and **cannot
start with `aws.`**. It carries no slashes, so the ARN below stays unambiguous. Names are unique per
account rather than per bus.

The ARN the service returns is:

```
arn:aws:events:{region}:{account}:event-sourcev2/{type}/{name}/{id}
```

`{type}` is `aws.service` or `aws.partner`, set by the service from your configuration, never supplied by
you. `{id}` is the generated 25-character identifier. Putting the type in the ARN lets a policy scope by
type in the `Resource` element alone, as in
`arn:aws:events:*:{account}:event-sourcev2/aws.partner/*` to cover partner event sources and nothing else.

The resource token is `event-sourcev2`, distinct from classic's `event-source`. A policy written against
classic partner event source ARNs does not match these.

---

## What a forwarded event looks like on the bus

This is the part that breaks expectations carried over from classic, so read it before writing a filter.

A forwarded event arrives carrying **the whole classic envelope as its payload**:

* `Data` holds the classic envelope JSON: `version`, `id`, `source`, `detail-type`, `account`, `time`,
  `region`, `resources`, and `detail`. Your own event content is under `Data.detail`.
* `SystemMetadata.ContentType` is `application/eventbridge+json`, which labels it as an envelope rather
  than a bare payload.
* `SystemMetadata` also carries **`aws:Source` and `aws:DetailType`**, set by the service from the
  envelope. For a forwarded AWS service event `aws:Source` is the service, as `aws.s3`. For a forwarded
  partner event it is the partner event source name. The two keys arrive together or not at all.

So the addressing is the same as any `PutEvents` event (chapter 6): your field `m` is at
`$events.Data.detail.m`, and the envelope's own fields are at `$events.Data.source` and
`$events.Data.detail-type`.

Side by side, the same S3 event. On the classic bus, the event is the envelope, and a rule pattern
addresses its top level:

```json
{ "source": ["aws.s3"], "detail": { "bucket": { "name": ["my-bucket"] } } }
```

Forwarded onto the new bus, that whole envelope is the payload, the provenance pair sits in system
metadata, and a subscriber filter names a `Scope`:

```json
{ "Scope": "SYSTEM_METADATA", "Pattern": "{\"aws:Source\":[\"aws.s3\"]}" }
{ "Scope": "DATA", "Pattern": "{\"detail\":{\"bucket\":{\"name\":[\"my-bucket\"]}}}" }
```

A classic pattern pasted into a subscriber filter unchanged matches nothing it should, and if it carried
`wildcard` it is rejected outright (see [filters-and-expressions.md](filters-and-expressions.md)). When a
filter that worked on classic matches nothing here, **read what was actually delivered before editing the
pattern**: point a `WITH_METADATA` subscriber with no filter at a queue you own, which shows the payload
and both metadata scopes, or read the subscriber log's recorded input
([delivery-troubleshooting.md](delivery-troubleshooting.md)), and write the pattern against that.

### Filtering forwarded events

A classic rule filtered on the top-level `source` and `detail-type`. **That pattern does not transfer**,
because on a new bus those values are not top-level event fields. You have two addresses for them:

| What you match | Scope | Pattern |
|---|---|---|
| the trusted source the service set | `SYSTEM_METADATA` | `{"aws:Source":["aws.s3"]}` |
| any AWS service or partner origin | `SYSTEM_METADATA` | `{"aws:Source":[{"prefix":"aws."}]}` |
| the envelope's own copy | `DATA` | `{"source":["aws.s3"]}` |
| your event content | `DATA` | `{"detail":{"orderId":[{"exists":true}]}}` |

**You SHOULD match the `SYSTEM_METADATA` form when provenance matters**, and the reason is not style.

`aws:Source` and `aws:DetailType` are service-written. No publish call can set them: the publish APIs
expose no member that reaches them, and a customer metadata key literally named `aws:Source` lands in the
separate `METADATA` scope and never collides. So a `SYSTEM_METADATA` match on that pair is the only match
that establishes an AWS service or a partner produced the event.

A payload can imitate the envelope perfectly. Publish a raw event whose body carries
`{"source":"aws.s3","detail-type":"Object Created","detail":{...}}` and a `DATA` filter on
`{"source":["aws.s3"]}` matches it exactly as readily as the genuine forwarded event. That is not a defect
in the filter. It is why the guarantee is written on system metadata: payload bytes are yours to write, so
matching them proves nothing about origin.

Matching on the presence of `aws:Source` is also not enough. A direct `PutEvents` to the same bus sets
the key too, from its own `Source`, which is never `aws.`-prefixed because that prefix is reserved.
**You MUST match the value**, either with the `aws.` prefix or an exact source.

**When a subscriber forwards to another bus, only `RAW` carries both keys across.** A `WITH_METADATA` or
`JSONATA` transformer drops them, so the event arrives on the second bus with no `aws:Source` and no
`aws:DetailType`, and a filter on either key there matches the `RAW` hop and neither of the other two.
The transformer decides this, not the source value, so a custom source is dropped like an `aws.` one.

To any other target, a `WITH_METADATA` transformer writes both keys into the message body, where they are
data the consumer reads rather than a value the service vouches for.

---

## The pattern on the event source

`Pattern` is optional. Absent, every event from the origin forwards. Supplied, it narrows what forwards,
and it is evaluated on the classic side against the classic envelope, so it is written in classic event
pattern syntax against envelope fields.

**Your pattern MUST NOT carry a `source` key, nor a top-level `account` or `region`**, because the service
sets all three itself to pin the forward to your account and the origin you named. Supplying one is
rejected with `InvalidInputException`.

The pattern is capped at 3753 characters. That is the classic 4096-character budget less what the keys the
service adds consume, so a pattern the SDK accepts always fits once those are merged in.

Narrowing at the event source and narrowing at a subscriber do different work. The event source pattern
decides what crosses onto your bus, so it decides what you are billed to ingest and store. A subscriber
filter decides what one consumer receives from what already arrived.

---

## Lifecycle

| State | Meaning |
|---|---|
| `CREATING`, `UPDATING`, `DELETING` | the operation's classic-side work is in progress |
| `ACTIVE` | the event source is forwarding |
| `CREATE_FAILED`, `UPDATE_FAILED` | the classic-side work failed. `DescribeEventSource` returns no reason field, so the detail is not readable from the record |
| `DELETE_FAILED` | teardown failed partway |

**Read the state back with `DescribeEventSource`** rather than assuming when the provisioning completes
relative to the response.

`Revoked` is not a state. It is a separate flag, and a revoked event source keeps whatever lifecycle state
it had ([authorization.md](authorization.md)).

**Recovery differs by which failure you have.** From `CREATE_FAILED` or `UPDATE_FAILED`, an
`UpdateEventSource` that includes the `Configuration` converges the classic side back to your record,
recreating whatever is missing; an update that changes only the description converges nothing.
`DeleteEventSource` tears down whatever exists. From `DELETE_FAILED` **the only recovery is calling
delete again**, because an update would rebuild the resources you asked to remove. Delete tolerates an
already-gone resource at every step, so repeating it is safe. A record in `CREATING`, `UPDATING`, or
`DELETING` can refuse delete with `InvalidStateException` telling you to wait for the in-flight
operation to settle.

The destination `EventBusArn` is **immutable**. Moving a feed to another bus means deleting the event
source and creating a new one, into a bus in one of the states named above.

### Update replaces the whole configuration block

`UpdateEventSource` takes `EventSourceArn`, `Configuration`, and `Description`. The general rule from
chapter 16 applies exactly: an omitted top-level member is unchanged, and a supplied block replaces that
whole block.

So an update that supplies `Configuration` in order to change the pattern, and omits
`OnFailureConfiguration`, **removes the dead-letter queue**. An update that supplies `Configuration`
carrying only `AwsService` removes the pattern. Both are the documented behaviour rather than a defect.

**You MUST read the event source with `DescribeEventSource`, modify the whole configuration, write it
back, and read it back again** to confirm what was stored.

### Idempotency

`CreateEventSource` carries a `ClientToken`. The SDK generates one per call, so a retry your own code
issues builds a new token and creates a second event source unless you supply your own.

* Same token, same parameters, inside 8 hours: the stored event source is returned.
* Same token, different parameters: `IdempotentParameterMismatchException`.
* A name already taken, outside a retry: `ResourceAlreadyExistsException`.
* Same token after the event source was deleted: a **new** event source with a new ARN. Delete removes the
  idempotency record with the resource, so the token cannot resurrect it.
* No token at all: `InvalidInputException`. Every SDK sets one, so this reaches you only from a hand-built
  request.

Two updates racing each other do not interleave. The one that loses gets a `ConcurrentModificationException`,
which is retryable.

### On a bus encrypted with a customer managed key

The destination bus's key policy has to admit the producer, not just the bus owner. A producer whose access
the key policy does not admit **fails closed on create, update, and describe** of the event source, because
those operations read and write customer-authored fields under that key. So a cross-account feed onto an
encrypted bus needs the bus owner to admit the producer account in the key policy as well as in the bus
policy ([security-and-sharing.md](security-and-sharing.md)).

---

## What appears in your classic account

The forwarding classic resources are visible in the account that owns the event source, marked as managed:

| Surface | What you see |
|---|---|
| classic `ListRules` / `DescribeRule` | the managed rule, with `ManagedBy` set to the EventBridge service principal |
| classic `ListTargetsByRule` | one target, the destination bus ARN, with no role, plus the dead-letter queue when you configured one |
| rule and target updates | rejected: the rule is managed |
| rule and target deletes | **allowed**. Deleting one stops the forwarding, and an `UpdateEventSource` that includes the `Configuration` is the way to rebuild it |
| classic vended logs | suppressed for managed rules, so the forwarding does not appear in them |
| classic rule metrics | **not** suppressed, so the managed rule reports its own match and delivery metrics |
| CloudTrail | the event source API call you made, and the classic `DescribeEventSource` at a partner create |

Managed rules do not consume your classic rule quota.

---

## Partner event sources

A partner event source is created by the partner, not by you, and offered to a specific account. Two
prerequisites before you can create an event source for it:

1. The partner MUST have offered the source **to your account**. Referencing a source the partner offered
   to a different account fails with `InvalidInputException`, because the check runs under your own
   credentials in your own account and the source is not there.
2. The classic source MUST be in state `PENDING`. That is the state a source sits in until a bus is
   created for it.

Creating the event source creates a dedicated event bus for that partner source, named after the source,
and **creating that bus is what activates the source**: it moves to `ACTIVE` and partner events start
arriving on it.

**That bus is managed and locked.** It appears in `ListEventBuses` and `DescribeEventBus` carrying a
`ManagedBy` marker. Your `UpdateEventBus` and `PutRule` against it are rejected while the event source
owns it. `DeleteEventBus` stays available as an escape hatch, and `UpdateEventSource` rebuilds what you
remove. The bus counts toward your classic event bus quota and is metered as any partner bus.

Deleting the event source deletes that bus and returns the partner source to `PENDING`, from where it can
be bound again. A source left in `PENDING` expires after about two weeks.

### Encrypting the partner bus

`PartnerBusKmsKeyIdentifier` sets the key for the managed partner bus. It MUST name a key in **your own
account and region**. Two checks run at create and at any change, under your own credentials:

* `kms:DescribeKey`, which proves the key exists and is usable.
* a `kms:Decrypt` dry run, which proves **you** may use it. A key policy can allow `DescribeKey` while
  denying `Decrypt`, and without this check that would surface only later, at runtime.

So a key you can describe but not decrypt is rejected at create. A grant revoked afterwards fails at
runtime instead, and those failures land in the dead-letter queue.

Because customer `UpdateEventBus` on the managed bus is locked, changing the key goes through
`UpdateEventSource`.

---

## Dead-lettering

`OnFailureConfiguration.Arn` names one SQS queue. It MUST be a **standard** queue in your own account and
region. A FIFO queue is refused with one message:
`OnFailureConfiguration.Arn must name a standard SQS queue: FIFO queues are not supported as EventSource dead-letter queues`

**The queue's own resource policy is what admits the send.** EventBridge sends under its own credentials
and there is no role in this path, so granting a role `sqs:SendMessage` achieves nothing here. This is the
opposite of a subscriber's dead-letter queue, where the delivery role you supply needs the grant
(chapter 13).

For a partner event source **one queue receives under two different source ARNs**: the managed rule's, for
delivery failures, and the managed partner bus's, for encryption failures on that bus. A queue policy
conditioned on `aws:SourceArn` MUST admit both, or one class of failure is dropped.

What reaches the queue is a delivery the destination refused, or a delivery to a bus that is gone.
Transient failures are retried first.

---

## Cross-account, and what a bus owner controls

`CreateEventSource` and `UpdateEventSource` are authorized **against the destination bus**, so attaching a
feed to someone else's bus needs that bus owner's permission. The check carries the `events:source`
condition key, holding the AWS service or the partner source name, so an owner can allow one origin and
not others.

A bus owner grants it through AWS RAM:

| Managed permission | Carries `events:CreateEventSource` |
|---|---|
| `AWSRAMEventBridgeEventBusV2FullAccess` | yes |
| `AWSRAMEventBridgeEventBusV2EventSourceAccess` | yes, and little else |
| `AWSRAMEventBridgeEventBusV2PublishOnly` | **no** |

So a producer holding only the publish-only permission can publish to the bus and cannot attach an event
source to it. Deleting the share stops further creates once the revocation converges.

**A bus owner's control is at create time, not at delivery time.**

* Authorizing `events:CreateEventSource` on the bus is the decision that admits a feed. Treat it as such.
* Removing a share afterwards does not stop an event source that already exists.
* **To stop an existing feed, the owner uses `RevokeResource`**, which stops the ingestion of its events
  and is terminal ([authorization.md](authorization.md)). Revoking stops the events reaching the bus. It
  does not stop the classic side forwarding them, so the refused deliveries dead-letter into the producer
  account's own queue for as long as the event source exists. Deleting it is what stops the forwarding,
  and only its owner can delete it.

Same-account event sources need no policy of this kind.

Reads are owner-scoped. `DescribeEventSource` is available to the owning account only. `ListEventSources`
defaults to the event sources the calling account owns; passing `EventBusArn` scopes it to one bus, and a
bus owner using that form sees every event source targeting their bus, each row carrying its
`EventSourceAccountId`.

---

## Observability

Publish metrics for forwarded traffic carry the `EventSource` dimension in addition to `{EventBus}`, which
is what gives you a per-event-source ingest breakdown. Managed forwarding is the only path that can be
attributed this way ([observability.md](observability.md)).

There is no per-event-source log configuration and no publish-path logging for forwarded events. Delivery
failures reach you through the dead-letter queue instead.
