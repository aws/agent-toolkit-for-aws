# OpenAI Models on Amazon Bedrock

**Last verified:** 2026-08-21
**Sources:** [OpenAI model cards](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards-openai.html) (per-model
cards linked below), [GPT-5.6 launch post](https://aws.amazon.com/blogs/machine-learning/get-started-with-openai-gpt-5-6-sol-terra-and-luna-on-amazon-bedrock/),
[GPT-5.6 GA announcement](https://aws.amazon.com/about-aws/whats-new/2026/07/openai-gpt-sol-terra/),
[GPT-5.6 pricing update](https://aws.amazon.com/about-aws/whats-new/2026/07/openai-gpt-terra-luna-pricing-bedrock/)

OpenAI's **proprietary** models are available on Bedrock, not just the open-weight `gpt-oss` family. This changes the
default shape of every OpenAI → AWS migration: the source model itself is frequently a Bedrock target, so a
cross-family swap to Claude/Nova is no longer the only option — and is no longer the default.

**This file is the single source of truth for OpenAI-on-Bedrock facts in this plugin.** `ai-openai-to-bedrock.md`
(mapping policy), `design-ai.md` (selection), `estimate-ai.md` (costing), and `ai-migration-guardrails.md` (quota
risk) all defer to it. Do not restate model IDs, regions, or endpoint paths elsewhere — link here.

---

## Model Catalog

| Model               | Model ID (mantle)                        | Launched     | Context | Lifecycle | Model card                                                                                                                                           |
| ------------------- | ---------------------------------------- | ------------ | ------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| GPT-5.6 Sol         | `openai.gpt-5.6-sol`                     | Jul 13, 2026 | 1M      | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-sol.html)                                                       |
| GPT-5.6 Terra       | `openai.gpt-5.6-terra`                   | Jul 13, 2026 | 1M      | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-terra.html)                                                     |
| GPT-5.6 Luna        | `openai.gpt-5.6-luna`                    | Jul 13, 2026 | 1M      | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-luna.html)                                                      |
| GPT-5.5             | `openai.gpt-5.5`                         | Jun 1, 2026  | 272K    | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-55.html)                                                           |
| GPT-5.4             | `openai.gpt-5.4`                         | Jun 1, 2026  | 272K    | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html)                                                           |
| gpt-oss-120b        | `openai.gpt-oss-120b`                    | Aug 5, 2025  | 128K    | Active    | open-weight; also on `bedrock-runtime` as `openai.gpt-oss-120b-1:0`                                                                                  |
| gpt-oss-20b         | `openai.gpt-oss-20b`                     | Aug 5, 2025  | 128K    | Active    | open-weight; also on `bedrock-runtime` as `openai.gpt-oss-20b-1:0`                                                                                   |
| GPT OSS Safeguard   | `openai.gpt-oss-safeguard-120b` / `-20b` | —            | —       | Active    | content-moderation / guardrail enforcement, not general chat                                                                                         |
| Daybreak Blue / Red | (gated)                                  | —            | —       | Active    | GPT-5.6 Cyber variants; require Trusted Access for Cyber enrollment — listed so they are not misread as "not on Bedrock"; unlikely migration targets |

**Naming:** GPT-5.6 uses generation number + capability tier. `Sol` = flagship reasoning, `Terra` = balanced
production, `Luna` = high-volume / low-latency. Tiers advance on independent cadences, so a future `Terra` may not
share a generation with a future `Sol`.

> **Context-window conflict (resolved):** the GPT-5.6 launch blog states 272K for all three variants; all three
> model cards state 1M. **The model cards are authoritative** — use 1M for GPT-5.6. GPT-5.5 and GPT-5.4 are 272K on
> both sources. Re-check on refresh; if AWS corrects the blog, the cards still win.

**Not on Bedrock (as of this refresh):** GPT-4o, GPT-4.1, GPT-4 / GPT-4 Turbo, GPT-3.5 Turbo, the o-series
(o1/o3/o4-mini), GPT-5 / GPT-5.1 / GPT-5.2, Codex (unverified — see the Codex note below), and the `*-Pro` variants
(GPT-5.5 Pro, GPT-5.4 Pro). Sources whose model is on this list have no same-model landing target — see
`ai-openai-to-bedrock.md` for the two-option path.

---

## Access Paths — Split by Family

**GPT-5.5 and GPT-5.4 are `bedrock-mantle`-only and in-region only.** Their model cards list a single
Programmatic Access row (`bedrock-mantle`, Geo/Global "Not supported") and In-Region pricing only.

