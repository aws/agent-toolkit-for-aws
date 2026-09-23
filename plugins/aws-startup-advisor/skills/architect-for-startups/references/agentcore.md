# AgentCore — Startup Decision Guide

## When to Use AgentCore (vs. Simpler Alternatives)

Most early-stage startups **should NOT start with AgentCore**. It's production infrastructure for agents you haven't built yet.

### Decision Framework

| Signal                                                    | Recommendation                                                                     |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Building your first AI feature                            | Skip AgentCore. Use Bedrock `InvokeModel` directly or Strands locally.             |
| Single agent, < 100 users                                 | Deploy on Lambda or ECS. AgentCore adds operational complexity you don't need yet. |
| Multiple agents needing shared memory/policy              | AgentCore justified — this is what it's built for.                                 |
| Need OAuth integration to 3rd-party APIs + access control | AgentCore Identity + Policy saves significant custom code.                         |
| Multi-tenant SaaS with per-customer agent guardrails      | AgentCore Policy (Cedar) is the right tool — building this custom is painful.      |

### When to Graduate to AgentCore

- You have 3+ agents that need to share session context
- You need Cedar-based policy enforcement (financial limits, role-based tool access)
- You need managed OAuth token refresh for third-party integrations
- You're spending engineering time building agent infrastructure instead of product features

## Cost Traps

- **AgentCore Runtime minimum: 1 vCPU / 2 GiB always-on.** Unlike Lambda, this doesn't scale to zero. At seed stage with 10 users, you're paying for idle capacity 23 hours/day.
- **Memory (LTM) provisioning: ~120-180s.** Not a cost trap, but a DX friction that slows iteration. STM is faster (~30-90s).
- **Session TTL defaults to 900s.** Idle sessions consume compute. For async/background agents, set short TTLs aggressively.

## Startup-Specific Architecture Advice

### Start Simple, Add Components Incrementally

```
Week 1-4:    Strands agent + Bedrock (no AgentCore)
Month 2-3:   Add AgentCore Runtime when you need persistent sessions
Month 3-6:   Add Policy when you have paying customers needing guardrails
Month 6+:    Add Memory, Gateway, Identity as specific needs emerge
```

**Counter to standard AWS guidance**: AWS docs suggest setting up the full stack (Runtime + Memory + Gateway + Policy + Observability). For startups, each component is operational overhead. Add them one at a time, driven by specific customer pain.

### Multi-Agent: Don't Go There Early

| Team size     | Agent architecture                          | Why                                                                  |
| ------------- | ------------------------------------------- | -------------------------------------------------------------------- |
| 1-3 engineers | Single agent, direct Bedrock calls          | You can't debug multi-agent orchestration AND build product features |
| 4-8 engineers | One supervisor + 2-3 specialist agents max  | Complexity grows exponentially with agent count                      |
| 8+ engineers  | Multi-agent with A2A or Bedrock Multi-Agent | You have the team to own the operational complexity                  |

### PoC to Production Pitfall

The AgentCore CLI (`agentcore init` → `agentcore deploy`) is fast for prototyping but creates resources that are NOT in IaC. Startups frequently build on CLI-deployed agents for months, then face a painful migration when they need CI/CD.

**Rule**: If you expect to use AgentCore for more than 2 weeks, start with CDK from day one. The AgentCore Starter Toolkit provides CDK templates — use them.

## Credits Guidance

- AgentCore Runtime compute is covered by AWS Activate credits (it's ECS/Fargate under the hood)
- Model invocations through agents still bill as Bedrock token usage (also credit-eligible)
- **Don't over-provision "because credits cover it"** — you're building muscle memory for architectures you can't afford post-credits

## What AgentCore Solves That's Hard to Build Custom

Only adopt AgentCore for these specific capabilities when you actually need them:

1. **Cedar policy enforcement on tool calls and Memory access** — AgentCore supports fine-grained access control (FGAC) for supported Memory operations through a Gateway and Cedar policies. For JWT-claim-based user or tenant isolation, configure OAuth (JWT) authentication and enforce Cedar policies that bind actor or namespace access to verified claims. IAM-authenticated callers can also be governed by Cedar using their IAM identity. `BatchCreateMemoryRecords`, `BatchUpdateMemoryRecords`, and `BatchDeleteMemoryRecords` are outside Cedar FGAC; IAM policies can allow or deny each batch operation as a whole. ([AWS documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-gateway-fgac.html); Memory FGAC guidance verified 2026-09-16.)
2. **Managed OAuth token lifecycle** — refresh tokens, secret rotation, multi-provider
3. **Cross-session memory with automatic summarization** — LTM extraction is non-trivial to build
4. **Built-in observability (OTel → X-Ray/CloudWatch)** — saves 1-2 weeks of instrumentation work
