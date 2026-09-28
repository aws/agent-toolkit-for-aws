# Messaging

Pass-2 rubric for every messaging type `index.md` routes here. Loaded only when the
inventory contains one.

**Outcome is `confidence: inferred`.** Never `deterministic` — `Microsoft.EventHub/namespaces`
is the one messaging type that _is_ a fast-path row, because owner decision 11.4 made
protocol the whole rubric and left nothing to reason about. Everything below has something
left to reason about.

The recurring shape: **Service Bus is one broker with many capabilities; AWS splits those
capabilities across SQS, SNS, EventBridge and Amazon MQ.** So the namespace does not map
to a service — its _entities_ do, and the namespace maps to whatever set they need.

## 1. Eliminators — hard technical blockers

Each is a property of the source entity, readable from IaC. Check them before anything else.

| Candidate                  | Eliminated when                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **SQS** (standard or FIFO) | the entity's `max_message_size_in_kilobytes` exceeds **1 MiB (1024 KiB)**. SQS standard and FIFO accept payloads up to 1 MiB (raised from 256 KiB on 2025-08-04, all commercial Regions + GovCloud; Lambda event source mapping updated to match); Service Bus Premium allows 100 MB. A payload at or under 1 MiB maps to SQS directly — do NOT add a claim-check for it. Only above 1 MiB: route to Amazon MQ, or to SQS with an S3 claim-check — and say which |
| **SQS**                    | `default_message_ttl` exceeds **14 days**, the SQS retention ceiling                                                                                                                                                                                                                                                                                                                                                                                             |
| **SQS FIFO**               | `duplicate_detection_history_time_window` exceeds **5 minutes**. FIFO's dedup window is fixed at 5 minutes; Service Bus allows up to 7 days. A longer window needs an idempotency table, which is application work                                                                                                                                                                                                                                               |
| **SQS**                    | messages are **scheduled more than 15 minutes** ahead (`scheduled_enqueue_time`). `DelaySeconds` caps at 900. Route long scheduling to EventBridge Scheduler or Step Functions                                                                                                                                                                                                                                                                                   |
| **SQS / SNS**              | the application speaks **AMQP 1.0 or JMS directly** rather than through the Service Bus SDK. SQS and SNS are HTTPS APIs; there is no AMQP surface. Amazon MQ is the only candidate that keeps the wire protocol                                                                                                                                                                                                                                                  |
| **SNS**                    | a subscription filter uses a **Service Bus SQL filter** that references anything other than equality on user properties — `LIKE`, `IN`, arithmetic, `sys.` system properties. SNS filter policies are attribute matching only                                                                                                                                                                                                                                    |
| **SNS**                    | the topic requires **ordered delivery with sessions**. SNS FIFO topics exist but require a FIFO SQS subscriber and offer no session concept                                                                                                                                                                                                                                                                                                                      |
| **Amazon MQ**              | the customer's stated goal includes **removing broker management**. Amazon MQ is a managed broker, not a serverless queue: it has instance sizes, patch windows and a maintenance model that SQS does not                                                                                                                                                                                                                                                        |
| **API Gateway WebSocket**  | the source uses SignalR's **server-to-client streaming or MessagePack hub protocol** unchanged. The hub protocol is SignalR-specific; either target is a client rewrite                                                                                                                                                                                                                                                                                          |

## 2. The six criteria, in order, first match wins

### 2.1 Eliminators

Section 1. Whatever survives is the candidate set.

### 2.2 Operational model

