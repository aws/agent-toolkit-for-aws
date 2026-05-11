# Amazon Bedrock Converse API — Python SDK Quick Reference

> Condensed patterns for boto3 bedrock-runtime. For full API structure
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
pip install "boto3>=1.34.0"
```

## Quick Start

```python
import boto3
from botocore.config import Config

# MUST use bedrock-runtime client (not bedrock) for inference
# MUST configure adaptive retry for production
client = boto3.client(
    "bedrock-runtime",
    config=Config(retries={"max_attempts": 5, "mode": "adaptive"})
)

response = client.converse(
    modelId="us.anthropic.claude-sonnet-4-6",
    messages=[{"role": "user", "content": [{"text": "Hello"}]}],
    inferenceConfig={
        "maxTokens": 1024,  # MUST set explicitly — see Non-Obvious Patterns
        "temperature": 0.7,
    },
)
print(response["output"]["message"]["content"][0]["text"])
```

## Non-Obvious Patterns

- **maxTokens MUST be set explicitly.** Leaving it unset defaults to model maximum (64K for Claude) and silently reserves 43x more quota than needed — the #1 cause of unexpected ThrottlingException.
- **Cross-region model IDs** require a geographic prefix (`us.`, `eu.`, `apac.`, `global.`, `us-gov.`, `au.`, `jp.`, `ca.`, etc.). Using a direct model ID without the prefix for cross-region inference causes `ResourceNotFoundException` or `AccessDeniedException`. **Model IDs in code examples below may be outdated** — always verify current model IDs before use: `aws bedrock list-foundation-models --region <region>` and `aws bedrock list-inference-profiles --region <region>`, or refer to the latest [Bedrock supported models](https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html) and [cross-region inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference-support.html).
- **Newer models** may require inference profile IDs instead of model IDs. Verify the correct ID format: `aws bedrock get-foundation-model --model-identifier``<model-id>```
- **Prompt management**: Pass prompt ARN as `modelId` — it *replaces* the model ID, not alongside it. When using managed prompts, MUST NOT include `inferenceConfig`, `system`, `toolConfig`, or `additionalModelRequestFields` (baked into the prompt). Messages are *appended* after the prompt's messages, not replacing them.
- **Streaming events** arrive in order: `messageStart` → `contentBlockStart` → `contentBlockDelta` (repeated) → `contentBlockStop` → `messageStop` → `metadata`.
- **Retry only**: ThrottlingException, ModelTimeoutException, ServiceUnavailableException, InternalServerException. Do NOT retry: ValidationException, AccessDeniedException.
- **bedrock-runtime** for inference, **bedrock** for management. Using the wrong client is the #1 cause of `UnknownOperationException`.

## Streaming

```python
response = client.converse_stream(
    modelId="us.anthropic.claude-sonnet-4-6",
    messages=[{"role": "user", "content": [{"text": "Explain RAG in 3 sentences."}]}],
    inferenceConfig={"maxTokens": 1024},
)
for event in response["stream"]:
    if "contentBlockDelta" in event:
        print(event["contentBlockDelta"]["delta"].get("text", ""), end="")
    elif "metadata" in event:
        usage = event["metadata"]["usage"]
        print(f"\nTokens: {usage['inputTokens']} in, {usage['outputTokens']} out")
```

## Tool Use

```python
tool_config = {
    "tools": [{
        "toolSpec": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "City name"}},
                    "required": ["city"],
                }
            },
        }
    }]
}

response = client.converse(
    modelId="us.anthropic.claude-sonnet-4-6",
    messages=[{"role": "user", "content": [{"text": "What's the weather in Seattle?"}]}],
    inferenceConfig={"maxTokens": 1024},
    toolConfig=tool_config,
)

# Check if model wants to use a tool
if response["stopReason"] == "tool_use":
    tool_block = next(
        b["toolUse"] for b in response["output"]["message"]["content"] if "toolUse" in b
    )
    tool_name = tool_block["name"]       # "get_weather"
    tool_input = tool_block["input"]     # {"city": "Seattle"}
    tool_use_id = tool_block["toolUseId"]

    # IMPORTANT: Validate tool_input before use — model outputs are untrusted.
    # The model could return malformed or unexpected values. Validate types,
    # lengths, and allowlists before passing to any tool handler.

    # Execute tool, then send result back
    messages = [
        {"role": "user", "content": [{"text": "What's the weather in Seattle?"}]},
        response["output"]["message"],  # assistant message with toolUse
        {
            "role": "user",
            "content": [{
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"text": "72°F, sunny"}],
                }
            }],
        },
    ]
    final = client.converse(
        modelId="us.anthropic.claude-sonnet-4-6",
        messages=messages,
        inferenceConfig={"maxTokens": 1024},
        toolConfig=tool_config,
    )
```

## Guardrail Integration

```python
response = client.converse(
    modelId="us.anthropic.claude-sonnet-4-6",
    messages=[{"role": "user", "content": [{"text": "Tell me about investments"}]}],
    inferenceConfig={"maxTokens": 1024},
    guardrailConfig={
        "guardrailIdentifier": "my-guardrail-id",
        "guardrailVersion": "1",  # Pin version in production, don't use DRAFT
        "trace": "disabled",  # MUST be "disabled" in production — "enabled" exposes PII/harmful content in response (HIPAA/GDPR risk)
    },
)
```

## Best Practices

1. Always set `maxTokens` explicitly — never rely on default
2. Use `bedrock-runtime` for inference, `bedrock` for management
3. Use adaptive retry: `Config(retries={"max_attempts": 5, "mode": "adaptive"})`
4. Use cross-region model IDs (`us.` prefix) for higher availability
5. Pin prompt management versions in production (`:1` suffix in ARN)
6. Use `converse_stream` for user-facing applications (lower time-to-first-token)
7. Pin guardrail versions — don't use DRAFT in production