**GPT-5.6 Sol / Terra / Luna have TWO endpoints** (verified 2026-08-21 — this changed after this file's original
2026-08-10 verification; the Refresh Checklist predicted it):

| Endpoint          | Reach                         | Model id form                                                                           | Base URL                                                   |
| ----------------- | ----------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `bedrock-mantle`  | In-region only                | `openai.gpt-5.6-sol` / `-terra` / `-luna`                                               | `https://bedrock-mantle.{region}.api.aws/openai/v1`        |
| `bedrock-runtime` | CRIS only (no in-region form) | Geo `us.openai.gpt-5.6-*` (or `in.` in India Regions), Global `global.openai.gpt-5.6-*` | `https://bedrock-runtime.{region}.amazonaws.com/openai/v1` |

The GPT-5.6 model cards now carry an explicit tip: _"Whenever possible, we recommend using the `bedrock-runtime`
endpoint for new applications."_

Constraints that still break naive assumptions:

1. **The path segment is `/openai/v1` on BOTH endpoints** — a bare `/v1` 404s. Every GPT model card states the
   mantle path explicitly, and the runtime example gives `bedrock-runtime.{region}.amazonaws.com/openai/v1`.
2. **The endpoints take different model-id forms.** Mantle takes the bare `openai.gpt-5.6-*` id and has no CRIS;
   `bedrock-runtime` takes ONLY a CRIS inference-profile id (`us.` / `in.` / `global.` prefixed) and has no
   in-region form. `bedrock:ListInferenceProfiles` returns the 5.6 CRIS profiles; it never returns the bare mantle
   ids, and it returns nothing for GPT-5.5 / GPT-5.4.
3. **API surfaces differ by endpoint.** The 5.6 cards list `Responses`, `Chat Completions`, `Invoke`, and
   `Converse` as supported APIs, with runtime-side feature splits: **Guardrails are Converse-only; prompt caching is
   Responses-only on runtime**; server-side tool use, structured outputs, and application inference profiles are NOT
   supported on runtime (server-side tool calling IS supported on mantle). For GPT-5.5 / GPT-5.4 treat Responses on
   mantle as the only verified surface.

### Client setup

Requires the OpenAI SDK at **>= 2.45.0**. Preferred client auto-refreshes a short-term Bedrock token:

```python
from aws_bedrock_token_generator import provide_token
from openai import BedrockOpenAI

region = "us-east-1"
client = BedrockOpenAI(
    aws_region=region,
    bedrock_token_provider=lambda: provide_token(region=region),
    max_retries=6,
)

response = client.responses.create(
    model="openai.gpt-5.6-terra",
    input="...",
    reasoning={"effort": "medium"},
)
```

The alternative — `OpenAI(base_url=".../openai/v1", api_key=os.environ["AWS_BEARER_TOKEN_BEDROCK"])` — uses a key
that expires within 12 hours and is not refreshed. Do not recommend it for production.

**IAM:** on the mantle path, the managed policy `AmazonBedrockMantleInferenceAccess` grants what inference needs,
including `bedrock-mantle:CreateInference` and `bedrock-mantle:CallWithBearerToken` — `bedrock:InvokeModel` does not
authorize mantle calls. On the GPT-5.6 `bedrock-runtime` path the usual `bedrock:InvokeModel*` against the CRIS
inference-profile ARN applies, as for any other runtime model.

**Reasoning effort:** all five accept `none`, `low`, `medium`, `high`, `xhigh`, `max`. Because these models reason
before responding, the model's output items (which may include reasoning items) must be passed back in the next
request for multi-turn and tool-calling flows.

---

## Regional Availability — Endpoint-Aware

**The mantle in-region matrix** (the only reach for GPT-5.5 / GPT-5.4, and the in-region option for GPT-5.6):

| Model         | us-east-1 | us-east-2 | us-west-2 | us-gov-west-1 | us-gov-east-1 |
| ------------- | --------- | --------- | --------- | ------------- | ------------- |
| GPT-5.6 Sol   | yes       | yes       | —         | —             | —             |
| GPT-5.6 Terra | yes       | yes       | yes       | yes           | yes           |
| GPT-5.6 Luna  | yes       | yes       | yes       | yes           | yes           |
| GPT-5.5       | yes       | yes       | —         | —             | —             |
| GPT-5.4       | yes       | yes       | yes       | yes           | —             |

Terra and Luna reached AWS GovCloud (US-West, US-East) in August 2026 — newer than the rest of this matrix.

