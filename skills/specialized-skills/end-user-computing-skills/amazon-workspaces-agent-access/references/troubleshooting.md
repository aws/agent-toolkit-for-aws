# Troubleshooting

Match on the exact error string, then apply the fix. The key distinction: **warmup/transient errors should be retried; `client_disconnected` should not** — it means the session is gone.

## Error string → cause → fix

| Error | Cause | Fix |
|---|---|---|
| `dcv session not ready` | Desktop still connecting after the streaming URL was created (5–30s, sometimes longer). | Retry with backoff. The service retries connection readiness for up to ~10 minutes; wait and retry rather than failing. |
| `Unknown tool` (right after connect) | DCV desktop session not fully connected yet, so tools aren't registered. | Same as above — poll/retry until tools appear (or use POLLING mode + `connection_status`). |
| `backend unavailable` | Transient service issue. | Retry briefly (a handful of attempts). |
| `client_disconnected` | The session was **stopped, or the auth (streaming URL / SAML assertion) expired or was revoked** — the user or orchestrator ended it, or it timed out. | Do **not** just retry the same connection. Reconnect with **fresh auth** — a new streaming URL (non-domain-joined) or a new SAML assertion (domain-joined). |
| `400 Bad Request` | SigV4 **signing region does not match the fleet region** (cross-region). | Sign for the fleet's region — set `AWS_REGION`/the MCP signing region to the fleet region and use the matching regional endpoint. |
| `401 Unauthorized` | SigV4 signing failed / credentials can't sign. | Check AWS credentials (`aws sts get-caller-identity`); verify the correct profile is used for MCP signing. |
| `403 Forbidden` | Missing IAM permissions for Agent Access. | Grant the specific `agentaccess-mcp` actions the agent calls (e.g. `InvokeMcp`, `GetScreenshot`, `LeftClick`, `TypeText`; add `CallForwardedTool` for forwarding), scoped by the `agentaccess-mcp:StackArn` condition key — avoid a blanket `agentaccess-mcp:*` (see connection-setup.md). |
| `DCV proxy not initialized` | No streaming URL (or SAML assertion) was provided. | Pass the streaming URL header (non-domain-joined) or the SAML `_meta` (domain-joined), or connect via a Gateway that auto-provisions. |
| Forwarded tool returns an error string | Often a path outside the sandbox, or the 5s tool-call timeout. | Read the error; fix the argument (keep paths in the server's sandbox) and retry once. Ensure the tool returns within 5s. |

## Retryable vs fatal (client behavior)

- **Retryable** (wait + reconnect): `dcv session not ready`, `Unknown tool` at startup, `channel not connected`, `connection to the mcp server was closed`, `timed out`, `backend unavailable`. Back off (e.g. increasing delay) across a few attempts.
- **Fatal without fresh auth:** `client_disconnected` — reconnect with a new streaming URL (non-domain-joined) or a new SAML assertion (domain-joined).
- **Fix-then-retry (config, not transient):** `400` (signing region), `401` (credentials), `403` (IAM) — correct the cause; retrying unchanged won't help.

## Cold start note

The first tool call after a cold start can take 10–30s while the desktop connects. This is expected — build in a wait/retry rather than treating the first slow call as a failure.
