# Cost Optimization

Understand what drives AgentCore costs and how to control them. Pricing values are volatile — always verify against the [AgentCore pricing page](https://aws.amazon.com/bedrock/agentcore/pricing/).

## Cost components

AgentCore charges for several things independently:

| Component | What you pay for | Published rate (verify for current) | Biggest cost drivers |
|---|---|---|---|
| **Runtime compute** | vCPU-hours + GB-hours while the session is active | v1 microVMs: $0.0895/vCPU-hr, $0.00945/GB-hr. v2 microVMs (consumption): $0.1276/vCPU-hr, $0.0169/GB-hr, billed per second on actual use, idle memory reclaimed after 120s | Session length, idle timeout, cold starts |
| **Short-term memory** | Events ingested, retrieved, and stored | From 2026-10-06: $1.00/GB ingested, $0.20/GB retrieved, $0.10/GB-month stored (through 2026-10-05 it was $0.25 per 1,000 new events) | Session volume, event payload size |
| **Long-term memory storage** | Long-term memory records stored | $0.75 per 1,000 records/month (built-in strategies); $0.25 (override/self-managed) | Number of strategies, expiry duration |
| **Long-term memory retrieval** | Retrieving memory records | $0.50 per 1,000 retrievals | Retrieval frequency, top_k value |
| **Gateway** | Per API call routed through gateway, plus search indexing | $0.005 per 1,000 (ListTools/InvokeTool/Ping); $0.025 per 1,000 (Search); tool indexing $0.02 per 100 tools/month | Tool call volume, number of indexed tools |
| **Evaluations** | Evaluator model usage | Built-in: $0.0024 per 1,000 input tokens, $0.012 per 1,000 output tokens. Custom: $1.50 per 1,000 evaluations (model usage billed separately). Batch evaluations: $0.0018 per 1,000 input tokens, $0.009 per 1,000 output tokens | Online eval sampling rate × session volume |
| **Bedrock model usage** | Input/output tokens for every model call | Varies by model — check Bedrock pricing | Model choice (Sonnet vs Haiku), conversation length |
| **Policy authorization** | Per authorization request + input tokens | $0.000025/request, $0.13 per 1,000 input tokens | Tool call volume with policy engine attached |
| **Identity** | Token/API key requests for non-AWS resources | $0.010 per 1,000 requests (no charge when used through Runtime or Gateway) | Credential fetch frequency |
| **CloudWatch logs/traces** | Ingestion and storage | Standard CloudWatch pricing | Log verbosity, retention policy |
| **ECR storage** (Container builds only) | Image storage | Standard ECR pricing | Image size, build frequency |

Rates above were read from the pricing page on 2026-10-26. Always verify against the [AgentCore pricing page](https://aws.amazon.com/bedrock/agentcore/pricing/) — pricing changes between releases.

## First-day cost questions

### "How much will my agent cost per invocation?"

There's no single number — it depends on:

- Which model (Haiku is ~10x cheaper than Sonnet per token)
- How long the session stays active (Runtime bills by vCPU-hour and GB-hour, not per request — idle sessions cost money)
- Whether it uses tools (gateway calls are $0.005 per 1,000 + any Lambda/API costs)
- Whether it uses memory (short-term memory is billed per GB ingested and retrieved; long-term strategies add record storage and retrieval charges)
- How long conversations run (more tokens = more model cost, and longer active sessions = more compute cost)

A simple Haiku-based agent with no memory and no tools costs very little per request — Runtime compute is billed by vCPU-hour and GB-hour (see the table), so a sub-second request on a small environment costs fractions of a cent. A Sonnet agent with semantic memory, 5 gateway tools, and online evals at 10% sampling costs significantly more per request — the model token costs alone can be 10–30x higher, plus memory ingestion and retrieval, gateway tool calls ($0.005 per 1,000 invocations), and evaluator usage. These are published rates as of the time of writing — verify against the [AgentCore pricing page](https://aws.amazon.com/bedrock/agentcore/pricing/) for current numbers. If the `awsknowledge` MCP server is available, use the `aws___search_documentation` tool to look up current AgentCore pricing.

### "How much will this demo/prototype cost me?"

Start from the smallest template that does the job (e.g. `agentcore create --name MyAgent --template agent-python-minimal`). Stay under the free tier where possible. The biggest surprises come from:

- **Idle sessions burning compute** — Runtime bills by vCPU-hour while the session is active, including idle time before `idleRuntimeSessionTimeout` reclaims it. Default timeout is 15 minutes. Call `StopRuntimeSession` when done, or lower the timeout. See `agents-harden` Session lifecycle management.
- Leaving an online eval config running at 100% sampling
- Forgetting to set CloudWatch log retention (defaults to indefinite)
- Keeping a test memory resource with an expensive strategy (SEMANTIC or EPISODIC) — the `agent-python-strands` template scaffolds a Memory by default with SEMANTIC, USER_PREFERENCE, SUMMARIZATION, and EPISODIC strategies, so check `memories[].strategies` in `agentcore/agentcore.json` and trim what you don't use

## Cost reduction levers

### Model selection

CLI templates can scaffold Bedrock, Anthropic, OpenAI, OpenAI-compatible, Gemini, or LiteLLM model clients — pick the right model for the task, not just the default:

| Model tier | Examples | Good for |
|---|---|---|
| **Cheapest / simplest** | `amazon.nova-micro-v1:0`, `claude-3-5-haiku-*`, Gemini Flash, GPT-5-nano | Classification, extraction, simple routing, short responses |
| **Mid-tier** | `amazon.nova-lite-v1:0`, Gemini 2.5 Flash | Most general-purpose agents with light reasoning |
| **Premium / reasoning** | `anthropic.claude-sonnet-4-5-*`, GPT-5, Gemini 2.5 Pro | Complex reasoning, code generation, multi-step planning |

Rules of thumb:

- Haiku or Nova Micro for simple extractive tasks (10–30x cheaper than Sonnet per token)
- Reserve Sonnet/Opus/GPT-5 for reasoning-heavy workflows
- **Use different models for agent vs evaluator** — a Haiku-based evaluator grading a Sonnet agent is a common cost-effective pattern
- For cost-sensitive customer support or classification agents, start with Nova Lite or Gemini Flash and only upgrade if quality is insufficient

### Memory

- Only enable strategies you actually use — each LTM strategy runs extraction on every session
- `SEMANTIC` is the most expensive strategy. If you only need session summaries, use `SUMMARIZATION` alone.
- Tune `relevance_score` up so fewer memory records retrieve per query
- Set `--event-expiry-duration` (days, 3–365) on `agentcore add memory` — or `eventExpiryDuration` in `agentcore.json` — to the shortest duration that serves your use case (default is 30 days)

### Online evals

- Start at 1–5% sampling in production, not 100%
- Use `agentcore eval online-eval pause --id <online-eval-id>` when debugging or iterating — `agentcore eval online-eval resume --id <online-eval-id>` when you're ready to measure (get the ID from `agentcore status --json`)
- Use `agentcore eval ondemand evaluate` on a handful of sessions while tuning evaluators instead of raising the online sampling rate
- Dataset replays (`agentcore eval ondemand simulate` / `batch-evaluation simulate`) invoke the agent once per example — you pay for those invocations and model tokens as well as the evaluations
- Pick the smallest evaluator set that gives signal

### Logs and traces

- Set retention policies on log groups:

  ```bash
  aws logs put-retention-policy \
    --log-group-name /aws/bedrock-agentcore/runtimes/<AGENT_ID>-DEFAULT \
    --retention-in-days 30
  ```

- Don't log entire payloads — log structured events with just what you need
- X-Ray sampling is configured automatically; no dial to turn there

### Gateway

- Tool calls are per-invocation, not per byte. Volume matters, not payload size.
- If a tool is called on every invocation for the same static data, consider baking that data into the system prompt instead

### Container builds

- If you don't need Container, use CodeZip — no ECR storage charge
- If you need Container, keep the image small (see `agents-harden` Initialization time section)

## Cross-references

- For model selection decisions, see [`references/evals.md`](evals.md) Path A (evaluator model choice applies the same way)
- For memory strategy decisions, see [`agents-build/references/memory.md`](../../agents-build/references/memory.md)
- For log retention (a harden concern), see `agents-harden` Observability section
