# AgentCore Runtime — Service Card

## One-liner

Agent-purpose-built runtime with two compute types: serverless microVMs (managed
session routing, true session isolation, built-in identity, $0 billing during I/O
wait) and Instances (AWS-managed EC2 in your account for multi-day, GPU, or
instance-type-specific agents). Same APIs, identity, and observability across both.

## Best for

Short agent sessions with high LLM I/O wait, human-in-the-loop, multi-tenant
isolation, minimal ops, cross-session memory, high-volume session launch
(microVMs) — plus multi-day sessions, GPU/heavy compute, shared-host multi-agent
collaboration, and workloads that must pick an instance type (Instances).

## Compute types (scoring emits `agentcore_compute_type`)

|              | microVMs (default)              | Instances (capacity provider)                                                    |
| ------------ | ------------------------------- | -------------------------------------------------------------------------------- |
| Session cap  | 8h (`maxLifetime` ≤ 28,800s)    | 14 days (`maxLifetime` ≤ 1,209,600s)                                             |
| Compute      | ≤ 2 vCPU / 8 GB, no GPU         | broad EC2 choice incl. GPU, ARM64/x86_64                                         |
| Host model   | one agent per microVM           | multiple agents share host + filesystem (`/tmp/agentcore-session/<session-id>/`) |
| Billing      | consumption; $0 during I/O wait | EC2 in YOUR account (Savings Plans / ODCRs apply) + AgentCore management fee     |
| Idle         | scale to zero                   | session stop/restart (hibernate)                                                 |
| Launch scope | all AgentCore regions           | Linux only; limited launch regions — verify via MCP                              |

Routing (mirrors `scoring.py::_select_agentcore_compute_type`): >8h sessions, GPU or
heavy compute, or an instance-type requirement → Instances; everything else → microVMs.
An always-on service is still a better ECS/EKS fit — Instances sessions end at 14 days.

## Hard limits (verify via MCP — volatile)

- microVMs session cap: 8h; Instances session cap: 14 days (not indefinite)
- microVMs compute cap: 2 vCPU / 8 GB (Instances lifts this via EC2 instance choice)
- Instances launch regions: limited set at launch (2026-08) — verify current list
- AWS Agent Registry GA Regions (2026-08-31 snapshot): `us-east-1`, `us-west-2`,
  `ap-northeast-1`, `ap-southeast-2`, `eu-west-1`
  ([GA announcement](https://aws.amazon.com/about-aws/whats-new/2026/08/aws-agent-registry-generally-available)).
  Verify Registry availability in its intended Region before recommending it; Runtime
  availability does not establish Registry availability. See `freshness.md`.
- FedRAMP: authorization in progress (WIP) — verify current status; NOT a hard block

## Deployment models

- **Harness** — no-code, config-driven; single agent, greenfield, OpenAI Assistants migration.
- **Framework on Runtime** — Strands / LangGraph / CrewAI / custom; multi-agent, complex orchestration.

## Six dimensions

- Identity: built-in (free), OAuth via enhanced Identity
- Observability: auto OTEL traces
- Guardrails: Bedrock Guardrails + Policy (Cedar) for high-risk actions
- Scaling: 5,000 concurrent sessions, 25 TPS launch (adjustable)
- Tool/Gateway: Gateway for external APIs / MCP; per-user/per-target **rate limits**
  (request RPS/RPM on all targets, token TPM on inference targets, connection CPS)
  keyed on JWT claims / IAM principal / target / tool, most-specific-match-wins.
  Rate limits evaluate BEFORE Policy and the gateway is fail-open — they are a cost
  and fairness control, not a security boundary.
- Protocols: HTTP/1.1, WebSocket; MCP, A2A

## Conditional services (relevant but not always)

- Payments: for agents that pay / transact on a user's behalf — surface only for
  transactional / high-risk-action workloads.
- AWS Agent Registry (`registry`): centralized discovery and governance for agents, tools,
  skills, MCP servers, and custom resources. Surface when the user needs a shared catalog,
  resource discovery, or approval-based governance, including single-agent workloads; multiple
  agents alone are not a reason to add it. Registry catalogs resources; it does not orchestrate
  their execution. The former AgentCore Registry now uses the dedicated `agent-registry`
  namespace ([migration guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-faq.html)).
  Access it via console, CLI, SDK, or MCP; it integrates with AgentCore, Amazon Quick, and Kiro IDE.

## Tradeoffs

microVMs: 2 vCPU / 8 GB ceiling; no process-level suspend (Session Storage persists
files only). Instances: pricing shifts from consumption to EC2 + management fee (idle
instances cost money unless stopped); 14-day session ceiling; Linux only at launch;
capacity provider is immutable after creation except its description.

## Serving & security notes

Entry: POST /invocations + GET /ping. IAM: execution role with InvokeModel + Gateway/Registry/SessionStorage permissions as needed. Networking: public service endpoints over TLS; VPC endpoints only if policy demands. Instances additionally run EC2 in your account: capacity provider defines OS, allowed instance types, VPC/subnets/security groups, gp3 storage, and service/infrastructure roles.
