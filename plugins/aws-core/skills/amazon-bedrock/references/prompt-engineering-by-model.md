# Prompt Engineering by Model Family — Bedrock-Specific Patterns

Only Bedrock-specific behaviors that differ from base model documentation or that agents consistently get wrong. For general prompting techniques, agents already have sufficient training data.

## Converse API — Cross-Model Normalization

The Converse API maps its unified format to each provider's native format. This abstraction handles system prompts, message roles, and tool use automatically. **Use Converse for all new code** — the patterns below are only needed for InvokeModel or when the abstraction leaks.

When the Converse abstraction leaks — use `additionalModelRequestFields`:

- Claude: `top_k`, `anthropic_version` override
- Llama: `top_k`
- Titan: `textGenerationConfig` sub-fields not in `inferenceConfig`

How Converse maps the `system` field under the hood (matters when debugging unexpected behavior):

- **Claude**: Maps directly to Claude's native `system` field — first-class system prompt support
- **Llama**: Wraps in `<|start_header_id|>system<|end_header_id|>` block inside the prompt string
- **Titan**: Prepends to `inputText` — no native system prompt, so quality may differ from Claude/Llama
- **Nova**: Maps directly to Nova's native `system` array — first-class support like Claude

Refer to the latest AWS documentation on Bedrock Converse additionalModelRequestFields for current supported fields per model.

## Claude on Bedrock

**InvokeModel format** (only when Converse API is insufficient):

```json
{
  "anthropic_version": "bedrock-2023-05-31",
  "max_tokens": 1024,
  "system": "You are a helpful assistant.",
  "messages": [{"role": "user", "content": "Hello"}]
}
```

Bedrock-specific behaviors:

- `anthropic_version` is REQUIRED and MUST be `bedrock-2023-05-31` — this is the Bedrock-specific version string, NOT the Anthropic direct API version. Using the wrong version string returns `ValidationException`.
- `max_tokens` is required in InvokeModel (unlike Converse where it defaults). Omitting it returns `ValidationException`.
- System prompt goes in the top-level `system` field, not inside `messages`. Putting system content in a user message works but degrades instruction following.
- Claude on Bedrock supports the same system prompt conventions as direct Anthropic API: role definition, output format instructions, and behavioral constraints all go in `system`.
- **Prompt caching**: Place `cachePoint` markers after large system prompts or few-shot examples in Converse API. Refer to the latest AWS documentation on Bedrock prompt caching for current model support and availability.

Refer to the latest AWS documentation on Bedrock InvokeModel for Anthropic Claude for current request body fields.

## Llama on Bedrock

**InvokeModel format (Llama 3+):**

```json
{
  "prompt": "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\nWhat is RAG?\n<|eot_id|>\n<|start_header_id|>assistant<|end_header_id|>\n",
  "max_gen_len": 512,
  "temperature": 0.7,
  "top_p": 0.9
}
```

With system prompt:

```json
{
  "prompt": "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\nYou are a helpful assistant.\n<|eot_id|>\n<|start_header_id|>user<|end_header_id|>\nWhat is RAG?\n<|eot_id|>\n<|start_header_id|>assistant<|end_header_id|>\n",
  "max_gen_len": 512,
  "temperature": 0.7
}
```

Bedrock-specific behaviors:

- InvokeModel takes a raw `prompt` string — you MUST construct the special token template yourself. The Converse API does this automatically.
- The template format is the #1 mistake: agents often send Converse-style `messages` array to InvokeModel for Llama, which returns `ValidationException`.
- **Llama 3+ uses `<|begin_of_text|>`, `<|start_header_id|>`, `<|end_header_id|>`, `<|eot_id|>` tokens.** The older Llama 2 `[INST]<<SYS>>` format will not work correctly with Llama 3 models.
- System prompt gets its own header block (`<|start_header_id|>system<|end_header_id|>`) before the user block.
- Parameter names differ: `max_gen_len` (not `max_tokens`), `temperature`, `top_p`.
- Multi-turn: alternate `user` and `assistant` header blocks, each terminated with `<|eot_id|>`. The Converse API handles this — use it for multi-turn.

