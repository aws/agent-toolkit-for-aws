# Amazon Bedrock Converse API — TypeScript SDK Quick Reference

> Condensed patterns for @aws-sdk/client-bedrock-runtime. For full API structure
> and provider-specific formats, see [model-invocation.md](model-invocation.md).

## Table of Contents

- Install
- Quick Start
- Non-Obvious Patterns
- Streaming
- Tool Use
- Guardrail Integration
- Best Practices

## Install

```bash
npm install @aws-sdk/client-bedrock-runtime@^3.0.0
```

## Quick Start

```typescript
import {
  BedrockRuntimeClient,
  ConverseCommand,
  type Message,
} from "@aws-sdk/client-bedrock-runtime";

// MUST use BedrockRuntimeClient (not BedrockClient) for inference
const client = new BedrockRuntimeClient({
  region: "us-east-1",
  maxAttempts: 5,
  retryMode: "adaptive", // enables adaptive retry with client-side rate limiting
});

const response = await client.send(
  new ConverseCommand({
    modelId: "us.anthropic.claude-sonnet-4-6",
    messages: [{ role: "user", content: [{ text: "Hello" }] }],
    inferenceConfig: {
      maxTokens: 1024, // MUST set explicitly — see Non-Obvious Patterns
      temperature: 0.7,
    },
  })
);

console.log(response.output?.message?.content?.[0]?.text);
```

## Non-Obvious Patterns

- **maxTokens MUST be set explicitly.** Leaving it unset defaults to model maximum (64K for Claude) and silently reserves 43x more quota than needed — the #1 cause of unexpected ThrottlingException.
- **Cross-region model IDs** require a geographic prefix (`us.`, `eu.`, `apac.`, `global.`, `us-gov.`, `au.`, `jp.`, `ca.`, etc.). Using a direct model ID without the prefix for cross-region inference causes `ResourceNotFoundException` or `AccessDeniedException`. **Model IDs in code examples below may be outdated** — always verify current model IDs before use: `aws bedrock list-foundation-models --region <region>` and `aws bedrock list-inference-profiles --region <region>`, or refer to the latest [Bedrock supported models](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html) and [cross-region inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference-support.html).
- **Newer models** may require inference profile IDs instead of model IDs. Verify the correct ID format: `aws bedrock get-foundation-model --model-identifier``<model-id>```
- **Prompt management**: Pass prompt ARN as `modelId` — it *replaces* the model ID. When using managed prompts, MUST NOT include `inferenceConfig`, `system`, `toolConfig`, or `additionalModelRequestFields`. Messages are *appended* after the prompt's messages.
- **Streaming events** arrive in order: `messageStart` → `contentBlockStart` → `contentBlockDelta` (repeated) → `contentBlockStop` → `messageStop` → `metadata`.
- **Retry only**: ThrottlingException, ModelTimeoutException, ServiceUnavailableException, InternalServerException. Do NOT retry: ValidationException, AccessDeniedException.
- **BedrockRuntimeClient** for inference, **BedrockClient** for management. Wrong client = `UnknownOperationException`.

## Streaming

```typescript
import { ConverseStreamCommand } from "@aws-sdk/client-bedrock-runtime";

const response = await client.send(
  new ConverseStreamCommand({
    modelId: "us.anthropic.claude-sonnet-4-6",
    messages: [{ role: "user", content: [{ text: "Explain RAG in 3 sentences." }] }],
    inferenceConfig: { maxTokens: 1024 },
  })
);

if (response.stream) {
  for await (const event of response.stream) {
    if (event.contentBlockDelta?.delta?.text) {
      process.stdout.write(event.contentBlockDelta.delta.text);
    }
    if (event.metadata?.usage) {
      const { inputTokens, outputTokens } = event.metadata.usage;
      console.log(`\nTokens: ${inputTokens} in, ${outputTokens} out`);
    }
  }
}
```

## Tool Use

```typescript
import { ConverseCommand, type Message, type Tool } from "@aws-sdk/client-bedrock-runtime";

const tools: Tool[] = [{
  toolSpec: {
    name: "get_weather",
    description: "Get current weather for a city",
    inputSchema: {
      json: {
        type: "object",
        properties: { city: { type: "string", description: "City name" } },
        required: ["city"],
      },
    },
  },
}];

const response = await client.send(
  new ConverseCommand({
    modelId: "us.anthropic.claude-sonnet-4-6",
    messages: [{ role: "user", content: [{ text: "What's the weather in Seattle?" }] }],
    inferenceConfig: { maxTokens: 1024 },
    toolConfig: { tools },
  })
);

if (response.stopReason === "tool_use") {
  const toolBlock = response.output?.message?.content?.find((b) => b.toolUse)?.toolUse;
  if (toolBlock) {
    const { name, input, toolUseId } = toolBlock;
    // name = "get_weather", input = { city: "Seattle" }

    // IMPORTANT: Validate input before use — model outputs are untrusted.
    // The model could return malformed or unexpected values. Validate types,
    // lengths, and allowlists before passing to any tool handler.

    // Execute tool, then send result back
    const messages: Message[] = [
      { role: "user", content: [{ text: "What's the weather in Seattle?" }] },
      response.output!.message!, // assistant message with toolUse
      {
        role: "user",
        content: [{
          toolResult: {
            toolUseId,
            content: [{ text: "72°F, sunny" }],
          },
        }],
      },
    ];
    const final = await client.send(
      new ConverseCommand({
        modelId: "us.anthropic.claude-sonnet-4-6",
        messages,
        inferenceConfig: { maxTokens: 1024 },
        toolConfig: { tools },
      })
    );
  }
}
```

## Guardrail Integration

```typescript
const response = await client.send(
  new ConverseCommand({
    modelId: "us.anthropic.claude-sonnet-4-6",
    messages: [{ role: "user", content: [{ text: "Tell me about investments" }] }],
    inferenceConfig: { maxTokens: 1024 },
    guardrailConfig: {
      guardrailIdentifier: "my-guardrail-id",
      guardrailVersion: "1", // Pin version in production, don't use DRAFT
      trace: "disabled", // MUST be "disabled" in production — "enabled" exposes PII/harmful content in response (HIPAA/GDPR risk)
    },
  })
);
```

## Best Practices

1. Always set `maxTokens` explicitly — never rely on default
2. Use `BedrockRuntimeClient` for inference, `BedrockClient` for management
3. Set `maxAttempts: 5` and `retryMode: "adaptive"` on client for adaptive retry
4. Use cross-region model IDs (`us.` prefix) for higher availability
5. Pin prompt management versions in production (`:1` suffix in ARN)
6. Use `ConverseStreamCommand` for user-facing applications (lower time-to-first-token)
7. Pin guardrail versions — don't use DRAFT in production
