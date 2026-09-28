# Replay, starting positions, pausing and resuming

Load this when a subscriber must read history rather than only new events, when pausing or resuming a
subscriber, or when a replay appears not to be working.

There is no separate replay API. Replay is a subscriber's starting position, evaluated against the bus's
retained events.

## The retention window bounds everything here

Retention is set per bus with `StorageConfiguration.RetentionPeriodInDays`. Reads return
`StorageConfigurationOutput` with an extra field, `RetentionWindowStartTime`: the earliest point from which
stored events are still available.

That field is computed, not stored:

```
RetentionWindowStartTime = max(now - RetentionPeriodInDays, time the bus was created)
```

Two consequences people trip over. A bus younger than its retention period reports its creation time, and
changing the retention period does not move the value until the bus is older than the period, because no
event can predate its own bus. And any time you name a point in the past, the service clamps it against
this same boundary; a point earlier than the window is rejected.

So on a young bus even a recent past timestamp can fall outside the window.

## StartingPosition at create time

`StartingPosition` is one of:

* `LATEST`: deliver only events published after this subscriber exists.
* `POINT_IN_TIME`: deliver from a point in the retained history. Requires `PointInTimeConfiguration`, whose
  `PointType` is either `HORIZON` (the oldest retained event) or `TIMESTAMP` (a `StartingPoint` you name).
  An optional `EndPoint` bounds the window, giving a finite replay that then stops.

Take a bus holding five events, all published before any subscriber existed, three of them before a chosen
midpoint and two after. Each starting position then delivers:

| Subscriber | Delivers |
|---|---|
| `LATEST` | none of the five |
| `POINT_IN_TIME` / `HORIZON` | all five, once each |
| `POINT_IN_TIME` / `TIMESTAMP` at the midpoint | exactly the two published after it |

Replay is exact. Three practical notes:

* **A replay has a startup delay, then runs at live speed.** The first replayed event arrives later
  than a live delivery would, so you SHOULD allow for the startup delay before concluding a replay
  is broken.
* **Replayed events are marked.** `SystemMetadata."aws:DeliveryType"` reads `REPLAY` instead of `LIVE`. Use
  it if a replay must be idempotent on the consumer side, and use `WITH_METADATA` or a JSONata transformer
  to surface it.
* **`StartingPoint` is a timestamp, so you MUST send it in the wire form for timestamps**, epoch seconds,
  because an ISO-8601 string is not accepted.

## Validation messages

The validation around starting positions is precise:

```
StartingPoint earlier than the retention window
  -> PointInTimeConfiguration.StartingPoint (...) falls outside the bus's retention window
StartingPoint in the future
  -> PointInTimeConfiguration.StartingPoint must not be in the future
POINT_IN_TIME without PointInTimeConfiguration
  -> PointInTimeConfiguration is required when StartingPosition is POINT_IN_TIME
PointType TIMESTAMP without StartingPoint
  -> PointInTimeConfiguration.StartingPoint is required and must be > 0 when PointType is TIMESTAMP
PointInTimeConfiguration supplied with StartingPosition LATEST
  -> PointInTimeConfiguration must not be provided when StartingPosition is LATEST
```

## Pausing and resuming

After the subscriber exists, pausing and resuming is `State` on `UpdateSubscriber`:

* `State: STOPPED` stops delivery. Events continue to accrue as a backlog, bounded by retention.
* `State: RUNNING` resumes. `ResumePosition` chooses what happens to the backlog: `LAST_PROCESSED` (the
  default) delivers it, and `LATEST` skips it and resumes at the tip.
* `ResumePosition` is honoured only on an update that moves `State` from `STOPPED` to `RUNNING`, and is
  rejected on any other call.
* `LATEST` is a one-shot instruction applied asynchronously. No read surface reports whether it has been
  applied yet, so a caller cannot distinguish "backlog already skipped" from "backlog about to be skipped".
  If that distinction matters, you SHOULD drive it from the consumer side using `aws:SequenceNumber`
  rather than infer it from the control plane.

## Replacing a subscriber without losing events

`StartingPosition` is create-only, and a subscriber replacement is delete-then-create, so a replacement
starts from its own starting position. With `LATEST` it never sees anything published during the gap. To
fill in that gap, you SHOULD give the replacement `POINT_IN_TIME` with a `TIMESTAMP` from before the
change.
See [infrastructure-as-code.md](infrastructure-as-code.md) for the CloudFormation form of this.
