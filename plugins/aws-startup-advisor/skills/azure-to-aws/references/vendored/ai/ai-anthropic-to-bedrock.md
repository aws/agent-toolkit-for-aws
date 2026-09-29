# Anthropic SDK → Amazon Bedrock Migration

> Canonical Anthropic-SDK → Bedrock client-swap guide. Source-cloud agnostic:
> the mapping depends on the SDK the code uses, never on which cloud hosted it.
> Vendored into each consuming skill as
> `references/vendored/ai/ai-anthropic-to-bedrock.md` and kept byte-identical by
> `shared:check`; edit HERE, then run `shared:sync`.
>
> Loaded by `design-ai.md` when `ai_source == "anthropic"`.
> The user is already on Claude via the Anthropic SDK. Migration is a client swap only.
> Mapping an older Claude version to a newer target is a model change. Validate
> request controls and output behavior before cutover.

---

## Step 1: Map model IDs to Bedrock

| Anthropic SDK model                    | Bedrock model ID                                                                   | Tier     | Input/Output per 1M                                                |
| -------------------------------------- | ---------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------ |
| `claude-opus-4-*` / `claude-opus-5-5*` | `global.anthropic.claude-opus-5-5` (Global) / `us.` `eu.` `au.` `jp.` Geo profiles | Premium  | Global $4/$20; commercial Geo/Mantle $4.40/$22; GovCloud $4.80/$24 |
| `claude-sonnet-5-*`                    | `anthropic.claude-sonnet-5`                                                        | Flagship | $2 / $10 intro†                                                    |
| `claude-sonnet-4-*`                    | `anthropic.claude-sonnet-5`                                                        | Flagship | $2 / $10 intro†                                                    |
| `claude-haiku-4-*`                     | `anthropic.claude-haiku-4-5-20251001-v1:0`                                         | Fast     | $1 / $5                                                            |

† Claude Sonnet 5 intro pricing through Aug 31, 2026; then $3 / $15 (same as Sonnet 4.6). Prefer the `us.` inference-profile prefix for on-demand invoke. Sonnet 4.6 (`anthropic.claude-sonnet-4-6`) remains Active if the customer must stay on the 4.6 SKU.

Older Claude models — Claude 3.5 Haiku, Claude 3 Sonnet, Claude 3.5 Sonnet (v1/v2), Claude 3 Haiku, and Claude 3.7 Sonnet — are past EOL or within the 90-day exclusion window. Do **not** recommend them as migration targets. See `references/vendored/ai/ai-model-lifecycle.md` for authoritative status (recomputed each run).

**Recommendation:** Default new Bedrock targets to **Claude Sonnet 5** (flagship) / **Claude Opus 5.5** (demanding reasoning; 20% lower standard input/output token prices than Opus 5; [Anthropic reports improved token efficiency](https://claude.com/blog/what-a-task-costs-on-opus-5-5), with actual usage varying by task and effort setting) / **Claude Haiku 4.5** (cost/speed). Converse API call shape is identical across generations. Do **not** default to Claude Fable 5 (frontier / Mythos-class pricing — opt-in only).

---

## Step 2: Rewrite client

Before: `anthropic.Anthropic(api_key=...)`
After: `boto3.client("bedrock-runtime", region_name="us-east-1")`

Remove ANTHROPIC_API_KEY. Use IAM role with bedrock:InvokeModel.

---

## Step 3: Rewrite API calls

Before: `client.messages.create(model=..., max_tokens=1024, messages=[{"role": "user", "content": "Hello"}])`

After: `client.converse(modelId="anthropic.claude-sonnet-5", messages=[{"role": "user", "content": [{"text": "Hello"}]}], inferenceConfig={"maxTokens": 1024})`

Key differences:

- content is typed blocks [{"text": "..."}] not a plain string
- max_tokens moves to inferenceConfig.maxTokens
- Select text blocks by their `text` key; reasoning and tool blocks can appear first.

```python
text = "".join(block["text"] for block in response["output"]["message"]["content"] if "text" in block)
stop_reason = response.get("stopReason", "unknown")
if not text or stop_reason in ("max_tokens", "model_context_window_exceeded", "guardrail_intervened", "content_filtered", "refusal", "tool_use"):
    raise ValueError(f"No complete text response (stopReason={stop_reason})")
```

For tool loops, retain the original `response["output"]["message"]` in assistant history,
including signed reasoning blocks, and handle every tool request before continuing.
The extraction above is for calls that expect a final text answer.

---

## Step 4: System prompts

Before: `system="You are helpful"` as a string param
After: `system=[{"text": "You are helpful"}]` as a list of blocks

---

## Step 5: Streaming

Before: `client.messages.stream()` context manager
After: `client.converse_stream()` — iterate `response["stream"]` for `contentBlockDelta` events

---

## Step 6: IAM permissions

Add bedrock:InvokeModel and bedrock:InvokeModelWithResponseStream on arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-*

---

## Step 7: Request Bedrock quota

Request TPM increases via Service Quotas. Cross-region inference profiles (us.* prefix) have higher shared limits.

---

## Validation checklist

- [ ] anthropic.Anthropic() replaced with boto3.client("bedrock-runtime")
- [ ] client.messages.create() replaced with client.converse()
- [ ] content blocks use typed format [{"text": "..."}]
- [ ] max_tokens moved to inferenceConfig.maxTokens
- [ ] Streaming uses converse_stream with contentBlockDelta events
- [ ] ANTHROPIC_API_KEY removed from environment/secrets
- [ ] IAM role has bedrock:InvokeModel permission
- [ ] Model IDs updated to Bedrock format (Claude 4.x recommended)

## Opus 5.5 target contract (verified 2026-09-24)

The [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html) identifies `anthropic.claude-opus-5-5` as
Active, with a 1M-token context window and 128K maximum output. On `bedrock-runtime`,
use a supported Geo or Global inference profile, never the bare ID. `global.` requires
permission to route worldwide and is unavailable in GovCloud. Geo profiles are `us.`,
`eu.`, `au.`, and `jp.`; use the model card's source-region matrix, not a guessed prefix.

The bare ID is supported by **Mantle Messages** only in `us-east-1`, `ap-southeast-4`,
and `us-gov-west-1`. It is not a runtime in-region target. Probe the selected API/profile
in the actual account; catalog availability is not proof of account access.

Thinking is always adaptive and cannot be disabled. Use `output_config.effort`
(`low`, `medium`, `high`, `xhigh`, `max`; default `medium`), not a manual `budget_tokens`.
For Converse, place `thinking` and `output_config` in `additionalModelRequestFields`.
`max_tokens` includes thinking and response text. Re-evaluate token usage and output
headroom; fewer tokens are not guaranteed on every task.

**Batch is not supported.** Keep Opus 4.6 as an alternative when Batch is required,
after checking its availability and rates. Do not infer Batch support from
another Opus version. For sourced on-demand/cache rates and region/profile differences,
use `references/shared/pricing-cache.md`.

**Structured output:** Opus 5.5 rejects forced `tool_choice` types `any` and `tool`
(including Converse `toolChoice.tool`) because thinking cannot be disabled. It also
rejects assistant prefill and supplies no native schema guarantee. Use automatic tool
choice or prompted JSON with application schema validation and a bounded retry policy;
return an explicit failure if validation cannot be satisfied. If a model-enforced
schema guarantee is mandatory, select another verified compatible target explicitly.
Do not substitute Opus 4.8 as an automatic fallback.
