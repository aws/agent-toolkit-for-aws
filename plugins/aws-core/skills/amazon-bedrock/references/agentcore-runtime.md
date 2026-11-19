# AgentCore Runtime — Protocol Selection & Deployment

## Table of Contents

- Task-to-Component Routing
- Protocol Selection Guide
- Container Contract
- Deployment Workflow
- Agent Lifecycle Models
- Scaling
- Security Considerations

## Task-to-Component Routing

Users describe a job, not a service name. Before you pick a Runtime protocol, match the job to ONE AgentCore component with this table. Rows are keyed on the words users actually use. If the job matches a row whose component is not Runtime, go to that row's reference first; the rest of this file applies only when the component is Runtime.

| Task the user describes | Component | Read first |
|-------------------------|-----------|------------|
| Deploy or host an agent you already wrote, for real users, with the least infrastructure to own: no cluster, no fleet to patch, no queue. Any framework (LangGraph, Strands, OpenAI Agents SDK, Spring AI, custom loop) | Runtime | Deployment Workflow below; [Runtime overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html) |
| Agent tasks run for minutes or hours and the current host kills them at the request timeout; background or asynchronous work must outlive the request | Runtime | [Asynchronous and long-running agents](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html) |
| Move an agent off a hand-built VM or a laptop to a real deployment target with versioned releases; roll back by pointing an endpoint at an earlier version | Runtime | Deployment Workflow below; [Runtime versioning and endpoints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html) |
| Stream agent output to a chat UI or browser in real time (SSE or WebSocket) | Runtime | Protocol Selection Guide below (HTTP or AG-UI); [Stream agent responses](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/response-streaming.html); [Bidirectional streaming](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-bidirectional-streaming.html) |
| Isolate each user session so one session cannot read another's files, memory or credentials (process vs container vs microVM question) | Runtime | [Isolated sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html); for untrusted generated code, see the Code Interpreter row |
| Cut compute cost for agents that mostly wait on model calls, tools or humans; consumption billing (CPU billed only while active) instead of an always-on fleet | Runtime | [How Runtime microVMs work](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html); [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) |
| Define agents as configuration (model, prompt, tools) with no agent loop or orchestration code to own; many agents as declarations, not codebases | Harness | [harness procedure](agentcore-harness.md); [Harness vs. Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-vs-runtime.html) |
| Run a prebuilt coding agent (Claude Code, Codex CLI, Pi or similar) as a hosted service: the agent brings its own loop, so package it in an ARM64 container behind the HTTP contract | Runtime | [container build procedure](agentcore-runtime-container-build.md); [Harness vs. Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-vs-runtime.html) (Harness runs its own loop and is not a host for another agent's loop) |
| Remember users across sessions: preferences, facts, summaries; replace homegrown memory tables or a vector store you maintain | Memory | [memory & observability](agentcore-memory-observability.md); [AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html) |
| Give agents your existing REST APIs, OpenAPI specs, Lambda functions or MCP servers as tools without rewriting the services | Gateway | [gateway procedure](agentcore-gateway.md) |
| Let the agent act on behalf of a user in Google, Microsoft, Okta, Salesforce or another OAuth provider; store and refresh tokens per user | Identity | [credentials & security](agentcore-credentials-and-security.md); [Obtain OAuth 2.0 access tokens](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-authentication.html) |
| Run model-generated or untrusted code safely (data analysis, scripts, notebooks) in a sandbox | Code Interpreter | [Code Interpreter](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html) |
| Browse websites, fill forms, navigate web apps and extract data (a portal login or an invoice download is this job) | Browser | [Browser](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-tool.html) |
| Trace, debug and monitor agent runs in production (OpenTelemetry, CloudWatch), see every step and tool call | Observability | [memory & observability](agentcore-memory-observability.md) |
| Score agent quality, catch regressions, block a release when checks fail (LLM-as-a-Judge, custom evaluators), then tune prompts and tool descriptions | Evaluations | [registry & evaluations](agentcore-registry-evaluations.md); [Optimization](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/optimization.html) |
| Allow or deny which tools an agent may call and under what conditions, with rules enforced outside the model | Policy | [AgentCore Policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html) |
| Catalog, publish, approve and discover agents, MCP servers, tools and skills across the organization | Registry | [registry & evaluations](agentcore-registry-evaluations.md) |
| Let the agent pay for x402-protected APIs, MCP tools or content with spending limits | Payments | [payments procedure](agentcore-payments.md) |

**Routing rules:**

- Pick ONE primary component per task. Add a second only when the user's task names two jobs (for example, host the agent AND remember users: Runtime plus Memory).
- When the user names an AgentCore component directly, use that component's row even if the task wording also matches another row.
- Classic Bedrock Agents (`bedrock-agent`), model invocation and Knowledge Bases are not AgentCore components. Route those through the "Which Bedrock Capability Do You Need?" table in SKILL.md.
- Components without a bundled reference (Code Interpreter, Browser, Policy) link to the AWS documentation. Read the linked page before responding.

This table is checked by `scripts/check_agentcore_routing.py` (stdlib only): run it after editing the table, the component list in SKILL.md, or any reference file it links to.

## Protocol Selection Guide

AgentCore Runtime supports 4 protocols. You MUST select before building the container — each has a different contract.

| Protocol | Container Contract | Best For |
|----------|-------------------|----------|
| **HTTP** | Health: `/ping` (GET), Invocation: `/invocations` (POST, JSON/SSE), optional `/ws` WebSocket, Port: 8080 | Existing web frameworks (FastAPI, Express, Flask). Simple request-response agents. |
| **MCP** | Endpoint: `/mcp` (POST, JSON-RPC / streamable-http), Port: 8000 | Tool-centric agents exposing capabilities as MCP tools. MCP ecosystem integration. |
| **A2A** | Agent Card: `/.well-known/agent-card.json`, root `/` POST endpoint (JSON-RPC 2.0), Health: `/ping`, Port: 9000 | Multi-agent systems with direct agent-to-agent communication. |
| **AG-UI** | Health: `/ping`, Event stream: `/invocations` (SSE), optional `/ws` WebSocket, Port: 8080, SSE standard event types | Frontend-connected agents with real-time UI updates. Chat interfaces. |

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
| **Health check** | Checked via the `/ping` GET endpoint for all protocols except MCP (returning `{"status":"Healthy"\|"HealthyBusy"}`) |
| **Port** | Per-protocol default: HTTP 8080, MCP 8000, A2A 9000, AG-UI 8080 (configurable) |
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
