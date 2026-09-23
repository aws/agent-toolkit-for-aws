# Messaging — Startup Decision Guide

## Stage-Based Recommendation

### Pre-PMF (Seed / <$1M ARR)

- **Default to SQS Standard.** Don't overthink messaging architecture. A single SQS queue between your API and a worker Lambda covers 90% of early async needs.
- **Skip EventBridge until you have 3+ services producing events.** For 1-2 services, direct SQS/SNS is simpler and cheaper.
- **Don't build event-driven microservices yet.** You'll refactor your domain model 5 times before PMF. Monolith + SQS for background jobs is the right pattern.

### Post-PMF / Growth ($1M-$10M ARR)

- **EventBridge when you have 3+ services that react to the same business events.** The content-based routing eliminates Lambda glue.
- **SNS + SQS fan-out for high-throughput notification patterns** (>10K events/sec).
- **FIFO queues only when you have actual ordering bugs** in production, not as a preventive measure. They cost more and have lower throughput (3,000 msg/sec with batching vs unlimited for Standard).

### Scale ($10M+ ARR)

- EventBridge + Schema Registry for event contracts across teams.
- Consider Kinesis/MSK only for true streaming use cases (>100K events/sec sustained).

## Cost Traps

| Trap                        | Impact                                                  | Fix                                                                                 |
| --------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Short polling SQS           | ~345K empty API calls/day per consumer at standard rate | Always `WaitTimeSeconds=20`. Saves ~90% of SQS API costs.                           |
| SQS FIFO "just to be safe"  | 50% more expensive + 3K msg/sec cap (vs unlimited)      | Use Standard unless you have a proven ordering bug. Design for idempotency instead. |
| EventBridge for everything  | $1.00/million events + complex debugging                | SQS direct is $0.40/million for simple point-to-point                               |
| SNS for point-to-point      | Extra hop + cost for single subscriber                  | Use SQS directly. SNS adds value only at 2+ subscribers.                            |
| Lambda polling empty queues | Lambda invocations checking SQS with nothing to process | Use SQS event source mapping (free polling) instead of custom pollers               |

## Counterintuitive Advice

- **Synchronous is fine at startup scale.** Don't add SQS between your API and database "for decoupling" when you have 10 requests/second. It adds latency, complexity, and debugging difficulty. Add async when you have a specific scaling bottleneck.
- **EventBridge Archives are not a replacement for event sourcing.** The replay is useful for debugging, not for rebuilding state. If you need event sourcing, use DynamoDB Streams or build a proper event store.
- **SQS FIFO's exactly-once is per message-group, not per queue.** If you thought FIFO makes your whole system exactly-once, you misunderstood it. You still need idempotent consumers for Standard OR FIFO.
- **DLQ without alerting is worse than no DLQ.** It gives you false confidence that errors are "handled" when they're actually just accumulating silently. Set up the CloudWatch alarm on DLQ message count ON THE SAME DAY you create the DLQ.

## Decision Shortcuts

### "Should I use messaging here?"

- Request-response with <1s latency requirement → No, call directly
- Fire-and-forget, no response needed → Yes, SQS
- One event, multiple reactions → Yes, SNS or EventBridge
- Smoothing traffic spikes → Yes, SQS in front of worker
- "Because microservices should be decoupled" → No, that's cargo culting

### "SQS Standard or FIFO?"

- Can you make your consumer idempotent? → Standard (higher throughput, lower cost)
- Is ordering a regulatory requirement? → FIFO
- Processing the same message twice causes money loss? → FIFO (with deduplication)
- You're not sure → Standard. You can always migrate later.

## When to Graduate

| Trigger                                                 | Action                                                         |
| ------------------------------------------------------- | -------------------------------------------------------------- |
| Background job takes >29s (API Gateway timeout)         | Add SQS + worker Lambda                                        |
| Same event needs to trigger 3+ different actions        | SNS fan-out or EventBridge                                     |
| You're writing Lambda "routers" that inspect event type | Switch to EventBridge rules                                    |
| You need cross-account event delivery                   | EventBridge (cross-account rules)                              |
| >10K events/sec sustained throughput                    | SNS+SQS fan-out (EventBridge has soft limits)                  |
| >100K events/sec sustained                              | Kinesis or MSK — you've outgrown messaging, you need streaming |