| Source                                                                                           | Target                                                                                      | Why                                                                                                                                               |
| ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Microsoft.ServiceBus/namespaces/queues`                                                         | **SQS**                                                                                     | A point-to-point queue with competing consumers is exactly SQS                                                                                    |
| `Microsoft.ServiceBus/namespaces/queues` with `requires_session = true`                          | **SQS FIFO**, session id → **message group id**                                             | Sessions are Service Bus's ordering primitive and the message group is SQS's. This is the closest mapping in the file                             |
| `Microsoft.ServiceBus/namespaces/topics`                                                         | **SNS**                                                                                     | Fan-out to multiple independent subscribers                                                                                                       |
| `Microsoft.ServiceBus/namespaces/topics` whose subscriptions carry **content-based** SQL filters | **EventBridge**                                                                             | EventBridge rules match on event content; SNS filter policies match on message attributes. If the filter reads the payload, SNS cannot express it |
| `Microsoft.ServiceBus/namespaces`                                                                | **the union of what its entities need**                                                     | The namespace is a container, not a broker instance. See § 3                                                                                      |
| `Microsoft.EventHub/namespaces/eventhubs`                                                        | **a topic in MSK**, or **a stream in Kinesis** — whichever the parent namespace resolved to | The hub is not its own service. See § 4                                                                                                           |
| `Microsoft.SignalRService/SignalR`, `service_mode = "Serverless"`                                | **API Gateway WebSocket API + Lambda**                                                      | Serverless SignalR already has no hub server; the shape matches                                                                                   |
| `Microsoft.SignalRService/SignalR`, `service_mode = "Default"` or `"Classic"`                    | **API Gateway WebSocket API**, with the hub server becoming a Fargate service or Lambda     | A hub server exists and has to land somewhere                                                                                                     |

### 2.3 User preference

`preferences.json` → `design_constraints` overrides 2.2. A customer who has said "keep
AMQP, we are not rewriting clients" has chosen Amazon MQ, and that answer wins.

### 2.4 Feature parity

Service Bus capabilities and where they land. Anything with **no** counterpart becomes a
`warnings[]` entry, never a silent omission.

| Service Bus feature                                        | AWS                                                                                  |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Dead-letter queue per entity                               | SQS redrive policy to a DLQ — direct                                                 |
| `lock_duration` / peek-lock                                | SQS visibility timeout — direct                                                      |
| `max_delivery_count`                                       | redrive `maxReceiveCount` — direct                                                   |
| Duplicate detection (≤ 5 min)                              | SQS FIFO content-based dedup — direct                                                |
| Sessions                                                   | SQS FIFO message group id — direct                                                   |
| Auto-forwarding between entities                           | **no equivalent.** Needs a Lambda relay, which is new code                           |
| Transactions spanning two entities                         | **no equivalent.** SQS and SNS have no cross-entity transaction                      |
| Scheduled messages > 15 min                                | EventBridge Scheduler — a different service, so a new component                      |
| Topic subscription **rule actions** (mutating the message) | **no equivalent.** SNS and EventBridge filter, they do not transform. Needs a Lambda |
| Geo-disaster recovery pairing                              | SQS/SNS are regional and already multi-AZ; cross-region needs explicit replication   |

**Premium namespaces are a signal, not a size.** `sku = "Premium"` buys resource isolation,
VNet integration and 100 MB messages. Do not read it as throughput and do not translate it
into a larger AWS resource — SQS has no instance size. Read it for the message-size
eliminator and for whether VNet integration implies a private-endpoint edge.

### 2.5 Cluster context

- A queue whose only producer and only consumer both map to **Lambda** favours SQS over
  Amazon MQ regardless of protocol preference — an event source mapping is native, and a
  broker connection from Lambda is a connection-pool problem.
- A namespace whose entities are consumed by a **VM or VMSS** workload keeps Amazon MQ in
  play: those clients are long-lived and already hold broker connections.
- When the same topic fans out to both an internal consumer and an external HTTP endpoint,
  **SNS** covers both; EventBridge to an HTTP endpoint needs an API destination.

### 2.6 Simplicity

Prefer the smaller target set. A topic with three subscriptions and no content filters is
SNS plus three SQS queues, not EventBridge plus three rules plus three queues.

## 3. A namespace maps to a set, not a service

`Microsoft.ServiceBus/namespaces` is the only row here whose target is derived from its
children rather than from itself.

1. Resolve every `queues` and `topics` child of the namespace first.
2. The namespace's `aws_service` is the **set** of services those children needed —
   `"SQS"`, `"SQS + SNS"`, `"SQS + SNS + EventBridge"`, or `"Amazon MQ"`.
3. **The namespace carries no cost line of its own** unless the answer is Amazon MQ, which
   is the one candidate with a priced broker instance. SQS and SNS are per-request: the
   entities carry the cost, the container does not.
4. Record the child entity ids in `aws_config` so the report can show what the set was
   derived from, and emit one `warnings[]` entry per child consumed this way.
5. A namespace with **zero** entities is idle: map it, and flag it as a cost-optimization
   finding, exactly as `compute.md` § 3 treats a zero-app plan.

An estimate that prices the namespace _and_ each queue has double-counted. An estimate
that prices only the namespace has priced nothing.

## 4. An Event Hub is a topic inside its namespace's target

`Microsoft.EventHub/namespaces` is a fast-path row: `kafka_enabled` → MSK, otherwise
Kinesis Data Streams. The hub inside it inherits that decision and must never re-open it.

| Parent resolved to       | Hub becomes       | Carry across                                                                                                                                                                                                             |
| ------------------------ | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **MSK**                  | a Kafka **topic** | `partition_count` → topic partitions; `message_retention` (days) → `retention.ms`; consumer groups → Kafka consumer groups, unchanged in concept                                                                         |
| **Kinesis Data Streams** | a **stream**      | `partition_count` → shard count as the starting point; `message_retention` → stream retention (24 h default, up to 365 days); consumer groups → **enhanced fan-out consumers**, which are priced per consumer-shard-hour |

Two traps:

- **Consumer groups are free on Event Hubs and are not free on Kinesis.** Enhanced fan-out
  is a priced dimension. A namespace with six consumer groups is a real cost line on
  Kinesis and is not on MSK. Name it.
- **Partition count is a starting point, not a mapping.** Kinesis shards carry a hard
  1 MB/s ingest and 2 MB/s egress limit per shard; Event Hubs partitions do not partition
  throughput the same way, since a namespace's throughput units are shared. Do not present
  partition-count parity as capacity parity.

`Microsoft.EventHub/namespaces/eventhubs/consumergroups` and `.../authorizationRules` are
Skip Mappings — they are configuration of the hub, not resources of their own.

## 5. Output

Per `schema-design-aws.md` § `services[]`: `aws_service`, `aws_config` (queue type, FIFO
flag, visibility timeout, redrive policy, filter policy shape, partition or shard count),
`confidence: "inferred"`, `rubric_applied: "messaging.md"`, and a `rationale` naming
**which criterion fired** and, where an eliminator was involved, which property triggered
it — "SQS FIFO eliminated: `duplicate_detection_history_time_window` is 1 hour, above the
5-minute FIFO ceiling" is auditable.

## Status — build step 5b

Implemented for Service Bus namespaces, queues and topics, Event Hubs entities, and
SignalR.

Event Grid does **not** route here and must not be re-decided in this file:
`Microsoft.EventGrid/topics` and `systemTopics` are **Direct Mappings**, and
`eventSubscriptions` is a Skip Mapping. That is the right call — an Event Grid topic is
EventBridge regardless of the architecture around it, which is the § 7a.3 admission test.
If you find yourself wanting a rubric for it, the change belongs in
`fast-path-services.json`, not here: a pattern may never override a `deterministic`
mapping, so a rubric row here would be unreachable anyway.
