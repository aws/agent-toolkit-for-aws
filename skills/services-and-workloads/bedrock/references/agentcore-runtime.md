# AgentCore Runtime — Protocol Selection & Deployment

## Table of Contents

- Protocol Selection Guide
- Container Contract
- Deployment Workflow
- Agent Lifecycle Models
- Scaling
- Security Considerations

## Protocol Selection Guide

AgentCore Runtime supports 4 protocols. You MUST select before building the container — each has a different contract.

| Protocol | Container Contract | Best For |
|----------|-------------------|----------|
| **HTTP** | Health: `/health`, Port: 8080, JSON req/res | Existing web frameworks (FastAPI, Express, Flask). Simple request-response agents. |
| **MCP** | Endpoint: `/mcp`, Streamable HTTP transport | Tool-centric agents exposing capabilities as MCP tools. MCP ecosystem integration. |
| **A2A** | Agent Card: `/.well-known/agent.json`, task endpoints | Multi-agent systems with direct agent-to-agent communication. |
| **AG-UI** | Health: `/ping`, Event stream: `/invocations`, Port: 8080, SSE standard event types | Frontend-connected agents with real-time UI updates. Chat interfaces. |

**Decision guide:**

| Question | Answer → Protocol |
|----------|------------------|
| Existing REST API or web framework? | HTTP |
| Agent provides tools to other agents? | MCP |
| Agents communicate directly with each other? | A2A |
| Agent streams results to a UI? | AG-UI |
| Not sure? | Start with HTTP — simplest, most familiar |

Refer to the latest AWS documentation on AgentCore Runtime protocols for current specifications.

## Container Contract

Requirements that apply to ALL protocols:

| Requirement | Detail |
|-------------|--------|
| **Architecture** | ARM64 (Graviton) — x86 images WILL NOT START |
| **Health check** | Protocol-specific endpoint (see table above) |
| **Port** | Default 8080, configurable |
| **Startup** | Must signal readiness within timeout |
| **Logging** | stdout/stderr → CloudWatch automatically |
| **Shutdown** | Handle SIGTERM for graceful shutdown |
| **Environment** | AgentCore provides: RUNTIME_ID, AWS_REGION, credentials |

See [container build procedure](agentcore-runtime-container-build.md) for the full build workflow with Dockerfile examples.

## Deployment Workflow

```
Deployment Progress:
- [ ] Step 1: Select protocol (see guide above)
- [ ] Step 2: Build ARM64 container — see [container build procedure](agentcore-runtime-container-build.md)
- [ ] Step 3: Push to ECR
- [ ] Step 4: Create Runtime: `aws bedrock-agentcore-control create-agent-runtime --agent-runtime-name <name> --agent-runtime-artifact '{"containerConfiguration":{"containerUri":"<ecr-uri>"}}' --role-arn <role-arn> --network-configuration '...' --authorizer-configuration '...' --protocol-configuration '{"serverProtocol":"<PROTOCOL>"}'` — where `<PROTOCOL>` is `HTTP`, `MCP`, `A2A`, or `AGUI` matching your Step 1 selection (note: AG-UI in the selection guide maps to API value `AGUI`). For `--network-configuration` and `--authorizer-configuration`, see the Security Considerations section below.
- [ ] Step 5: Create Runtime Endpoint: `aws bedrock-agentcore-control create-agent-runtime-endpoint --agent-runtime-id <id-from-step-4> --name <endpoint-name>`
- [ ] Step 6: Wait for endpoint status `READY` — the runtime is not invocable until the endpoint is active
- [ ] Step 7: Verify health check passes: `aws bedrock-agentcore-control get-agent-runtime-endpoint --agent-runtime-id <id> --endpoint-id <endpoint-id>` — confirm status is `READY` and health check is passing
```

**Constraints:**

- You MUST select the protocol BEFORE building the container (Step 1 before Step 2)
- You MUST use ARM64 architecture — see [container build procedure](agentcore-runtime-container-build.md)
- You MUST create the endpoint (Step 5) after the runtime (Step 4) — without an endpoint, the runtime cannot receive traffic
- You MUST verify health check passes after deployment
- For updates: use rolling update (default) or blue/green via alias switching
- For rollback: deploy previous container image version

## Agent Lifecycle Models

| Model | State | Memory Service | Use When |
|-------|-------|---------------|----------|
| Per-request | Stateless — new instance per request | Not needed | Simple Q&A, stateless tools |
| Per-session | Stateful — persists across requests in session | Required | Multi-turn chat, context accumulation |

Per-session agents use the Memory service for state persistence. See [memory & observability](agentcore-memory-observability.md).

## Scaling

- Auto-scaling based on invocation count, latency, or custom metrics
- Configure min/max instances in Runtime configuration
- Cold start: first request to a new instance has higher latency
- For predictable high-volume: consider provisioned capacity
- Refer to the latest AWS documentation on AgentCore Runtime scaling for current configuration options

## Security Considerations

**IAM and access control:**

- The `--role-arn` in `create-agent-runtime` defines what AWS resources the agent can access — scope to least-privilege permissions
- You MUST use IAM roles (not IAM users) for the runtime execution role
- Include `aws:SourceArn` and `aws:SourceAccount` conditions in the execution role trust policy to prevent confused deputy
- Separate runtime roles per agent — do not share a single role across multiple agents with different access needs

**Network security:**

- AgentCore terminates TLS at the load balancer — containers receive plaintext HTTP internally
- You MUST NOT expose container ports directly to the internet — all traffic must route through AgentCore
- Use VPC configuration in `--network-configuration` to restrict network access to required resources only
- You SHOULD use VPC mode (`"networkMode":"VPC"`) for production workloads — PUBLIC mode exposes the endpoint to the internet and should only be used for development/testing in isolated accounts

**Authentication:**

- Configure `--authorizer-configuration` to require authentication for inbound requests
- You MUST NOT deploy production runtimes without an authorizer — unauthenticated endpoints are a security risk

**Secrets and environment variables:**

- You MUST NOT put secrets, API keys, or credentials in `--environment-variables` — these are visible in the runtime configuration via `get-agent-runtime`
- Use AWS Secrets Manager for secrets and reference them at runtime from your agent code
- Use `--environment-variables` only for non-sensitive configuration (feature flags, region overrides, log levels)

**Logging and sensitive data:**

- Agent runtimes log request and response payloads to CloudWatch automatically — these may contain PII
- You MUST encrypt the CloudWatch log group with a KMS key: configure `kms-key-id` on the `/aws/bedrock-agentcore/runtimes/<agent-id>` log group
- Configure CloudWatch Logs retention limits — do not retain logs indefinitely
- You MUST NOT log secrets or credentials in agent output

**Monitoring:**

- Enable CloudTrail for all `bedrock-agentcore-control` API calls to audit runtime creation, updates, and deletions
- Monitor runtime health via CloudWatch metrics — first discover the exact namespace (CloudWatch namespaces are case-sensitive):
  1. `aws cloudwatch list-metrics --namespace "Bedrock-AgentCore"` — if no results, try `--namespace "Bedrock-Agentcore"`
  2. Use the namespace that returns metrics in all subsequent alarm and query commands
- Configure alarms for error rates and latency degradation

- Refer to the latest AWS documentation on Bedrock AgentCore security best practices
