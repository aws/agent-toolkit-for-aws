# Bedrock — Startup Decision Guide

## Model Selection: Cost-First Thinking

**The #1 startup cost trap**: Defaulting to Claude Sonnet/Opus "to be safe" during prototyping, then getting locked into those costs at scale.

### Stage-Specific Strategy

| Stage         | Strategy                                               | Why                                                                                               |
| ------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| Pre-seed/Seed | Nova Micro/Lite for everything, Sonnet only for demos  | Credits burn fast on token-heavy workloads; prove the product logic works with cheap models first |
| Series A      | Route 80% to Nova Micro/Lite, 20% to Sonnet            | Intelligent routing saves 60-70% vs blanket Sonnet usage                                          |
| Series B+     | Optimize per-endpoint with measured quality thresholds | You have traffic data now — let it drive model selection                                          |

### Counterintuitive Advice

- **Don't start with the best model and optimize later.** Start with Nova Micro. If it fails, you've learned exactly what capability gap you need — and you'll prompt-engineer around it first. Most startups discover 70%+ of their calls work fine on the cheapest model.
- **Nova Pro is underrated.** For most startup use cases (summarization, extraction, Q&A), Nova Pro matches Claude Sonnet quality at ~3-5x lower cost per token. Evaluate it before assuming you need Anthropic models.
- **Batch API saves 50% — use it aggressively.** Any workload that doesn't need real-time response (nightly processing, background enrichment, evaluation runs) should use batch. Most startups leave this on the table.

## Architecture: What NOT to Build Early

### The Agent Tax

Every agent step multiplies cost: tool selection reasoning + tool execution + result synthesis = 3-5x the token cost of a single invoke.

**Startup rule of thumb:**

- < $500/month LLM spend → Never use agents. Use `InvokeModel` with structured prompts.
- $500-5K/month → One simple agent max. Router + specialist only if you have genuinely distinct domains.
- $5K+/month → Agent architecture justified if you have evidence single-call can't do the job.

### Credits-Specific Guidance

- Bedrock on-demand pricing is token-based — AWS Activate credits cover it fully (no commitment needed)
- **Don't buy Provisioned Throughput with credits.** Credits expire; provisioned commitments don't. You'll be stuck paying on-demand rates after credits burn down with capacity you may not need.
- Prompt caching is automatic for supported models — structure your prompts with stable system prompts first to maximize cache hits (free repeated tokens)

## Knowledge Bases: PoC Cost Trap

**OpenSearch Serverless minimum cost: ~$700/month** (2 OCU indexing + 2 OCU search minimum).

### Startup Alternatives

| Monthly queries | Vector store choice                                       | Monthly cost             |
| --------------- | --------------------------------------------------------- | ------------------------ |
| < 1,000         | Skip KB entirely — stuff context into prompt              | $0 (just token cost)     |
| 1K-50K          | Aurora Serverless v2 with pgvector                        | $50-150 (scales to zero) |
| 50K-500K        | Single OpenSearch Serverless collection shared across KBs | $700 minimum             |
| 500K+           | Dedicated OpenSearch Serverless per KB                    | $700+ per collection     |

**When to graduate from prompt-stuffing to RAG:**

- Source documents exceed 50K tokens total
- Documents change frequently (weekly+)
- You need citation/attribution in answers
- Multiple distinct document collections need separate retrieval

## Anti-Patterns (Startup-Specific)

- **Building "AI features" before product-market fit.** LLM costs scale with users. If you haven't validated demand, you're burning credits on a product nobody wants. Validate with a Wizard-of-Oz or rules-based MVP first.
- **OpenSearch Serverless for a PoC.** $700/month minimum for something 50 users will touch. Use pgvector on Aurora Serverless or just stuff documents into prompts until scale demands RAG.
- **Custom fine-tuning before exhausting prompt engineering.** Fine-tuning on Bedrock costs real money (training tokens + hosting custom model). 95% of startup use cases are solved with better prompts + few-shot examples. Fine-tune only when you have 10K+ labeled examples and measurable quality gap.
- **Not tracking per-feature token costs.** When you have 5 AI features, one will be 80% of your bill. Without per-feature cost attribution, you can't make informed product decisions about which features to keep/kill/optimize.
