# Cross-Generation Claude Model Migration on Bedrock

Migration checklist for upgrading between Claude model generations on Bedrock. Each generation introduces breaking changes that fail silently or with unclear errors.

## Table of Contents

- [Claude 4.5 to 4.6 Migration](#claude-45-to-46-migration)
- [Claude 4.6 to 4.7 Migration](#claude-46-to-47-migration)
- [Failover Configuration](#failover-configuration)
- [Prompt Caching Across Generations](#prompt-caching-across-generations)

## Claude 4.5 to 4.6 Migration

### Breaking Changes

| Change | 4.5 Behavior | 4.6 Behavior | Impact |
|--------|-------------|-------------|--------|
| **Prefill** | Supported | Hard 400 error | MUST remove all prefill before switching. Use structured outputs or system prompt instructions instead. |
| **Structured outputs** | `output_format` param | `output_config.format` param (old name deprecated) | Update param name, or use `tool_use` for structured output (works on both). On Bedrock Converse API: `outputConfig.textFormat`. |
| **Thinking config** | `thinking: {type: "enabled", budget_tokens: N}` | `thinking: {type: "adaptive"}` | Failover logic MUST swap the config (not just strip it) to maintain thinking on both sides. |
| **Effort parameter** | Works on Opus 4.5 only. Errors on Sonnet 4.5 and Haiku 4.5. | GA on all 4.6 models (Opus, Sonnet, Haiku) | Failover to 4.5 Sonnet/Haiku MUST strip the effort parameter. |
| **Context window** | 200K tokens (Sonnet 4.5 1M deprecated April 30, 2026) | 1M tokens (GA) | Prompts sized for 1M WILL fail on 4.5 failover. This is the biggest silent risk. |
| **Cache thresholds** | Sonnet 4.5: 1,024 tokens. Opus 4.5: 4,096. | Sonnet 4.6: 2,048 tokens. Opus 4.6: 4,096. | Content cached on 4.5 (1,024–2,047 tokens) will NOT cache on Sonnet 4.6. |

### Migration Steps

1. **Remove prefill** from all requests. Replace with structured outputs or system prompt instructions.
2. **Update structured output params** — switch to `output_config.format` or use `tool_use` for cross-generation compatibility.
3. **Update thinking config** — change `{type: "enabled", budget_tokens: N}` to `{type: "adaptive"}`.
4. **Test effort parameter** — works on all 4.6 models. If using failover to 4.5, strip effort for Sonnet/Haiku 4.5.
5. **Verify prompt size** — if using >200K context, ensure failover targets also support it or add truncation logic.
6. **Verify cache thresholds** — if caching content between 1,024–2,047 tokens, it will stop caching on Sonnet 4.6. Increase content or accept the regression.
7. **Update model IDs** — e.g., `us.anthropic.claude-sonnet-4-5-20250929-v1:0` to `us.anthropic.claude-sonnet-4-6`.

## Claude 4.6 to 4.7 Migration

Opus 4.7 is available. Key changes:

- **Endpoint**: Use `bedrock-runtime` (same as 4.6). Model ID: `us.anthropic.claude-opus-4-7` or `global.anthropic.claude-opus-4-7`.
- **Thinking**: Same `{type: "adaptive"}` config as 4.6. Effort parameter works.
- **Context window**: 1M (same as 4.6).
- **Cache thresholds**: Verify with current docs — thresholds may differ from 4.6.

This migration is lower-risk than 4.5 → 4.6 since the API contract is consistent. Primary concern is testing output quality and verifying quota/pricing changes.

## Failover Configuration

When running multi-model routing (LiteLLM, custom AI gateways), failover between Claude generations requires config translation:

```
Primary: Claude Sonnet 4.6
  thinking: {type: "adaptive"}
  effort: "high"
  output_config: {format: ...}
  context_window: 1M

Fallback: Claude Sonnet 4.5
  thinking: {type: "enabled", budget_tokens: 10000}
  effort: STRIP (errors on Sonnet 4.5)
  output_format: ...  (not output_config)
  context_window: 200K (truncate if needed)
  prefill: must already be removed
```

Most AI gateways (LiteLLM, custom routers) handle param translation automatically. Verify your gateway supports Claude generation-specific config mapping.

## Prompt Caching Across Generations

Cache keys are model-specific. Cross-generation failover ALWAYS results in a cache miss on the fallback model. This impacts both latency (cold cache on failover) and cost (cache write charges on both models).

If using failover with prompt caching, account for:

- Double cache write cost during failover events
- Higher latency on the first request to the fallback model
- Different minimum token thresholds per generation (see [prompt-caching.md](prompt-caching.md))
