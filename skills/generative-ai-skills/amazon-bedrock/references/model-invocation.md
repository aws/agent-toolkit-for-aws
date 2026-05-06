# Model Invocation — Converse API & InvokeModel Reference

## Table of Contents

- Converse API Request Structure
- Streaming with ConverseStream
- InvokeModel (Provider-Specific)
- Cross-Region Inference
- Prompt Caching
- Service Tiers
- Prompt Management
- max_tokens Quota Mechanics
- Throttling & Retry Strategy

## Converse API Request Structure

The Converse API is the unified interface. Key fields:

| Field | Required | Purpose |
|-------|----------|---------|
| `modelId` | Yes | Model ID, cross-region ID (`us.` prefix), or prompt ARN |
| `messages` | Conditional | Conversation history: `[{role, content}]`. Required unless using a prompt ARN, where messages are optional (appended after prompt's messages) |
| `system` | No | System prompt: `[{text: "..."}]` |
| `inferenceConfig` | No | `maxTokens`, `temperature`, `topP`, `stopSequences` |
| `toolConfig` | No | Tool definitions for function calling |
| `guardrailConfig` | No | Guardrail ID + version |
| `additionalModelRequestFields` | No | Provider-specific fields not in Converse |
| `additionalModelResponseFieldPaths` | No | JSON Pointer paths for extra model response fields to return |
| `outputConfig` | No | Output format configuration (e.g., structured text format) |
| `performanceConfig` | No | Latency optimization settings |
| `promptVariables` | No | Variable values for prompt management templates (`{{variable}}` placeholders) |
| `requestMetadata` | No | Key-value pairs for filtering invocation logs |
| `serviceTier` | No | Processing tier object: `{"type": "<value>"}` where value is `"reserved"`, `"priority"`, `"default"`, or `"flex"` |

**Content block types** in messages:

| Type | Use For |
|------|---------|
| `text` | Text content |
| `image` | Image input (base64 or S3) |
| `document` | PDF, DOCX, etc. |
| `video` | Video input |
| `audio` | Audio content in conversation |
| `toolUse` | Model requesting tool execution (in assistant messages) |
| `toolResult` | Tool execution result (in user messages) |
| `guardContent` | Content to evaluate with guardrail selectively |
| `cachePoint` | Prompt caching marker |
| `reasoningContent` | Chain of Thought reasoning from extended thinking models |
| `citationsContent` | Generated text with associated citation/source traceability |
| `searchResult` | Search result content block |

Refer to the latest AWS documentation on Bedrock Converse API for supported content types and fields.

**Security note**: For workloads handling PII or sensitive data, use `guardrailConfig` to apply content filtering to both prompts and responses, and `guardContent` blocks to selectively evaluate only user input while excluding system prompts. See [guardrails reference](guardrails.md) for configuration details and the PII logging compliance gap.

## Streaming with ConverseStream

Events arrive in strict order:

```
messageStart (role)
  → contentBlockStart (contentBlockIndex, toolUse start if applicable)
    → contentBlockDelta (text delta or toolUse input delta) — repeated
  → contentBlockStop
  → (next content block if multiple)
→ messageStop (stopReason — see values below)
→ metadata (metrics: latencyMs; usage: inputTokens, outputTokens, totalTokens)
```

`stopReason` values:

- `end_turn` — model finished naturally
- `tool_use` — model wants to call a tool, process toolUse blocks
- `max_tokens` — hit maxTokens limit, response may be truncated
- `stop_sequence` — model generated one of your custom stop sequences
- `guardrail_intervened` — a guardrail blocked the response, check trace for details
- `content_filtered` — model's built-in safety filtered the response

Additional values exist for edge cases (`malformed_model_output`, `malformed_tool_use`, `model_context_window_exceeded`). Refer to the latest AWS documentation on Bedrock Converse stopReason for the full current list — new values are added as features launch.

## InvokeModel (Provider-Specific)

Use InvokeModel ONLY for provider-specific features not available in Converse. For streaming with InvokeModel, use `InvokeModelWithResponseStream` — it returns the same provider-specific response format but as a stream. Each provider has a different request body format:

**Anthropic Claude**: `anthropic_version` required, `messages` format differs from Converse.
**Meta Llama**: Uses `prompt` string with `max_gen_len` and `temperature`. Llama 2 uses `[INST]...[/INST]` prompt wrapping; Llama 3+ uses `<|begin_of_text|><|start_header_id|>user<|end_header_id|>...<|eot_id|><|start_header_id|>assistant<|end_header_id|>` special tokens.
**Amazon Titan**: Uses `inputText`, `textGenerationConfig`.
**Amazon Nova**: Uses Converse-compatible format but with Nova-specific parameters.

For detailed format examples, parameter names, and common mistakes per provider, see [prompt engineering by model](prompt-engineering-by-model.md).

Refer to the latest AWS documentation on Bedrock InvokeModel for current request body formats per provider. The Converse API eliminates the need to know these formats for most use cases.

## Cross-Region Inference

Model ID format determines how requests are routed:

- In-region (base model ID): e.g., `anthropic.claude-3-haiku-20240307-v1:0` — single-region invocation, only for models with In-Region availability in your region
- Geo cross-region (inference profile): e.g., `us.anthropic.claude-sonnet-4-6` — routes within a geography (US, EU, APAC). Required for many newer models, even for standard on-demand invocation
- Global cross-region (inference profile): e.g., `global.anthropic.claude-sonnet-4-6` — routes to any commercial region where the model is available, for maximum throughput
- Provisioned throughput: ARN format `arn:aws:bedrock:<region>:<account-id>:provisioned-model/<id>`

Common errors from using the wrong ID format:

- Using a base model ID for a model without In-Region support: `ValidationException: "on-demand throughput isn't supported"` — use an inference profile ID instead
- Using a cross-region prefix from an unsupported source region: `ResourceNotFoundException` or `AccessDeniedException`

Verify the Correct ID format:

- For foundation models: `aws bedrock get-foundation-model --model-identifier``<model-id>```
- For inference profiles: `aws bedrock list-inference-profiles --region <region>` - see [Supported inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)

## Prompt Caching

Insert `cachePoint` blocks in the content to mark cache boundaries:

```json
{"cachePoint": {"type": "default"}}
```

Placement rules:

- Place after large, reusable content (system prompts, few-shot examples, documents)
- Content before the cachePoint is cached; content after is not
- Supported on select models — refer to the latest AWS documentation on Bedrock prompt caching for current model support and availability
- Reduces latency and cost for repeated prompts with shared prefixes

## Service Tiers

| Tier | API Value | Behavior | Use When |
|------|-----------|----------|----------|
| Reserved | `reserved` | Guaranteed capacity, committed pricing | Mission-critical apps, no downtime tolerance |
| Priority | `priority` | Preferential processing, lower latency | Customer-facing apps sensitive to latency |
| Standard | `default` | Standard processing | Most workloads (used when `serviceTier` is omitted) |
| Flex | `flex` | Best-effort, may queue during peak | Non-time-critical: evaluations, batch summarization |

Set via `serviceTier` object in Converse API request: `"serviceTier": {"type": "priority"}`. If omitted, Bedrock routes to the Standard tier (API value `"default"`).

Refer to the latest AWS documentation on Bedrock service tiers for current pricing, latency benchmarks, and model availability per tier.

## Prompt Management

When using a managed prompt, pass the prompt ARN as `modelId`:

```
modelId: "arn:aws:bedrock:us-east-1:<account-id>:prompt/PROMPTID:1"
```

**Critical restrictions when using managed prompts:**

- MUST NOT include `inferenceConfig` — baked into the prompt definition
- MUST NOT include `system` — baked into the prompt definition
- MUST NOT include `toolConfig` — baked into the prompt definition
- MUST NOT include `additionalModelRequestFields`
- If you include `messages`, they are **appended after** the prompt's messages, not replacing them
- `promptVariables` field: JSON with keys matching `{{variable}}` placeholders in the prompt
- Pin version in production: use `:1` suffix, not DRAFT
- `guardrailConfig` still works — applied to the entire prompt + appended messages

## max_tokens Quota Mechanics

Bedrock reserves quota at request start based on total input tokens (including cache read/write tokens) + `max_tokens`. Three stages:

1. **Initial reservation**: `InputTokenCount + CacheReadInputTokens + CacheWriteInputTokens + max_tokens` — determines if request is throttled
2. **Dynamic adjustment**: Bedrock releases unused reserved tokens as output is generated
3. **Final settlement**: `InputTokenCount + CacheWriteInputTokens + (OutputTokenCount × burndown rate)` — `CacheReadInputTokens` do not count toward final settlement

**Burndown rate**: Anthropic Claude 3.7+ models have a **5x burndown rate** for output tokens — 1 output token = 5 quota tokens at settlement. All other models: 1x.

**Impact of unset max_tokens** (Claude Sonnet example): With 500 input tokens:

- `max_tokens=1000`: reserves 1,500 tokens → ~1,333 concurrent requests from 2M TPM
- `max_tokens` unset (defaults to model max): reserves based on model's max output — e.g. 8,192 for Claude 3.5 Sonnet v2, up to 64K for Claude 3.7 Sonnet/4.x with extended thinking → as few as ~31 concurrent requests from 2M TPM
- **Massive difference** in concurrent capacity from one parameter (up to 43x with 64K models)

Right-size `max_tokens` to your expected output length. Use CloudWatch `OutputTokenCount` metrics to calibrate.

**Model invocation logging**: If model invocation logging is enabled, full prompts and responses are captured to CloudWatch Logs and/or S3. This is disabled by default but when enabled, logs contain complete text of every request and response. For PII-sensitive workloads: encrypt log destinations with KMS, restrict access, or disable invocation logging entirely. See the parent skill's Critical Warnings section for the guardrails PII logging gap.

## Throttling & Retry Strategy

Two types of 429 ThrottlingException:

- **RPM (requests per minute)**: Too many requests. Quota refreshes on 60-second windows.
- **TPM (tokens per minute)**: Too many tokens reserved. Affected by max_tokens (see above).

Use adaptive retry mode — it handles both types:

```python
from botocore.config import Config
config = Config(retries={"max_attempts": 5, "mode": "adaptive"})
```

For sustained throttling:

- Right-size `max_tokens` (biggest impact)
- Check current limits: `aws service-quotas get-service-quota --service-code bedrock --quota-code <code> --region <region>`
- Request quota increase through AWS Service Quotas
- Consider provisioned throughput for predictable high-volume workloads
- Use batch inference for non-real-time processing (discounted pricing)
