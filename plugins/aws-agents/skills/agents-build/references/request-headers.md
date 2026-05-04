# request-headers

Pass custom HTTP headers from the caller through to your agent's invocation code.

## When to use

- You need to pass a tenant ID, correlation ID, or feature flag from your app to your agent
- You're implementing a protocol that requires specific headers (A2A, MCP, vendor-specific)
- You want OpenTelemetry baggage or trace headers to propagate from the caller
- You tried adding a header to the request and your agent code never sees it
- You're integrating with an external system that uses idempotency keys or similar headers

## The default: most headers are stripped

AgentCore Runtime strips all incoming headers from the request before it reaches your agent code **except**:

- `Authorization` — always passed through
- Any header matching `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*` — this is the reserved prefix for custom headers

Anything else — `X-Tenant-Id`, `X-Correlation-Id`, `traceparent`, `A2A-Version`, `Idempotency-Key`, whatever — will not appear in your invocation context unless you explicitly add it to the runtime's request header allowlist.

This is an intentional security boundary: the runtime doesn't forward arbitrary caller-supplied headers by default. It's also the #1 reason developers ask "why can't my agent see the header I'm sending?"

## Two ways to pass custom data

### Option 1: Use the reserved prefix

Rename headers at the caller to use the `X-Amzn-Bedrock-AgentCore-Runtime-Custom-` prefix. These pass through without any runtime configuration change.

```
# Caller sends:
X-Amzn-Bedrock-AgentCore-Runtime-Custom-Tenant-Id: acme-corp
X-Amzn-Bedrock-AgentCore-Runtime-Custom-Correlation-Id: 8b2e3d...

# Agent code sees the same headers in the invocation context
```

This is the simplest option for headers you control end-to-end (your app, your agent).

### Option 2: Add headers to the request header allowlist

If the header names are fixed by a protocol or external system (A2A requires `A2A-Version` and `A2A-Extensions`; OpenTelemetry uses `traceparent` and `baggage`; some APIs use `Idempotency-Key`), you can't rename them. Configure the runtime to allow them explicitly.

**Edit `agentcore/agentcore.json`** and add `requestHeaderAllowlist` to the runtime entry:

```json
{
  "runtimes": [
    {
      "name": "MyAgent",
      "requestHeaderAllowlist": [
        "X-Amzn-Bedrock-AgentCore-Runtime-Custom-X-Tenant-Id",
        "X-Amzn-Bedrock-AgentCore-Runtime-Custom-A2A-Version"
      ]
    }
  ]
}
```

Then `agentcore deploy`. The `$schema` URL at the top of the file (`https://schema.agentcore.aws.dev/v1/agentcore.json`) gives IDE autocomplete and validation for every field.

**CLI shortcut** — `agentcore add agent --request-header-allowlist "X-Tenant-Id,A2A-Version"` writes the same array. **Important:** the CLI auto-prefixes entries with `X-Amzn-Bedrock-AgentCore-Runtime-Custom-` as they land in `agentcore.json`. If you're editing the JSON by hand, write the prefixed form directly. If you're using the CLI, pass the short name and let the CLI add the prefix.

`Authorization` passes through by default and doesn't need to be in the allowlist.

### Constraints

- **Maximum 20 headers** in the allowlist (including `Authorization` if you include it explicitly)
- **Header name length:** up to 256 characters
- **Header value size:** up to 4 KB per header
- **Names are case-sensitive** — list them exactly as they'll be sent
- **Changes take effect after the next deploy** of the runtime

If you hit the 20-header cap, combine related data into one JSON-encoded header rather than using many separate ones.

## Common use cases

### Multi-tenancy

```
Caller:       X-Tenant-Id: acme-corp
Agent code:   reads tenant from the header, scopes memory/data/tools per tenant
```

Add `X-Tenant-Id` to the allowlist. The agent can then isolate memory namespaces, database queries, and tool-call authorization per tenant.

### Distributed tracing propagation

```
Caller:       traceparent: 00-<trace-id>-<span-id>-01
              baggage:     userId=alice,env=prod
Agent code:   uses OTel SDK to continue the parent trace
```

Add `traceparent` and `baggage` to the allowlist. Your OTel SDK instrumentation will pick them up automatically and produce spans connected to the caller's trace.

### A2A protocol compliance

```
Caller:       A2A-Version:    1.0
              A2A-Extensions: x-capability-foo
Agent code:   branches behavior based on protocol version
```

A2A v1.0 requires these headers. Add both to the allowlist; A2A v0.3 doesn't need either.

### Idempotency keys

```
Caller:       Idempotency-Key: 7f3a...
Agent code:   deduplicates or caches based on the key
```

For agents that call external APIs with idempotency, propagating the caller's key through to the agent's outbound calls avoids duplicate side effects on retry.

## Reading the headers in agent code

Headers arrive in the runtime's `context` object passed to your invocation handler. The exact accessor depends on the framework — check the bedrock-agentcore SDK docs for your language. In Python:

```python
@app.entrypoint
def invoke(payload, context):
    tenant = context.headers.get("X-Tenant-Id")
    correlation_id = context.headers.get("X-Correlation-Id")
    # ... use as needed
```

Headers that weren't in the allowlist will be absent (not empty string) from the context.

## What won't work

- **Sending headers without configuring the allowlist** — anything outside the default pass-through set is silently dropped. Your agent code won't see the header, and there's no error. Check the runtime's `requestHeaderConfiguration` if a header you expect to see isn't arriving.
- **Using this for secrets** — 4 KB values and the allowlist configuration are designed for metadata, not credentials. Use the AgentCore Identity credential provider for API keys, OAuth tokens, and secrets. See `agents-connect` Path D.
- **Dynamic headers** — the allowlist is static runtime configuration. You can't vary it per-request.

## Troubleshooting

**"My agent doesn't see the header I'm sending"**
Check (in order): (1) Is the header in the allowlist? (2) Is the spelling an exact match including case? (3) Did you redeploy the runtime after updating the allowlist? (4) Is the caller actually sending the header — `curl -v` or equivalent network inspection.

**"I hit the 20-header limit"**
Consolidate related data into a single JSON-encoded header. For example, instead of `X-Region`, `X-Environment`, `X-Service-Name` as three separate headers, use `X-Context: {"region":"us-west-2","env":"prod","service":"billing"}`.

**"Allowlist update didn't take effect"**
Redeploy the runtime. The header allowlist is config that applies on the next `agentcore deploy`, not immediately after editing `agentcore.json`.

## Output

- Decision on prefix vs. allowlist approach
- CLI command to update the allowlist if needed
- Agent code pattern for reading the headers
