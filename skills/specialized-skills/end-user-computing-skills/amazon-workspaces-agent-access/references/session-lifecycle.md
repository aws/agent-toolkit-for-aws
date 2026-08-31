# Session Lifecycle

## Lifecycle

1. **Starts** on the first MCP `initialize` with a streaming URL (or auto-provisioned via an AgentCore Gateway). The request is authorized by the `agentaccess-mcp:InvokeMcp` IAM action (see connection-setup.md → IAM permissions).
2. **Active** while the MCP connection is open — tools can be called repeatedly and desktop state persists (apps stay open, files remain on disk).
3. **Ends** when the connection closes, the session hits the fleet's timeouts, or the streaming URL's validity window lapses before it is used to connect.

Two separate limits are often confused:
- **Streaming URL validity** — how long the URL can be used to *initiate* a connection. Set by the `Validity` parameter of `CreateStreamingURL`: 1–604800 seconds (7 days); API default 60 seconds. (AWS sample tooling commonly passes 3600 / 1 hour.) Once connected, the URL's validity no longer matters. It is a **bearer credential** — do not log it or pass it via environment variables that may be captured in process listings or crash dumps; redact `X-Amzn-AgentAccess-Streaming-Session-Url` if MCP headers are logged.
- **Maximum session duration** — how long a connected session may run. Governed by the fleet's `MaxUserDurationInSeconds`, plus `DisconnectTimeoutInSeconds` and `IdleDisconnectTimeoutInSeconds` for teardown after disconnect/idle. These are per-fleet configuration, not a fixed Agent Access cap — confirm the values on your fleet (see [CreateFleet](https://docs.aws.amazon.com/appstream2/latest/APIReference/API_CreateFleet.html) for allowed ranges).

## Cleanup and expire-on-delete

Control whether the underlying streaming session is expired when the agent disconnects with the `X-Amzn-AgentAccess-Expire-Streaming-Session-On-Delete` header:

| Value | Behavior |
|---|---|
| `true` | On an explicit HTTP `DELETE`, the server expires the streaming session as part of cleanup. This terminates the streaming instance and triggers the fleet's autoscaling policy. |
| `false` (default) | The session keeps running until the fleet's disconnect timeout is reached. |

`mcp-proxy-for-aws` issues the `DELETE` automatically when you end the client lifecycle cleanly (e.g. exit the `async with` block). So to reclaim capacity promptly after a run, set the header to `true` and let the client close normally.

## One agent per session

Only one agent can be connected to a given session at a time. A named user (`UserId`) can have only one active session per fleet at a time. To run multiple agents concurrently, give each its own session (and distinct `UserId`).

## Idle behavior

Sessions have an idle/disconnect timeout at the fleet level. For long-lived automations, keep the MCP connection active or plan for reconnection (a fresh streaming URL) if the session times out. If a later tool call returns `client_disconnected`, the session was stopped or the auth expired — reconnect with fresh auth (a new streaming URL for non-domain-joined, or a new SAML assertion for domain-joined) rather than retrying the same connection (see troubleshooting.md).
