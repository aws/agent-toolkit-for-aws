# Migrating from classic EventBridge

Load this when planning or executing a migration from classic EventBridge, or when classic habits are
producing configurations on the new custom event bus that do not behave as expected. This file calls it
the new bus for short. It has three parts: the concept mapping, the habits that carry over incorrectly,
and a step-by-step migration sequence.

## Concept mapping

| Classic | New custom event bus |
|---|---|
| Event bus | Event bus, plus retention |
| Rule + target | One subscriber |
| `PutEvents` | Two publish APIs: `PutEvents` and `PutRawEvents` |
| Input transformer | `Transformer`, with a JSONata option |
| Event pattern | Filter, scoped (see chapter 7) |
| Archive + replay | Retention plus a subscriber starting position |
| Dead-letter queue on a target | `OnFailureConfiguration` on the subscriber |
| `AWS::Events::Rule` | `AWS::EventsV2::Subscriber` |

The IAM namespace is `events` for both services, so a policy statement looks similar while naming a
different API. The CLI command distinguishes them: `events` for classic, `eventsv2` for the new buses.
The SDK client name for the new buses is `eventbridgev2`.

## Four new-bus concepts with no classic analogue

* **Retention on the bus itself.** In classic, an event not matched at publish time is gone. The new bus
  keeps it for the retention period, which is what makes the next three possible.
* **Starting position.** A subscriber on the new bus can begin at the tip, at the oldest retained event, or
  at a timestamp. A classic rule only ever sees what arrives after it exists.
* **Pause and resume.** A stopped subscriber accrues a backlog and can resume from it, either delivering
  the backlog or skipping it. Disabling a classic rule discards everything published while it was disabled.
* **Two publish APIs with different payload models.** This changes how you write filters,
  transformers, and target parameters. A classic event pattern ported unchanged to a `DATA` filter works
  only for `PutEvents` traffic, because only `PutEvents` keeps the classic envelope. See chapter 6 and
  [filters-and-expressions.md](filters-and-expressions.md).

## Habits that carry over incorrectly

* **One rule with many targets becomes many subscribers.** A subscriber has exactly one target, so a classic
  rule fanning out to three targets is three subscribers on the same bus. Each is billed a delivery.
* **A classic archive plus replay becomes retention plus a starting position.** There is no replay API to
  call. See [replay-and-recovery.md](replay-and-recovery.md).
* **A dead-letter queue moves from the target to the subscriber.** It is `OnFailureConfiguration` on the
  subscriber, it must be SQS, and the delivery role needs `sqs:SendMessage` on it (chapter 13).

## A migration sequence that is reversible at every step

The risk in a migration is not the concept mapping; it is a one-shot cutover. The sequence below runs
classic and the new bus side by side, moves one party at a time, and keeps a rollback at every step.
Retention is what makes it safe: with events retained on the new bus, a consumer cutover that goes
wrong is replayed with a `POINT_IN_TIME` subscriber rather than lost.

**Step 0: decide whether to migrate at all.** Classic EventBridge remains a supported service. Migrate
to get what classic does not have: retention, replay, pause and resume, ordering, deduplication, and
binary payloads. If none of those matter to the workload, staying on classic is a valid outcome of
this step.

**Step 1: bridge classic into the new bus, changing nothing else.** Create the new bus, then add a
non-managed classic rule on the existing classic bus whose target is the new bus, carrying a role you
supply. Both systems now carry the same traffic, and every later step works against live data. Two
authorization facts govern the bridge: the forwarding is authorized per event against the new bus's
resource policy, and a stream mixing AWS service events with your own needs both `events:PutEvents` and
`events:PutRawEvents` granted (see [authorization.md](authorization.md)). Rollback: delete the rule.

**Step 2: confirm consumer idempotency before anything is dual-delivered.** During a consumer's
cutover, and during any later replay, a consumer can see the same logical event twice: once through
its classic target and once through its new subscriber. You SHOULD confirm each consumer deduplicates on
a business key from the payload before moving it. A consumer that cannot be made idempotent needs a
hard cutover (stop classic delivery, then start the subscriber) instead of a shadow period, so
identify those consumers now.

**Step 3: move consumers one team at a time, shadow first.** For each consumer: create a subscriber on
the new bus with the filter that matches its classic rule pattern (ported per the payload-shape rules
above), point it at a shadow target the team owns, and compare shadow output against the classic
delivery until the team trusts it. Then cut over: point the subscriber at the real target and disable
the classic rule's target. Rollback: re-enable the classic target and pause the subscriber
(`State: STOPPED`); the classic path never stopped carrying the traffic. If a cutover gap is
discovered later, create a replacement subscriber with `StartingPosition: POINT_IN_TIME` and a
`TIMESTAMP` from before the cutover, and the gap is refilled from retention (see
[replay-and-recovery.md](replay-and-recovery.md)).

**Step 4: move publishers last, which removes the bridge.** Once every consumer reads from the new
bus, repoint each publisher from the classic `PutEvents` call to the new bus. The lift-and-shift is
small: swap the client (for the AWS SDK for Java v2, `EventBridgeClient` becomes `EventBridgeV2Client`),
name the bus by ARN at the request level instead of `EventBusName` per entry, and keep `Source`,
`DetailType`, and `Detail` unchanged. Update the caller's IAM policy to cover the
`event-busv2/` resource ARN. When the last publisher moves, the bridge rule carries nothing; delete
it. Rollback per publisher: repoint it at classic, where the bridge still forwards.

**Step 5: decommission.** Delete the classic rules and targets, and any classic archive whose job the
new bus's retention now does. You MUST do this only after the retention period has covered at least one
full business cycle of replay demand, because a classic archive deleted early is the one thing in this
sequence with no rollback.
