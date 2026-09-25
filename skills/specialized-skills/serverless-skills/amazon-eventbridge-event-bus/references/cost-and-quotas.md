# Cost, throttling, and quotas

Load this when estimating cost, deciding how to shape events or subscribers for cost, or handling throttling.

## What you are billed for

Four dimensions: ingestion, delivery, retention, and enriched operations. This file states the billing
mechanics only. For the current rates, check the
[EventBridge pricing page](https://aws.amazon.com/eventbridge/pricing/), because prices change and a
figure copied here goes stale.

| Dimension | Billed on |
|---|---|
| Ingestion | per KB, rounded up |
| Delivery | per KB, rounded up |
| Retention | stored volume over time |
| Enriched operations | per operation |

Two of these change how you design, so read them as design inputs rather than as accounting.

**Rounding is per KB and upward, on both ingestion and delivery.** So a large number of small events
costs more than the byte total suggests. If you control the producer and you are publishing many tiny
events, batching related facts into one event is cheaper than sending each separately.

**"Enriched operations" are the features that do per-event work**: content-based deduplication, schema
deserialization, and JSONata evaluation. They are metered separately from ingestion and delivery. So a
JSONata transformer is billed per event, and so is `CONTENT_BASED` deduplication. You SHOULD prefer `RAW` or
`WITH_METADATA` when they suffice, and SHOULD prefer per-entry `DeduplicationId` deduplication (omit
`DeduplicationConfiguration` and set `SystemMetadata.DeduplicationId` on each entry) when you already
have a natural idempotency key, because `CONTENT_BASED` is then paying for a hash you did not need.

Delivery is billed per delivery, so fanning one event out to five subscribers bills five deliveries, a
reason to filter at the subscriber rather than deliver broadly and discard downstream.

## Who pays what in a multi-account setup

Each billing dimension has its own payer, and the split is what makes a shared bus economical:

| Dimension | Billed to |
|---|---|
| Ingestion | the account that made the publish call |
| Delivery | the account that owns the subscriber |
| Retention | the account that owns the bus |

Three consequences for a platform team running a central shared bus:

* **Consumers pay for their own consumption.** A subscriber lives in the consumer's account (its
  delivery role must belong to the account creating it), so every delivery it receives is billed to
  the consumer. Adding a consumer does not grow the bus owner's bill.
* **Publishers pay for what they publish.** A cross-account publisher's ingestion is billed to the
  publishing account, so the bus owner pays ingestion only for its own publishes.
* **The bus owner pays retention.** Retention scales with retained volume and the retention period,
  and it is the one dimension the owner pays for everyone's traffic. That is the number to watch when
  a central bus's retention period is raised for one team's replay needs.

Chargeback therefore falls out of account boundaries on its own: keep each team's subscribers and
publishers in that team's account, and each team's bill carries its own usage.

The topology changes the per-event cost shape. With hub-and-spoke, meaning consumers subscribe
directly to the central bus, one event is billed one ingestion, one retention, and one delivery per
consumer. A bus-to-bus hop, meaning a subscriber on the central bus forwards into a team's own bus,
adds a delivery (billed to the forwarding subscriber's owner) plus a second ingestion and a second
retention at the destination bus. So forward bus-to-bus when the team needs its own retention, replay
window, or access control, and subscribe directly when it does not.

## Throttling and quotas

Throttling runs on separate buckets rather than one limit, and one publish call is charged against
more than one of them at once: the account bucket for the API, and the per-event-group bucket for each
group its entries fall into. So exhausting one bucket says nothing about the others. Defaults are
raisable through Service Quotas.

| Bucket | Scope | Cost of one request |
|---|---|---|
| `PutEvents` and `PutRawEvents` combined | account | one request |
| Combined ingestion per event group | one event group on one bus | the entry count plus the total size of those entries in KB |
| `CreateSubscriber` and `DeleteSubscriber` | account | one request |
| The remaining control-plane operations | account, one shared bucket | one request |
| Each resource-policy operation | account, one bucket per operation | one request |

Five consequences follow from that shape.

The two publish buckets fail differently. The account bucket is charged per request, so exhausting it
rejects the whole call. A group over its limit fails only the entries in that group, and the rest of
the batch still publishes. So a group throttle reaches you as per-entry failures inside a call that
returned a response, and an account throttle reaches you as a `ThrottlingException` on the call.

The per-event-group bucket is size-weighted and the account bucket is not. So a producer that publishes
large events inside one event group can exhaust the group limit while the account bucket still has room,
and raising the account publish quota will not help it.

`CreateSubscriber` and `DeleteSubscriber` sit in their own account bucket, separate from both the publish
budget and the shared control-plane bucket. So a deployment that creates or tears down many subscribers
can be throttled while publishing is nowhere near its ceiling. Serialise those calls, as
[provisioning-and-state.md](provisioning-and-state.md) already requires for contention reasons.
`DescribeSubscriber`, `UpdateSubscriber`, and `ListSubscribers` stay on the shared control-plane bucket.

The resource-policy operations each throttle under their own name rather than joining the control-plane
bucket. So heavy policy reads do not consume the budget your creates and describes need.

Every one of these surfaces as `ThrottlingException` with the message `Rate exceeded.`, so the exception
alone does not tell you which bucket you exhausted. The operation you called does.

Resource counts are limited too: the number of event sources you can create is capped per account,
account-wide rather than per bus.

This file states no quota values; look them up in the Service Quotas console, because defaults change and
per-account overrides exist.

You SHOULD handle `ThrottlingException` with backoff as chapter 21 describes, and SHOULD raise the quota
rather than retrying harder if you are steadily at the ceiling, because backoff alone will not clear a
sustained overage. Creating more buses is not a remedy: the publish bucket is the account's, spanning
every bus, so spreading the same traffic across buses consumes the same budget.

Two response codes are not failures. A throttled entry inside a call that returned normally reaches you
as a per-entry failure, so read the response per entry rather than treating the call's success as every
entry's. And `SuccessCode: DEDUPLICATED` is a success, a suppressed duplicate rather than a drop
(chapter 11), so counting it as a failure inflates your error rate.
