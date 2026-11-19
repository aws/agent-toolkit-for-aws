# Startup and Shutdown (Live Only)

## Startup order

Start upstream first. A resource is NOT ready until it reaches its final running
state. `STARTING` ≠ running. Always poll and confirm before proceeding.

| Step | Action | Poll field | Ready state |
|------|--------|------------|-------------|
| 1 | `start-flow` (MediaConnect) | `Flow.Status` | `ACTIVE` |
| 1b | (Router input only) Confirm router I/Os are Active and a route is assigned to the MediaLive-facing output | I/O state / route | Active + route assigned |
| 2 | Start source encoder | Confirm content flowing via CloudWatch | — |
| 3 | `start-channel` (MediaLive) | `State` | `RUNNING` |
| 4 | Verify playback URL returns valid manifest | — | — |

## Polling pattern

`start-flow` and `start-channel` return immediately while the resource
transitions asynchronously. Always poll until the resource reaches its
ready state — a one-shot describe-* call will see `STARTING` and falsely
suggest the next step is safe to take.

- Poll on a tight cadence (≈5 seconds). Do NOT wait 30/90/180 seconds
  between checks; long sleeps add unnecessary delay to multi-step
  workflows.
- For MediaLive channels, prefer the built-in waiter
  (`channel-running` / `channel-stopped`) when available.
- For MediaConnect flows, poll `Flow.Status` until it reaches the
  expected state (`ACTIVE` for startup, `STANDBY` for shutdown).

The same pattern applies in reverse for shutdown.

**MediaConnect Router startup:** Router I/Os have their own Standby→Active
lifecycle (separate from any MediaConnect flow). Content reaches a downstream
consumer (e.g., a MediaLive input) only once the router I/Os are Active AND a
route has been assigned ("taken") to the output feeding that consumer. There is
no separate "enable output" step — an output with no assigned input carries no
content.

## Shutdown order

Reverse of startup. `STOPPING` ≠ stopped — poll until idle.

| Step | Action | Poll field | Stopped state |
|------|--------|------------|---------------|
| 1 | `stop-channel` (MediaLive) | `State` | `IDLE` |
| 2 | Stop source encoder | — | — |
| 3 | `stop-flow` (MediaConnect) | `Flow.Status` | `STANDBY` |

Note: MediaConnect billing continues while the flow is `ACTIVE`, even with no
consuming outputs.