**GPT-5.6 additionally reaches most commercial regions via `bedrock-runtime` CRIS** (Geo `us.` / `in.`, Global
`global.` inference profiles; the Sol card's runtime footprint spans 30+ regions). So a region outside the mantle
matrix does NOT make the same-model path unavailable for GPT-5.6 — it means using the runtime endpoint with a CRIS
id, with the data-residency implications of cross-region routing. For GPT-5.5 / GPT-5.4 the mantle matrix is a hard
gate: no CRIS, no fallback.

Verify current footprints per model card / `aws___get_regional_availability` (AWS MCP Server) — the CRIS lists move faster than this file.

## Pricing

Read off the model cards, 2026-08-31. All rates per 1M tokens, Standard tier (Priority and Flex are NOT supported
for these models). Sol rates reflect the Aug 21, 2026 reduction (−20% input / −33% output vs launch rates), which
the AWS What's New announcement lists as promotional through at least Nov 21, 2026. **Pricing now has an
inference-option dimension:**

- **In-Region and Geo CRIS: 1.10x OpenAI's standard list price** (parity with OpenAI's _data residency_ tier).
- **Global CRIS: OpenAI's standard list price** — cost parity, available for GPT-5.6 only, and only when the
  workload has no data-residency constraint.

So the honest cost statement is conditional, not flat: a same-model GPT-5.6 move on Global CRIS is
**cost-neutral**; the same move in-region or Geo (and any GPT-5.5 / GPT-5.4 move) is **~10% more expensive**.
Never state either number without stating the inference option it belongs to.

### GPT-5.6 — short context (272K)

| Model | In-Region / Geo (in · out) | Global CRIS (in · out) | Cache write / read (In-Region) |
| ----- | -------------------------- | ---------------------- | ------------------------------ |
| Sol   | 4.40 · 22.00               | 4.00 · 20.00           | 5.50 / 0.44                    |
| Terra | 2.20 · 13.20               | 2.00 · 12.00           | 2.75 / 0.22                    |
| Luna  | 0.22 · 1.32                | 0.20 · 1.20            | 0.275 / 0.022                  |

### GPT-5.6 — long context (1M): 2.0x input / 1.5x output of short-context, per option

| Model | In-Region / Geo (in · out) | Global CRIS (in · out) |
| ----- | -------------------------- | ---------------------- |
| Sol   | 8.80 · 33.00               | 8.00 · 30.00           |
| Terra | 4.40 · 19.80               | 4.00 · 18.00           |
| Luna  | 0.44 · 1.98                | 0.40 · 1.80            |

A workload above 272K context must be priced at the long-context tier.

### GPT-5.5 / GPT-5.4 — In-Region only (no CRIS, no long-context tier; usable window 272K)

| Model   | In-Region (in · out) | Cache read | Notes                            |
| ------- | -------------------- | ---------- | -------------------------------- |
| GPT-5.5 | 5.50 · 33.00         | 0.55       | no cache-write rate published    |
| GPT-5.4 | 2.75 · 16.50         | 0.275      | GovCloud (US-West): 3.30 · 19.80 |

> **The Luna "blog discrepancy" resolved differently than first recorded.** The AWS News Blog's 0.20 / 1.20 is not
> an error — it is the **Global CRIS** rate, now published on the Luna card. An earlier revision of this file said
> global pricing was unpublished and treated the blog figure as wrong; both statements are corrected here.
> Separately, the **AWS Price List API still carries no GPT-5.x rows** (checked 2026-08-04):
> a missing or empty price-list result must not be read as "model unavailable."

### Prompt caching — GPT-5.6 only

Listed as a supported feature on the Sol, Terra, and Luna model cards. The GPT-5.5 and GPT-5.4 cards list
client-side tool calling in that slot instead and do **not** list prompt caching. Do not assume caching on 5.5/5.4.

| Property          | Value                                                        |
| ----------------- | ------------------------------------------------------------ |
| Cached input read | 90% discount vs uncached input                               |
| Cache write       | 1.25x the uncached input rate                                |
| Minimum prefix    | 1,024 tokens (below this nothing caches, `cached_tokens`= 0) |
| Breakpoints       | up to 4 per request                                          |
| Retention         | at least 30 minutes                                          |
| Modes             | implicit (on by default) and explicit (cache breakpoints)    |

Explicit mode uses `prompt_cache_options={"mode": "explicit"}` plus a `prompt_cache_breakpoint` on the content block
ending the reusable prefix; a stable `prompt_cache_key` improves match reliability. Cached input tokens **do not
count against the input-TPM quota**, which compounds the benefit at scale.

---

## Quotas

