# Anthropic SDK → Amazon Bedrock Migration

> Canonical Anthropic SDK → Bedrock Runtime Messages (default) / Converse
> alternative guide. Source-cloud agnostic: the mapping depends on the SDK the
> code uses, never on which cloud hosted it. Vendored into each consuming skill as
> `references/vendored/ai/ai-anthropic-to-bedrock.md` and kept byte-identical by
> `shared:check`; edit HERE, then run `shared:sync`.
>
> Loaded by `design-ai.md` for an Anthropic source, or when Claude Haiku 5.5 is a candidate or selected target.
> For a non-Anthropic source, only the Haiku 5.5 target contract below applies;
> use the source provider guide for SDK and request translation. Steps 1–7 and
> the Anthropic Messages checklist apply only to Anthropic-source migrations.
> For an Anthropic source, the user is already on Claude via the Anthropic SDK.
> The default migration keeps that SDK and points it at the `bedrock-runtime`
> Anthropic Messages endpoint (`migration_path: "runtime_messages"`,
> `required_client_api: "messages"`), per
> [Inference using Anthropic Messages API](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html)
> (read 2026-11-07) and `references/vendored/ai/bedrock-endpoint-policy.md`.
> A Converse rewrite (`migration_path: "converse"`) is an explicit alternative;
> Mantle Messages (`migration_path: "mantle_messages"`) is selector-gated.
> Mapping an older Claude version to a newer target is a model change. Validate
> request controls and output behavior before cutover.

---

## Step 1: Map model IDs to Bedrock

| Anthropic SDK model                    | Bedrock model ID                                                                   | Tier     | Input/Output per 1M                                                |
| -------------------------------------- | ---------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------ |
| `claude-opus-4-*` / `claude-opus-5-5*` | `global.anthropic.claude-opus-5-5` (Global) / `us.` `eu.` `au.` `jp.` Geo profiles | Premium  | Global $4/$20; commercial Geo/Mantle $4.40/$22; GovCloud $4.80/$24 |
| `claude-sonnet-5-*`                    | `anthropic.claude-sonnet-5`                                                        | Flagship | $2 / $10 (Global); $2.20 / $11 (Geo)†                              |
| `claude-sonnet-4-*`                    | `anthropic.claude-sonnet-5`                                                        | Flagship | $2 / $10 (Global); $2.20 / $11 (Geo)†                              |
| `claude-haiku-4-*` / `claude-haiku-5-5*` | `anthropic.claude-haiku-5-5` (select a supported runtime inference profile below) | Fast | Global $0.10/$0.50 up to 100K prompt tokens; $0.50/$2.50 above 100K |

† Claude Sonnet 5 is $2 / $10 (Global) and $2.20 / $11 (Geo, `us.`-prefixed) per 1M tokens — the June 30, 2026 launch rate became the standard price on Sep 1, 2026 (the scheduled $3 / $15 increase was cancelled; see `references/vendored/ai/bedrock-pricing-cache.md`). Prefer the `us.` inference-profile prefix for on-demand invoke. Sonnet 4.6 (`anthropic.claude-sonnet-4-6`) remains Active if the customer must stay on the 4.6 SKU.

Claude Sonnet 5.5 facts (verified 2026-10-26 against its [Bedrock model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html)): Bedrock ID `anthropic.claude-sonnet-5-5`; Global profile `global.anthropic.claude-sonnet-5-5`; Geo profiles `us.` / `eu.` / `au.`; Active (launched 2026-09-28, EOL no sooner than 2027-09-28); 1M context, 128K max output; Global $2 / $10, Geo $2.20 / $11 per 1M tokens, cache read $0.10 Global / $0.11 Geo since Oct 7, 2026 (see the pricing cache). Forced `tool_choice` (`any` / named tool) is not supported — the card lists `auto` and `none` only; see the Capability Constraints table in `references/vendored/ai/ai-model-lifecycle.md`.

Older Claude models — Claude 3.5 Haiku, Claude 3 Sonnet, Claude 3.5 Sonnet (v1/v2), Claude 3 Haiku, and Claude 3.7 Sonnet — are past EOL or within the 90-day exclusion window. Do **not** recommend them as migration targets. See `references/vendored/ai/ai-model-lifecycle.md` for authoritative status (recomputed each run).

