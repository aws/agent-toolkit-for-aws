# Provisioning, resource state, and deletion

Load this when creating or updating a bus, when a resource is stuck in a state you did not expect, or when
creating many resources at once.

## Creating a bus is asynchronous

`CreateEventBus` returns immediately with `State: CREATING`, and the bus becomes usable later.

**You SHOULD use the waiter rather than writing your own poll.** `EventBusActive` and
`EventBusDeleted` are defined on `DescribeEventBus`, so every SDK and the CLI expose them:

```
aws eventsv2 wait event-bus-active  --event-bus-arn "$BUS_ARN"
aws eventsv2 wait event-bus-deleted --event-bus-arn "$BUS_ARN"
```

The active waiter beats a hand-rolled loop in one specific way: it fails fast on `CREATE_FAILED`,
`UPDATE_FAILED`, and `DELETE_FAILED` and surfaces `StateReason`, instead of spinning until a timeout. Use it
after a create and after an update.

## What each state allows

A bus has seven states, and which operations they permit is not obvious from the names:

| State | Publish | Create or update a subscriber or event source | `UpdateEventBus` | `DeleteEventBus` |
|---|---|---|---|---|
| `CREATING` | no | no | no | no |
| `ACTIVE` | yes | yes | yes | yes |
| `UPDATING` | yes | yes | no | no |
| `UPDATE_FAILED` | yes | yes | yes | yes |
| `CREATE_FAILED` | no | no | no | yes |
| `DELETING` | no | no | no | no |
| `DELETE_FAILED` | no | no | no | yes |

Three readings from that table:

* **An update never interrupts ingestion**, since publishing and subscriber creation continue while the bus
  is `UPDATING`. So changing retention or encryption needs no maintenance window.
* **`UPDATE_FAILED` is recoverable in place and `CREATE_FAILED` is not.** A failed update leaves everything
  working and `UpdateEventBus` available, so read `StateReason`, fix the cause, and retry. A failed create
  permits only delete, so that bus must be deleted and recreated.
* **A failed delete is retryable.** `DELETE_FAILED` still permits `DeleteEventBus`, so retry it after
  removing whatever blocked it.

`StateReason` carries the cause on every failure state. A bus whose encryption key is unusable settles at
`CREATE_FAILED` with something like
`KMS_ACCESS_DENIED: The event bus's KMS key policy does not grant EventBridge access.` It distinguishes a
fixable input from a retry, so you **SHOULD** read it before doing anything else.

## Create idempotency

`CreateEventBus`, `CreateSubscriber`, and `CreateEventSource` each accept a `ClientToken`. A retry carrying
the same token is idempotent: it returns the original result rather than creating a second resource.

An SDK fills the field when you omit it, generating a fresh token for each call. That covers the SDK's own
transport-level retry of one call, and it covers nothing above that. A retry your code issues builds the
request again, so it carries a new token and the service treats it as an unrelated create. So you
**MUST** supply your own token whenever the retry can cross a process, a queue, or a workflow step, and
you **MUST** derive that token from the work rather than generate it at the point of retry.

Reusing a token with different parameters returns `IdempotentParameterMismatchException`. The remedy is a
new token, or resending the earlier request unchanged.

A second create that reaches the service without a matching token collides on the name instead, and
returns `ResourceAlreadyExistsException`.

## Deleting

You **MUST** delete subscribers and event sources first, then the bus. A bus that still has either
rejects `DeleteEventBus` with `ResourceInUseException`, and the message names which kind is blocking, so
it is a list-and-clean-up instruction rather than a transient failure worth retrying. Both kinds are
evaluated before the refusal, so one attempt reports everything you have to remove. Revoked subscribers
and event sources are not counted, and neither is a `CREATE_FAILED` event source, so a bus whose only
remaining attachments are those deletes.

That refusal is a fail-fast at the API. The authoritative check runs in the workflow after the delete is
accepted, so a delete that passes the immediate check can still settle at `DELETE_FAILED`, which is
retryable.

Revocation does not appear in `State`. `EventSourceState` defines no value for it: the values are
`CREATING`, `ACTIVE`, `UPDATING`, `CREATE_FAILED`, `UPDATE_FAILED`, `DELETING`, and `DELETE_FAILED`. A
revoked event source is reported by its `Revoked` flag alone. So a wait or an assertion on a revoked
`State` never succeeds, and the check is `Revoked` on `DescribeEventSource`.

## Creating many resources at once

Concurrent creates on one bus contend. Creating many subscribers in parallel produces
`ConcurrentModificationException` on most of them. You **MUST** create them serially, or retry with
backoff; the exception is retryable and the model marks it so.

Subscriber creation is also not instant. A subscriber created and published to immediately can miss
the first event, so you **SHOULD** allow a short delay before publishing (see
[delivery-troubleshooting.md](delivery-troubleshooting.md)).