Inference on `bedrock-mantle` is governed by **two per-model, per-region quotas: input tokens per minute and output
tokens per minute. There is no requests-per-minute quota.** Exceeding a TPM quota returns HTTP 429.

This corrects two claims that were previously applied to all Mantle traffic in this plugin:

- There is **no shared 10,000 RPM account limit** governing these models — the quota dimension is TPM, per model,
  per region.
- "Switch to `bedrock-runtime`" is **not a throughput remedy for GPT-5.5 / GPT-5.4** — they have no
  `bedrock-runtime` path at all. For GPT-5.6 the runtime path DOES exist (CRIS only; see Access Paths above), so
  moving there is a legitimate option — but treat it as an endpoint/architecture choice with its own quota family
  and residency implications, not a free throughput escape hatch.

The supported mitigations are: exponential backoff with a bounded retry count (`max_retries` on the OpenAI SDK),
spreading load across minutes rather than bursting, ramping request rate gradually, and prompt caching (cached input
is exempt from the input-TPM quota). For sustained volume beyond that, pursue a quota increase.

The model cards now state tier support in text: pricing shown is Standard, and **Priority and Flex are not
supported for these models**. Do not recommend Flex as a cost lever for any GPT model here; Reserved is
account-level via the AWS account team.

---

## Features With No Bedrock Equivalent

These are the remaining legitimate reasons to keep a workload on OpenAI's own API. Cost is no longer one of them.

| OpenAI capability                                                           | Status on Bedrock                                                 |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Realtime API                                                                | No equivalent                                                     |
| Image generation (gpt-image)                                                | Not an OpenAI model on Bedrock; use Stability AI (see lifecycle)  |
| Whisper (STT) / TTS                                                         | Amazon Transcribe / Polly — different service, API, pricing model |
| Embeddings (`text-embedding-3-*`)                                           | No OpenAI embedding model on Bedrock; use Titan Embeddings v2     |
| Assistants API with file search, vector stores, code interpreter            | No direct equivalent — see the decision tree in the mapping guide |
| A model not in the catalog above (GPT-4o, o-series, `*-Pro`, GPT-5/5.1/5.2) | No same-model target; cross-family or upgrade required            |

**Data handling:** these are third-party models under OpenAI terms. Classifier-flagged traffic is retained up to 30
days for automated abuse detection; retained inputs/outputs are stored and processed by AWS and not shared with
OpenAI unless the customer opts in. Prompts and completions are not used to train models. Calls run under the
customer's IAM policies, inside their VPC, logged to CloudTrail, and in-region inference keeps data in-region.

**Codex on Bedrock: unverified — do not price it.** An earlier revision of this file stated Codex is GA on Bedrock
with pay-per-token pricing. As of 2026-09-02, Codex does not appear on the
[OpenAI model card index](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards-openai.html), and no
Codex rate exists on the Bedrock pricing page, in `pricing-cache.md`, or in `bedrock_pricing.py`'s static table.
When the source workload is a coding agent, re-check the model card index first; if Codex is still absent, treat it
as "a model not in the catalog above" (see the table in this section): plan a cross-family target (GPT-5.6 Sol /
Terra are the coding-agent tier fits) and price that target — or report `pricing_source: "unverified"` with no
dollar figure. Never attach a fabricated Codex rate to an estimate.

---

## Refresh Checklist

This model family is moving fast (two GA waves and a repricing inside 10 weeks). On each refresh:

1. Re-read the [OpenAI model card index](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards-openai.html)
   for models added or removed, and each per-model card for lifecycle state and EOL date.
2. Recheck the region matrix AND the GPT-5.6 CRIS footprints — for 5.5/5.4 a region change is migration-blocking;
   for 5.6 the runtime/CRIS path usually covers the region instead.
3. Recheck rates on the Bedrock pricing page OpenAI tab, and resolve any row still marked _unverified_.
4. Recheck whether the Price List API has gained GPT-5.x coverage; if it has, drop the caveat above and let
   `estimate-ai.md` price these models from the MCP.
5. Recheck whether Chat Completions and `bedrock-runtime` support have been added or clarified.
6. Feed any lifecycle change into `ai-model-lifecycle.md` and any rate change into `pricing-cache.md`.
7. **Re-verify within 14 days of any merge touching this file.** Item 5's prediction fired on 2026-08-21: between
   2026-08-10 and 2026-08-21 the GPT-5.6 family gained a `bedrock-runtime`/CRIS path, published Global CRIS pricing
   at standard-price parity, and listed Chat Completions/Converse as supported — invalidating three of this file's
   then-central claims in under two weeks. This family moves faster than a normal refresh cadence.