**Recommendation:** Default new Bedrock targets to **Claude Sonnet 5** (flagship) / **Claude Opus 5.5** (demanding reasoning; 20% lower standard input/output token prices than Opus 5; [Anthropic reports improved token efficiency](https://claude.com/blog/what-a-task-costs-on-opus-5-5), with actual usage varying by task and effort setting) / **Claude Haiku 5.5** (cost/speed). The Converse envelope is shared, but model-specific request controls and compatibility differ; apply the target contract below before changing models. Do **not** default to Claude Fable 5 (frontier / Mythos-class pricing — opt-in only).

---

## Step 2: Repoint the client (Runtime Messages, default)

Keep `anthropic.Anthropic`. Change only the base URL and the credential
([Inference using Anthropic Messages API](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html), read 2026-11-07):

Before: `anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])`

After:

```python
from anthropic import Anthropic
from aws_bedrock_token_generator import provide_token

region = "us-east-1"

def handle_request(prompt: str) -> str:
    # Mint one short-term Bedrock bearer token per client; the SDK accepts only a
    # string credential here, so create the client per request boundary and close it.
    with Anthropic(
        base_url=f"https://bedrock-runtime.{region}.amazonaws.com/anthropic",
        api_key=provide_token(region=region),
    ) as client:
        ...
```

- The base URL ends at `/anthropic`; the SDK appends `/v1/messages` itself and adds the
  required `anthropic-version` header.
- `api_key` is a **string** Bedrock token from `aws_bedrock_token_generator.provide_token`
  minted from the application's IAM credentials. Mint it per client and re-create the client at
  each request boundary; do not cache one token for the process lifetime.
- A short-lived CLI or test may instead export `AWS_BEARER_TOKEN_BEDROCK` (a Bedrock API key)
  and pass it as `api_key`; long-running services use `provide_token`.
- Remove `ANTHROPIC_API_KEY` from environment and secrets; the credential is now IAM-derived.

---

## Step 3: API calls

`client.messages.create(...)` is unchanged except for the model ID: use a supported `global.`
or Geo (`us.`/`eu.`/`au.`/`jp.`) inference-profile ID from Step 1 (for example
`global.anthropic.claude-sonnet-5`). Use the bare `anthropic.claude-*` ID only where the model
card documents an in-region runtime endpoint (today the `eu-west-2` Opus 5.5 route below).

Response parsing keeps the native shape: select text blocks by `type == "text"`, never by
position, because thinking and tool-use blocks can appear first.

```python
text = "".join(block.text for block in response.content if block.type == "text")
if not text or response.stop_reason in ("max_tokens", "refusal", "tool_use"):
    raise ValueError(f"No complete text response (stop_reason={response.stop_reason})")
```

For tool loops, retain the complete assistant `response.content` in history, including
signed thinking blocks, and handle every tool request before continuing.

---

## Step 4: System prompts

Unchanged: `system="You are helpful"` stays a string (or a list of native blocks) parameter.

---

## Step 5: Streaming

Unchanged: `with client.messages.stream(...) as stream:` and `stream.text_stream` /
`stream.get_final_message()` work as before. Keep the SDK accumulator so signed blocks stay
complete while only text deltas reach text consumers.

---

## Step 6: IAM permissions

Source: [Prerequisites for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-prereq.html) (read 2026-11-07).

- `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on the inference-profile ARN
  (`arn:aws:bedrock:{region}:{account}:inference-profile/global.anthropic.claude-sonnet-5`) **and**
  on the `foundation-model/anthropic.claude-*` ARN in every destination Region the profile routes to.
- `bedrock:GetInferenceProfile` on the inference-profile ARN.
- No `bedrock-mantle:*` permission is involved on this lane.

---

## Step 7: Request Bedrock quota

Request TPM increases via Service Quotas. Cross-region inference profiles (us.* prefix) have higher shared limits.

---

## Validation checklist (Runtime Messages lane)

- [ ] `anthropic.Anthropic` retained; `base_url` is `https://bedrock-runtime.{region}.amazonaws.com/anthropic` (ends at `/anthropic`; the SDK sends `/anthropic/v1/messages`)
- [ ] `api_key` is a string Bedrock token (`provide_token(region=...)` per client, or `AWS_BEARER_TOKEN_BEDROCK` for a short CLI); `ANTHROPIC_API_KEY` removed from environment/secrets
- [ ] Client created per request boundary and closed (`with Anthropic(...) as client:`)
- [ ] `messages.create` / `messages.stream` calls unchanged apart from the model ID
- [ ] Model IDs are supported `global.`/Geo inference profiles (bare ID only on a documented in-region route)
- [ ] Text selected by `type == "text"`; signed thinking/tool blocks preserved in tool history
- [ ] IAM grants `bedrock:InvokeModel*` on the profile and destination foundation-model ARNs plus `bedrock:GetInferenceProfile` on the profile
- [ ] `aws-design-ai.json` row records `migration_path: "runtime_messages"` and `required_client_api: "messages"`

## Converse alternative (explicit)

Record `migration_path: "converse"` only when the user asks for a Bedrock-native request shape or
needs a Converse-only feature (Guardrails on Converse, application inference profiles, per-request
metadata). This is a rewrite, not a repoint:

- Client: `anthropic.Anthropic(api_key=...)` → `boto3.client("bedrock-runtime", region_name="us-east-1")`.
- Calls: `client.messages.create(model=..., max_tokens=1024, messages=[{"role": "user", "content": "Hello"}])`
  → `client.converse(modelId="anthropic.claude-sonnet-5", messages=[{"role": "user", "content": [{"text": "Hello"}]}], inferenceConfig={"maxTokens": 1024})`.
  Content becomes typed blocks `[{"text": "..."}]`; `max_tokens` moves to `inferenceConfig.maxTokens`;
  select text blocks by their `text` key because reasoning and tool blocks can appear first:

  ```python
  text = "".join(block["text"] for block in response["output"]["message"]["content"] if "text" in block)
  stop_reason = response.get("stopReason", "unknown")
  if not text or stop_reason in ("max_tokens", "model_context_window_exceeded", "guardrail_intervened", "content_filtered", "refusal", "tool_use"):
      raise ValueError(f"No complete text response (stopReason={stop_reason})")
  ```

  For tool loops, retain the original `response["output"]["message"]` in assistant history,
  including signed reasoning blocks, and handle every tool request before continuing.
- System prompts: `system="You are helpful"` → `system=[{"text": "You are helpful"}]`.
- Streaming: `client.messages.stream()` → `client.converse_stream()`; iterate `response["stream"]`
  for `contentBlockDelta` events.
- IAM: the same `bedrock:InvokeModel*` grants as Step 6; `ANTHROPIC_API_KEY` removed.

## Mantle Messages (selector-gated)

Record `migration_path: "mantle_messages"` only together with a `bedrock_models[].mantle_selector`
from `references/vendored/ai/bedrock-endpoint-policy.md` — normally `workspaces` (Anthropic-compatible
Workspaces exist only on `bedrock-mantle`). The client shape is the Step 2 repoint with
`base_url="https://bedrock-mantle.{region}.api.aws/anthropic"`, a Bedrock API key or token as the
string `api_key`, the bare `anthropic.claude-*` model ID in a Mantle-listed Region, and
`bedrock-mantle:*` IAM instead of `bedrock:InvokeModel*`. API continuity alone never selects Mantle;
the Runtime lane above already keeps the Anthropic SDK.

## Opus 5.5 target contract (verified 2026-09-24)

The [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html) identifies `anthropic.claude-opus-5-5` as
Active, with a 1M-token context window and 128K maximum output. On `bedrock-runtime`,
use a supported Geo or Global inference profile, or the bare ID in `eu-west-2`
(runtime in-region availability verified 2026-10-03). Other runtime regions require CRIS. `global.` requires
permission to route worldwide and is unavailable in GovCloud. Geo profiles are `us.`,
`eu.`, `au.`, and `jp.`; use the model card's source-region matrix, not a guessed prefix.

For **Mantle Messages**, the bare ID is supported only in `us-east-1`, `ap-southeast-4`,
and `us-gov-west-1`. The London runtime in-region path uses the commercial
$4.40/$22 per 1M input/output rate (AWS Price List verified 2026-10-03). Probe the selected API/profile
in the actual account; catalog availability is not proof of account access.

Thinking is always adaptive and cannot be disabled. Use `output_config.effort`
(`low`, `medium`, `high`, `xhigh`, `max`; default `medium`), not a manual `budget_tokens`.
For Converse, place `thinking` and `output_config` in `additionalModelRequestFields`.
`max_tokens` includes thinking and response text. Re-evaluate token usage and output
headroom; fewer tokens are not guaranteed on every task.

**Batch is not supported.** Keep Opus 4.6 as an alternative when Batch is required,
after checking its availability and rates. Do not infer Batch support from
another Opus version. For sourced on-demand/cache rates and region/profile differences,
use `references/vendored/ai/bedrock-pricing-cache.md`.

**Structured output:** Opus 5.5 rejects forced `tool_choice` types `any` and `tool`
(including Converse `toolChoice.tool`) because thinking cannot be disabled. It also
rejects assistant prefill and supplies no native schema guarantee. Use automatic tool
choice or prompted JSON with application schema validation and a bounded retry policy;
return an explicit failure if validation cannot be satisfied. If a model-enforced
schema guarantee is mandatory, select another verified compatible target explicitly.
Do not substitute Opus 4.8 as an automatic fallback.

## Haiku 5.5 target contract (verified 2026-10-27)

The [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html) lists `anthropic.claude-haiku-5-5` as Active, with **1M context** and **128K maximum output**. On `bedrock-runtime`, select a supported `us.`, `eu.`, `au.`, `jp.`, or `global.` inference profile from the model card's source-region matrix; the bare ID has no in-region runtime endpoint. Global requires permission to route worldwide. `bedrock-mantle` uses the bare ID only in its listed regions. Verify the selected model/profile in the actual account before cutover.

Follow the [Haiku 5.5 migration guide](https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide):

- Omit `temperature`, `top_p`, and `top_k` (including Converse `temperature`/`topP`). Replace manual `thinking: {"type": "enabled", "budget_tokens": N}` with adaptive thinking; control depth with `output_config.effort`. For Converse, pass model-specific controls through `additionalModelRequestFields`. Adaptive thinking defaults to medium effort; reserve output headroom for thinking as well as answer tokens.
- End messages with a user turn; assistant prefill is rejected even with thinking disabled. Select text blocks by type, preserve signed thinking/tool blocks in tool loops, and handle truncation/refusal explicitly. Haiku 5.5 accepts forced tool choice, but the response then begins with the tool call without a thinking block; do not inherit Opus 5.5's forced-tool restriction.
- Keep replayed conversations append-only and use the account that produced their thinking blocks (or a linked account). Changes to earlier system/tools/messages can invalidate signatures. For Bedrock computer use, replace `computer_20250124` with `computer_20251124` and its `computer-use-2025-11-24` beta header.
- Recount target tokens: the newer tokenizer produces approximately 30% more tokens for the same text than Haiku 4.5, and image tokenization also changes. Re-evaluate output limits, retained thinking history, and costs rather than carrying forward source token counts.
- Apply the **100K prompt boundary**, including cache reads/writes, independently of the 1M context limit. Above 100K, higher input/output/cache rates apply to the whole request. Use the selected Global/Geo rates in `references/vendored/ai/bedrock-pricing-cache.md`; unknown request sizes require both tier scenarios, not a single savings claim.
- The Bedrock model card lists Standard as the supported service tier; do not assume Batch, Priority, Flex, Reserved, or provisioned capacity from another model's support. Tune effort, stream, verify quotas, and measure first-token/end-to-end latency on representative requests. A model's speed ranking is not a latency guarantee.

Keep Haiku 4.5 as an explicit alternative when a workload must retain its existing behavior and cannot yet satisfy the migration checks; use its own model/profile and prices. These are migration-guide recommendations. The separate `agent-advisor` executable catalogs remain curated independently and are not upgraded by editing this guide.