Multi-turn example:

```json
{
  "prompt": "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\nWhat is RAG?\n<|eot_id|>\n<|start_header_id|>assistant<|end_header_id|>\nRAG is Retrieval-Augmented Generation.\n<|eot_id|>\n<|start_header_id|>user<|end_header_id|>\nHow do I set it up on Bedrock?\n<|eot_id|>\n<|start_header_id|>assistant<|end_header_id|>\n",
  "max_gen_len": 512
}
```

- Refer to the latest AWS documentation on Bedrock Llama prompt format to verify the current template for newer Llama versions.

## Titan on Bedrock

**InvokeModel format:**

```json
{
  "inputText": "You are a helpful assistant.\n\nUser: What is RAG?\nAssistant:",
  "textGenerationConfig": {
    "maxTokenCount": 512,
    "temperature": 0.7,
    "topP": 0.9,
    "stopSequences": ["User:"]
  }
}
```

Bedrock-specific behaviors:

- No separate system prompt field in InvokeModel — prepend instructions to `inputText`. The Converse API adds system prompt support that InvokeModel lacks for Titan.
- Parameter names: `maxTokenCount` (not `max_tokens`), nested under `textGenerationConfig`.
- Multi-turn: must manually format as `User:` / `Assistant:` turns in `inputText` with `stopSequences: ["User:"]` — this prevents the model from generating the next user turn, which completion-style models will do without a stop sequence. Converse API handles this automatically.

Refer to the latest AWS documentation on Bedrock InvokeModel for Amazon Titan for current request body fields.

**Note:** Titan Embeddings (for Knowledge Bases) use a completely different format from text generation. Refer to the latest AWS documentation on Bedrock Titan Embeddings request body for current parameters.

## Nova on Bedrock

Nova is AWS-native with less community documentation — this is where the skill adds the most value.

**InvokeModel format:**

Nova uses a Converse-compatible message format through InvokeModel, unlike other providers:

```json
{
  "messages": [{"role": "user", "content": [{"text": "Hello"}]}],
  "system": [{"text": "You are a helpful assistant."}],
  "inferenceConfig": {"maxTokens": 1024, "temperature": 0.7}
}
```

Bedrock-specific behaviors:

- Nova's InvokeModel format mirrors the Converse API structure — this is unique among Bedrock models. Agents may incorrectly apply Claude or Llama format conventions to Nova.
- Nova supports multimodal input (text + image + video) through both Converse and InvokeModel.
- Nova-specific parameters beyond Converse's `inferenceConfig` go in `additionalModelRequestFields`.
- Nova models are only available on Bedrock — no external API or documentation outside AWS. Refer to the latest AWS documentation on Bedrock Nova for current capabilities and parameters.
- Nova Micro (text-only, lowest cost), Nova Lite (multimodal, balanced), Nova Pro (multimodal, highest capability). The prompt format is identical across all tiers — the difference is capability (Micro is text-only, Lite/Pro accept multimodal input). List current Nova model IDs: `aws bedrock list-foundation-models --region <region> --by-provider Amazon`

## Common Cross-Model Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Sending Converse `messages` format to InvokeModel for Llama | `ValidationException` | Use raw `prompt` string with Llama 3 special tokens |
| Using Anthropic API version instead of Bedrock version for Claude | `ValidationException` | Use `bedrock-2023-05-31` |
| Omitting `max_tokens`/`max_gen_len`/`maxTokenCount` in InvokeModel | `ValidationException` (Claude/Llama) or model default (Titan) | Always set explicitly |
| Putting system prompt in messages for Titan InvokeModel | Works but poor quality | Prepend to `inputText` |
| Applying Claude InvokeModel format to Nova | `ValidationException` | Nova uses Converse-compatible format |
| Using Llama special tokens in Converse API | Redundant, may confuse model | Converse handles formatting — send plain text |
