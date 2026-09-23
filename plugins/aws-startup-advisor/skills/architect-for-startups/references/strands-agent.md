# Strands Agents — Startup Decision Guide

## When to Use Strands (vs. Alternatives)

| Situation                                    | Recommendation       | Why                                                                         |
| -------------------------------------------- | -------------------- | --------------------------------------------------------------------------- |
| Building first AI agent on AWS               | **Strands**          | Thinnest abstraction, least vendor lock-in, direct Bedrock integration      |
| Already invested in LangChain/LangGraph      | Stay on LangChain    | Migration cost isn't worth it unless you're hitting LangChain-specific pain |
| Need managed multi-agent orchestration       | Bedrock Agents       | If you don't want to manage containers and agent routing yourself           |
| Simple single-call LLM feature (no tool use) | Direct `InvokeModel` | Strands adds overhead you don't need for prompt-in/text-out                 |

## TypeScript vs Python: Startup Perspective

**Default to TypeScript for startups** unless your team is Python-native:

- Most startup backends are Node/TypeScript already — one language = one deployment pipeline
- Type safety catches tool schema bugs at compile time (agent tool bugs are expensive to debug in production)
- Strands TS has first-class support and bundles Zod for tool validation

**Pick Python only if**: Your team is Python-first, you need Python-specific ML libraries in tools, or you need Strands Evals (Python-only).

## Cost Architecture: The Tool Count Rule

**Each additional tool costs you money on every single invocation** because the model must reason about which tool to use. The cost isn't just token count — it's reasoning quality degradation.

| Tool count | Impact                                                    | Guidance                                   |
| ---------- | --------------------------------------------------------- | ------------------------------------------ |
| 1-3        | Minimal overhead, fast reasoning                          | Ideal for seed-stage agents                |
| 4-7        | Noticeable cost increase, occasional wrong tool selection | Acceptable if tools are clearly distinct   |
| 8-12       | Significant cost, frequent mis-routing                    | Split into multiple agents or add a router |
| 13+        | Unreliable, expensive                                     | Refactor immediately                       |

**Startup rule**: If your PoC agent has > 5 tools and you have < $2K/month LLM budget, you're over-engineering. Split into two focused agents or remove tools.

## Memory: Don't Add It Until You Need It

Memory modes ranked by startup relevance:

1. **NO_MEMORY (start here)**: Stateless tool-calling. Cheapest. Works for 80% of startup agent use cases (internal tools, one-shot tasks, API orchestration).
2. **STM_ONLY (add when)**: Users complain about repeating themselves within a session. Multi-turn conversations that reference earlier context.
3. **STM_AND_LTM (add when)**: You have paying users who want personalization across sessions AND you've validated they actually return frequently enough for LTM to matter.

**Cost of premature LTM**: Memory extraction runs additional model calls per session. At 1000 sessions/day, that's meaningful token spend for personalization most early users won't notice.

## Deployment: The Container Gotcha (TypeScript)

TypeScript agents REQUIRE containerized deployment (`--deployment-type container`). This means:

- ECR image build in your CI/CD pipeline
- Container image maintenance (base image updates, dependency patches)
- Slightly higher cold-start than Python agents

**If you're deploying to Lambda for cost reasons (scale-to-zero)**: Use Python Strands agents — they work with Lambda's native runtime. TypeScript agents need Lambda container image support (slower cold starts, 10GB image limit).

## Evaluation: Ship Evals from Day One (But Cheaply)

**Counterintuitive**: Most startups skip evals entirely OR over-invest in a massive eval suite. The right answer:

**Minimum viable eval suite (3 evaluators, ~$5/day at 100 test cases):**

1. `GoalSuccessRateEvaluator` — Did the agent achieve the user's intent?
2. `ToolSelectionAccuracyEvaluator` — Is it using the right tools?
3. `FaithfulnessEvaluator` — Is it hallucinating? (Critical for customer-facing agents)

**Add more evaluators only when**: You have a specific quality issue you can't diagnose with these three.

**Cost trap**: Evals invoke LLM-as-Judge. 9 evaluators × 500 test cases × daily = significant token spend. Start with 3 evaluators × 50 golden test cases × on-PR-only.

## Gotchas That Waste Startup Time

- **Default model is Claude Sonnet** — expensive for iteration. Override to Nova Micro/Lite during development: saves 10-20x on development costs.
- **VPC config is immutable** — if you deploy with VPC settings and realize you don't need them, you must create an entirely new agent config. Start WITHOUT VPC unless you know you need private resource access.
- **`agentcore destroy` deletes everything** — including memory resources with user data. Always `--dry-run` first. No undo.
- **Memory provisioning takes 2-3 minutes** — friction during rapid iteration. Use NO_MEMORY for development, add memory only in staging/prod configs.
- **OTel is on by default in AgentCore** — traces go to CloudWatch/X-Ray (which costs money). Disable with `--disable-otel` during early development if you're not looking at traces yet.
